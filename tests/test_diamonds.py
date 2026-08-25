from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.diamonds import calculate_diamond_current, moon_spring_neap_factor, parse_diamonds


ROOT = Path(__file__).parent.parent


def test_dataset_has_twelve_valid_points_and_skips_thirteen():
    points, warnings = parse_diamonds(ROOT / "data" / "diamonds.txt")
    assert len(points) == 12
    assert [point.number for point in points] == list(range(1, 13))
    assert warnings == ["diamond 13: missing_coordinates"]
    assert all(len(point.rates) == 13 for point in points)


def test_vector_interpolation_crosses_true_north():
    rates = [
        {"hours_from_high_water": 0, "direction_deg": 350, "spring_speed_knots": 1, "neap_speed_knots": 1},
        {"hours_from_high_water": 1, "direction_deg": 10, "spring_speed_knots": 1, "neap_speed_knots": 1},
    ]
    result = calculate_diamond_current(rates, 0.5, 0.5)
    assert result["direction_deg"] == pytest.approx(0, abs=0.001)
    assert result["speed_knots"] == pytest.approx(0.985, abs=0.001)


def test_moon_factor_is_bounded():
    factor = moon_spring_neap_factor(datetime(2026, 8, 25, tzinfo=timezone.utc))
    assert 0 <= factor <= 1
