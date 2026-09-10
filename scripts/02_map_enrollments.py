"""Step 1 - snap every enrolled location to its nearest grid node and audit the snap."""
import pandas as pd
from _bootstrap import DATA, OUT
from src import gridding

def main() -> None:
    enroll = pd.read_csv(DATA / "enrollments.csv")
    grid = pd.read_csv(DATA / "grid_nodes.csv")

    mapped = gridding.snap_to_grid(enroll, grid, max_distance_km=30.0)
    weights = gridding.grid_exposure_weights(mapped, by=["state", "district"], sum_insured_col="sum_insured")
    report = gridding.snap_quality_report(mapped, by=["state", "district"])

    mapped.to_csv(OUT / "01_enrollments_mapped.csv", index=False)
    weights.to_csv(OUT / "01_grid_exposure_weights.csv", index=False)
    report.to_csv(OUT / "01_snap_quality_report.csv", index=False)

    print("SNAP QUALITY BY DISTRICT")
    print(report.to_string(index=False))
    print(f"\nlocations mapped   : {len(mapped):,}")
    print(f"grid nodes in use  : {weights[['grid_lat','grid_lon']].drop_duplicates().shape[0]:,}")
    print(f"beyond 30 km       : {(mapped['snap_flag'] == 'far').sum():,}")
    print(f"median snap (km)   : {mapped['snap_distance_km'].median():.2f}")

if __name__ == "__main__":
    main()
