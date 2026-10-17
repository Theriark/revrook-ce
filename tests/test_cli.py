import os
import subprocess
import sys
import threading
from pathlib import Path

import pytest

from app import cli

ROOT = Path(__file__).resolve().parent.parent
DATABASE_URL = "postgresql+asyncpg://revrook:unused@127.0.0.1:1/revrook"


def run_cli(*args: str, **extra_env: str) -> subprocess.CompletedProcess[str]:
    """Run `python -m app.cli` in a clean environment (no keys unless given)."""
    env = {
        "PATH": os.environ.get("PATH", ""),
        "DATABASE_URL": DATABASE_URL,
        **extra_env,
    }
    return subprocess.run(
        [sys.executable, "-m", "app.cli", *args],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


@pytest.mark.parametrize("args", [(), ("web",), ("worker",), ("all",)])
def test_every_role_fails_at_startup_without_the_keys(args: tuple[str, ...]) -> None:
    result = run_cli(*args)
    assert result.returncode == 2
    assert "SECRET_KEY is required" in result.stderr
    assert "FERNET_KEY is required" in result.stderr


def test_startup_failure_does_not_print_the_secret_it_was_given() -> None:
    result = run_cli("web", SECRET_KEY="sentinel-secret-value-123456")
    assert result.returncode == 2
    assert "FERNET_KEY is required" in result.stderr
    assert "SECRET_KEY is required" not in result.stderr
    assert "sentinel-secret-value-123456" not in result.stderr + result.stdout


@pytest.mark.parametrize("command", ["make-fixtures"])
def test_unbuilt_commands_exit_nonzero_with_a_reason(
    command: str, capsys: pytest.CaptureFixture[str]
) -> None:
    assert cli.main([command]) == 2
    assert "not available until phase" in capsys.readouterr().err


def test_migrate_brings_the_schema_to_the_newest_revision(
    monkeypatch: pytest.MonkeyPatch,
    migrated_database: str,
    env: dict[str, str],
) -> None:
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    assert cli.main(["migrate"]) == 0
    # A second run finds nothing left to do and still succeeds.
    assert cli.main(["migrate"]) == 0


def test_main_reports_settings_errors(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("SECRET_KEY", raising=False)
    monkeypatch.delenv("FERNET_KEY", raising=False)
    monkeypatch.setenv("DATABASE_URL", DATABASE_URL)
    assert cli.main(["web"]) == 2
    assert "SECRET_KEY is required" in capsys.readouterr().err


class FakeProcess:
    """Stands in for subprocess.Popen: exits with `code` after `exits_after` polls."""

    def __init__(
        self, exits_after: int | None = None, code: int = 0, hangs: bool = False
    ) -> None:
        self.exits_after = exits_after
        self.code = code
        self.hangs = hangs
        self.polls = 0
        self.returncode: int | None = None
        self.terminated = False
        self.killed = False

    def poll(self) -> int | None:
        if self.returncode is None and self.exits_after is not None:
            self.polls += 1
            if self.polls > self.exits_after:
                self.returncode = self.code
        return self.returncode

    def terminate(self) -> None:
        self.terminated = True
        if self.returncode is None:
            self.returncode = -15

    def wait(self, timeout: float | None = None) -> int | None:
        if self.hangs and not self.killed:
            raise subprocess.TimeoutExpired("fake", timeout or 0)
        return self.returncode

    def kill(self) -> None:
        self.killed = True
        self.returncode = -9


def supervise(*processes: FakeProcess, stop: threading.Event | None = None) -> int:
    queue = list(processes)
    return cli.supervise(
        [["web"], ["worker"]][: len(queue)],
        spawn=lambda _command: queue.pop(0),  # type: ignore[arg-type,return-value]
        poll_interval=0,
        stop=stop,
    )


def test_supervise_returns_the_exit_code_of_the_first_process_to_end() -> None:
    running, failing = FakeProcess(), FakeProcess(exits_after=2, code=3)
    assert supervise(running, failing) == 3
    assert running.terminated
    assert not failing.terminated


def test_supervise_treats_a_clean_exit_as_a_failure() -> None:
    assert supervise(FakeProcess(), FakeProcess(exits_after=0, code=0)) == 1


def test_supervise_stops_everything_on_request_and_returns_zero() -> None:
    first, second = FakeProcess(), FakeProcess()
    stop = threading.Event()
    stop.set()
    assert supervise(first, second, stop=stop) == 0
    assert first.terminated
    assert second.terminated


def test_supervise_kills_a_process_that_ignores_terminate() -> None:
    stubborn = FakeProcess(hangs=True)
    stop = threading.Event()
    stop.set()
    assert supervise(stubborn, stop=stop) == 0
    assert stubborn.terminated
    assert stubborn.killed
