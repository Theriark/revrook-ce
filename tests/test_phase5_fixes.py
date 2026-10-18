"""Fixes after the review of phase 5, part 2 (blockers B-1 and D-3).

* B-1: a firewall rule source is read in linear time. A CSV cell is only bounded by
  the csv field limit, so a long run of spaces must not cost a quadratic scan.
* D-3: `revrook verify-controls` exits 1 for a library that lacks a control.
"""

import dataclasses
import time

import pytest

from app.checks.library import load_library
from app.cli import verify_controls_command
from app.importers.generic import source_scope

LIBRARY = load_library()


def test_a_long_run_of_spaces_in_a_source_is_read_in_linear_time() -> None:
    blanks = " " * 100_000
    started = time.monotonic()
    assert source_scope("a" + blanks + "b") is None
    assert source_scope("0.0.0.0" + blanks + "-" + blanks + "255.255.255.255") == "any"
    assert source_scope(blanks + "10.0.0.0/8" + blanks) == "restricted"
    # A quadratic scan of 100,000 blanks takes minutes; linear takes milliseconds.
    # The bound only has to tell the two apart, so a slow CI machine cannot trip it.
    assert time.monotonic() - started < 30.0


def test_a_name_beside_a_spaced_dash_is_one_unreadable_word() -> None:
    """Known limit: `0.0.0.0/0 - LAN` joins into one word, so it is unknown."""
    assert source_scope("0.0.0.0/0 - LAN") is None


def test_verify_controls_exits_0_for_the_library_of_the_report() -> None:
    assert verify_controls_command() == 0


def test_verify_controls_exits_1_for_a_library_with_50_controls(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    fewer = dataclasses.replace(LIBRARY, controls=LIBRARY.controls[:-1])
    monkeypatch.setattr("app.cli.load_library", lambda: fewer)
    assert verify_controls_command() == 1
    out = capsys.readouterr().out
    assert out.startswith("revrook verify-controls: ")
    assert "the library has 50 controls, not 51" in out
