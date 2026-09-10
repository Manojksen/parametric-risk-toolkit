"""
Weather index construction.

Every parametric cover in this toolkit follows the same three-step shape:

    daily weather at a grid node
        -> a PHASE (a window of the crop calendar, e.g. 1 Jan - 31 Jan)
            -> a single INDEX number per grid-node per underwriting year

The index is deliberately a scalar: it is the only thing the policy wording
and the payout ladder ever look at. Anything clever has to happen *before*
this point, because after it the contract must be mechanically settleable.

Perils implemented here are the ones that cover the bulk of an agri book:

    excess_rainfall_index   ERI   max n-day accumulation in the phase
    deficit_rainfall_index  WDI   capped-rainfall total (water deficit)
    dry_spell_index         DCW   longest run of consecutive dry days/weeks
    disease_spell_index     Blight/DCW-humid: longest run of days where
                                  temperature AND humidity sit in the
                                  disease-favourable box
    heat_index              Heatwave: days (or longest run) above a threshold
    unseasonal_rain_index   Rain in a window where rain is not expected
"""
from __future__ import annotations

import numpy as np
import pandas as pd

# --------------------------------------------------------------------------
# calendar helpers
# --------------------------------------------------------------------------


def assign_underwriting_year(
    dates: pd.Series, wrap_months: tuple[int, ...] = (1, 2, 3)
) -> pd.Series:
    """Map a date to its underwriting year (UWY).

    A rabi cover running Dec -> Feb spans two calendar years but is ONE
    underwriting year. Months listed in ``wrap_months`` are pulled back to the
    previous calendar year so that a Dec-2023/Feb-2024 season is a single
    UWY 2023 row. Getting this wrong silently halves your event count.
    """
    d = pd.to_datetime(dates)
    return np.where(d.dt.month.isin(wrap_months), d.dt.year - 1, d.dt.year)


def slice_phase(
    df: pd.DataFrame,
    start: str,
    end: str,
    date_col: str = "date",
    wrap_months: tuple[int, ...] = (1, 2, 3),
) -> pd.DataFrame:
    """Cut the daily frame down to one crop-calendar phase, per UWY.

    ``start`` / ``end`` are 'MM-DD' strings, so the same phase definition is
    reused across every historical year. Handles year-wrapping windows
    (e.g. '12-01' -> '02-28') without special-casing leap years.
    """
    out = df.copy()
    out[date_col] = pd.to_datetime(out[date_col])
    out["uwy"] = assign_underwriting_year(out[date_col], wrap_months)

    s_m, s_d = (int(x) for x in start.split("-"))
    e_m, e_d = (int(x) for x in end.split("-"))
    md = out[date_col].dt.month * 100 + out[date_col].dt.day
    s_md, e_md = s_m * 100 + s_d, e_m * 100 + e_d

    mask = (md >= s_md) & (md <= e_md) if s_md <= e_md else (md >= s_md) | (md <= e_md)
    return out.loc[mask].copy()


def _longest_run(flags: np.ndarray) -> int:
    """Longest run of True in a boolean array."""
    best = run = 0
    for f in flags:
        run = run + 1 if f else 0
        best = max(best, run)
    return int(best)


def _group_keys(grid_cols: tuple[str, str]) -> list[str]:
    return [*grid_cols, "uwy"]


# --------------------------------------------------------------------------
# rainfall perils
# --------------------------------------------------------------------------


def excess_rainfall_index(
    daily: pd.DataFrame,
    window_days: int = 5,
    rain_col: str = "rain_mm",
    date_col: str = "date",
    grid_cols: tuple[str, str] = ("grid_lat", "grid_lon"),
) -> pd.DataFrame:
    """ERI: maximum rolling n-day rainfall accumulation inside the phase.

    A 5-day window is the usual agri standard -- it captures the cyclonic /
    depression rainfall that actually flattens a standing crop, while a plain
    phase total would let a wet-but-harmless month trigger the cover.
    """
    df = daily.sort_values([*grid_cols, date_col]).copy()
    df["roll"] = (
        df.groupby(_group_keys(grid_cols), sort=False)[rain_col]
        .transform(lambda s: s.rolling(window_days, min_periods=1).sum())
    )
    out = (
        df.groupby(_group_keys(grid_cols), sort=False)
        .agg(index_value=("roll", "max"), days_observed=(rain_col, "size"))
        .reset_index()
    )
    out["index_name"] = f"ERI_max_{window_days}d_rain_mm"
    return out.round({"index_value": 2})


