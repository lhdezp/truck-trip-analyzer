# Architecture

## Purpose

Truck Load Analyzer turns load offer screenshots into a structured, financially
justified recommendation. Deterministic Python code owns every calculation; the AI
provider only extracts and interprets what is visible in the images.

## Layers

| Layer | Responsibility | May import |
|---|---|---|
| `domain` | Entities, value objects, business rules, financial maths, decision rules | standard library, Pydantic, `domain` itself |
| `application` | Use cases, orchestration, ports (interfaces), application schemas | `domain`, its own ports |
| `infrastructure` | Gemini, Freight Data Watch, OpenRouteService, NWS, SQLAlchemy, HTTPX adapters | `domain`, `application` ports, third-party SDKs |
| `presentation` | FastAPI routers, aiogram handlers | `application` use cases and schemas |
| `helpers` | Generic utilities with no business meaning | standard library |

Dependency rule: **inward only**. `domain` knows nobody. `presentation` never
calculates money. `application` never imports `fastapi`, `aiogram`, `google-genai`,
`sqlalchemy` or `httpx`.

## Target structure

```text
src/app/
├── main.py                     entrypoint and future composition root
├── config.py                   settings
├── logging_config.py           logging setup
├── exceptions.py               common errors
├── domain/
│   ├── base.py                 ValueObject (frozen) and Entity bases
│   ├── exceptions.py           domain errors
│   ├── entities/               load.py, vehicle.py
│   ├── value_objects/          money, distance, weight, dimensions, location,
│   │                           time_window, equipment, provenance, costs,
│   │                           profitability, compatibility, recommendation,
│   │                           driver_pay
│   ├── services/               financial engine, vehicle compatibility
│   └── rules/                  thresholds and preliminary recommendation
├── application/
│   ├── schemas/                extraction, analysis, result, routing, weather
│   ├── interfaces/             vision, market, routing, weather, clock ports
│   ├── use_cases/              V0.6 (AnalyzeLoadUseCase)
│   └── services/               extraction_merge (cross-image consolidation)
├── infrastructure/             ai/gemini (wire, prompt, mapping, provider)
│                               market/freight_datawatch, maps/openrouteservice,
│                               weather/nws, external (V0.5+), persistence (V0.9)
├── presentation/               api/ (routers, dependencies, middleware), telegram/
├── helpers/
└── dependencies/               dependency wiring
```

Only the modules that hold real code exist today. Empty packages are added with the
feature that needs them, so the tree never claims capability the code does not have.

## Current state (V0.1 to V0.4)

- `config.py`: `Settings` validates every environment variable declared in
  `.env.example`, wraps credentials in `SecretStr`, parses
  `TELEGRAM_ALLOWED_USERS` and exposes `safe_summary()` for logging. AI timeout and
  image-count limits are validated here too (`GEMINI_TIMEOUT_SECONDS`,
  `MAX_IMAGES_PER_ANALYSIS`).
- `logging_config.py`: single root-logger configuration, called explicitly by the
  entrypoint, never on import. It is **not** named `logging.py` on purpose: a module
  with that name shadows the standard library as soon as the package directory lands
  on `sys.path[0]`, which happens when the file is executed directly.
- `exceptions.py`: `AppError`, `ConfigurationError` and `ProviderError` as the shared
  error hierarchy. Provider adapters translate vendor failures into `ProviderError`.
- `main.py`: loads settings, configures logging, logs a secret-free summary and builds
  the Gemini adapter, so a missing `GEMINI_MODEL` or key is caught at boot instead of
  on the first request.
- `domain/`: `LoadOffer`, `VehicleProfile`, value objects with units and invariants,
  `SourcedField[T]` for provenance, the financial engine, vehicle compatibility and the
  preliminary decision rules. See [domain-model.md](domain-model.md) and
  [business-rules.md](business-rules.md).
- `application/schemas/`: extraction, analysis blocks and the nine-block result.
- `application/interfaces/`: `VisionProvider`, `MarketDataProvider`,
  `RoutingProvider`, `WeatherProvider`, `Clock` ports.
- `application/services/`: `merge_extractions`, the deterministic cross-image
  consolidation used by every vision adapter.
- `infrastructure/ai/gemini/`: wire schemas, extraction prompt, wire-to-domain mapping
  and `GeminiVisionProvider`. See [providers/gemini.md](providers/gemini.md).
- No FastAPI application, no Telegram bot, no routing or weather client, no
  persistence.
- `infrastructure/market/freight_datawatch/`: `FreightDataWatchClient` (HTTP,
  explicit User-Agent, vendor errors to `ProviderError`) and
  `FreightDataWatchMarketProvider`, which maps the national specialized-equipment
  rates to `MarketReference`. See [providers/freight-datawatch.md](providers/freight-datawatch.md).

## Decisions

### D1 — Project identity

Distribution name `truck-load-analyzer`, importable package `app` under `src/`,
console script `truck-analyzer`. Repository directory keeps its original name to
avoid breaking existing paths.

