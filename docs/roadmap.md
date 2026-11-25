# Roadmap

Statuses: `PENDING`, `IN_PROGRESS`, `COMPLETED`, `BLOCKED`.

| Version | Scope | Status | Notes |
|---|---|---|---|
| 0.1 | Foundation: uv project, structure, settings, logging, tooling, docs | IN_PROGRESS | Code and configuration done. Tests and quality gates pending: the owner installs dependencies, and tests are added in a later phase. |
| 0.2 | Domain model and provider contracts | IN_PROGRESS | Code complete: entities, value objects, extraction/analysis/result schemas, ports. Test suite deferred by owner. |
| 0.3 | Financial engine | IN_PROGRESS | Code complete: costs, driver pay policies, profitability, thresholds, decision rules, vehicle compatibility. Test suite deferred by owner. |
| 0.4 | Gemini integration | IN_PROGRESS | Code complete: wire schema, transcription prompt, mapping to `LoadExtraction`, deterministic multi-image merge, per-image degradation. Live call blocked by key (403). |
| 0.5 | External integrations | IN_PROGRESS | Freight Data Watch market client implemented against the live API; response schema pinned. OpenRouteService and NWS still pending (routing/weather providers not yet built). |
| 0.6 | Analysis orchestration | IN_PROGRESS | `AnalyzeLoadUseCase` composes vision, market, routing, financial engine and recommendation. Partial results when a provider is unavailable. |
| 0.7 | REST API | PENDING | Bearer auth, image validation, rate limiting, OpenAPI. |
| 0.8 | Telegram bot | PENDING | aiogram 3, allowed-user check, shared use case. |
| 0.9 | Persistence and history | PENDING | SQLAlchemy + SQLite repositories behind domain-independent ports. |
| 1.0 | Complete MVP | PENDING | End-to-end validation and documentation. |

## V0.1 detail

Done:

- `pyproject.toml` with distribution `truck-load-analyzer`, runtime and dev
  dependency groups, Ruff, mypy, console script.
- `.gitignore` covering `.env`, databases and tool caches.
- `.env.example` with every variable; local `.env` created and ignored.
- `src/app`: `config.py`, `logging_config.py`, `exceptions.py`, `main.py`, `py.typed`.
- `docs/architecture.md`, this roadmap, README.

Remaining before `COMPLETED`:

- Test suite for configuration and layer boundaries (deferred by request; no `tests/`
  tree exists yet).

Verified on 2026-11-24: `uv sync` completed by the owner, `ruff check` and
`ruff format --check` clean, `mypy src` strict clean, and the entrypoint starts via
`python -m app.main`, the `truck-analyzer` script and direct file execution.

## V0.2 detail

Done:

- `domain/base.py`: `ValueObject` (frozen) and `Entity` bases with `extra="forbid"`.
- `domain/value_objects/`: `Money`, `RatePerMile`, `RatePerHour`, `Distance`,
  `Duration`, `Weight`, `Dimensions`, `USLocation`, `TimeWindow`, `EquipmentType`,
  `SourcedField[T]`, `DataSource`, `ConfidenceLevel`.
- `domain/entities/`: `LoadOffer` with `missing_fields()`, `VehicleProfile`.
- `application/schemas/`: extraction, analysis blocks, nine-block result, routing and
  weather contracts.
- `application/interfaces/`: `VisionProvider`, `MarketDataProvider`,
  `RoutingProvider`, `WeatherProvider`, `Clock`.
- `docs/domain-model.md` documenting types, invariants and deliberate omissions.

Verified by execution on 2026-11-24 (not stored as tests): 33 contract checks covering
rounding, negative money, unknown vs zero, invalid state/ZIP, MPG zero, route total
consistency, recommendation reasons, market basis rejection, unverified return loads,
negotiation band order, weather availability, missing market timestamp, oversized
image and forbidden domain imports. `ruff` and `mypy` clean.

Remaining before `COMPLETED`:

- Unit tests for the same invariants (deferred by owner: no `tests/` tree exists).

## V0.3 detail

Done:

- `domain/services/financial.py`: fuel, driver (per mile / percentage / hourly / fixed),
  factoring, tolls, operating cost, other cost, total cost, net profit, gross and net
  RPM, profit per hour. Incomplete inputs produce `None` plus named `missing_inputs`.
- `domain/services/compatibility.py`: equipment, payload and dimension checks.
- `domain/rules/recommendation.py`: `ProfitThresholds`, break-even and target price,
  `ACCEPT` / `NEGOTIATE` / `REJECT` / `INSUFFICIENT_DATA` rules.
- `domain/value_objects/`: `CostBreakdown`, `Profitability`, `FinancialEstimate`,
  `VehicleCompatibility`, `FinalRecommendation`, driver pay policies.
- `VehicleProfile.driver_cost_per_mile` replaced by the typed `driver_pay` policy, so
  there is one source of truth for driver compensation.
- `RatePerMile` now allows negative amounts: a losing load has negative net RPM.
  Non-negativity moved to `MarketReference`, where it actually applies.
- `docs/business-rules.md` with every formula, assumption and a worked example.

