"""
Enrollment -> weather-grid mapping.

In a parametric book the policy is written on a *location*, but the weather
observation lives on a *grid node* (IMD 0.25 deg rain, IMD 0.5/1.0 deg temp,
ERA5 0.25 deg, CHIRPS 0.05 deg ...). Every enrolled village/farm must be
snapped to the nearest node of the chosen product grid before any index is
built, and the snap distance must be auditable -- a 60 km snap on a convective
rainfall peril is a basis-risk problem, not a rounding detail.

Pure numpy haversine so the module has no heavy geospatial dependency.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

EARTH_RADIUS_KM = 6371.0088


def haversine_matrix(lat1, lon1, lat2, lon2) -> np.ndarray:
    """Pairwise great-circle distance (km) between two coordinate sets."""
    lat1 = np.radians(np.asarray(lat1, dtype=float))[:, None]
    lon1 = np.radians(np.asarray(lon1, dtype=float))[:, None]
    lat2 = np.radians(np.asarray(lat2, dtype=float))[None, :]
    lon2 = np.radians(np.asarray(lon2, dtype=float))[None, :]

    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = np.sin(dlat / 2.0) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin(dlon / 2.0) ** 2
    return 2.0 * EARTH_RADIUS_KM * np.arcsin(np.sqrt(np.clip(a, 0.0, 1.0)))


def snap_to_grid(
    enrollments: pd.DataFrame,
    grid: pd.DataFrame,
    lat_col: str = "latitude",
    lon_col: str = "longitude",
    grid_lat_col: str = "grid_lat",
    grid_lon_col: str = "grid_lon",
    max_distance_km: float | None = 40.0,
    chunk: int = 4000,
) -> pd.DataFrame:
    """Attach the nearest grid node to every enrollment row.

    Returns the enrollment frame plus ``grid_lat``, ``grid_lon``,
    ``snap_distance_km`` and ``snap_flag`` ('ok' / 'far' / 'unmapped').
    Rows beyond ``max_distance_km`` are kept but flagged, never dropped
    silently -- underwriting needs to see them.
    """
    if enrollments.empty or grid.empty:
        raise ValueError("enrollments and grid must both be non-empty")

    g_lat = grid[grid_lat_col].to_numpy(dtype=float)
    g_lon = grid[grid_lon_col].to_numpy(dtype=float)

    idx_out = np.empty(len(enrollments), dtype=int)
    dist_out = np.empty(len(enrollments), dtype=float)

    lat = enrollments[lat_col].to_numpy(dtype=float)
    lon = enrollments[lon_col].to_numpy(dtype=float)

    for start in range(0, len(enrollments), chunk):
        stop = min(start + chunk, len(enrollments))
        d = haversine_matrix(lat[start:stop], lon[start:stop], g_lat, g_lon)
        idx_out[start:stop] = d.argmin(axis=1)
        dist_out[start:stop] = d.min(axis=1)

    out = enrollments.copy()
    out[grid_lat_col] = g_lat[idx_out]
    out[grid_lon_col] = g_lon[idx_out]
    out["snap_distance_km"] = np.round(dist_out, 2)

    if max_distance_km is None:
        out["snap_flag"] = "ok"
    else:
        out["snap_flag"] = np.where(out["snap_distance_km"] <= max_distance_km, "ok", "far")
    return out


def grid_exposure_weights(
    mapped: pd.DataFrame,
    by: list[str] | None = None,
    sum_insured_col: str | None = None,
    grid_cols: tuple[str, str] = ("grid_lat", "grid_lon"),
) -> pd.DataFrame:
    """Exposure weight of each grid node inside its administrative unit.

    Weight = share of sum insured (or share of enrolled locations when no SI
    column is given). These weights are what turn a grid-level index into a
    district- or department-level loss.
    """
    by = by or ["state", "district"]
    keys = by + list(grid_cols)

    if sum_insured_col:
        agg = mapped.groupby(keys, dropna=False)[sum_insured_col].sum().rename("exposure")
    else:
        agg = mapped.groupby(keys, dropna=False).size().rename("exposure")

    df = agg.reset_index()
    # weight WITHIN the administrative unit -- used to roll a grid index up to a
    # district loss for the client-facing loss summary
    df["weight"] = df["exposure"] / df.groupby(by, dropna=False)["exposure"].transform("sum")
    # weight across the WHOLE book -- used for portfolio aggregation. A grid node
    # straddling two districts appears twice above, so the book weight must be
    # taken on the total, never by summing the within-unit weights.
    df["book_weight"] = df["exposure"] / df["exposure"].sum()
    return df


def book_weights(weights: pd.DataFrame, grid_cols: tuple[str, str] = ("grid_lat", "grid_lon")) -> pd.DataFrame:
    """Collapse per-unit weights to one exposure share per grid node (sums to 1)."""
    out = weights.groupby(list(grid_cols), dropna=False)["exposure"].sum().reset_index()
    out["weight"] = out["exposure"] / out["exposure"].sum()
    return out


def snap_quality_report(mapped: pd.DataFrame, by: list[str] | None = None) -> pd.DataFrame:
    """Per-unit snap diagnostics -- the table that goes to the underwriter."""
    by = by or ["state", "district"]
    rep = mapped.groupby(by, dropna=False).agg(
        locations=("snap_distance_km", "size"),
        mean_snap_km=("snap_distance_km", "mean"),
        p95_snap_km=("snap_distance_km", lambda s: float(np.percentile(s, 95))),
        max_snap_km=("snap_distance_km", "max"),
        far_locations=("snap_flag", lambda s: int((s == "far").sum())),
    )
    rep["far_pct"] = (rep["far_locations"] / rep["locations"] * 100).round(2)
    return rep.round(2).reset_index()
