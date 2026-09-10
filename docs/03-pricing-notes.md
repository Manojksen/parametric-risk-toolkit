# Pricing notes

## Everything is a fraction of sum insured

Payouts, losses and premiums are all held as a fraction of SI — never currency.
That is what lets a Rajasthan cumin cover and a Honduran coffee cover sit in one
portfolio table and be compared, and it keeps FX and inflation out of the risk
model where they do not belong.

## The strike ladder

A step ladder, typically five steps, with payouts at 5% / 15% / 30% / 65% / 100%
of SI. `direction='above'` for excess perils (rainfall accumulation, heat days,
wind speed), `direction='below'` for deficit perils (capped rainfall total).

Two rules the code enforces because both get violated by hand:

* **Ladders do not stack.** The payout is that of the deepest step breached, not
  the sum of every step breached. A 5-step ladder that stacks pays 215% of SI on
  a severe event.
* **A zero index never pays.** An 'above' ladder whose first strike sits at zero
  is not insurance, it is a coupon. Strikes are floored above the smallest
  event-bearing value.

## Combining phases and perils

Phases of the **same peril** combine with `max` by default: only the worst phase
pays. This is standard for rainfall covers and it exists for a real reason — one
weather system straddling a phase boundary would otherwise pay twice for one
event. `sum` (capped) is available where phases are genuinely independent.

Different **perils** on the same policy are additive, capped at SI. Blight and
excess rainfall are separate physical failures; a season can suffer both.

## Solving the ladder backwards

The usual order is: choose strikes, compute the burn cost, discover the price,
tell the client, watch them refuse it, adjust, repeat.

The conversation actually starts at the price. A subsidised agri cover lives at
roughly **3% of sum insured**: much above that and the farmer will not buy and
the subsidy will not stretch; much below and there is no meaningful cover left
to sell. So `calibrate_ladder_to_target` fixes the rate and searches for the
ladder that delivers it — strikes placed at percentiles of the historical index,
then the whole ladder shifted in percentile space by bisection until the burn
cost lands on target.

`calibrate_peril_to_target` wraps that with an outer bisection, because the
target has to be imposed **after** the phases combine. Three phases each
calibrated to 1.8% do not combine to 1.8%; take the worst phase and you are near
5%. The outer loop searches for the common per-phase rate whose combined loss
equals the peril's target.

Rates are then allocated across perils by design intent — on the worked cumin
example, 1.8% to blight and 1.2% to excess rainfall out of a 3% budget, because
blight is the peril the client was actually buying protection against.

## Burn cost

Trailing means over 10, 20 and 30 years, then their simple average.

Each window is wrong on its own. Ten years carries the current climate signal
but almost no tail — one bad year moves it by ten percent of itself. Thirty
years is stable but averages in a climate that no longer exists. Averaging the
three stops either from dominating, and it is what the market expects to see, so
it does not need defending in every negotiation.

Reported alongside, always: **max historical loss** and **loss frequency**. A 2%
rate means something very different when the worst year paid 15% than when it
paid 100% of SI, and a cover that pays a little in half of all years is a
different product from one that pays a lot in one year of fifteen — even at the
identical rate.

## Risk premium

Expected loss plus a loading for the uncertainty in the expected loss itself.

The blended burn cost is a point estimate of a mean off roughly thirty draws of
a heavily skewed distribution. Selling at that number assumes the sample was
representative. It usually is not, and the loading — a multiple of the standard
error of the loss distribution — is what stops a quiet thirty-year sample from
being priced at a rate the first real event wipes out.

## Commercial premium

Risk premium grossed up multiplicatively for expenses, cession margin and
profit — default 20% / 10% / 5%, so a 3.5% risk premium becomes 5.4% commercial.
Multiplicative because the loadings apply to premium actually collected, not to
the pure loss cost.

## Portfolio metrics

The unit-level rate is not what a reinsurer buys. They buy the aggregate, and
what they want to know is what the whole book would have cost in each of the
last thirty-odd years:

* **expected loss** — the technical rate for the book
* **VaR 95 / TVaR 95** — the bad year, and the average of the bad years
* **PML 1-in-25** — the capacity question
* **max historical loss**

Agri risk is spatially correlated in a way that motor or property is not: a
monsoon failure is felt by every policy in the state at once, so diversification
inside a book is far weaker than the location count suggests. The year-by-year
portfolio table is where that shows up honestly, and it is the table that
decides whether the programme is cedeable at all.