Verified by execution on 2026-11-24 (not stored as tests): 36 checks covering the
worked example to the cent, all four driver pay strategies, loss → `REJECT`,
unknown miles → `INSUFFICIENT_DATA`, zero miles and zero duration divisions, invalid
factoring rate, negative price, inconsistent profitability, and the three
compatibility outcomes. `ruff` and `mypy` clean.

Remaining before `COMPLETED`:

- Unit tests for the formulas and the decision table (deferred by owner).

## V0.4 detail

Done:

- `infrastructure/ai/gemini/wire.py`: response-schema models. Flat `{value, evidence}`
  wrappers, every field optional, `extra="ignore"` because `extra="forbid"` emits
  `additionalProperties: false`, which the API rejects.
- `infrastructure/ai/gemini/prompt.py`: fixed transcription contract. No arithmetic,
  no unit conversion, no guessed corrections; `evidence` is verbatim and mandatory;
  equipment labels are copied and mapped in Python; a date without an hour is returned
  as `YYYY-MM-DD`.
- `infrastructure/ai/gemini/mapping.py`: wire-to-domain translation. Every value is
  rebuilt through its value object, so an invalid ZIP or state does not cost the rest
  of the offer. A per-mile rate becomes a total only when the distance is visible on
  the same screenshot; that total is marked `CALCULATED` and capped at `MEDIUM`
  confidence.
- `application/services/extraction_merge.py`: deterministic multi-image
  consolidation. Agreement across every capture is `HIGH` when a quote exists, partial
  agreement is `MEDIUM`, disagreement keeps the first reading and drops to `LOW`
  with an explicit `Contradiction`. No averaging, ever.
- `infrastructure/ai/gemini/provider.py`: `GeminiVisionProvider`, one request per
  image with `asyncio.gather`, per-image `image_failed:<ref>` degradation and vendor
  errors translated to `ProviderError`. Configuration problems (`GEMINI_MODEL`
  missing, empty key) raise `ConfigurationError` before any request.
- `config.py`: `GEMINI_TIMEOUT_SECONDS` (`0 < value ≤ 300`) and
  `MAX_IMAGES_PER_ANALYSIS` (`1 ≤ value ≤ 20`).
- `application/schemas/extraction.py`: `LoadExtraction.warnings` so a degradation is
  reported, not silently dropped.
- `docs/providers/gemini.md`: request shape, prompt, mapping and merge rules,
  limits, and how to unblock the live check.

Verified by execution on 2026-11-24 (not stored as tests): 58 offline checks through
the real adapter with a fake `generate` function — clean extraction, evidence and
confidence, rate-to-total derivation, every invalid-field rejection, alias
normalisation, date-only windows, multiple offers, not-a-load-offer, unreadable
screenshots, merge agreement and conflict, partial agreement, image-count and input
validation, per-image degradation, JSON-text fallback, and the two configuration
failures. `ruff` and `mypy` clean.

Remaining before `COMPLETED`:

- Unit tests for the mapping and merge rules (deferred by owner).
- One real load screenshot through a working `GEMINI_API_KEY` to close the live
  check: the configured key returns `403 Forbidden` from Google's edge (an HTML page,
  not an API error), so it is a credential/account/network restriction, not a schema
  or prompt failure. No code change should be needed once a working key is set.

## V0.5 detail

Done:

- `infrastructure/market/freight_datawatch/wire.py`: response-schema models for the
  specialized-market payload, pinned from a recorded live response (2026-11-24).
- `infrastructure/market/freight_datawatch/provider.py`:
  `FreightDataWatchClient` (HTTP, explicit `User-Agent`, vendor errors to
  `ProviderError`) and `FreightDataWatchMarketProvider`, which maps the provider's
  national specialized rates to `MarketReference` with `basis=ESTIMATED` and
  `scope=NATIONAL`. Dry van, reefer and flatbed queries return an empty list by
  design, so a box truck is never compared against a trailer rate.
- `main.py` builds the market adapter at boot.

Verified against the live API on 2026-11-24 (not stored as tests): 13 checks
covering a box truck reference (rate, scope, basis, equipment, timestamp, notes),
the empty-list behaviour for dry van / reefer / flatbed, and the hotShot →
`STRAIGHT_TRUCK` and sprinterVan → `CARGO_VAN` mappings. `ruff` and `mypy` clean.

Remaining before `COMPLETED`:

- OpenRouteService routing adapter and NWS weather adapter (V0.5 still pending).
- Unit tests for the market client (deferred by owner).

## Blocked / waiting on information

Freight Data Watch: the developer portal documents paths, auth, plans and error codes,
but not response payloads. V0.5 needs one recorded response per endpoint (or a sandbox
key) to fix field names, units and timestamps. Until then, the market adapter must not
be written. See [providers/freight-datawatch.md](providers/freight-datawatch.md).

Gemini: the configured `GEMINI_API_KEY` returns `403 Forbidden` from Google's edge
(an HTML error page, not an API error body). This blocks the live-call check for
V0.4. A working key is needed; no code change is expected once a valid key is set.
