# The production workflow

This is the loop a live parametric agri programme actually runs on. In the
Indian programme I handled it repeated on a fortnightly cycle — enrolment
closed on the 1st and the 16th, and a priced product had to exist before the
cover period started.

## 1. Enrolment arrives

A file of enrolled locations: village or farm, latitude/longitude, crop, area,
sum insured, cover start date. Volume moves with the season; the shape does not.

First job is hygiene, and it is not optional. Duplicate rows, coordinates with
swapped lat/long, a district name that does not match the state, a farm sitting
in the sea two degrees off its village — all of these arrive, and all of them
survive silently into a settlement file if nobody looks. Every location that
cannot be placed is quarantined and sent back, not quietly dropped.

## 2. Snap to the weather grid

The policy is written on a location; the observation lives on a grid node. So
every enrolled location is snapped to the nearest node of whichever product
grid the cover will settle on — 0.25° for IMD gridded rainfall, 0.5° or 1.0° for
IMD temperature, 0.25° for ERA5, 0.05° for CHIRPS.

Two things come out of this step and both matter:

* **the mapping**, which is what every later step joins on, and
* **the snap-distance audit** — mean, p95, max, and the count beyond tolerance,
  per district. A cover whose average location sits 30 km from its observation
  point is carrying basis risk that has to be priced or disclosed.

Where the cover settles at district or department level rather than grid level,
this step also produces the **exposure weights**: each node's share of the sum
insured inside its unit. Those weights are what turn grid indices into a unit
loss later.

## 3. Choose the dataset (before designing anything)

Covered in `02-dataset-selection.md`. The short version: the dataset is chosen
against documented events, not against convenience, and the choice is made
before the product is designed — because the product's strikes are only
meaningful in the units of the series that will settle it.

## 4. Define phases from the crop calendar

A crop is not equally vulnerable across its season. Cumin can absorb rain while
vegetative and cannot at seed set; wheat is indifferent to a warm January and
loses yield to the same temperature during grain filling.

So the cover period is cut into phases that follow the crop calendar, each with
its own index and its own strikes. Phase boundaries come from the agronomy —
state agriculture department calendars, the client's own sowing data — not from
month ends, though they often land close.

Rabi phases wrap the new year, which makes the **underwriting year** a real
piece of logic rather than a label: December, January and February belong to one
season and must carry one UWY.

## 5. Build the index

One scalar per grid node per phase per underwriting year. After this point the
contract must be mechanically settleable, so anything judgemental has to have
happened already.

The index definitions in `src/indices.py` are the ones that carry most of an
agri book — max n-day rainfall, capped rainfall total, longest dry spell,
longest disease-conducive spell, count of days above a heat threshold, max wind
within a radius.

Indices are built over the **full historical record** available for that
dataset — 30 to 34 years for IMD and ERA5 — not just recent years, because the
next step needs the tail.

## 6. Price it

Covered in `03-pricing-notes.md`. Strike ladder solved backwards from an
affordable rate, burn cost over trailing windows, risk premium with a loading
for estimation uncertainty, commercial premium grossed up for expenses and
cession, and portfolio metrics — expected loss, VaR, TVaR, PML — for the
reinsurer.

Deliverable is a workbook: index sheet, product/term-sheet sheet, unit-level
loss summary, year-by-year portfolio loss summary.

## 7. After the season: the loss update

Once the cover period closes and the observed data is published, the same index
code runs on the realised season and produces the settlement loss summary —
which units paid, at which strike, how much. This is also the only honest
feedback the model gets: modelled versus realised, and where reported ground
loss exists, the basis-risk comparison in `src/validation.py`.

A cover that paid nothing in a year the client's own field reports call a
disaster is the single most useful thing that can happen to a parametric
programme, provided somebody writes it down and changes the index next season.
