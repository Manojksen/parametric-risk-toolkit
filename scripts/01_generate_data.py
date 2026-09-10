"""
Step 0 - build the synthetic universe.

Nothing in data/ is committed to the repository: this script regenerates every
byte of it deterministically from a fixed seed, so a fresh clone reproduces the
exact numbers in the README. No client data ever enters the repo.
"""
import time

from _bootstrap import DATA
from src import simulate


def main() -> None:
    t0 = time.time()
    grid = simulate.make_grid()
    enroll = simulate.make_enrollments(grid, n=1200)
    primary = simulate.simulate_daily_weather(grid, 1990, 2023)
    primary["source"] = "PRIMARY_GRIDDED"
    alt = simulate.perturb_as_alternate_dataset(primary)
    tracks = simulate.simulate_cyclone_tracks()

    grid.to_csv(DATA / "grid_nodes.csv", index=False)
    enroll.to_csv(DATA / "enrollments.csv", index=False)
    primary.to_csv(DATA / "daily_primary.csv.gz", index=False, compression="gzip")
    alt.to_csv(DATA / "daily_alternate.csv.gz", index=False, compression="gzip")
    tracks.to_csv(DATA / "cyclone_tracks.csv", index=False)

    print(f"grid nodes      : {len(grid):>9,}")
    print(f"enrollments     : {len(enroll):>9,}")
    print(f"daily rows/set  : {len(primary):>9,}  ({primary['date'].min().date()} -> {primary['date'].max().date()})")
    print(f"cyclone fixes   : {len(tracks):>9,}")
    print(f"elapsed         : {time.time() - t0:>9.1f}s")


if __name__ == "__main__":
    main()
