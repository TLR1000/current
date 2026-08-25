import pytest

from app.main import interpolate_vectors, spatial_weights


def test_inverse_distance_squared_weights():
    points = [{"distance_km_raw": 1.0}, {"distance_km_raw": 2.0}]
    weights = spatial_weights(points)
    assert weights == pytest.approx([0.8, 0.2])


def test_vector_components_are_interpolated_not_directions():
    calculations = [
        {"current": {"u": -0.174, "v": 0.985}},  # 350 degrees
        {"current": {"u": 0.174, "v": 0.985}},   # 10 degrees
    ]
    result = interpolate_vectors(calculations, [0.5, 0.5])
    assert result["directionDegreesTrue"] == pytest.approx(0, abs=0.001)
    assert result["northwardMetersPerSecond"] == pytest.approx(0.985)


def test_exact_atlas_point_gets_full_weight():
    points = [{"distance_km_raw": 0.0}, {"distance_km_raw": 2.0}]
    assert spatial_weights(points) == [1.0, 0.0]
