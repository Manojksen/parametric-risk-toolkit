"""
Step 5 (side track) - a wind-speed cyclone cover from track data.

Same machinery, different peril: instead of a grid of daily weather, the input
is a set of storm track fixes. Each insured location takes the strongest wind
of any fix passing within a radius, and the ladder settles on that number.
"""
import pandas as pd
from _bootstrap import DATA, OUT
from src import indices, pricing

RADIUS_KM = 100.0

def main() -> None:
    tracks = pd.read_csv(DATA / "cyclone_tracks.csv")
    enroll = pd.read_csv(DATA / "enrollments.csv").head(300).copy()
    enroll = enroll.rename(columns={"latitude": "lat", "longitude": "lon"})

    idx = indices.cyclone_proximity_index(tracks, enroll, radius_km=RADIUS_KM)
    if idx.empty:
        print("no track points inside the radius")
        return

    # full grid of location x season, so quiet years count as zero-loss years
    seasons = sorted(tracks["season"].unique())
    frame = pd.MultiIndex.from_product(
        [enroll["location_id"], seasons], names=["location_id", "uwy"]
    ).to_frame(index=False)
    idx = frame.merge(idx[["location_id", "uwy", "index_value"]], on=["location_id", "uwy"], how="left")
    idx["index_value"] = idx["index_value"].fillna(0.0)

    ladder = pricing.StrikeLadder(
        name="Cyclone wind (kt)",
        direction="above",
        steps=[(64, 0.10), (83, 0.25), (96, 0.50), (113, 0.75), (137, 1.00)],
    )
    paid = pricing.apply_ladder(idx, ladder)
    burn = pricing.burn_cost(paid, keys=["location_id"])
    priced = pricing.commercial_premium(pricing.risk_premium(burn, losses=paid, keys=["location_id"]))

    by_year = paid.groupby("uwy")["payout_pct_SI"].mean().reset_index(name="portfolio_loss")
    metrics = pricing.portfolio_metrics(by_year)

    priced.round(5).to_csv(OUT / "05_cyclone_loss_by_location.csv", index=False)
    by_year.round(5).to_csv(OUT / "05_cyclone_portfolio_by_year.csv", index=False)

    print(f"CYCLONE COVER  ({RADIUS_KM:.0f} km radius, Saffir-Simpson style wind ladder)")
    print(ladder.to_frame().to_string(index=False))
    print(f"\n  locations           : {enroll['location_id'].nunique():,}")
    print(f"  seasons             : {len(seasons)}")
    print(f"  blended burn cost   : {priced['burn_blend'].mean():.3%}")
    print(f"  commercial premium  : {priced['commercial_premium'].mean():.3%}")
    print("\nPORTFOLIO RISK METRICS")
    for k, v in metrics.items():
        print(f"  {k:<18} {v:.4f}" if isinstance(v, float) else f"  {k:<18} {v}")

if __name__ == "__main__":
    main()
