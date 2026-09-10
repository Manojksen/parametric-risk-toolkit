"""
Product specifications: the crop calendar, in code.

A parametric cover is fully described by (peril, phase windows, index
definition, payout ladder, aggregation rule). Holding that in a declarative
spec rather than scattered through a notebook is what makes a book of 40
covers across 16 states maintainable -- and what makes a wording change a
one-line diff instead of a re-run of everything.

Phase windows follow the crop calendar, not the calendar month: sowing,
vegetative, flowering and maturity each have their own weather sensitivity,
so each gets its own window and its own strikes.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Phase:
    name: str
    start: str  # 'MM-DD'
    end: str    # 'MM-DD'


@dataclass
class PerilSpec:
    """One peril inside a product."""
    name: str
    index_fn: str                     # function name in src.indices
    params: dict = field(default_factory=dict)
    direction: str = "above"          # ladder direction
    phases: list[Phase] = field(default_factory=list)
    combine: str = "max"              # how phases of this peril combine
    target_rate: float = 0.015        # risk rate this peril is calibrated to


@dataclass
class ProductSpec:
    name: str
    crop: str
    region: str
    wrap_months: tuple[int, ...]
    perils: list[PerilSpec]
    target_total_rate: float = 0.03   # affordability + cedeability ceiling
    max_payout: float = 1.0


# --------------------------------------------------------------------------
# Two worked examples. Both are rabi covers, so Jan-Mar wraps back into the
# previous underwriting year.
# --------------------------------------------------------------------------

CUMIN_RABI = ProductSpec(
    name="Rabi Cumin - Blight & Excess Rainfall",
    crop="Cumin",
    region="Rajasthan / Gujarat (illustrative)",
    wrap_months=(1, 2, 3),
    target_total_rate=0.03,
    perils=[
        PerilSpec(
            name="Blight (disease-conducive spell)",
            index_fn="disease_spell_index",
            params={"temp_range": (10.0, 20.0), "rh_min": 80.0},
            direction="above",
            target_rate=0.018,
            phases=[
                Phase("P1 vegetative", "12-01", "12-31"),
                Phase("P2 flowering", "01-01", "01-31"),
                Phase("P3 seed set", "02-01", "02-28"),
            ],
            combine="max",
        ),
        PerilSpec(
            name="Excess rainfall (unseasonal)",
            index_fn="excess_rainfall_index",
            params={"window_days": 3},
            direction="above",
            target_rate=0.012,
            phases=[
                Phase("P1 vegetative", "12-01", "12-31"),
                Phase("P2 flowering", "01-01", "01-31"),
                Phase("P3 seed set", "02-01", "02-28"),
            ],
            combine="max",
        ),
    ],
)

WHEAT_RABI = ProductSpec(
    name="Rabi Wheat - Terminal Heat & Excess Rainfall",
    crop="Wheat",
    region="North-west India (illustrative)",
    wrap_months=(1, 2, 3, 4),
    target_total_rate=0.03,
    perils=[
        PerilSpec(
            name="Terminal heat (grain filling)",
            index_fn="heat_index",
            params={"threshold_c": 34.0, "mode": "count"},
            direction="above",
            target_rate=0.020,
            phases=[
                Phase("P1 grain filling", "02-15", "03-31"),
                Phase("P2 maturity", "04-01", "04-15"),
            ],
            combine="max",
        ),
        PerilSpec(
            name="Excess rainfall at harvest",
            index_fn="excess_rainfall_index",
            params={"window_days": 3},
            direction="above",
            target_rate=0.010,
            phases=[Phase("P1 harvest", "03-15", "04-15")],
            combine="max",
        ),
    ],
)

CATALOGUE = {"cumin": CUMIN_RABI, "wheat": WHEAT_RABI}
