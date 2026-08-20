from __future__ import annotations

from datetime import datetime

from fuji_visibility.fingerprint import FingerprintSearcher, coordinate_grid, load_fingerprint
from fuji_visibility.models import Fingerprint, FingerprintObservation, ForecastResult


def test_coordinate_grid_contains_center_and_expected_points():
    grid = coordinate_grid(35.52, 138.75, 0.01, 0.01)
    assert len(grid) == 9
    assert (35.52, 138.75) in grid


def test_synthetic_fingerprint_ranks_known_coordinate_and_mapping(make_hour):
    observations = [
        FingerprintObservation(
            valid_time=datetime.fromisoformat("2026-08-26T09:00:00+09:00"),
            temperature_c=27.2,
            displayed_cloud_pct=5,
            visibility_km=42.5,
        ),
        FingerprintObservation(
            valid_time=datetime.fromisoformat("2026-08-26T10:00:00+09:00"),
            temperature_c=27.8,
            displayed_cloud_pct=8,
            visibility_km=40.0,
        ),
    ]
    fingerprint = Fingerprint(observations=observations)

    class FakeClient:
        def fetch_forecast(self, latitude, longitude, **kwargs):
            is_correct = abs(latitude - 35.52) < 0.0001 and abs(longitude - 138.75) < 0.0001
            return ForecastResult(
                model=kwargs["model"],
                resolved_model="synthetic",
                requested_lat=latitude,
                requested_lon=longitude,
                timezone="Asia/Tokyo",
                retrieved_at=datetime.fromisoformat("2026-08-21T07:35:00+09:00"),
                hours=[
                    make_hour(
                        "2026-08-26T09:00:00+09:00",
                        cloud_total_pct=60 if is_correct else 5,
                        cloud_mid_pct=5 if is_correct else 45,
                        visibility_m=42500 if is_correct else 10000,
                        temperature_c=27.2 if is_correct else 20,
                    ),
                    make_hour(
                        "2026-08-26T10:00:00+09:00",
                        cloud_total_pct=60 if is_correct else 5,
                        cloud_mid_pct=8 if is_correct else 45,
                        visibility_m=40000 if is_correct else 10000,
                        temperature_c=27.8 if is_correct else 20,
                    ),
                ],
                raw_payload={},
            )

    result = FingerprintSearcher(FakeClient()).search_live(
        fingerprint,
        latitude_center=35.52,
        longitude_center=138.75,
        radius_deg=0.01,
        step_deg=0.01,
        models=["synthetic"],
        cloud_mappings=["total", "mid"],
    )
    assert result.candidates
    best = result.candidates[0]
    assert (best.latitude, best.longitude) == (35.52, 138.75)
    assert best.cloud_mapping == "mid"
    assert best.error == 0


def test_load_fingerprint_fixture():
    fingerprint = load_fingerprint("data/fingerprints/isitvisible_2026-08-21_0730_jst.json")
    assert len(fingerprint.observations) == 3
    assert fingerprint.observations[0].valid_time.tzinfo is not None
