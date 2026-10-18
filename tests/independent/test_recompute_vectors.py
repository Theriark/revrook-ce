"""Runs the independent recomputation (tests/independent/recompute_vectors.py).

The script does not import the application; this file only lets pytest, and so the
merge gate, collect its unittest case.
"""

from recompute_vectors import RecomputeVectors

__all__ = ["RecomputeVectors"]
