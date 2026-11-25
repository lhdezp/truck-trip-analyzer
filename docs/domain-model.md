# Domain model and contracts (V0.2)

This document is the contract reference. If code and this document disagree, the code
is wrong.

## Principles encoded in the types

1. **Unknown is not zero.** Every optional load datum is `None` when unknown. A present
   datum can legitimately be zero (e.g. an offered price of `$0` is known, absurd, and
   analysable).
2. **A value never travels alone.** Relevant data is a `SourcedField[T]` carrying
   source, confidence, evidence, evidence references and observation time.
3. **Units live in the type.** `Distance` is miles, `Duration` is hours, `Weight` is
   pounds, `Money` is USD amounts, `RatePerMile` is USD per mile. No naked numbers in
   the financial path.
4. **No floats for money.** `Decimal`, rounded explicitly at construction.
5. **Incompatible comparisons are unrepresentable.** A `MarketReference` demands
   equipment category, geographic scope and a provider/estimate basis.

## Value objects

| Type | Unit | Precision | Invariants |
|---|---|---|---|
| `Money` | USD | 2 decimals, half-up | negative allowed (net profit can be negative) |
| `RatePerMile` | USD/mi | 4 decimals | sign allowed: net RPM is negative on a losing load; market references reject negatives |
| `RatePerHour` | USD/h | 2 decimals | negative allowed only if produced by a loss calculation |
| `Distance` | miles | 0.1 | non-negative |
| `Duration` | hours | 0.01 | non-negative |
| `Weight` | pounds | 0.1 | non-negative |
| `Dimensions` | inches | 0.1 | each axis > 0 |
| `USLocation` | — | — | 50 states + DC + PR; ZIP `12345` or `12345-6789`; city normalised |
| `TimeWindow` | local wall clock | — | `end >= start`; naive datetimes allowed but never treated as UTC |

`USLocation.postal_code` is a string on purpose: `00501` must not become `501`.

## Provenance

`DataSource`: `extracted`, `calculated`, `api`, `estimated`, `user_provided`.

`ConfidenceLevel`: `high`, `medium`, `low`, `unknown`. It expresses data quality and
consistency. It is **not** a probability and must never be shown as a percentage.

`SourcedField[T]`:

```python
SourcedField[Money](
    value=Money(amount=Decimal("1250.00")),
    source=DataSource.EXTRACTED,
    confidence=ConfidenceLevel.HIGH,
    evidence="Offer card: $1,250",
    evidence_refs=("image:0",),
    observed_at=datetime(...),
)
```

## Entities

### `LoadOffer`

Optionally holds: broker, reference number, origin, destination, announced distance,
offered price, commodity, weight, pieces (>= 1), dimensions, pickup window, delivery
window, required equipment, special requirements, notes. Each one is a
`SourcedField` or `None`.

`missing_fields()` returns what blocks a financial analysis, in stable order: `origin`,
`destination`, `price_offered`. Weight and dimensions degrade the compatibility check
but do not block cost estimation, so they are not in that list.

### `VehicleProfile`

Identity (`id`), name, equipment type, max payload, interior dimensions, MPG (> 0),
fuel price per gallon, operating cost per mile, driver pay policy, tolls per mile,
monthly fixed cost, restrictions, notes.

Factoring rate and deadhead assumptions are **excluded**: they describe a deal or a
business setting, not a vehicle. Baking them into the profile would make every profile
a policy document.

### Driver pay policy

A discriminated union, so invalid combinations cannot exist:

| Strategy | Fields |
|---|---|
| `per_mile` | `rate_per_mile`, `mile_basis` (`total` or `loaded`) |
| `percentage` | `percent` (0 < percent ≤ 100) |
| `hourly` | `rate_per_hour` |
| `fixed` | `amount` |

MPG is validated `> 0` at construction: the cheapest place to prevent a division by
zero.

## Equipment categories

`box_truck`, `straight_truck`, `cargo_van`, `dry_van`, `reefer`, `flatbed`, `other`.

`EquipmentType.is_straight_truck_family` distinguishes vehicles with an integrated
cargo box from trailer-based equipment. Market rates for the latter are not comparable
with the former.

## Extraction contract

`LoadExtraction` = `load: LoadOffer` + `contradictions`, `ambiguous_fields`,
`images_analyzed`, `provider`, `model`, `raw_text`, `extracted_at`.

`ImageInput` fixes the media types (`jpeg`, `png`, `webp`) and a hard ceiling of 8 MiB
in the contract itself, so API, Telegram and CLI cannot drift.

`Contradiction` names the field, describes the disagreement and points at evidence
references. A contradiction is data, not an exception: the analysis continues and
reports it.

## Result blocks

`LoadAnalysisResult` contains the nine blocks of the product contract:

| Block | Type | Notes |
|---|---|---|
| Load data | `LoadOffer` | always present |
| Route analysis | `RouteAnalysis \| None` | total must match loaded + empty within 0.5 mi |
| Vehicle compatibility | `VehicleCompatibility \| None` | `None` means undetermined, not incompatible |
| Cost analysis | `CostBreakdown \| None` | missing components stay `None` |
| Profitability | `Profitability \| None` | includes `is_complete` and `missing_inputs` |
| Market analysis | `MarketAnalysis \| None` | references carry scope + equipment |
| Dead zone analysis | `DeadZoneAnalysis \| None` | verified return loads separated from demand signals |
| Negotiation | `Negotiation \| None` | min <= target <= recommended max |
| Final recommendation | `FinalRecommendation` | always present, at least one reason |

Cross-cutting: `missing_fields`, `warnings` (`code`/`message`/`severity`), `confidence`,
`sources`, `calculated_at`, `market_data_timestamp`.

Enforced invariants:

- `RouteAnalysis`: `total_miles == loaded_miles + empty_miles` (tolerance 0.5 mi).
- `MarketReference`: basis must be `api` or `estimated`; extracted or user-provided
  numbers are not market data.
- `DeadZoneAnalysis`: cannot list return loads while `return_data_available` is false.
- `Negotiation`: minimum cannot exceed target; recommended max cannot be below target.
- `FinalRecommendation`: reasons are mandatory and non-empty.
- `WeatherReport`: `available` must match the actual presence of conditions.
- `LoadAnalysisResult`: references without `market_data_timestamp` are rejected.

## Financial engine and rules

`domain/services/financial.py` computes costs and profitability; `domain/services/
compatibility.py` checks vehicle fit; `domain/rules/recommendation.py` applies thresholds
and produces the preliminary decision. Formulas, assumptions, rounding and the verified
worked example are in [business-rules.md](business-rules.md).

`CostBreakdown`, `Profitability`, `VehicleCompatibility` and `FinalRecommendation` are
domain value objects: the engine owns them, and the application result contract composes
them. They are frozen, so a computed result cannot be mutated by a later layer.

## Ports

| Port | Implemented in |
|---|---|
| `VisionProvider.extract_load` | V0.4 (Gemini) |
| `MarketDataProvider.fetch_market_references` | V0.5 (Freight Data Watch) |
| `RoutingProvider.analyze_route` | V0.5 (OpenRouteService) |
| `WeatherProvider.get_weather_report` | V0.5 (NWS) |
| `Clock.now` | injected in tests and use cases |

## Deliberately absent

No market comparison, no dead-zone analysis, no negotiation bands, no persistence and no
provider clients. `CostBreakdown` is filled by the V0.3 engine; the blocks that depend on
external data stay empty until V0.5 and V0.6.
