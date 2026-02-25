"""
Tests for humanization helpers — Bezier paths, typing delays, scroll direction.

These tests verify mathematical correctness without running a real browser.
"""
import math
import pytest
from src.infrastructure.scrapers.humanization.mouse_movements import (
    generate_bezier_path,
    _bezier_point,
)
from src.infrastructure.scrapers.humanization.typing_simulator import (
    _wpm_to_char_delay,
    _neighbour_key,
    FAST_BIGRAMS,
    QWERTY_NEIGHBORS,
)


# ---------------------------------------------------------------------------
# Bezier curve
# ---------------------------------------------------------------------------


def test_bezier_point_at_t0_returns_p0():
    p0, p1, p2, p3 = (0, 0), (1, 0), (0, 1), (1, 1)
    x, y = _bezier_point(0.0, p0, p1, p2, p3)
    assert abs(x) < 1e-9
    assert abs(y) < 1e-9


def test_bezier_point_at_t1_returns_p3():
    p0, p1, p2, p3 = (0, 0), (1, 0), (0, 1), (5, 7)
    x, y = _bezier_point(1.0, p0, p1, p2, p3)
    assert abs(x - 5) < 1e-9
    assert abs(y - 7) < 1e-9


def test_generate_bezier_path_correct_length():
    path = generate_bezier_path((0, 0), (100, 200), num_points=60)
    assert len(path) == 60


def test_generate_bezier_path_starts_near_origin():
    path = generate_bezier_path((0, 0), (1000, 1000), num_points=50)
    first_x, first_y = path[0]
    # With Gaussian noise σ≈1.5px the first point should be very close to (0,0)
    assert abs(first_x) < 20
    assert abs(first_y) < 20


def test_generate_bezier_path_ends_near_target():
    path = generate_bezier_path((0, 0), (500, 300), num_points=80)
    last_x, last_y = path[-1]
    assert abs(last_x - 500) < 20
    assert abs(last_y - 300) < 20


def test_bezier_path_all_points_are_tuples():
    path = generate_bezier_path((10, 20), (300, 400), num_points=30)
    for pt in path:
        assert len(pt) == 2
        assert isinstance(pt[0], float)
        assert isinstance(pt[1], float)


# ---------------------------------------------------------------------------
# Typing simulator
# ---------------------------------------------------------------------------


def test_wpm_to_char_delay_reasonable():
    # At 65 WPM (5 chars/word) → 325 chars/min → ~0.185 s/char
    delay = _wpm_to_char_delay(65)
    assert 0.15 < delay < 0.25


def test_wpm_to_char_delay_faster_for_higher_wpm():
    assert _wpm_to_char_delay(120) < _wpm_to_char_delay(60)


def test_fast_bigrams_are_strings():
    for bigram in FAST_BIGRAMS:
        assert isinstance(bigram, str)
        assert len(bigram) == 2


def test_neighbour_key_returns_valid_char():
    for char in "abcdefghijklmnopqrstuvwxyz":
        if char in QWERTY_NEIGHBORS:
            neighbour = _neighbour_key(char)
            assert neighbour is not None
            assert neighbour in QWERTY_NEIGHBORS[char]


def test_neighbour_key_nonexistent_char_returns_none():
    assert _neighbour_key("€") is None
    assert _neighbour_key("1") is None
