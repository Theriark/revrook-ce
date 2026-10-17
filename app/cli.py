"""Command line entry point: revrook web | worker | all | verify-chain | make-fixtures.

Without a subcommand the ROLE setting (web, worker or all; default all) decides.
"""

import argparse
import logging
import signal
import subprocess
import sys
import threading
from collections.abc import Callable, Sequence

import uvicorn

from app.settings import Settings, SettingsError, load_settings
from app.worker import serve

PORT = 8080
STUBS = {
    "verify-chain": "not available until phase 2 (evidence hash chain)",
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


def _serve_web(settings: Settings) -> int:  # pragma: no cover
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
    for name, reason in STUBS.items():
        subcommands.add_parser(name, help=reason)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if args.command in STUBS:
        print(f"revrook {args.command}: {STUBS[args.command]}", file=sys.stderr)
        return 2
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
    if command == "web":
        return _serve_web(settings)
    if command == "worker":
        return _serve_worker(settings)
    return _serve_all()


if __name__ == "__main__":
    sys.exit(main())
