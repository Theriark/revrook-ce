"""Command line entry point.

Subcommands: web, worker, all, migrate, verify-chain, verify-controls,
make-fixtures.
Without a subcommand the ROLE setting (web, worker or all; default all) decides.
"""

import argparse
import asyncio
import logging
import signal
import subprocess
import sys
import threading
from collections.abc import Callable, Sequence

import uvicorn
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.checks.engine import engine_problems
from app.checks.library import (
    ControlLibraryError,
    count_problems,
    describe,
    load_library,
)
from app.checks.reference import load_reference_names, reference_problems
from app.db import make_engine
from app.evidence.chain import ChainResult, verify_all
from app.migrate import upgrade_to_head
from app.settings import Settings, SettingsError, load_settings
from app.worker import serve

PORT = 8080
STUBS = {
    "make-fixtures": "not available until phase 3 (synthetic fixtures)",
}

Spawner = Callable[[list[str]], "subprocess.Popen[bytes]"]


def _spawn(command: list[str]) -> "subprocess.Popen[bytes]":
    return subprocess.Popen(command)


def supervise(
    commands: Sequence[Sequence[str]],
    spawn: Spawner = _spawn,
    poll_interval: float = 0.5,
    stop: threading.Event | None = None,
) -> int:
    """Run commands side by side until one exits or stop is set.

    Every other process is then terminated. Returns 0 when stopped on request,
    otherwise the exit code of the first process that ended (1 if it was 0,
    because a role that exits on its own is a failure).
    """
    halt = stop or threading.Event()
    processes = [spawn(list(command)) for command in commands]
    first_exit: int | None = None
    try:
        while first_exit is None:
            for process in processes:
                code = process.poll()
                if code is not None:
                    first_exit = code
                    break
            else:
                if halt.wait(poll_interval):
                    break
    finally:
        for process in processes:
            if process.poll() is None:
                process.terminate()
        for process in processes:
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
    if first_exit is None:
        return 0
    return first_exit or 1


async def _verify_all_chains(database_url: str) -> list[ChainResult]:
    engine = make_engine(database_url)
    try:
        async with async_sessionmaker(engine)() as session:
            return await verify_all(session)
    finally:
        await engine.dispose()


def verify_chain_command(settings: Settings) -> int:
    """Verify every client's evidence chain. Exit 0 intact, 1 broken, 2 no database."""
    try:
        results = asyncio.run(_verify_all_chains(settings.database_url))
    except (SQLAlchemyError, OSError) as error:
        print(f"revrook verify-chain: the database cannot be read: {error}")
        return 2
    broken = 0
    for result in results:
        if result.ok:
            print(
                f"client {result.client_id}: intact, {result.records} records, "
                f"head {result.head_hash}"
            )
        else:
            broken += 1
            print(
                f"client {result.client_id}: BROKEN at record "
                f"{result.failed_record_id}: {result.reason}"
            )
    print(f"{len(results) - broken} of {len(results)} chains intact")
    return 1 if broken else 0


def verify_controls_command() -> int:
    """Load the control library and the NIST names. Exit 0 valid, 1 not.

    Needs no database and no keys: it only reads data/controls.yaml and data/nist.
    """
    try:
        library = load_library()
        references = load_reference_names()
    except ControlLibraryError as error:
        print(f"revrook verify-controls: {error}")
        return 1
    problems = [
        *count_problems(library),
        *engine_problems(library),
        *reference_problems(library, references),
    ]
    if problems:
        print("revrook verify-controls: " + "; ".join(problems))
        return 1
    print(describe(library))
    for key in sorted(references):
        print(f"{references[key].framework}: {len(references[key].names)} names")
    return 0


def _serve_web(settings: Settings) -> int:  # pragma: no cover
    # The first-run page needs the tables, so the web role brings the schema up
    # to date before it listens (a locked, one-at-a-time step; see app.migrate).
    upgrade_to_head()
    uvicorn.run(
        "app.main:create_app",
        factory=True,
        host="0.0.0.0",
        port=PORT,
        log_level=settings.log_level,
    )
    return 0


def _serve_worker(settings: Settings) -> int:  # pragma: no cover
    serve(settings)
    return 0


def _serve_all() -> int:  # pragma: no cover
    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    base = [sys.executable, "-m", "app.cli"]
    return supervise([[*base, "web"], [*base, "worker"]], stop=stop)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="revrook")
    subcommands = parser.add_subparsers(dest="command")
    subcommands.add_parser("web", help="serve the web interface on port 8080")
    subcommands.add_parser("worker", help="run the background worker")
    subcommands.add_parser("all", help="run web and worker as two processes")
    subcommands.add_parser("migrate", help="bring the database schema up to date")
    subcommands.add_parser("verify-chain", help="verify the evidence hash chains")
    subcommands.add_parser(
        "verify-controls", help="check the control library and the NIST names"
    )
    for name, reason in STUBS.items():
        subcommands.add_parser(name, help=reason)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if args.command in STUBS:
        print(f"revrook {args.command}: {STUBS[args.command]}", file=sys.stderr)
        return 2
    if args.command == "verify-controls":
        return verify_controls_command()
    try:
        settings = load_settings()
    except SettingsError as error:
        print(f"revrook: {error}", file=sys.stderr)
        return 2
    logging.basicConfig(
        level=settings.log_level.upper(),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    command = args.command or settings.role
    if command == "migrate":
        upgrade_to_head()
        return 0
    if command == "verify-chain":
        return verify_chain_command(settings)
    if command == "web":
        return _serve_web(settings)
    if command == "worker":
        return _serve_worker(settings)
    return _serve_all()


if __name__ == "__main__":
    sys.exit(main())
