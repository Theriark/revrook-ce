"""An independent recomputation of the scoring vectors of clients A, B and C.

Written first by the Test Engineer (THE-310) and committed here as a carry-over of
phase 6. It does NOT import the application: the scoring model of rnd-report-3
section 3.5 is typed again below from the plan, with its own control table, and the
result is compared with the hand vectors of tests/scoring_vectors/clients.json
(tolerance 0.05). The only things it reads from the repository are that vector file
and data/controls.yaml, to check its control table against the control file; the
control file wins if they ever differ.

Statuses are p (pass), h (partial), f (fail), u (unknown) and n (not applicable). A
control state is (status, quality as a Fraction, age in days of its evidence or None).

Run it from the repository root:

    python3 -m unittest tests/independent/recompute_vectors.py
"""

import json
import unittest
from fractions import Fraction as F
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
CLIENTS = ROOT / "tests" / "scoring_vectors" / "clients.json"
CONTROLS = ROOT / "data" / "controls.yaml"
TOLERANCE = F(5, 100)

WEIGHT_OF_DOMAIN = {
    "ACC": 22,
    "DEV": 14,
    "END": 10,
    "EML": 12,
    "BCK": 16,
    "NET": 6,
    "LOG": 8,
    "GOV": 12,
}
N = None
# One row per control, in order: weight, gate (1 or 0), maximum age in days of an
# automatic result, maximum age of a manual one (None: no limit).
# fmt: off
TABLE = {
    "ACC": [
        (3, 1, 35, 365), (3, 1, 35, 365), (3, 0, 35, 365), (2, 0, 35, 365),
        (2, 0, 35, 365), (2, 0, 35, 365), (1, 0, 35, 365), (1, 0, N, 365),
    ],
    "DEV": [
        (2, 0, 7, 365), (3, 0, 7, N), (2, 0, 7, N), (3, 0, 7, N),
        (2, 0, 7, N), (1, 0, 35, 365), (2, 0, 7, N),
    ],
    "END": [
        (3, 0, 7, N), (2, 0, 7, N), (2, 0, 7, N), (2, 0, 35, N), (1, 0, 35, 365),
    ],
    "EML": [
        (2, 0, 35, 365), (2, 0, 35, 365), (3, 0, 35, 365), (2, 0, 35, 365),
        (2, 0, 35, 365), (1, 0, 35, 365), (1, 0, N, 365),
    ],
    "BCK": [
        (3, 1, 7, N), (2, 0, 7, N), (3, 0, 100, 100), (2, 0, 7, N),
        (1, 0, 35, N), (2, 0, N, 365),
    ],
    "NET": [
        (2, 0, 35, 365), (2, 0, 35, 365), (2, 0, 35, 365), (1, 0, 35, 365),
        (1, 0, 35, 365),
    ],
    "LOG": [
        (3, 0, 35, 365), (2, 0, 35, 365), (2, 0, 35, 365), (2, 0, 35, 365),
        (1, 0, N, 35), (1, 0, 35, 365),
    ],
    "GOV": [
        (2, 0, N, 365), (2, 0, N, 365), (2, 0, 365, 365), (2, 0, 35, 365),
        (2, 0, N, 365), (1, 0, 35, 365), (1, 0, N, 365),
    ],
}
# fmt: on
CONTROL_TABLE: dict[str, tuple[Any, ...]] = {}
for _domain, _rows in TABLE.items():
    for _number, _row in enumerate(_rows, 1):
        CONTROL_TABLE[f"PC-{_domain}-{_number:02d}"] = (_domain, *_row)

State = dict[str, tuple[str, F, int | None]]
CODE_OF_STATUS = {"pass": "p", "partial": "h", "fail": "f", "unknown": "u", "na": "n"}
EARNED = {"p": F(1), "h": F(1, 2), "f": F(0), "u": F(0), "n": F(0)}
CAP_FAIL = 49
CAP_PARTIAL = 69
MIN_COVERAGE = F(3, 5)


def freshness(age: int | None, limit: int | None) -> F:
    """1 up to the limit M, falling in a straight line to 0 at twice M."""
    if age is None or limit is None or age <= limit:
        return F(1)
    if age >= 2 * limit:
        return F(0)
    return 2 - F(age, limit)


def is_stale(age: int | None, limit: int | None) -> bool:
    return age is not None and limit is not None and age > limit


def limit_of(control_id: str, quality: F) -> int | None:
    """The maximum age that applies: the automatic one at quality 1, else manual."""
    automatic, manual = CONTROL_TABLE[control_id][3:5]
    return automatic if quality == 1 else manual


def control_rows(state: State) -> list[dict[str, Any]]:
    rows = []
    for control_id, (status, quality, age) in state.items():
        domain, weight, gate = CONTROL_TABLE[control_id][:3]
        limit = limit_of(control_id, quality)
        fresh = freshness(age, limit)
        row = {"id": control_id, "domain": domain, "weight": weight, "gate": gate}
        row["status"] = status
        row["fresh"] = fresh
        row["stale"] = is_stale(age, limit)
        row["score"] = EARNED[status] * quality * fresh
        rows.append(row)
    return rows


def gate_cap(rows: list[dict[str, Any]]) -> tuple[int, str] | None:
    """The lowest cap a gate control puts on the score, the first on a tie."""
    cap = None
    for row in rows:
        if not row["gate"] or row["status"] == "n":
            continue
        if row["status"] in "fu" or (row["stale"] and row["fresh"] == 0):
            limit = CAP_FAIL
        elif row["status"] == "h" or row["stale"]:
            limit = CAP_PARTIAL
        else:
            continue
        if cap is None or limit < cap[0]:
            cap = (limit, row["id"])
    return cap


