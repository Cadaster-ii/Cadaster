"""
agent/tests/test_duplicate_check.py

Unit tests for the duplicate/overlap check.
"""

import pytest
from agent.checks.duplicate_check import check_no_overlap

PARIS = {
    "type": "Polygon",
    "coordinates": [[
        [2.2241, 48.8153],
        [2.4699, 48.8153],
        [2.4699, 48.9022],
        [2.2241, 48.9022],
        [2.2241, 48.8153],
    ]],
}

# WKT of Paris bounding box
PARIS_WKT = (
    "POLYGON ((2.2241 48.8153, 2.4699 48.8153, 2.4699 48.9022, "
    "2.2241 48.9022, 2.2241 48.8153))"
)

# A non-overlapping polygon (London area)
LONDON_WKT = (
    "POLYGON ((-0.5103 51.2867, 0.3340 51.2867, 0.3340 51.6919, "
    "-0.5103 51.6919, -0.5103 51.2867))"
)


class TestCheckNoOverlap:
    def test_no_existing_always_passes(self):
        r = check_no_overlap(PARIS, [])
        assert r.passed
        assert r.evidence["checked_against"] == 0

    def test_non_overlapping_passes(self):
        r = check_no_overlap(PARIS, [LONDON_WKT])
        assert r.passed

    def test_identical_polygon_fails(self):
        r = check_no_overlap(PARIS, [PARIS_WKT])
        assert not r.passed
        assert len(r.evidence["overlapping"]) >= 1

    def test_large_overlap_fails(self):
        # Slightly shifted Paris — still mostly overlapping
        shifted = {
            "type": "Polygon",
            "coordinates": [[
                [2.25, 48.83],
                [2.48, 48.83],
                [2.48, 48.89],
                [2.25, 48.89],
                [2.25, 48.83],
            ]],
        }
        r = check_no_overlap(shifted, [PARIS_WKT])
        assert not r.passed

    def test_tiny_border_touch_passes(self):
        # A polygon that only touches at a corner
        adjacent = {
            "type": "Polygon",
            "coordinates": [[
                [2.4699, 48.8153],
                [2.6, 48.8153],
                [2.6, 48.9022],
                [2.4699, 48.9022],
                [2.4699, 48.8153],
            ]],
        }
        # Touching at an edge — tiny or zero-area intersection
        r = check_no_overlap(adjacent, [PARIS_WKT], max_overlap_fraction=0.05)
        # Shared edge has zero area, so passes
        assert r.passed
