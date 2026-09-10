"""
Payout structures and pricing.

Once an index exists, pricing a parametric cover is three questions:

    1. What does the index pay?          -> a strike ladder (payout_from_ladder)
    2. What would it have paid?          -> historical burn cost (burn_cost)
    3. What do we charge for that?       -> risk + commercial premium

Convention throughout: losses and payouts are expressed as a FRACTION OF SUM
INSURED (0.30 = 30% of SI), never in currency. That keeps a Rajasthan cumin
cover and a Honduran coffee cover on the same scale and lets them sit in one
portfolio table.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd


@dataclass
class StrikeLadder:
    """A step payout ladder.

    ``direction='above'`` -> excess perils (ERI, heat, cyclone wind): the index
    exceeding a strike triggers that step.
    ``direction='below'`` -> deficit perils (WDI, capped rainfall): the index
    falling below a strike triggers.

    Steps are held as (strike, payout_fraction_of_SI) and the realised payout
    is the payout of the DEEPEST step breached -- ladders do not stack.
    """

    name: str
    direction: str  # 'above' | 'below'
    steps: list[tuple[float, float]] = field(default_factory=list)
    max_payout: float = 1.0

    def __post_init__(self) -> None:
        if self.direction not in {"above", "below"}:
            raise ValueError("direction must be 'above' or 'below'")
        if not self.steps:
            raise ValueError(f"ladder '{self.name}' has no steps")
        reverse = self.direction == "below"
        self.steps = sorted(self.steps, key=lambda s: s[0], reverse=reverse)
        payouts = [p for _, p in self.steps]
        if payouts != sorted(payouts):
            raise ValueError(f"ladder '{self.name}': payouts must increase with severity")
        if max(payouts) > self.max_payout:
            raise ValueError(f"ladder '{self.name}': payout exceeds max_payout")

    def payout(self, index_value: float) -> float:
        if index_value is None or (isinstance(index_value, float) and np.isnan(index_value)):
            return 0.0
        hit = 0.0
        for strike, pay in self.steps:
            breached = index_value >= strike if self.direction == "above" else index_value <= strike
            if breached:
                hit = pay
        return float(min(hit, self.max_payout))

    def to_frame(self) -> pd.DataFrame:
        op = ">=" if self.direction == "above" else "<="
        return pd.DataFrame(
            {
                "step": [f"Strike {i + 1} ({op})" for i in range(len(self.steps))],
                "strike": [s for s, _ in self.steps],
                "payout_pct_SI": [round(p * 100, 2) for _, p in self.steps],
            }
        )


def apply_ladder(index_df: pd.DataFrame, ladder: StrikeLadder, value_col: str = "index_value") -> pd.DataFrame:
    """Turn an index table into a payout table."""
    out = index_df.copy()
    out["payout_pct_SI"] = out[value_col].apply(ladder.payout)
    out["ladder"] = ladder.name
    return out


def combine_phase_payouts(
    payouts: pd.DataFrame,
    keys: list[str],
    phase_col: str = "phase",
    method: str = "max",
    cap: float = 1.0,
) -> pd.DataFrame:
    """Collapse several phases of one peril into one loss per unit per UWY.

    ``method='max'``  -> only the worst phase pays (standard for ERI covers,
                         keeps the rate down and avoids double-paying one event
                         that straddles a phase boundary).
    ``method='sum'``  -> phases are independent and additive, capped at ``cap``.
    """
    agg = "max" if method == "max" else "sum"
    out = payouts.groupby(keys, dropna=False)["payout_pct_SI"].agg(agg).reset_index()
    out["payout_pct_SI"] = out["payout_pct_SI"].clip(upper=cap)
    out["combine_method"] = method
    return out


def combine_perils(frames: list[pd.DataFrame], keys: list[str], cap: float = 1.0) -> pd.DataFrame:
    """Add up independent perils (e.g. WDI + ERI) on the same policy, capped at SI."""
    merged = None
    for i, f in enumerate(frames):
        f = f[keys + ["payout_pct_SI"]].rename(columns={"payout_pct_SI": f"peril_{i}"})
        merged = f if merged is None else merged.merge(f, on=keys, how="outer")
    peril_cols = [c for c in merged.columns if c.startswith("peril_")]
    merged[peril_cols] = merged[peril_cols].fillna(0.0)
    merged["payout_pct_SI"] = merged[peril_cols].sum(axis=1).clip(upper=cap)
    return merged


# --------------------------------------------------------------------------
# burn cost and premium
# --------------------------------------------------------------------------


def burn_cost(
    losses: pd.DataFrame,
    keys: list[str],
    year_col: str = "uwy",
    loss_col: str = "payout_pct_SI",
    windows: tuple[int, ...] = (10, 20, 30),
) -> pd.DataFrame:
    """Historical burn cost per unit over trailing windows, plus the blend.

    Three windows, then their simple average, is the market-standard compromise:
    the 10-year mean carries the current climate signal, the 30-year mean carries
    enough tail events to be stable, and averaging them stops either from
    dominating the rate. ``max_loss`` is reported alongside because a rate of 2%
    means something very different when the worst year paid 15% than when it
    paid 100%.
    """
    rows = []
    latest = int(losses[year_col].max())
    for key_vals, g in losses.groupby(keys, dropna=False):
        key_vals = key_vals if isinstance(key_vals, tuple) else (key_vals,)
        rec = dict(zip(keys, key_vals))
        for w in windows:
            sel = g[g[year_col] > latest - w]
            rec[f"burn_{w}y"] = float(sel[loss_col].mean()) if len(sel) else np.nan
        rec["burn_blend"] = float(np.nanmean([rec[f"burn_{w}y"] for w in windows]))
        rec["max_loss"] = float(g[loss_col].max())
        rec["loss_years"] = int((g[loss_col] > 0).sum())
        rec["years_observed"] = int(g[year_col].nunique())
        rec["loss_frequency"] = rec["loss_years"] / max(rec["years_observed"], 1)
        rows.append(rec)
    return pd.DataFrame(rows)


def risk_premium(
    burn: pd.DataFrame,
    base_col: str = "burn_blend",
    volatility_loading: float = 0.25,
    losses: pd.DataFrame | None = None,
    keys: list[str] | None = None,
    loss_col: str = "payout_pct_SI",
) -> pd.DataFrame:
    """Risk premium = expected loss + a loading for its own uncertainty.

    The blended burn cost is only a point estimate of the mean off ~30 draws.
    Loading a multiple of the standard error (default 0.25 sigma/sqrt(n)-style
    via the loss standard deviation) is what stops a quiet 30-year sample from
    being sold at a rate the first real event wipes out.
    """
    out = burn.copy()
    if losses is not None and keys:
        sd = (
            losses.groupby(keys, dropna=False)[loss_col]
            .agg(["std", "count"])
            .rename(columns={"std": "loss_sd", "count": "n_years"})
            .reset_index()
        )
        out = out.merge(sd, on=keys, how="left")
        out["loss_sd"] = out["loss_sd"].fillna(0.0)
        out["uncertainty_load"] = volatility_loading * out["loss_sd"] / np.sqrt(out["n_years"].clip(lower=1))
    else:
        out["uncertainty_load"] = volatility_loading * out[base_col]

    out["risk_premium"] = out[base_col] + out["uncertainty_load"]
    return out


def commercial_premium(
    priced: pd.DataFrame,
    risk_col: str = "risk_premium",
    expense_ratio: float = 0.20,
    reinsurance_margin: float = 0.10,
    profit_margin: float = 0.05,
) -> pd.DataFrame:
    """Gross the risk premium up for expenses, cession margin and profit.

    Multiplicative gross-up, so the loadings apply to the premium actually
    collected rather than to the pure loss cost.
    """
    out = priced.copy()
    total_load = expense_ratio + reinsurance_margin + profit_margin
    if total_load >= 1.0:
        raise ValueError("total loading must be < 100%")
    out["commercial_premium"] = out[risk_col] / (1.0 - total_load)
    out["loss_ratio_at_expected"] = out[risk_col] / out["commercial_premium"]
    return out


# --------------------------------------------------------------------------
# portfolio view
# --------------------------------------------------------------------------


def portfolio_loss_by_year(
    losses: pd.DataFrame,
    weights: pd.DataFrame,
    keys: list[str],
    year_col: str = "uwy",
    loss_col: str = "payout_pct_SI",
    weight_col: str = "weight",
) -> pd.DataFrame:
    """Exposure-weighted portfolio loss for every historical year.

    This is the table an underwriter actually reads: 'if we had written this
    book every year since 1990, what would each year have cost?'
    """
    df = losses.merge(weights[keys + [weight_col]], on=keys, how="left")
    df[weight_col] = df[weight_col].fillna(0.0)
    df["weighted"] = df[loss_col] * df[weight_col]
    out = (
        df.groupby(year_col)
        .agg(portfolio_loss=("weighted", "sum"), units=(loss_col, "size"))
        .reset_index()
    )
    return out


def portfolio_metrics(port: pd.DataFrame, loss_col: str = "portfolio_loss") -> dict:
    """Headline risk metrics for the aggregate book."""
    x = port[loss_col].to_numpy(dtype=float)
    x = x[~np.isnan(x)]
    if x.size == 0:
        return {}
    var95 = float(np.percentile(x, 95))
    tail = x[x >= var95]
    return {
        "expected_loss": float(x.mean()),
        "std_dev": float(x.std(ddof=1)) if x.size > 1 else 0.0,
        "max_loss": float(x.max()),
        "loss_years_pct": float((x > 0).mean()),
        "VaR_95": var95,
        "TVaR_95": float(tail.mean()) if tail.size else var95,
        "PML_1_in_25": float(np.percentile(x, 96)),
        "years": int(x.size),
    }


def _strikes_from_quantiles(vals: np.ndarray, quantiles: np.ndarray, direction: str) -> list[float]:
    """Percentile strikes, repaired into a strictly monotone, payable ladder.

    Two failure modes have to be handled or the ladder is nonsense:

      * a sparse index (many zero years) makes several percentiles collapse onto
        the same value, which would let one event trigger every step at once;
      * an 'above' ladder with a zero strike pays on a no-event year, i.e. it is
        not insurance, it is a coupon.

    Strikes are therefore floored above the smallest event-bearing value and
    forced strictly apart.
    """
    q = np.clip(quantiles, 0.005, 0.995) * 100.0
    strikes = np.percentile(vals, q).astype(float)

    if direction == "above":
        positive = vals[vals > 0]
        floor = float(positive.min()) if positive.size else 1e-6
        strikes = np.maximum(strikes, floor)
        for i in range(1, strikes.size):
            if strikes[i] <= strikes[i - 1]:
                strikes[i] = strikes[i - 1] * 1.05 + 1e-6
    else:
        ceiling = float(vals.max())
        strikes = np.minimum(strikes, ceiling)
        for i in range(1, strikes.size):
            if strikes[i] >= strikes[i - 1]:
                strikes[i] = strikes[i - 1] * 0.95 - 1e-6
        strikes = np.maximum(strikes, 0.0)
    return [float(round(x, 4)) for x in strikes]


def calibrate_ladder_to_target(
    index_df: pd.DataFrame,
    direction: str,
    payouts: tuple[float, ...] = (0.05, 0.15, 0.30, 0.65, 1.00),
    target_rate: float = 0.03,
    tolerance: float = 0.002,
    value_col: str = "index_value",
    name: str = "calibrated",
    max_iter: int = 80,
) -> tuple[StrikeLadder, float]:
    """Solve for the strike ladder that prices a cover at a target risk rate.

    Strikes are placed at percentiles of the historical index, then the whole
    ladder is shifted in percentile space by bisection until the burn cost lands
    on ``target_rate`` -- typically ~3% for an agri cover, the level at which the
    farmer will still buy it and a reinsurer will still take the cession.

    This inverts the textbook order. Instead of choosing strikes and discovering
    the price, the affordable price is fixed first and the strikes are derived
    from it, which is how the conversation with a distribution partner actually
    goes.

    Returns the ladder and the burn cost it produces. If the index is too sparse
    to reach the target at all, the closest achievable ladder is returned -- the
    caller should compare the returned rate against the target rather than
    assume it was met.
    """
    vals = index_df[value_col].dropna().to_numpy(dtype=float)
    if vals.size == 0:
        raise ValueError("no index values to calibrate against")

    n_steps = len(payouts)
    base = (
        np.linspace(0.70, 0.98, n_steps)
        if direction == "above"
        else np.linspace(0.30, 0.02, n_steps)
    )

    def build(shift: float) -> StrikeLadder:
        strikes = _strikes_from_quantiles(vals, base + shift, direction)
        return StrikeLadder(name=name, direction=direction, steps=list(zip(strikes, payouts)))

    def rate_of(ladder: StrikeLadder) -> float:
        return float(np.mean([ladder.payout(v) for v in vals]))

    lo, hi = -0.35, 0.30
    best_ladder, best_rate = build(0.0), None
    best_rate = rate_of(best_ladder)
    best_gap = abs(best_rate - target_rate)

    for _ in range(max_iter):
        if best_gap <= tolerance:
            break
        mid = (lo + hi) / 2.0
        ladder = build(mid)
        rate = rate_of(ladder)
        gap = abs(rate - target_rate)
        if gap < best_gap:
            best_ladder, best_rate, best_gap = ladder, rate, gap
        # pushing strikes further into the tail makes payouts rarer
        if rate > target_rate:
            lo = mid
        else:
            hi = mid

    return best_ladder, best_rate


def calibrate_peril_to_target(
    phase_indices: dict[str, pd.DataFrame],
    direction: str,
    keys: list[str],
    target_rate: float,
    combine: str = "max",
    payouts: tuple[float, ...] = (0.05, 0.15, 0.30, 0.65, 1.00),
    value_col: str = "index_value",
    tolerance: float = 0.0015,
    max_iter: int = 18,
    peril_name: str = "peril",
) -> tuple[dict[str, StrikeLadder], pd.DataFrame, float]:
    """Calibrate ALL phases of a peril so the COMBINED peril hits its rate.

    Calibrating each phase to the peril's target separately is the mistake that
    quietly triples a rate: three phases each priced at 1.8% do not combine to
    1.8%, they combine to something near 5% once you take the worst phase.

    So the target is imposed after combination. An outer bisection searches for
    the common per-phase rate whose combined (max or sum) loss equals the
    peril's target, and the phase ladders are rebuilt at each step.

    Returns {phase: ladder}, the combined loss table, and the achieved rate.
    """
    n = max(len(phase_indices), 1)
    lo, hi = target_rate / (n * 4.0), min(target_rate * 1.5, 0.95)

    best = None
    for _ in range(max_iter):
        mid = (lo + hi) / 2.0
        ladders, paid = {}, []
        for phase, df in phase_indices.items():
            ladder, _ = calibrate_ladder_to_target(
                df,
                direction=direction,
                payouts=payouts,
                target_rate=mid,
                value_col=value_col,
                name=f"{peril_name} | {phase}",
            )
            ladders[phase] = ladder
            p = apply_ladder(df, ladder, value_col=value_col)
            p["phase"] = phase
            paid.append(p)

        combined = combine_phase_payouts(pd.concat(paid, ignore_index=True), keys=keys, method=combine)
        achieved = float(combined["payout_pct_SI"].mean())

        if best is None or abs(achieved - target_rate) < abs(best[2] - target_rate):
            best = (ladders, combined, achieved)
        if abs(achieved - target_rate) <= tolerance:
            break
        if achieved > target_rate:
            hi = mid
        else:
            lo = mid

    return best