### D2 — Secrets optional in development, mandatory in production

Exigir credenciales para arrancar en desarrollo bloquea el trabajo real y empuja a
valores falsos. El validador de `APP_ENV=production` exige `API_SECRET`,
`TELEGRAM_BOT_TOKEN`, `GEMINI_API_KEY`, `GEMINI_MODEL`,
`FREIGHT_DATAWATCH_API_KEY`, `OPENROUTESERVICE_API_KEY` y al menos un
`TELEGRAM_ALLOWED_USERS`. Faltante ⇒ `ConfigurationError` con la lista exacta.

### D3 — Secrets never leave the process

All credentials are `SecretStr`. Logs and `repr` show `**********`; only
`secrets_configured: {name: bool}` is logged.

### D4 — Configuration is the only environment reader

`get_settings()` is cached and is the single access point. `os.environ` must not be
read anywhere else, which keeps tests and future dependency injection simple.

### D5 — No placeholder scaffolding

Empty layers, routers and handlers are created together with their first real
implementation. A file that exists but does nothing is a claim the system cannot
back.

### D6 — Quality gates are declared, not assumed

Ruff (`E,F,W,I,UP,B,SIM,RUF`, line length 100, py313) and mypy `strict` with the
`pydantic.mypy` plugin are configured in `pyproject.toml`. They run once the owner
installs the dev group with `uv sync`.

### D7 — No HTTP surface yet

FastAPI and uvicorn are declared dependencies because the stack requires them, but no
application object, router or `/health` endpoint exists. Health checks belong to
V0.7, where authentication and error normalisation are designed together.

### D8 — Market provider is Freight Data Watch, not Stretch XL

Stretch XL is dropped from the stack by owner decision. The replacement is the
Freight Data Watch API (`https://app.freightdatawatch.com/api/v1`), whose contract is
recorded in [providers/freight-datawatch.md](providers/freight-datawatch.md).

Why it fits: the only endpoint that publishes **Box Truck** rates
(`/market/specialized`) is included in the free tier (100 req/day), so market
context does not require a paid plan for the MVP.

What it constrains, and the docs say so explicitly:

- Box Truck `$1.93/mi` is a **modeled national estimate**, not load-board transaction
  data, with no lane, metro or state breakdown and no sample counts. Market analysis
  may compare against it only as `ESTIMATED` / national, never as a lane comparable.
- Dry van, reefer and flatbed rates are not substitutes. Presenting them as Box Truck
  equivalents would invent comparability that the provider does not offer.
- The provider rejects default script user agents (`403` / Cloudflare `1010`), so the
  adapter must send an explicit `User-Agent`.
- Quota is daily per key and exposed via `X-RateLimit-Remaining`; the adapter must
  surface that instead of silently exhausting the allowance.

Renamed configuration: `STRETCH_XL_API_KEY` → `FREIGHT_DATAWATCH_API_KEY`, plus
`MARKET_PROVIDER` and `FREIGHT_DATAWATCH_BASE_URL`. The base URL is configurable so
integration tests can point at a local stub.

### D9 — Pydantic inside the domain

The domain imports Pydantic. It does not import FastAPI, aiogram, google-genai,
httpx or SQLAlchemy.

Why: Pydantic is a pure validation library with no I/O, no transport and no
persistence. Using it in the domain gives one validation technology instead of
dataclass entities plus a parallel DTO layer that must be kept in sync. The layer
rule that matters — no provider, transport or database coupling — is untouched.

Cost accepted: swapping Pydantic would touch the domain. That is a deliberate,
one-time trade for eliminating a whole class of drift bugs, not an accidental
dependency.

### D10 — One Gemini request per image, merge in Python

The adapter sends one screenshot per request and combines the answers with
`merge_extractions`. Letting the model consolidate several screenshots in one prompt
would produce a single answer with no auditable trail: a value that appears in image A
but not image B could not be traced to its source, and a disagreement would vanish
into prose.

The cost is more requests and a merge step. The benefit is that every field keeps its
`evidence_refs`, agreement is explicit (`HIGH` when every capture agrees with a quote),
and disagreement becomes a `Contradiction` with `LOW` confidence instead of an
invisible average.

A screenshot that fails is reported as `image_failed:<reference>` and the analysis
continues; only when every image fails does the provider raise.

### D11 — The response schema is a transport type, not a domain type

`infrastructure/ai/gemini/wire.py` mirrors what the model may return, with every value
wrapped in `{value, evidence}` and every field optional. Domain construction happens
afterwards in `mapping.py`, where each value is validated by the value object that owns
the rule.

Why not ask Gemini for domain objects directly: Pydantic's `extra="forbid"` emits
`additionalProperties: false` into the response schema, which the API rejects, and a
single failed nested field would reject the whole answer. Mapping per field means one
unreadable ZIP code does not cost us the rest of the offer.


