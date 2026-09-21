"""
Step 7 - the three pictures in the README.

Reads only files the earlier steps wrote (outputs/ and data/), so it adds no
new modelling: it just shows what one season, one term sheet and one book of
history look like to the person who has to sign off the cover.

    docs/img/season_monitor.png   one grid node through one season, with strikes
    docs/img/payout_ladders.png   two real WRMS ladder shapes (rainfall, blight)
    docs/img/burn_history.png     35 years of portfolio loss vs the priced rate
"""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker
import numpy as np
import pandas as pd
from _bootstrap import OUT, ROOT
from _loaders import load_daily

IMG = ROOT / "docs" / "img"
IMG.mkdir(parents=True, exist_ok=True)

INK, MUTED, GRID = "#1f2933", "#6b7785", "#e4e7eb"
RAIN, HEAT, PAY = "#3b6fb6", "#c8553d", "#2f9e6e"
PHASE_BG = ["#f4f6f8", "#ffffff", "#f4f6f8"]

plt.rcParams.update({
    "font.family": "DejaVu Sans", "font.size": 9.5, "axes.edgecolor": GRID,
    "axes.labelcolor": INK, "xtick.color": MUTED, "ytick.color": MUTED,
    "axes.spines.top": False, "axes.spines.right": False, "axes.grid": True,
    "grid.color": GRID, "grid.linewidth": 0.7, "axes.titleweight": "bold",
    "axes.titlesize": 10.5, "axes.titlecolor": INK, "figure.dpi": 150, "axes.axisbelow": True,
})


def _ladder(term: pd.DataFrame, peril_key: str) -> dict:
    t = term[term["peril"].str.contains(peril_key)]
    out = {}
    for phase, g in t.groupby("phase", sort=False):
        w = g["phase_window"].iloc[0].split(" to ")
        out[phase] = dict(start=w[0], end=w[1], strikes=g["strike"].tolist(), pay=g["payout_pct_SI"].tolist())
    return out


def _pay(value: float, strikes: list, pay: list) -> float:
    hit = [p for s, p in zip(strikes, pay) if value >= s]
    return max(hit) if hit else 0.0


