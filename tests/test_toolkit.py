"""
Unit tests.

Index and pricing code fails silently: a wrong window or an off-by-one in the
underwriting-year mapping produces a plausible-looking number, gets priced,
gets sold, and only shows up when a claim is disputed. These tests pin the
behaviour that has to hold.

Run with:  python3 tests/test_toolkit.py     (or: pytest tests)
"""
import sys
import pathlib

import numpy as np
import pandas as pd

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from src import gridding, indices, pricing, validation  # noqa: E402


def _daily(rain, start="2023-01-01", **cols):
    n = len(rain)
    df = pd.DataFrame(
        {
            "date": pd.date_range(start, periods=n, freq="D"),
            "grid_lat": 23.0,
            "grid_lon": 74.0,
            "rain_mm": rain,
        }
    )
    for k, v in cols.items():
        df[k] = v
    df["uwy"] = 2023
    return df


def test_haversine_known_distance():
    # Delhi -> Jaipur is ~240 km great-circle
    d = gridding.haversine_matrix([28.6139], [77.2090], [26.9124], [75.7873])[0, 0]
    assert 230 < d < 250, d


def test_snap_picks_nearest_and_flags_far():
    enroll = pd.DataFrame({"latitude": [23.02, 30.0], "longitude": [74.01, 80.0], "state": "X", "district": "Y"})
    grid = pd.DataFrame({"grid_lat": [23.0, 24.0], "grid_lon": [74.0, 75.0]})
    out = gridding.snap_to_grid(enroll, grid, max_distance_km=25.0)
    assert out.loc[0, "grid_lat"] == 23.0 and out.loc[0, "snap_flag"] == "ok"
    assert out.loc[1, "snap_flag"] == "far"          # far rows are kept, not dropped
    assert len(out) == len(enroll)


def test_book_weights_sum_to_one():
    mapped = pd.DataFrame(
        {
            "state": ["X"] * 4,
            "district": ["A", "A", "B", "B"],
            "grid_lat": [23.0, 23.0, 23.0, 24.0],   # one node straddles two districts
            "grid_lon": [74.0, 74.0, 74.0, 75.0],
            "sum_insured": [100, 100, 200, 200],
        }
    )
    w = gridding.grid_exposure_weights(mapped, sum_insured_col="sum_insured")
    book = gridding.book_weights(w)
    assert abs(book["weight"].sum() - 1.0) < 1e-9
    assert len(book) == 2                            # collapsed to unique nodes


def test_underwriting_year_wraps_rabi_season():
    dates = pd.Series(pd.to_datetime(["2023-12-15", "2024-01-20", "2024-02-10", "2024-06-01"]))
    uwy = indices.assign_underwriting_year(dates, wrap_months=(1, 2, 3))
    assert list(uwy) == [2023, 2023, 2023, 2024]     # Dec-Feb is ONE season


def test_phase_slice_handles_year_wrap():
    df = _daily(np.zeros(400), start="2023-06-01")
    ph = indices.slice_phase(df, "12-01", "02-28", wrap_months=(1, 2, 3))
    months = set(pd.to_datetime(ph["date"]).dt.month)
    assert months <= {12, 1, 2} and len(ph) > 0


def test_eri_takes_max_rolling_window_not_total():
    rain = [0, 0, 40, 40, 40, 0, 0, 10, 10, 10]      # 120 mm in 3 days, 180 mm total
    out = indices.excess_rainfall_index(_daily(rain), window_days=3)
    assert abs(out["index_value"].iloc[0] - 120.0) < 1e-6


def test_wdi_cap_bites():
    rain = [200.0, 0, 0, 0]                          # one cloudburst, crop saw ~50 mm
    out = indices.deficit_rainfall_index(_daily(rain), daily_cap_mm=50.0)
    assert abs(out["index_value"].iloc[0] - 50.0) < 1e-6


def test_dry_spell_is_longest_run_not_total_dry_days():
    rain = [0, 0, 0, 10, 0, 0, 0, 0, 0, 10]          # 3-run then 5-run, 8 dry days total
    out = indices.dry_spell_index(_daily(rain), dry_threshold_mm=2.5)
    assert out["index_value"].iloc[0] == 5


def test_disease_spell_needs_both_conditions_and_consecutiveness():
    temp = [15, 15, 15, 30, 15, 15]
    rh = [85, 85, 85, 85, 85, 60]                    # runs: 3 conducive, then 1
    df = _daily(np.zeros(6), t2m_c=temp, rh_pct=rh)
    out = indices.disease_spell_index(df, temp_range=(10, 20), rh_min=80)
    assert out["index_value"].iloc[0] == 3
    assert out["conducive_days"].iloc[0] == 4


