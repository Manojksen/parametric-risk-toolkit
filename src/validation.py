"""
Dataset selection and index validation.

The single largest source of basis risk in a parametric cover is not the
payout ladder -- it is choosing a dataset that does not see the event the
farmer lived through. Before any product was priced, the working rule was:

    1. Build a short list of documented events for the region
       (cyclone landfalls, cloudburst dates, declared drought years,
       state agriculture-department loss notifications, credible news reports).
    2. Run every candidate dataset -- IMD gridded, IMD/AWS station, ERA5,
       ERA5-Land, CHIRPS, CMORPH, TAMSAT, national met service -- over those
       dates and check whether the index would have fired.
    3. Score them, then write the product on the dataset that captures the
       events AND is operationally settleable (published on time, versioned,
       no retro-revision after settlement).

This module is that step, made reproducible.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def contingency_scores(observed_hit: np.ndarray, dataset_hit: np.ndarray) -> dict:
    """POD / FAR / CSI / bias for a candidate dataset against known events.

    POD (probability of detection) -- of the events that really happened, what
        share did this dataset see? Low POD means unpaid genuine losses, which
        is how a parametric programme loses its distribution partner.
    FAR (false alarm ratio) -- of the times this dataset fired, what share had
        no real event? High FAR means paying for nothing, which is how it loses
        its reinsurer.
    CSI (critical success index) -- the combined score; this is the one to rank on.
    """
    o = np.asarray(observed_hit, dtype=bool)
    d = np.asarray(dataset_hit, dtype=bool)

    hits = int((o & d).sum())
    misses = int((o & ~d).sum())
    false_alarms = int((~o & d).sum())
    correct_neg = int((~o & ~d).sum())

    pod = hits / (hits + misses) if (hits + misses) else np.nan
    far = false_alarms / (hits + false_alarms) if (hits + false_alarms) else np.nan
    csi = hits / (hits + misses + false_alarms) if (hits + misses + false_alarms) else np.nan
    bias = (hits + false_alarms) / (hits + misses) if (hits + misses) else np.nan

    return {
        "hits": hits,
        "misses": misses,
        "false_alarms": false_alarms,
        "correct_negatives": correct_neg,
        "POD": round(pod, 3) if pod == pod else np.nan,
        "FAR": round(far, 3) if far == far else np.nan,
        "CSI": round(csi, 3) if csi == csi else np.nan,
        "frequency_bias": round(bias, 3) if bias == bias else np.nan,
    }


def event_capture_table(
    candidates: dict[str, pd.DataFrame],
    known_events: pd.DataFrame,
    index_col: str = "index_value",
    trigger_col: str = "trigger",
    key_cols: tuple[str, ...] = ("unit", "uwy"),
) -> pd.DataFrame:
    """Score every candidate dataset against a list of documented events.

    ``candidates``   name -> index frame carrying ``key_cols`` and ``index_col``
    ``known_events`` frame with ``key_cols``, a boolean ``event_occurred`` and
                     a ``source`` note (report / bulletin / news reference)
    ``trigger_col``  threshold above which the dataset is said to have seen it
    """
    rows = []
    for name, df in candidates.items():
        merged = known_events.merge(df, on=list(key_cols), how="left")
        dataset_hit = merged[index_col].fillna(-np.inf) >= merged[trigger_col]
        scores = contingency_scores(merged["event_occurred"].to_numpy(), dataset_hit.to_numpy())
        scores["dataset"] = name
        scores["events_checked"] = int(len(merged))
        rows.append(scores)

    out = pd.DataFrame(rows)
    cols = ["dataset", "events_checked", "hits", "misses", "false_alarms", "POD", "FAR", "CSI", "frequency_bias"]
    return out[cols].sort_values("CSI", ascending=False).reset_index(drop=True)


def compare_to_reference(
    candidate: pd.Series, reference: pd.Series, wet_threshold: float = 2.5
) -> dict:
    """Bias / RMSE / correlation of a gridded product against station truth.

    Run per grid node against its nearest usable station before the dataset is
    frozen into the wording. Gridded reanalysis is systematically wetter on
    drizzle days and flatter on extremes -- if that bias is not measured, it
    reappears as an unexplained gap between modelled and settled losses.
    """
    df = pd.DataFrame({"cand": candidate, "ref": reference}).dropna()
    if df.empty:
        return {}
    err = df["cand"] - df["ref"]
    cand_wet = df["cand"] >= wet_threshold
    ref_wet = df["ref"] >= wet_threshold
    return {
        "n": int(len(df)),
        "mean_reference": round(float(df["ref"].mean()), 3),
        "mean_candidate": round(float(df["cand"].mean()), 3),
        "bias": round(float(err.mean()), 3),
        "mae": round(float(err.abs().mean()), 3),
        "rmse": round(float(np.sqrt((err ** 2).mean())), 3),
        "pearson_r": round(float(df["cand"].corr(df["ref"])), 3),
        "wet_day_agreement": round(float((cand_wet == ref_wet).mean()), 3),
        "p95_candidate": round(float(df["cand"].quantile(0.95)), 3),
        "p95_reference": round(float(df["ref"].quantile(0.95)), 3),
    }


def index_stability(
    index_df: pd.DataFrame,
    year_col: str = "uwy",
    value_col: str = "index_value",
    split_year: int | None = None,
) -> dict:
    """Has the index distribution shifted between the early and recent record?

    A cover priced off 33 years is only defensible if the peril is roughly
    stationary. When the recent half is materially heavier, the 30-year burn
    cost understates the rate and the trailing 10-year window has to carry
    more weight -- or the strikes have to move.
    """
    df = index_df[[year_col, value_col]].dropna()
    if df.empty:
        return {}
    split = split_year or int(df[year_col].median())
    early = df.loc[df[year_col] <= split, value_col]
    recent = df.loc[df[year_col] > split, value_col]
    if early.empty or recent.empty:
        return {}

    mean_shift = float(recent.mean() - early.mean())
    return {
        "split_year": int(split),
        "early_mean": round(float(early.mean()), 3),
        "recent_mean": round(float(recent.mean()), 3),
        "mean_shift": round(mean_shift, 3),
        "mean_shift_pct": round(mean_shift / early.mean() * 100, 2) if early.mean() else np.nan,
        "early_p90": round(float(early.quantile(0.90)), 3),
        "recent_p90": round(float(recent.quantile(0.90)), 3),
        "flag": "non-stationary" if abs(mean_shift) > 0.15 * abs(early.mean() or 1) else "stable",
    }


def basis_risk_report(
    modelled_loss: pd.Series, reported_loss: pd.Series, tolerance: float = 0.10
) -> dict:
    """Compare index payouts against reported ground loss, where available.

    Two failure modes matter and they are not symmetric: an unpaid real loss
    ('false negative') destroys trust with the insured, an overpaid non-loss
    destroys the loss ratio. Both are reported separately.
    """
    df = pd.DataFrame({"modelled": modelled_loss, "reported": reported_loss}).dropna()
    if df.empty:
        return {}
    gap = df["modelled"] - df["reported"]
    return {
        "n": int(len(df)),
        "mean_modelled": round(float(df["modelled"].mean()), 4),
        "mean_reported": round(float(df["reported"].mean()), 4),
        "mean_gap": round(float(gap.mean()), 4),
        "within_tolerance_pct": round(float((gap.abs() <= tolerance).mean() * 100), 2),
        "false_negative_pct": round(float(((df["reported"] > tolerance) & (df["modelled"] <= 0.001)).mean() * 100), 2),
        "false_positive_pct": round(float(((df["modelled"] > tolerance) & (df["reported"] <= 0.001)).mean() * 100), 2),
        "correlation": round(float(df["modelled"].corr(df["reported"])), 3),
    }