def season_monitor() -> None:
    term = pd.read_csv(OUT / "04_term_sheet_cumin.csv")
    eri, bl = _ladder(term, "Excess"), _ladder(term, "Blight")
    idx = pd.read_csv(OUT / "03_indices_cumin.csv")

    # pick the node-season where the excess-rainfall cover paid the most
    e = idx[idx["peril"].str.contains("Excess")].copy()
    e["paid"] = [_pay(v, eri[p]["strikes"], eri[p]["pay"]) for v, p in zip(e["index_value"], e["phase"])]
    b = idx[idx["peril"].str.contains("Blight")].copy()
    b["paid"] = [_pay(v, bl[p]["strikes"], bl[p]["pay"]) for v, p in zip(b["index_value"], b["phase"])]
    bpaid = b.groupby(["grid_lat", "grid_lon", "uwy"])["paid"].max().rename("bpaid")
    epaid = e.groupby(["grid_lat", "grid_lon", "uwy"])["paid"].max().rename("epaid")
    both = pd.concat([epaid, bpaid], axis=1).fillna(0)
    both = both[(both["epaid"] > 0) & (both["bpaid"] > 0) & (both["epaid"] < 100)]
    pick = both.sort_values(["epaid", "bpaid"], ascending=False).reset_index().iloc[0]
    best = pick
    lat, lon, uwy = best["grid_lat"], best["grid_lon"], int(best["uwy"])

    d = load_daily("primary")
    d = d[(d["grid_lat"] == lat) & (d["grid_lon"] == lon)]
    d = d[(d["date"] >= f"{uwy}-12-01") & (d["date"] <= f"{uwy + 1}-02-28")].sort_values("date").copy()
    d["roll3"] = d["rain_mm"].rolling(3, min_periods=1).sum()
    d["conducive"] = d["t2m_c"].between(10, 20) & (d["rh_pct"] >= 80)
    run, spell = 0, []
    for f in d["conducive"]:
        run = run + 1 if f else 0
        spell.append(run)
    d["spell"] = spell

    fig, (a1, a2) = plt.subplots(2, 1, figsize=(10, 5.6), sharex=True, gridspec_kw={"hspace": 0.45})
    bounds = [(pd.Timestamp(f"{uwy}-12-01"), pd.Timestamp(f"{uwy}-12-31")),
              (pd.Timestamp(f"{uwy + 1}-01-01"), pd.Timestamp(f"{uwy + 1}-01-31")),
              (pd.Timestamp(f"{uwy + 1}-02-01"), pd.Timestamp(f"{uwy + 1}-02-28"))]
    names = list(eri.keys())

    for ax in (a1, a2):
        for (s, t), bg in zip(bounds, PHASE_BG):
            ax.axvspan(s, t + pd.Timedelta(days=1), color=bg, zorder=0, lw=0)

    a1.bar(d["date"], d["rain_mm"], width=0.8, color=RAIN, alpha=0.35, label="daily rain (mm)")
    a1.plot(d["date"], d["roll3"], color=RAIN, lw=1.6, label="index: 3-day rolling total (mm)")
    for (s, t), ph in zip(bounds, names):
        k = eri[ph]
        a1.hlines(k["strikes"][0], s, t, color=PAY, lw=1.3, ls="--")
        a1.hlines(k["strikes"][-1], s, t, color=HEAT, lw=1.3, ls="--")
    top = max(d["roll3"].max(), max(eri[p]["strikes"][-1] for p in names)) * 1.18
    a1.set_ylim(0, top)
    for (s, t), ph in zip(bounds, names):
        a1.text(s + (t - s) / 2, top * 0.95, ph.split(" ", 1)[1], ha="center", va="top", color=MUTED, fontsize=8.5)
    m = d.loc[d["roll3"].idxmax()]
    ph_m = names[[s <= m["date"] <= t for s, t in bounds].index(True)]
    paid_m = _pay(m["roll3"], eri[ph_m]["strikes"], eri[ph_m]["pay"])
    a1.annotate(f"{m['roll3']:.0f} mm  ->  pays {paid_m:.0f}% of SI", xy=(m["date"], m["roll3"]),
                xytext=(-8, -16), textcoords="offset points", ha="right", color=INK, fontsize=8.5, weight="bold")
    a1.plot([], [], color=PAY, ls="--", label="strike 1 (first payout)")
    a1.plot([], [], color=HEAT, ls="--", label="exit (100% payout)")
    a1.set_ylabel("rainfall (mm)")
    a1.set_title("Excess rainfall cover")
    a1.legend(loc="upper left", bbox_to_anchor=(0, -0.04), ncol=4, frameon=False, fontsize=8)

    a2.bar(d["date"], d["conducive"].astype(int) * 0.6, width=0.9, bottom=0, color=HEAT, alpha=0.18,
           label="blight-conducive day (10-20 C, RH >= 80%)")
    a2.step(d["date"], d["spell"], where="mid", color=HEAT, lw=1.6, label="index: current conducive run (days)")
    for (s, t), ph in zip(bounds, names):
        a2.hlines(bl[ph]["strikes"][0], s, t, color=PAY, lw=1.3, ls="--")
    a2.set_ylim(0, max(d["spell"].max(), max(bl[p]["strikes"][0] for p in names)) * 1.35 + 1)
    j = d["spell"].idxmax(); r = d.loc[j]
    ph_b = names[[s <= r["date"] <= t for s, t in bounds].index(True)]
    paid_b = _pay(r["spell"], bl[ph_b]["strikes"], bl[ph_b]["pay"])
    a2.annotate(f"{int(r['spell'])}-day run  ->  pays {paid_b:.0f}% of SI", xy=(r["date"], r["spell"]),
                xytext=(8, -2), textcoords="offset points", color=INK, fontsize=8.5, weight="bold")
    a2.plot([], [], color=PAY, ls="--", label="strike 1 (first payout)")
    a2.set_ylabel("consecutive days")
    a2.yaxis.set_major_locator(matplotlib.ticker.MaxNLocator(integer=True))
    a2.set_title("Blight cover")
    a2.legend(loc="upper left", bbox_to_anchor=(0, -0.13), ncol=3, frameon=False, fontsize=8)

    fig.suptitle(f"One season at one grid node ({lat}N, {lon}E), rabi {uwy}-{str(uwy + 1)[2:]}  -  synthetic data",
                 x=0.07, ha="left", fontsize=11.5, weight="bold", color=INK)
    fig.savefig(IMG / "season_monitor.png", bbox_inches="tight", facecolor="white")
    plt.close(fig)


