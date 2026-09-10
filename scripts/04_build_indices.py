"""
Step 3 - build every phase index for a product.

One row per grid node, per phase, per underwriting year. This is the table the
policy settles on and the only table the pricing step is allowed to see.
"""
import argparse

import pandas as pd
from _bootstrap import OUT
from _loaders import load_daily
from src import indices, products

def build_product_indices(daily: pd.DataFrame, spec: products.ProductSpec) -> pd.DataFrame:
    out = []
    for peril in spec.perils:
        fn = getattr(indices, peril.index_fn)
        for phase in peril.phases:
            sliced = indices.slice_phase(daily, phase.start, phase.end, wrap_months=spec.wrap_months)
            if sliced.empty:
                continue
            idx = fn(sliced, **peril.params)
            idx["peril"] = peril.name
            idx["phase"] = phase.name
            idx["phase_window"] = f"{phase.start} to {phase.end}"
            out.append(idx)
    return pd.concat(out, ignore_index=True)

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--product", default="cumin", choices=list(products.CATALOGUE))
    args = ap.parse_args()

    spec = products.CATALOGUE[args.product]
    daily = load_daily("primary")
    idx = build_product_indices(daily, spec)
    idx.to_csv(OUT / f"03_indices_{args.product}.csv", index=False)

    print(f"PRODUCT: {spec.name}  [{spec.region}]")
    print(f"index rows: {len(idx):,}   grid nodes: {idx[['grid_lat','grid_lon']].drop_duplicates().shape[0]}   UWYs: {idx['uwy'].nunique()}\n")
    summary = (
        idx.groupby(["peril", "phase", "index_name"])["index_value"]
        .agg(min="min", mean="mean", p90=lambda s: s.quantile(0.90), max="max")
        .round(2)
        .reset_index()
    )
    print(summary.to_string(index=False))

if __name__ == "__main__":
    main()
