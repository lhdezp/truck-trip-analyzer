# Truck Load Analyzer

Analyze freight load offers from US load boards and get a funded recommendation:
**ACCEPT**, **NEGOTIATE**, **REJECT** or **INSUFFICIENT_DATA**.

The project is built in phases. Code currently ships up to **V0.4**: typed
configuration, logging, common exceptions, the domain model, the financial engine and
the Gemini vision adapter. No market/routing/weather client, HTTP API, Telegram bot or
persistence is implemented yet, and no module pretends otherwise.

## Status

| Phase | Scope | Status |
|---|---|---|
| 0.1 | Project foundation | IN_PROGRESS (tests and quality gates pending) |
| 0.2 | Domain model and contracts | IN_PROGRESS (code complete, tests pending) |
| 0.3 | Financial engine | IN_PROGRESS (code complete, tests pending) |
| 0.4 | Gemini extraction | IN_PROGRESS (code complete, live call blocked by key; tests pending) |
| 0.5 | External integrations | IN_PROGRESS (market done; routing and weather pending) |
| 0.6 | Analysis orchestration | PENDING |
| 0.7 | REST API | PENDING |
| 0.8 | Telegram bot | PENDING |
| 0.9 | Persistence and history | PENDING |
| 1.0 | Complete MVP | PENDING |

See [docs/roadmap.md](docs/roadmap.md) for the detailed breakdown.

## Requirements

- Python 3.13+
- [uv](https://docs.astral.sh/uv/)

## Setup

```bash
uv sync                    # resolves and installs runtime + dev dependencies
cp .env.example .env       # on Windows: copy .env.example .env
```

`.env` is ignored by git. Never commit real credentials; `.env.example` documents
every variable with safe placeholders.

Development runs with empty secrets on purpose. With `APP_ENV=production` the
application refuses to start unless every required secret, the Gemini model and at
least one allowed Telegram user are configured.

## Commands

```bash
uv run truck-analyzer         # bootstrap: validate config, configure logging
uv run python -m app.main     # same entrypoint without the console script
uv run ruff check .           # lint
uv run ruff format --check .  # formatting
uv run mypy src               # static typing (strict)
uv run pytest                 # test suite (added in a later phase)
```

## Layout

```text
src/app/
├── __init__.py            package version
├── main.py                process entrypoint
├── config.py              validated settings (pydantic-settings)
├── logging_config.py      logging configuration
├── exceptions.py          common application errors
├── py.typed               typing marker
├── domain/
│   ├── base.py            ValueObject / Entity bases
│   ├── exceptions.py      domain errors
│   ├── entities/          LoadOffer, VehicleProfile
│   ├── value_objects/     money, distance, weight, dimensions, location,
│   │                      time_window, equipment, provenance, costs,
│   │                      profitability, compatibility, recommendation, driver_pay
│   ├── services/          financial engine, vehicle compatibility
│   └── rules/             thresholds and preliminary recommendation
└── application/
    ├── schemas/           extraction, analysis, result, routing, weather
    ├── interfaces/        vision, market, routing, weather, clock ports
    └── services/          cross-image extraction merge
└── infrastructure/
    ├── ai/gemini/         wire schema, prompt, mapping, provider
    └── market/freight_datawatch/   wire schema, HTTP client, market provider
```

Market, routing, weather and persistence adapters land in V0.5 and V0.9. The target
structure and the dependency rules are documented in
[docs/architecture.md](docs/architecture.md); the contract reference is
[docs/domain-model.md](docs/domain-model.md).

## Documentation

- [docs/architecture.md](docs/architecture.md) — layers, dependency rule, decisions
- [docs/domain-model.md](docs/domain-model.md) — value objects, entities, invariants
- [docs/business-rules.md](docs/business-rules.md) — formulas, assumptions, decision rules
- [docs/providers/gemini.md](docs/providers/gemini.md) — Gemini adapter design, mapping and merge rules
- [docs/providers/freight-datawatch.md](docs/providers/freight-datawatch.md) — market data contract, recorded responses, client
- [docs/roadmap.md](docs/roadmap.md) — phase status