def deficit_rainfall_index(
    daily: pd.DataFrame,
    daily_cap_mm: float = 50.0,
    rain_col: str = "rain_mm",
    date_col: str = "date",
    grid_cols: tuple[str, str] = ("grid_lat", "grid_lon"),
) -> pd.DataFrame:
    """WDI: total rainfall in the phase, with each day capped.

    The cap is the point of the index. Without it, one 200 mm cloudburst day
    makes a genuinely drought-stricken season look adequately watered -- the
    crop never saw that water, it ran off. Capping at roughly the daily
    infiltration limit keeps the index aligned with plant-available water.
    """
    df = daily.copy()
    df["capped"] = df[rain_col].clip(upper=daily_cap_mm)
    out = (
        df.groupby(_group_keys(grid_cols), sort=False)
        .agg(index_value=("capped", "sum"), days_observed=(rain_col, "size"))
        .reset_index()
    )
    out["index_name"] = f"WDI_capped{int(daily_cap_mm)}mm_total_rain_mm"
    return out.round({"index_value": 2})


def dry_spell_index(
    daily: pd.DataFrame,
    dry_threshold_mm: float = 2.5,
    unit: str = "days",
    rain_col: str = "rain_mm",
    date_col: str = "date",
    grid_cols: tuple[str, str] = ("grid_lat", "grid_lon"),
) -> pd.DataFrame:
    """DCW / dry-spell: longest consecutive run of dry days in the phase.

    ``unit='weeks'`` returns the run in completed 7-day blocks, which is how
    'dry continuous weeks' covers are normally worded.
    """
    df = daily.sort_values([*grid_cols, date_col]).copy()
    df["is_dry"] = df[rain_col] < dry_threshold_mm

    rows = []
    for keys, g in df.groupby(_group_keys(grid_cols), sort=False):
        run = _longest_run(g["is_dry"].to_numpy())
        rows.append((*keys, run // 7 if unit == "weeks" else run, len(g)))

    out = pd.DataFrame(rows, columns=[*_group_keys(grid_cols), "index_value", "days_observed"])
    out["index_name"] = f"DCW_longest_dry_spell_{unit}_lt{dry_threshold_mm}mm"
    return out


def unseasonal_rain_index(
    daily: pd.DataFrame,
    min_daily_mm: float = 10.0,
    rain_col: str = "rain_mm",
    date_col: str = "date",
    grid_cols: tuple[str, str] = ("grid_lat", "grid_lon"),
) -> pd.DataFrame:
    """Unseasonal rainfall: count of meaningfully wet days in a dry-season phase.

    Used for standing/harvested-crop damage covers where the loss driver is
    rain happening at all, not how much fell.
    """
    df = daily.copy()
    df["wet"] = (df[rain_col] >= min_daily_mm).astype(int)
    out = (
        df.groupby(_group_keys(grid_cols), sort=False)
        .agg(index_value=("wet", "sum"), days_observed=(rain_col, "size"))
        .reset_index()
    )
    out["index_name"] = f"UNSEASONAL_wet_days_ge{min_daily_mm}mm"
    return out


# --------------------------------------------------------------------------
# temperature / humidity perils
# --------------------------------------------------------------------------


def disease_spell_index(
    daily: pd.DataFrame,
    temp_range: tuple[float, float] = (10.0, 20.0),
    rh_min: float = 80.0,
    temp_col: str = "t2m_c",
    rh_col: str = "rh_pct",
    date_col: str = "date",
    grid_cols: tuple[str, str] = ("grid_lat", "grid_lon"),
) -> pd.DataFrame:
    """Blight-type disease index: longest run of disease-favourable days.

    A day is 'conducive' when mean temperature sits inside the pathogen's
    window AND relative humidity is at or above the sporulation threshold.
    Late blight in potato is the classic case (~10-20 C with RH >= 80%);
    the same shape re-parameterises for cumin blight, downy mildew, etc.

    The index is the longest CONSECUTIVE run, not the total count, because
    infection needs sustained leaf wetness -- twenty scattered conducive days
    do far less than eight back-to-back ones.
    """
    df = daily.sort_values([*grid_cols, date_col]).copy()
    lo, hi = temp_range
    df["conducive"] = (df[temp_col].between(lo, hi)) & (df[rh_col] >= rh_min)

    rows = []
    for keys, g in df.groupby(_group_keys(grid_cols), sort=False):
        flags = g["conducive"].to_numpy()
        rows.append((*keys, _longest_run(flags), int(flags.sum()), len(g)))

    out = pd.DataFrame(
        rows,
        columns=[*_group_keys(grid_cols), "index_value", "conducive_days", "days_observed"],
    )
    out["index_name"] = f"BLIGHT_max_spell_T{lo}-{hi}C_RHge{rh_min}"
    return out


def heat_index(
    daily: pd.DataFrame,
    threshold_c: float = 34.0,
    mode: str = "count",
    temp_col: str = "tmax_c",
    date_col: str = "date",
    grid_cols: tuple[str, str] = ("grid_lat", "grid_lon"),
) -> pd.DataFrame:
    """Heatwave index: days above a threshold, or the longest such run.

    Terminal heat in wheat is the standard use: grain filling collapses when
    Tmax sits above ~34 C during Feb-Apr, so the index counts those days in
    the grain-filling phase only.
    """
    df = daily.sort_values([*grid_cols, date_col]).copy()
    df["hot"] = df[temp_col] >= threshold_c

    rows = []
    for keys, g in df.groupby(_group_keys(grid_cols), sort=False):
        flags = g["hot"].to_numpy()
        val = _longest_run(flags) if mode == "spell" else int(flags.sum())
        rows.append((*keys, val, len(g)))

    out = pd.DataFrame(rows, columns=[*_group_keys(grid_cols), "index_value", "days_observed"])
    out["index_name"] = f"HEAT_{mode}_ge{threshold_c}C"
    return out


# --------------------------------------------------------------------------
# cyclone
# --------------------------------------------------------------------------


def cyclone_proximity_index(
    tracks: pd.DataFrame,
    locations: pd.DataFrame,
    radius_km: float = 100.0,
    lat_col: str = "lat",
    lon_col: str = "lon",
    wind_col: str = "wind_kt",
    season_col: str = "season",
) -> pd.DataFrame:
    """Max sustained wind of any cyclone track point passing within a radius.

    Track data (IBTrACS-style: one row per 3/6-hourly fix) is reduced to, per
    location per season, the strongest wind observed inside the circle. That
    single number is what the wind ladder settles on -- no damage model, no
    adjuster, which is the whole point of a parametric cyclone cover.
    """
    from .gridding import haversine_matrix

    d = haversine_matrix(
        locations[lat_col], locations[lon_col], tracks[lat_col], tracks[lon_col]
    )
    inside = d <= radius_km
    winds = tracks[wind_col].to_numpy(dtype=float)
    seasons = tracks[season_col].to_numpy()

    rows = []
    for i in range(len(locations)):
        sel = inside[i]
        loc = locations.iloc[i]
        if not sel.any():
            continue
        s = pd.DataFrame({"season": seasons[sel], "wind": winds[sel]})
        for season, grp in s.groupby("season"):
            rows.append(
                {
                    "location_id": loc.get("location_id", i),
                    lat_col: loc[lat_col],
                    lon_col: loc[lon_col],
                    "uwy": int(season),
                    "index_value": float(grp["wind"].max()),
                    "track_points_in_radius": int(len(grp)),
                }
            )

    out = pd.DataFrame(rows)
    if not out.empty:
        out["index_name"] = f"CYCLONE_max_wind_kt_within_{int(radius_km)}km"
    return out
