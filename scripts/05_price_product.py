"""
Step 4 - price the product and produce the loss summary.

The workflow inverts the textbook order. The client tells you the rate they
can afford (agri covers live at roughly 3% of sum insured -- above that the
farmer will not buy and the subsidy will not stretch); the job is to find the
strike ladder that delivers cover at that rate and to show the underwriter
what that ladder would have cost in every one of the last 30+ years.

Outputs:
    04_term_sheet_<product>.csv     strike ladders, per peril and phase
    04_loss_by_unit_<product>.csv   burn cost and premium per grid node
    04_portfolio_by_year_<product>.csv  what the book would have cost each year
    04_portfolio_metrics_<product>.csv  EL, VaR, TVaR, PML
"""
import argparse

import pandas as pd
from _bootstrap import OUT
from src import gridding, pricing, products

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--product", default="cumin", choices=list(products.CATALOGUE))
    ap.add_argument("--target-rate", type=float, default=None)
    args = ap.parse_args()

    spec = products.CATALOGUE[args.product]
    target_total = args.target_rate or spec.target_total_rate
    idx = pd.read_csv(OUT / f"03_indices_{args.product}.csv")
    weights = pd.read_csv(OUT / "01_grid_exposure_weights.csv")

    keys = ["grid_lat", "grid_lon", "uwy"]
    scale = target_total / sum(p.target_rate for p in spec.perils)

    term_rows, peril_losses = [], []

    for peril in spec.perils:
        peril_idx = idx[idx["peril"] == peril.name]
        phase_indices = {ph: g for ph, g in peril_idx.groupby("phase")}

        ladders, combined, achieved = pricing.calibrate_peril_to_target(
            phase_indices,
            direction=peril.direction,
            keys=keys,
            target_rate=peril.target_rate * scale,
            combine=peril.combine,
            peril_name=peril.name,
        )
        combined["peril"] = peril.name
        peril_losses.append(combined)

        want = peril.target_rate * scale
        if abs(achieved - want) > 0.003:
            print(
                f"  ! {peril.name}: target {want:.2%}, achieved {achieved:.2%} -- "
                "index too sparse for a finer ladder at this payout structure"
            )

        for phase, ladder in ladders.items():
            g = phase_indices[phase]
            t = ladder.to_frame()
            t.insert(0, "phase", phase)
            t.insert(0, "peril", peril.name)
            t["index"] = g["index_name"].iloc[0]
            t["phase_window"] = g["phase_window"].iloc[0]
            t["peril_target_rate"] = round(peril.target_rate * scale, 4)
            t["peril_achieved_rate"] = round(achieved, 4)
            term_rows.append(t)

    total = pricing.combine_perils(peril_losses, keys=keys, cap=spec.max_payout)

    burn = pricing.burn_cost(total, keys=["grid_lat", "grid_lon"])
    priced = pricing.risk_premium(burn, losses=total, keys=["grid_lat", "grid_lon"])
    priced = pricing.commercial_premium(priced)

    book = gridding.book_weights(weights)
    port = pricing.portfolio_loss_by_year(total, book, keys=["grid_lat", "grid_lon"])
    metrics = pricing.portfolio_metrics(port)

    term = pd.concat(term_rows, ignore_index=True)
    term.to_csv(OUT / f"04_term_sheet_{args.product}.csv", index=False)
    priced.round(5).to_csv(OUT / f"04_loss_by_unit_{args.product}.csv", index=False)
    port.round(5).to_csv(OUT / f"04_portfolio_by_year_{args.product}.csv", index=False)
    pd.DataFrame([metrics]).round(5).to_csv(OUT / f"04_portfolio_metrics_{args.product}.csv", index=False)

    print(f"PRODUCT : {spec.name}")
    print(f"REGION  : {spec.region}   TARGET RISK RATE: {target_total:.2%}\n")
    print("TERM SHEET (strike ladders)")
    show = term[["peril", "phase", "phase_window", "step", "strike", "payout_pct_SI", "peril_achieved_rate"]].copy()
    show["strike"] = show["strike"].round(2)
    print(show.to_string(index=False))

    print("\nPRICING (exposure-weighted book)")
    print(f"  blended burn cost   : {priced['burn_blend'].mean():.3%}")
    print(f"  risk premium        : {priced['risk_premium'].mean():.3%}")
    print(f"  commercial premium  : {priced['commercial_premium'].mean():.3%}")
    print(f"  worst node max loss : {priced['max_loss'].max():.1%} of SI")
    print(f"  mean loss frequency : {priced['loss_frequency'].mean():.1%} of years")

    print("\nPORTFOLIO RISK METRICS")
    for k, v in metrics.items():
        print(f"  {k:<18} {v:.4f}" if isinstance(v, float) else f"  {k:<18} {v}")

    worst = port.nlargest(5, "portfolio_loss")
    print("\nWORST 5 YEARS (loss as % of SI)")
    print(worst.assign(portfolio_loss=lambda d: (d["portfolio_loss"] * 100).round(2)).to_string(index=False))

if __name__ == "__main__":
    main()
