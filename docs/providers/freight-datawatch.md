# Provider contract — Freight Data Watch

Status: **client implemented** (V0.5) against the live API. Payloads below are
recorded from real responses (2026-11-24), not inferred from the portal. The
routing and weather providers are not yet implemented; their open questions remain.

## Recorded responses (2026-11-24)

The live API answered three endpoints with a valid key. The shapes the client
consumes are now known and pinned in
`src/app/infrastructure/market/freight_datawatch/wire.py`:

`GET /market/specialized`

```json
{
  "equipment": {
    "boxTruck":   { "avgRate": 1.93, "rateChange": 1.0, "availability": "Moderate",
                    "avgLoadWeight": 10200, "demandTrend": "Growing",
                    "historicalMonthly": [ { "month": "2025-12", "rate": 1.71 }, "..." ],
                    "topLanes": [ "NYC-Philadelphia", "..." ] },
    "hotShot":    { "avgRate": 2.37, "..." : "..." },
    "sprinterVan":{ "avgRate": 2.2,  "..." : "..." }
  },
  "dataType": "modeled_estimate",
  "geography": "national",
  "methodology": "Indicative national estimates ... avgRate equals the latest month ...",
  "attribution": "Freight Data Watch estimates — https://app.freightdatawatch.com",
  "lastUpdated": "2026-11-23T11:04:54Z"
}
```

Key facts the analysis depends on:

- `dataType` is `modeled_estimate` and `geography` is `national`. This is not
  load-board transaction data.
- The provider's keys are camelCase (`boxTruck`, `hotShot`, `sprinterVan`); the
  client maps them to `BOX_TRUCK`, `STRAIGHT_TRUCK` and `CARGO_VAN`. There is no
  `/market/specialized` entry for dry van, reefer or flatbed, so a query for those
  categories returns an empty reference list by design.
- `lastUpdated` is an ISO-8601 UTC timestamp; the client stamps every
  `MarketReference` with it.
- `rateChange` is a month-over-month percentage, not a dollar delta.

`GET /market` and `GET /market/summary` returned 200 as well, but they report
trailer-based spot/contract rates (dry van, reefer, flatbed) and a headline
summary. The MVP's market comparison only needs the specialized endpoint, so the
client is scoped to it; the other two are recorded here for later use.

Sources:

- Developer portal: <https://app.freightdatawatch.com/developers>
- Specialized equipment rates page: <https://app.freightdatawatch.com/freight-rates>
- Probe executed 2026-11-23: `GET https://app.freightdatawatch.com/api/v1/market`
  without a key returned `401` with body
  `{"error":"Missing or invalid API key. Include X-API-Key header."}`.

## Connection

| Item | Value |
|---|---|
| Base URL | `https://app.freightdatawatch.com/api/v1` |
| Auth | `Authorization: Bearer <key>` (docs also accept `X-API-Key: <key>`) |
| Content type | JSON, UTF-8 |
| Rate limit | Per API key, per **day**, resets at midnight UTC |
| Quota header | `X-RateLimit-Remaining` in every response |

**User-Agent requirement:** the portal warns that default script user agents (it
names `Python-urllib/3.x`) are rejected with `403` and Cloudflare error `1010` before
reaching the API. HTTPX must therefore send an explicit descriptive `User-Agent`
header on every request. This is a hard requirement of the adapter, not a nicety.

## Plans

| Plan | Price | Requests/day | Notable inclusions |
|---|---|---|---|
| Free | $0 | 100 | Market data & rates, top lanes, market summary, specialized equipment, cross-border |
| Starter | $79/mo | 200 | Free + doubled quota |
| Professional | $199/mo | 1,000 | + carrier search/lookup, trust scores, forecasts, port dwell, capacity index |
| Enterprise | $499/mo | 5,000 | + AI briefs, what-if scenarios, new carrier alerts, webhooks |

`/api/v1/market/specialized` — the only endpoint that reports Box Truck rates — is
listed under the **Free** tier, so the MVP does not need a paid plan for market rates.

## Endpoints advertised

Market intelligence: `GET /market`, `GET /lanes`, `GET /market/summary`,
`GET /market/specialized`, `GET /ports`, `GET /market/cross-border`,
`GET /market/forecast`, `GET /market/capacity-index`.

Carrier data: `GET /carriers/search`, `GET /carriers/:dot`,
`GET /carriers/:dot/snapshots`, `GET /carriers/:dot/trust-score`,
`GET /carriers/new`.

AI: `GET /ai/market-brief`, `POST /ai/scenario`.

Plan gating is enforced server-side: `403` means "endpoint not included in your
plan or account suspended", `429` means daily quota exhausted.

## Error shape

```json
{ "error": "Description of what went wrong" }
```

`400` invalid parameters, `401` invalid key, `403` plan/suspension, `404` unknown
resource, `429` quota, `500` server error.

## Data caveats that constrain the analysis

These are not implementation details; they change what the product may say.

1. **Box Truck rates are modeled estimates, not transactions.** The rates page states
   explicitly: "Modeled estimate — national, indicative estimates for box truck, hot
   shot and Sprinter van — not load-board transaction data. No state, metro or
   lane-level breakdowns or sample counts." Current published value: Box Truck
   `$1.93/mi` (updated daily).
2. **No lane-level box truck comparison exists** in this provider. Market analysis may
   compare a Box Truck offer against the national Box Truck estimate and must label it
   `ESTIMATED` + `national`, never as a lane comparable.
3. **Dry van / reefer / flatbed rates must never be substituted** for Box Truck,
   Straight Truck or Cargo Van. The site publishes regional spot and contract rates for
   those three trailer types only; using them as truck equivalents would invent a
   comparability that does not exist.
4. **Every market figure must carry its retrieval timestamp** (`market_data_timestamp`
   in the result contract) and the equipment category it belongs to.

## Open questions before implementing the client (V0.5)

The specialized-market client is implemented against the recorded response above.
The remaining open questions apply to the routing and weather providers, which are
not yet built:

- OpenRouteService: exact profile names accepted for a box truck, whether the free
  key enforces HOS-aware duration, and the response field names for distance vs.
  duration.
- NWS: whether a ZIP-code lookup for a route's ends is rate-limited, and how to
  express "no data" for a location without alerts.
- Whether 4xx responses on any provider consume daily quota.
- Whether a sandbox/test key exists for the market provider; otherwise integration
  tests use the recorded payloads above and a live call stays opt-in.
