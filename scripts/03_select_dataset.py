"""
Step 2 - decide which dataset the product is written on.

Two candidates, same index definition, same strike. The one that sees the
documented events with fewer false alarms wins. Stationarity and station-bias
diagnostics are reported alongside, because a dataset can score well on events
and still be unusable if it drifts.
"""
import numpy as np
import pandas as pd
from _bootstrap import OUT
from _loaders import load_daily
from src import indices, validation

PHASE = ("06-01", "09-30")          # kharif rainfall phase
ERI_TRIGGER_MM = 120.0              # 5-day accumulation that defines "an event"

def _phase_index(daily: pd.DataFrame) -> pd.DataFrame:
    ph = indices.slice_phase(daily, *PHASE, wrap_months=())
    idx = indices.excess_rainfall_index(ph, window_days=5)
    idx["unit"] = idx["grid_lat"].round(2).astype(str) + "_" + idx["grid_lon"].round(2).astype(str)
    return idx

def main() -> None:
    primary, alt = load_daily("primary"), load_daily("alternate")
    idx_p, idx_a = _phase_index(primary), _phase_index(alt)

    # ---- the "documented event list" -------------------------------------
    # In production this list is built by hand: IMD bulletins, state
    # agriculture-department loss notifications, reinsurer event reports and
    # dated news coverage. Here the true event is taken from the underlying
    # process both datasets are noisy observations of.
    truth = idx_p.merge(idx_a, on=["unit", "uwy"], suffixes=("_p", "_a"))
    truth["event_occurred"] = (truth["index_value_p"] + truth["index_value_a"]) / 2 >= ERI_TRIGGER_MM
    known_events = truth[["unit", "uwy", "event_occurred"]].copy()
    known_events["trigger"] = ERI_TRIGGER_MM
    known_events["source"] = "met bulletin / loss notification (illustrative)"

    scores = validation.event_capture_table(
        {"PRIMARY_GRIDDED": idx_p, "ALT_GRIDDED": idx_a}, known_events
    )

    # ---- bias against a reference series ---------------------------------
    node = primary["grid_id"].iloc[0]
    ref = primary.loc[primary["grid_id"] == node, "rain_mm"].reset_index(drop=True)
    cand = alt.loc[alt["grid_id"] == node, "rain_mm"].reset_index(drop=True)
    bias = validation.compare_to_reference(cand, ref)

    stability = validation.index_stability(idx_p)

    scores.to_csv(OUT / "02_dataset_event_capture.csv", index=False)
    pd.DataFrame([bias]).to_csv(OUT / "02_dataset_bias_vs_reference.csv", index=False)
    pd.DataFrame([stability]).to_csv(OUT / "02_index_stationarity.csv", index=False)

    print("EVENT CAPTURE (ranked by CSI)")
    print(scores.to_string(index=False))
    print("\nALT dataset vs PRIMARY at one node")
    for k, v in bias.items():
        print(f"  {k:<20} {v}")
    print("\nINDEX STATIONARITY (primary)")
    for k, v in stability.items():
        print(f"  {k:<20} {v}")
    print(f"\n-> writing the cover on: {scores.iloc[0]['dataset']}")

if __name__ == "__main__":
    main()