def test_ladder_pays_deepest_step_only():
    lad = pricing.StrikeLadder("t", "above", [(50, 0.10), (100, 0.30), (150, 1.00)])
    assert lad.payout(20) == 0.0
    assert lad.payout(60) == 0.10
    assert lad.payout(120) == 0.30
    assert lad.payout(500) == 1.00                   # capped, not stacked


def test_below_ladder_direction():
    lad = pricing.StrikeLadder("t", "below", [(80, 0.05), (60, 0.30), (40, 1.00)])
    assert lad.payout(90) == 0.0
    assert lad.payout(70) == 0.05
    assert lad.payout(30) == 1.00


def test_ladder_rejects_decreasing_payouts():
    try:
        pricing.StrikeLadder("bad", "above", [(50, 0.50), (100, 0.10)])
    except ValueError:
        return
    raise AssertionError("ladder accepted a payout that falls as severity rises")


def test_phase_max_combine_does_not_double_pay():
    payouts = pd.DataFrame(
        {
            "grid_lat": [23.0] * 3,
            "grid_lon": [74.0] * 3,
            "uwy": [2020] * 3,
            "phase": ["P1", "P2", "P3"],
            "payout_pct_SI": [0.15, 0.30, 0.05],
        }
    )
    out = pricing.combine_phase_payouts(payouts, keys=["grid_lat", "grid_lon", "uwy"], method="max")
    assert abs(out["payout_pct_SI"].iloc[0] - 0.30) < 1e-9


def test_combine_perils_caps_at_sum_insured():
    keys = ["grid_lat", "grid_lon", "uwy"]
    a = pd.DataFrame({"grid_lat": [23.0], "grid_lon": [74.0], "uwy": [2020], "payout_pct_SI": [0.8]})
    b = a.copy()
    b["payout_pct_SI"] = 0.7
    out = pricing.combine_perils([a, b], keys=keys, cap=1.0)
    assert abs(out["payout_pct_SI"].iloc[0] - 1.0) < 1e-9


def test_burn_cost_windows_and_blend():
    years = list(range(1994, 2024))
    losses = pd.DataFrame(
        {"grid_lat": 23.0, "grid_lon": 74.0, "uwy": years, "payout_pct_SI": [0.0] * 20 + [0.3] * 10}
    )
    b = pricing.burn_cost(losses, keys=["grid_lat", "grid_lon"])
    assert abs(b["burn_10y"].iloc[0] - 0.30) < 1e-9          # all recent years paid
    assert abs(b["burn_30y"].iloc[0] - 0.10) < 1e-9
    assert b["burn_blend"].iloc[0] > b["burn_30y"].iloc[0]   # blend picks up the recent signal
    assert b["loss_frequency"].iloc[0] == 10 / 30


def test_commercial_premium_grosses_up():
    priced = pd.DataFrame({"risk_premium": [0.03]})
    out = pricing.commercial_premium(priced, expense_ratio=0.20, reinsurance_margin=0.10, profit_margin=0.05)
    assert abs(out["commercial_premium"].iloc[0] - 0.03 / 0.65) < 1e-9
    assert out["loss_ratio_at_expected"].iloc[0] < 1.0


def test_calibration_hits_target_rate_on_a_dense_index():
    rng = np.random.default_rng(1)
    idx = pd.DataFrame({"index_value": rng.gamma(2.0, 30.0, 4000)})
    ladder, rate = pricing.calibrate_ladder_to_target(idx, "above", target_rate=0.03)
    assert abs(rate - 0.03) < 0.006, rate
    strikes = [s for s, _ in ladder.steps]
    assert strikes == sorted(strikes) and len(set(strikes)) == len(strikes)
    assert min(strikes) > 0                                   # a zero index must never pay


def test_contingency_scores():
    obs = np.array([1, 1, 1, 0, 0, 0], dtype=bool)
    hit = np.array([1, 1, 0, 1, 0, 0], dtype=bool)
    s = validation.contingency_scores(obs, hit)
    assert s["hits"] == 2 and s["misses"] == 1 and s["false_alarms"] == 1
    assert abs(s["POD"] - 2 / 3) < 1e-3
    assert abs(s["FAR"] - 1 / 3) < 1e-3   # 1 false alarm out of 3 firings
    assert abs(s["CSI"] - 0.5) < 1e-3


def test_portfolio_metrics_tail_ordering():
    port = pd.DataFrame({"portfolio_loss": [0.0, 0.01, 0.02, 0.05, 0.40]})
    m = pricing.portfolio_metrics(port)
    assert m["TVaR_95"] >= m["VaR_95"] >= m["expected_loss"]
    assert m["max_loss"] == 0.40


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"  PASS  {t.__name__}")
        except Exception as exc:
            failed += 1
            print(f"  FAIL  {t.__name__}: {exc}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
