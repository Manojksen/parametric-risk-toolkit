# Field notes

Notes on the work behind this repository, kept at the level of method and
geography. No client is named, no figure from a live programme appears, and
nothing here would let anyone reconstruct a book of business.

## India — a multi-state agri programme, end to end

The one I ran on my own. A fortnightly enrolment cycle: enrolment closed on the
1st and the 16th, and a priced product had to exist before cover incepted.

Each cycle: intake and clean the enrolment file, snap every location to the
nearest IMD grid node (0.25° for rainfall, 0.5° or 1.0° for temperature),
build the phase indices over the full historical record, design or refresh the
product for that state and crop calendar, price it, and issue the workbook.
After the season, run the same index code on realised data and produce the
settlement loss summary.

Covers I built or maintained, across roughly a dozen states:

* **Excess rainfall** — max n-day accumulation inside a phase
* **Deficit rainfall / drought** — capped daily rainfall totalled over the phase
* **Dry continuous weeks** — longest run of dry days
* **Late blight and other disease covers** — longest consecutive run of days
  with mean temperature inside the pathogen's window and relative humidity at or
  above the sporulation threshold, built off hourly reanalysis aggregated to
  daily
* **Terminal heat** — days above a temperature threshold during grain filling
* **Unseasonal rainfall and fog** — for standing and harvested crops

Crops included cumin, chilli, potato, wheat, rabi pulses and mustard, each with
its own phase structure. Where the same crop was written across several states,
the phases and strikes differed by state because the sowing calendar did.

Recurring lessons, in the order they cost me time:

* The underwriting year for a rabi cover is not the calendar year. Get it wrong
  and every season splits in two.
* Enrolment files are the least reliable input in the chain and the one everyone
  assumes is clean.
* Hourly reanalysis has to be aggregated to daily with the aggregation the index
  needs — daily mean for a disease index, daily max for heat, daily total for
  rain — and mixing them up produces a plausible number that is simply wrong.
* Grid-to-village mapping is a defensible engineering decision that has to be
  documented, not a lookup to be done once and forgotten.

## Central America — department-level covers on reanalysis

Multi-crop covers built on ERA5 at department level: coffee, corn, sugarcane and
tomato, each on its own phase structure, with water-deficit and excess-rainfall
legs priced together.

The interesting constraint was that settlement was at department level while the
observation was gridded, so exposure-weighted aggregation from node to
department was the load-bearing step rather than an afterthought. Two versions
of every index were carried, with and without the underwriting-year wrap, purely
so the effect of that choice on the rate was visible to the client.

## Caribbean — forecast-triggered and observed indices side by side

Rainfall covers built on satellite rainfall, with parallel index families at
5-, 10- and 15-day horizons on forecast fields against the observed record. The
question being answered was whether a forecast-triggered cover could pay out
before the loss was fully realised without an unacceptable false-alarm rate.
Comparing the index families against each other was most of the work.

## East Africa — four datasets, one index

A district-level programme in a region where the station network is too thin to
settle on. The same index was built on four independent sources — two satellite
rainfall products, one reanalysis, and the national met service station record —
and compared node by node before anything was priced. They were not close. The
comparison, not a preference, chose the source.

## Pacific and South-East Asia — cyclone wind

Wind-speed covers built from IBTrACS track fixes: for each insured location and
each season, the maximum sustained wind of any track point passing within a
radius, settled on a Saffir-Simpson-style ladder. Built for several island
territories and for a national programme in South-East Asia, the latter on
national met service station rainfall alongside the wind cover.

Cyclone is the cleanest parametric peril to build — the trigger is a physical
measurement with no crop model in between — and the hardest to price, because
thirty seasons of tracks give you very few events per location and the loss
distribution is almost all tail.

## Microfinance — drought covers for a lending book

Drought indices over 2- and 3-month accumulation windows across a national
lending footprint, sized to the loan book rather than to a crop. Different
buyer, same machinery: the index protects the lender's portfolio against
correlated default in a bad monsoon, so the metric that mattered was the
aggregate — VaR and PML on the book — rather than the unit rate.

## What I would do differently

Most of the work above lived in notebooks. It worked, and it shipped, but a
notebook is a poor place for logic that has to be identical across forty covers
and reproducible two years later at settlement. This repository is that logic
rewritten as a library with tests, which is how I would build it now.
