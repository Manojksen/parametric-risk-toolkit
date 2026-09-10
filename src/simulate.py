"""
Synthetic weather and exposure generator.

Every dataset in this repository is generated here. No client data, no
licensed reanalysis extract and no book of business is included -- the point
of the repo is the method, and the method has to be runnable by anyone who
clones it.

The generator is not noise. It reproduces the structure that actually makes
index design hard:

  * a monsoon-shaped seasonal cycle, so phases matter
  * a shared year effect across grid nodes, so a bad year is bad everywhere
    (spatially correlated loss is what makes an agri portfolio uncedeable
    without reinsurance)
  * a mixed rainfall distribution -- many dry days, a gamma-ish wet tail --
    so extremes exist and capping/rolling windows change the answer
  * a mild warming and drying trend, so stationarity tests have something to find
  * a second 'satellite' dataset with wet-drizzle bias and flattened extremes,
    so dataset comparison is a real exercise
"""
from __future__ import annotations

import numpy as np
import pandas as pd

RNG_SEED = 20240115


def make_grid(lat_range=(22.0, 24.5), lon_range=(72.0, 74.5), step: float = 0.5) -> pd.DataFrame:
    """A regular lat/lon grid, IMD-style (0.25 deg rainfall, 0.5/1.0 deg temperature)."""
    lats = np.round(np.arange(lat_range[0], lat_range[1] + 1e-9, step), 3)
    lons = np.round(np.arange(lon_range[0], lon_range[1] + 1e-9, step), 3)
    mesh = [(la, lo) for la in lats for lo in lons]
    df = pd.DataFrame(mesh, columns=["grid_lat", "grid_lon"])
    df["grid_id"] = [f"G{i:04d}" for i in range(len(df))]
    return df


def make_enrollments(grid: pd.DataFrame, n: int = 1200, districts=("Alwar", "Kota", "Bhilwara", "Ajmer"), seed: int = RNG_SEED) -> pd.DataFrame:
    """Policy locations scattered over the grid footprint, with sum insured.

    Locations are deliberately NOT placed on grid nodes -- that offset is the
    snap distance, and the snap distance is basis risk.
    """
    rng = np.random.default_rng(seed)
    lat_lo, lat_hi = grid["grid_lat"].min(), grid["grid_lat"].max()
    lon_lo, lon_hi = grid["grid_lon"].min(), grid["grid_lon"].max()

    df = pd.DataFrame(
        {
            "location_id": [f"L{i:05d}" for i in range(n)],
            "state": "RAJASTHAN",
            "district": rng.choice(districts, n),
            "latitude": np.round(rng.uniform(lat_lo, lat_hi, n), 4),
            "longitude": np.round(rng.uniform(lon_lo, lon_hi, n), 4),
            "crop": rng.choice(["Cumin", "Wheat", "Mustard"], n, p=[0.45, 0.35, 0.20]),
            "area_ha": np.round(rng.gamma(2.0, 0.6, n) + 0.2, 2),
        }
    )
    df["sum_insured"] = np.round(df["area_ha"] * rng.uniform(28000, 42000, n), 0)
    return df


def _seasonal_rain_mean(doy: np.ndarray) -> np.ndarray:
    """Monsoon-shaped climatology: sharp Jun-Sep peak, dry rabi season."""
    monsoon = 9.0 * np.exp(-0.5 * ((doy - 205) / 33.0) ** 2)
    winter = 0.5 * np.exp(-0.5 * ((doy - 20) / 28.0) ** 2)
    return monsoon + winter + 0.12