# Two ladder shapes lifted from real WRMS term sheets (product terms only;
# no client, exposure or loss data).
JAIPUR_ERI = {  # cabbage, Chomu sub-district, rabi 2023-24, option 1 (4.5% rate), Rs per bigha, SI Rs 25,000
    "Nov (germination)":  ([20, 45, 70, 95, 120], [950, 2500, 6250, 9375, 12500]),
    "Dec-Jan (growth)":   ([20, 45, 70, 95, 120], [1500, 3750, 9375, 15000, 18750]),
    "Feb (maturity)":     ([20, 45, 70, 95, 120], [1875, 5000, 12500, 18750, 25000]),
}
UP_BLIGHT = ([4, 9, 14, 19], [10, 20, 30, 50])  # one district, Feb 2024, days -> % SI


def _step(ax, strikes, pay, xmax, color, label, lw=1.8):
    xs, ys = [0], [0]
    for s, p in zip(strikes, pay):
        xs += [s, s]; ys += [ys[-1], p]
    xs.append(xmax); ys.append(ys[-1])
    ax.plot(xs, ys, color=color, lw=lw, label=label)


def payout_ladders() -> None:
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(10, 3.7), gridspec_kw={"wspace": 0.28})
    shades = ["#9dbbe3", "#5b8fd0", "#1f4f96"]
    for (name, (s, p)), c in zip(JAIPUR_ERI.items(), shades):
        _step(a1, s, p, 150, c, name)
    a1.set_xlabel("index: max 3-day rainfall (mm)")
    a1.set_ylabel("payout (Rs per bigha)")
    a1.set_title("Excess rainfall - cabbage, Jaipur (Rabi 2023-24)")
    a1.axhline(25000, color=MUTED, lw=0.8, ls=":")
    a1.text(2, 25500, "sum insured Rs 25,000", color=MUTED, fontsize=8)
    a1.set_ylim(0, 28000)
    a1.legend(frameon=False, fontsize=8, loc="upper left", bbox_to_anchor=(0, 0.9))

    _step(a2, *UP_BLIGHT, 24, HEAT, "")
    for s, p in zip(*UP_BLIGHT):
        a2.text(s + 0.3, p + 1.5, f"{p}%", color=INK, fontsize=8)
    a2.set_xlabel("index: longest run of blight-conducive days")
    a2.set_ylabel("payout (% of sum insured)")
    a2.set_title("Blight - Uttar Pradesh district (Feb 2024)")
    a2.set_ylim(0, 60)
    fig.suptitle("How a payout ladder turns one index number into money", x=0.07, ha="left",
                 fontsize=11.5, weight="bold", color=INK, y=1.02)
    fig.savefig(IMG / "payout_ladders.png", bbox_inches="tight", facecolor="white")
    plt.close(fig)


def burn_history() -> None:
    y = pd.read_csv(OUT / "04_portfolio_by_year_cumin.csv")
    y["loss_pct"] = y["portfolio_loss"] * 100
    fig, ax = plt.subplots(figsize=(10, 3.2))
    ax.bar(y["uwy"], y["loss_pct"], color=RAIN, alpha=0.75, width=0.75, label="portfolio loss that year")
    ax.axhline(3.0, color=PAY, lw=1.5, ls="--", label="target risk rate 3%")
    ax.set_axisbelow(True)
    ax.text(y["uwy"].max() + 0.6, 3.25, f"priced at 3%, back-test average {y['loss_pct'].mean():.2f}%", ha="right", color=PAY, fontsize=8.5, weight="bold")
    worst = y.loc[y["loss_pct"].idxmax()]
    ax.annotate(f"{int(worst['uwy'])}: {worst['loss_pct']:.1f}%", xy=(worst["uwy"], worst["loss_pct"]),
                xytext=(6, -2), textcoords="offset points", fontsize=8.5, weight="bold", color=INK)
    ax.set_ylabel("loss (% of sum insured)")
    ax.set_title("Cumin cover, 35 underwriting years of back-tested loss (synthetic data)", loc="left")
    ax.legend(frameon=False, fontsize=8, loc="upper right", ncol=2)
    ax.set_ylim(0, max(y["loss_pct"].max() * 1.25, 4))
    fig.savefig(IMG / "burn_history.png", bbox_inches="tight", facecolor="white")
    plt.close(fig)


def main() -> None:
    season_monitor()
    payout_ladders()
    burn_history()
    for p in sorted(IMG.glob("*.png")):
        print(f"wrote {p.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
