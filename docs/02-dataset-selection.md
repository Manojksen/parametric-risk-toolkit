# Choosing the dataset

The largest source of basis risk in a parametric cover is not the payout
ladder. It is settling on a dataset that does not see the event the farmer
lived through.

Gridded and reanalysis rainfall products disagree with each other, and with
stations, in ways that are systematic rather than random:

* they invent light rain on dry days, which inflates a deficit index and makes
  a genuine drought look survivable;
* they smear extremes across the grid box, which flattens the peak of a
  cloudburst and makes an excess-rainfall index under-fire exactly when it
  matters;
* they resolve terrain badly, so a valley station and its grid node can sit in
  different rainfall regimes a few kilometres apart.

None of that is a reason to avoid gridded data — station networks are too
sparse to write a book on. It is a reason to measure the disagreement before
the dataset is named in a wording.

## The procedure

**Build an event list first.** For the region and peril in question, assemble
dates and locations where something documented happened: cyclone landfalls,
cloudburst dates, declared drought years, state agriculture-department loss
notifications, insurer event reports, credible dated news coverage. This list is
built by hand and it is the ground truth for everything that follows. It does
not need to be large — twenty to forty well-documented events is enough to
separate candidate datasets.

**Run every candidate over those dates.** Same index definition, same trigger,
each candidate dataset. Ask a binary question: would this cover have fired?

**Score with contingency statistics.** `src/validation.py` implements them:

| | meaning | what it costs you |
|---|---|---|
| **POD** | of real events, the share the dataset saw | misses are unpaid genuine losses — the distribution partner walks |
| **FAR** | of firings, the share with no real event | false alarms are paid non-losses — the reinsurer walks |
| **CSI** | combined score | the one to rank on |
| **bias** | firings ÷ events | >1 means the trigger is too loose before you even look at strikes |

**Check the bias against station truth.** For nodes with a usable nearby
station, compare the candidate series directly: mean bias, RMSE, correlation,
wet-day agreement, and the ratio of the 95th percentiles. The last one is the
tell for extreme damping.

**Check stationarity.** A cover priced off 33 years is only defensible if the
peril is roughly stable across them. Split the record, compare means and upper
percentiles. When the recent half is materially heavier, the 30-year burn cost
understates the rate — either the trailing 10-year window has to carry more
weight, or the strikes have to move.

**Then apply the operational filter.** A dataset can win on every score above
and still be unusable:

* Is it published on a schedule that lets you settle inside the promised window?
  A parametric cover's whole product promise is a fast payout; a dataset with a
  three-month publication lag cannot deliver it.
* Is it versioned, and can values be revised *after* settlement? Retro-revision
  is disqualifying — you cannot re-open a settled claim.
* Is the licence compatible with using it as a contractual settlement source?
* Will it still exist in five years, and does someone accountable publish it?

Operational failure is the more common reason to reject a dataset than accuracy.

## What went into this in practice

Different programmes ended up on different sources for exactly these reasons —
national met service gridded data where it existed and was timely, satellite
rainfall (CHIRPS, CMORPH, TAMSAT) where station networks were too thin,
reanalysis (ERA5) where a long consistent record mattered more than local
precision, forecast fields (GEFS/GFS) where a cover needed a forward-looking
trigger, and IBTrACS for cyclone wind. For one temperature cover I built the
same index on six candidate sources — gridded at two resolutions, surface daily,
AWS, WMO stations, and a hydrology network — purely to see how far apart they
placed the trigger. They were not close, and that comparison, not a preference,
is what picked the source.

The cross-check I used most was the cheapest one: take the dates the index says
were extreme, and go find out — from bulletins, reports and dated news — whether
anything actually happened there that day. A dataset that fires on days nobody
remembers is telling you something.