def simulate_daily_weather(
    grid: pd.DataFrame,
    start_year: int = 1990,
    end_year: int = 2023,
    seed: int = RNG_SEED,
    warming_c_per_decade: float = 0.22,
) -> pd.DataFrame:
    """Daily rain / Tmax / Tmin / T2m / RH for every grid node."""
    rng = np.random.default_rng(seed)
    dates = pd.date_range(f"{start_year}-01-01", f"{end_year}-12-31", freq="D")
    doy = dates.dayofyear.to_numpy()
    year = dates.year.to_numpy()

    n_days, n_grid = len(dates), len(grid)

    # shared year effect: one wet/dry signal felt by every node in that year
    year_effect = {y: rng.normal(0.0, 0.30) for y in range(start_year, end_year + 1)}
    ye = np.array([year_effect[y] for y in year])

    clim = _seasonal_rain_mean(doy)
    wet_prob = np.clip(0.06 + 0.42 * (clim / clim.max()) + 0.05 * ye, 0.01, 0.85)

    lat_gradient = (grid["grid_lat"].to_numpy() - grid["grid_lat"].mean()) * 0.10

    frames = []
    for j, (_, node) in enumerate(grid.iterrows()):
        local = rng.normal(0.0, 0.10, n_days)
        p_wet = np.clip(wet_prob + lat_gradient[j] * 0.05 + local * 0.02, 0.005, 0.9)
        wet = rng.random(n_days) < p_wet

        scale = clim * (1.0 + 0.35 * ye) * (1.0 - 0.03 * (year - start_year) / 30.0)
        amount = rng.gamma(shape=0.85, scale=np.maximum(scale, 0.05) * 2.4)
        rain = np.where(wet, amount, 0.0)
        # occasional cloudburst: the tail the 5-day ERI window exists to catch
        burst = rng.random(n_days) < 0.0022
        rain = rain + burst * rng.gamma(2.2, 26.0, n_days)

        temp_season = 24.0 + 8.5 * np.sin(2 * np.pi * (doy - 105) / 365.25)
        trend = warming_c_per_decade * (year - start_year) / 10.0
        tmax = temp_season + 8.0 + trend + rng.normal(0, 2.1, n_days) - 0.05 * np.minimum(rain, 40)
        tmin = temp_season - 6.5 + trend + rng.normal(0, 1.8, n_days)
        t2m = (tmax + tmin) / 2.0
        # Relative humidity carries a winter fog bump (real over north-west
        # India in Dec-Jan) and an AR(1) anomaly, so humid conditions arrive in
        # multi-day SPELLS rather than isolated days. Without that persistence
        # a disease index built on consecutive conducive days is degenerate.
        winter_bump = 13.0 * np.exp(-0.5 * (((doy + 15) % 365 - 30) / 34.0) ** 2)
        rh_base = 52.0 + 15.0 * np.sin(2 * np.pi * (doy - 200) / 365.25) + winter_bump
        shock = rng.normal(0, 8.0, n_days)
        anom = np.zeros(n_days)
        for t in range(1, n_days):
            anom[t] = 0.78 * anom[t - 1] + shock[t]
        rh = np.clip(rh_base + anom * 0.75 + 0.85 * np.minimum(rain, 30), 12, 100)

        frames.append(
            pd.DataFrame(
                {
                    "date": dates,
                    "grid_lat": node["grid_lat"],
                    "grid_lon": node["grid_lon"],
                    "grid_id": node["grid_id"],
                    "rain_mm": np.round(rain, 2),
                    "tmax_c": np.round(tmax, 2),
                    "tmin_c": np.round(tmin, 2),
                    "t2m_c": np.round(t2m, 2),
                    "rh_pct": np.round(rh, 1),
                }
            )
        )
    return pd.concat(frames, ignore_index=True)


def perturb_as_alternate_dataset(
    daily: pd.DataFrame, seed: int = 77, drizzle_bias: float = 0.9, extreme_damping: float = 0.72
) -> pd.DataFrame:
    """Second candidate dataset with realistic gridded-product biases.

    Satellite and reanalysis rainfall products share two well-documented
    failure modes: they invent light rain on dry days, and they smear extremes
    across the grid box so peak accumulations come out low. Both are applied
    here so the dataset-selection step in ``validation.py`` has a genuine
    choice to make rather than two copies of the same series.
    """
    rng = np.random.default_rng(seed)
    out = daily.copy()
    r = out["rain_mm"].to_numpy(dtype=float)

    dry = r < 0.5
    r = np.where(dry, np.abs(rng.normal(0, drizzle_bias, r.size)) * (rng.random(r.size) < 0.35), r)
    heavy = r > 40
    r = np.where(heavy, 40 + (r - 40) * extreme_damping, r)
    r = r * rng.normal(1.0, 0.07, r.size)

    out["rain_mm"] = np.round(np.clip(r, 0, None), 2)
    out["tmax_c"] = np.round(out["tmax_c"] + rng.normal(-0.35, 0.5, len(out)), 2)
    out["source"] = "ALT_GRIDDED"
    return out


def simulate_cyclone_tracks(
    n_seasons: int = 30, start_season: int = 1994, seed: int = 5, lat_c: float = 18.5, lon_c: float = 74.0
) -> pd.DataFrame:
    """IBTrACS-shaped track fixes: one row per storm position, with wind speed."""
    rng = np.random.default_rng(seed)
    rows = []
    for s in range(start_season, start_season + n_seasons):
        for storm in range(rng.poisson(1.6) + 1):
            n_fix = rng.integers(14, 40)
            lat0 = lat_c + rng.normal(-3.0, 2.2)
            lon0 = lon_c + rng.normal(2.5, 2.5)
            peak = float(np.clip(rng.gamma(4.2, 13.0), 25, 165))
            for k in range(n_fix):
                frac = k / max(n_fix - 1, 1)
                rows.append(
                    {
                        "season": s,
                        "storm_id": f"{s}_{storm}",
                        "lat": round(lat0 + frac * rng.normal(4.5, 1.0), 3),
                        "lon": round(lon0 - frac * rng.normal(3.0, 1.0), 3),
                        "wind_kt": round(peak * np.sin(np.pi * min(frac * 1.15, 1.0)) + rng.normal(0, 4), 1),
                    }
                )
    df = pd.DataFrame(rows)
    df["wind_kt"] = df["wind_kt"].clip(lower=15)
    return df
