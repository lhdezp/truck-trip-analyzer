# Financial rules (V0.3)

The engine lives in `src/app/domain/services/financial.py`. It is deterministic, has
no I/O, never calls an AI provider and never fills a gap with a guess.

Every formula below is implemented and was verified numerically on 2026-11-24 with the
worked example at the end of this document.

## Inputs

| Input | Type | Unknown? |
|---|---|---|
| Offered price | `Money` | required |
| Loaded miles | `Distance \| None` | `None` = unknown |
| Empty miles | `Distance \| None` | `None` = unknown |
| Duration | `Duration \| None` | `None` = unknown |
| Vehicle | `VehicleProfile` | required |
| Factoring rate | `Decimal \| None` | fraction 0–1; `None` = unknown |
| Diesel price | `Money \| None` | overrides the profile price |
| Tolls | `Money \| None` | overrides the per-mile estimate |
| Other costs | `Money \| None` | `None` = not declared |
| Driver pay | `DriverPayPolicy \| None` | overrides the profile policy |

"Unknown" never means zero. An unknown input makes the dependent metric `None` and adds
its name to `missing_inputs`.

## Formulas

```
total_miles   = loaded_miles + empty_miles
fuel          = total_miles / mpg × diesel_price
driver        = policy (see below)
factoring     = price_offered × factoring_rate
tolls         = tolls_per_mile × total_miles      (or an explicit amount)
operational   = operating_cost_per_mile × total_miles
other         = declared amount, or 0 with an explicit assumption
total_costs   = fuel + driver + factoring + tolls + operational + other
net_profit    = price_offered - total_costs
gross_rpm     = price_offered / total_miles       (only when total_miles > 0)
net_rpm       = net_profit / total_miles          (only when total_miles > 0)
profit_per_hour = net_profit / duration_hours     (only when duration_hours > 0)
```

`total_costs` is `None` unless **every** component is known. A partial sum would
understate cost and overstate profit, which is the worst possible bug in this product.

### Driver pay

| Strategy | Amount |
|---|---|
| `per_mile` | `miles × rate`; `mile_basis` selects total or loaded miles |
| `percentage` | `gross_revenue × percent / 100` (percent in 1–100) |
| `hourly` | `hours × rate`; requires duration |
| `fixed` | declared amount |

Per-mile pay defaults to **total** miles: the driver drives the deadhead too. Loaded-only
pay is supported because some fleets price it that way, and the choice is recorded as an
assumption in the result.

### Rounding

- `Money` → 2 decimals, half-up, at construction.
- `RatePerMile` → 4 decimals half-up.
- `RatePerHour` → 2 decimals half-up.
- `Distance` → 0.1 mi; `Duration` → 0.01 h.

Rounding happens when a value is created, never at display time, so two calculation
paths cannot disagree.

## Explicit assumptions

Assumptions are returned with the estimate and surface as warnings in the final result:

| Assumption | When |
|---|---|
| Other costs were not declared and are treated as zero. | `other_costs` omitted |
| Tolls are estimated from the vehicle toll rate per mile. | toll rate used instead of an explicit amount |
| Per-mile driver pay uses total (or loaded) miles. | per-mile policy |
| Monthly fixed costs are not allocated to a single load. | profile has a monthly fixed cost |

## Missing inputs

Possible names in `Profitability.missing_inputs`: `loaded_miles`, `empty_miles`,
`total_miles`, `fuel_price_per_gallon`, `driver_pay`, `factoring_rate`, `tolls`,
`operating_cost_per_mile`, `duration`.

Duplicates are removed, first occurrence wins, so the order is stable and explains the
root cause before its consequences.

`is_complete` is true only when net profit, gross RPM, net RPM and profit per hour are
all present. It is a strict definition on purpose: "complete" must not mean "most of it".

## Thresholds

`ProfitThresholds` is business policy supplied by the caller:

- `minimum_net_profit: Money`
- `minimum_net_rpm: RatePerMile`
- `minimum_profit_per_hour: RatePerHour | None`

Derived prices, both from real costs and never from market guesses:

```
break_even_price = total_costs
target_price     = total_costs + minimum_net_profit
```

`break_even_price` is the lowest offer that does not lose money. `target_price` is the
lowest offer that satisfies the profit policy. Negotiation use cases build their bands
from these two numbers in V0.6.

## Decision rules

Evaluated in order by `evaluate_recommendation`:

| Condition | Decision | Rationale |
|---|---|---|
| Net profit or net RPM unavailable | `INSUFFICIENT_DATA` | a categorical answer would be irresponsible |
| Net profit < 0 or net RPM < 0 | `REJECT` | the trip does not pay for itself; a few cents will not fix a structural loss |
| All thresholds met | `ACCEPT` | verified numbers satisfy policy |
| Any threshold missed | `NEGOTIATE` | viable but underpriced relative to policy |

Reasons are mandatory and always list which threshold passed or failed. Confidence is
passed in by the caller from the data-quality assessment; the rule does not invent it.

## Vehicle compatibility

`check_vehicle_compatibility` compares load against profile:

| Check | Incompatible when | Unknown when |
|---|---|---|
| Equipment | required equipment differs from the profile | load states no equipment |
| Payload | load weight > max payload | either weight is unknown |
| Dimensions | any cargo axis exceeds interior | either set is unknown |

`compatible` is `False` if any performed check fails, `True` only if all performed
checks pass and at least one ran, `None` otherwise.

**No substitution is assumed.** A `box_truck` load is not silently accepted for a
`straight_truck`, even though an operator might consider them close. That judgement
belongs to the person, not to a hardcoded equivalence.

## Worked example

Inputs: price `$1,250`, loaded `600 mi`, empty `100 mi`, duration `12 h`, MPG `10`,
diesel `$4.00/gal`, operating cost `$0.25/mi`, toll rate `$0.05/mi`, driver
`$0.60/mi` on total miles, factoring `3 %`.

| Line | Value |
|---|---|
| Total miles | 700.0 mi |
| Fuel | $280.00 |
| Driver | $420.00 |
| Factoring | $37.50 |
| Tolls | $35.00 |
| Operational | $175.00 |
| Other | $0.00 |
| **Total costs** | **$947.50** |
| **Net profit** | **$302.50** |
| Gross RPM | $1.7857/mi |
| Net RPM | $0.4321/mi |
| Profit per hour | $25.21/h |

With thresholds `$250`, `$0.40/mi` and `$25.00/h` the recommendation is `ACCEPT`.
Break-even price is `$947.50`; target price is `$1,197.50`.

## Out of scope for V0.3

Market comparison, dead-zone analysis, negotiation bands and the final assembled result
belong to V0.6. This engine answers one question: given these numbers, what does the trip
pay?

Known limitations, recorded rather than hidden:

- Monthly fixed costs are not allocated per load.
- Tolls are a per-mile estimate unless the caller supplies a real amount.
- No tax, insurance or maintenance schedule modelling.
- Duration comes from routing; the engine does not model hours-of-service legality.