def assess(state: State) -> tuple[dict[str, Any], F, F, Any, F]:
    """Domain scores, overall O, score S, the gate cap and the coverage."""
    rows = control_rows(state)
    domains: dict[str, Any] = {}
    for domain in WEIGHT_OF_DOMAIN:
        members = [row for row in rows if row["domain"] == domain]
        possible = sum(row["weight"] for row in members if row["status"] != "n")
        earned = sum(row["weight"] * row["score"] for row in members)
        domains[domain] = F(100) * earned / possible if possible else None
    live = [domain for domain in WEIGHT_OF_DOMAIN if domains[domain] is not None]
    total_weight = sum(WEIGHT_OF_DOMAIN[domain] for domain in live)
    weighted = sum(WEIGHT_OF_DOMAIN[domain] * domains[domain] for domain in live)
    overall = weighted / total_weight
    cap = gate_cap(rows)
    score = overall if cap is None else min(overall, F(cap[0]))
    counted = sum(row["weight"] for row in rows if row["status"] != "n")
    fresh_rows = [row for row in rows if row["status"] in "phf" and not row["stale"]]
    covered = sum(row["weight"] for row in fresh_rows)
    return domains, overall, score, cap, F(covered, counted)


def best_case(state: State) -> State:
    """Every unknown or stale control becomes a fresh pass at quality 1."""
    completed: State = {}
    for control_id, (status, quality, age) in state.items():
        limit = limit_of(control_id, quality)
        if status != "n" and (status == "u" or is_stale(age, limit)):
            completed[control_id] = ("p", F(1), 0)
        else:
            completed[control_id] = (status, quality, age)
    return completed


def client_state(document: dict[str, Any], name: str) -> State:
    """All 51 controls of a client: pass, quality 1, age 0, then its overrides."""
    client = document["clients"][name]
    if "base" in client:
        state = client_state(document, client["base"])
    else:
        state = {control_id: ("p", F(1), 0) for control_id in CONTROL_TABLE}
    for control_id, (status, quality, age) in client.get("controls", {}).items():
        state[control_id] = (CODE_OF_STATUS[status], F(quality), age)
    return state


def percent(value: F) -> int:
    """Whole percent, halves rounded up (the display of the application)."""
    return int(value * 100 + F(1, 2))


class RecomputeVectors(unittest.TestCase):
    document: dict[str, Any]

    @classmethod
    def setUpClass(cls) -> None:
        cls.document = json.loads(CLIENTS.read_text(encoding="utf-8"))

    def test_the_control_table_is_the_control_file(self) -> None:
        loaded = yaml.safe_load(CONTROLS.read_text(encoding="utf-8"))
        weights = {item["code"]: item["weight"] for item in loaded["domains"]}
        self.assertEqual(weights, WEIGHT_OF_DOMAIN)
        found = {}
        for item in loaded["controls"]:
            ages = item["max_age_days"]
            found[item["id"]] = (
                item["domain"],
                item["weight"],
                int(item["gate"]),
                ages["automatic"],
                ages["manual"],
            )
        self.assertEqual(found, CONTROL_TABLE)
        self.assertEqual(len(found), 51)

    def check(self, name: str, score: str, best: str, coverage: int) -> None:
        expect = self.document["clients"][name]["expect"]
        state = client_state(self.document, name)
        domains, _, result, cap, covered = assess(state)
        upper = assess(best_case(state))[2]
        self.assertLessEqual(abs(result - F(score)), TOLERANCE, float(result))
        self.assertLessEqual(abs(upper - F(best)), TOLERANCE, float(upper))
        self.assertEqual(percent(covered), coverage)
        self.assertEqual(expect["coverage_percent"], coverage)
        self.assertGreaterEqual(covered, MIN_COVERAGE)
        for domain, text in expect["domains"].items():
            self.assertLessEqual(abs(domains[domain] - F(text)), TOLERANCE, domain)
        wanted = expect["cap"]
        if wanted is None:
            self.assertIsNone(cap)
        else:
            self.assertEqual(cap, (wanted["limit"], wanted["control"]))

    def test_client_a(self) -> None:
        self.check("A", "89.5", "90.5", 99)

    def test_client_b(self) -> None:
        self.check("B", "45.7", "69.0", 71)

    def test_client_c(self) -> None:
        self.check("C", "49.0", "49.0", 100)

    def test_client_c_is_capped_from_86_6(self) -> None:
        state = client_state(self.document, "C")
        _, overall, result, cap, _ = assess(state)
        self.assertLessEqual(abs(overall - F("86.6")), TOLERANCE)
        self.assertEqual(result, 49)
        self.assertEqual(cap, (49, "PC-ACC-02"))

    def test_freshness_at_m_one_and_a_half_m_and_two_m(self) -> None:
        self.assertEqual(freshness(10, 10), 1)
        self.assertEqual(freshness(None, 10), 1)
        self.assertEqual(freshness(99, None), 1)
        self.assertEqual(freshness(15, 10), F(1, 2))
        self.assertEqual(freshness(20, 10), 0)
        self.assertEqual(freshness(35, 10), 0)


if __name__ == "__main__":
    unittest.main()
