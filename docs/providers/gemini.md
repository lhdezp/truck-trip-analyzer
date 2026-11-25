# Gemini vision provider (V0.4)

Adapter: `src/app/infrastructure/ai/gemini/`. Port:
`src/app/application/interfaces/vision.py`.

Status: **code complete**. All logic is verified offline. A live call could not be
completed from this machine because the configured `GEMINI_API_KEY` is rejected at
Google's edge with `403 Forbidden` (an HTML error page, not an API error body). See
[Live verification](#live-verification).

## Configuration

| Variable | Default | Rule |
|---|---|---|
| `AI_PROVIDER` | `gemini` | only supported value |
| `GEMINI_API_KEY` | — | required to start the adapter |
| `GEMINI_MODEL` | — | required; the adapter refuses to start with an empty model |
| `GEMINI_TIMEOUT_SECONDS` | `60` | `0 < value ≤ 300`, converted to milliseconds for the SDK |
| `MAX_IMAGES_PER_ANALYSIS` | `6` | `1 ≤ value ≤ 20`; enforced before any request is sent |

`GEMINI_TIMEOUT_SECONDS` becomes `HttpOptions.timeout`, which the SDK expresses in
**milliseconds**. The client also retries transport-level failures three times with a
1 s initial delay and an 8 s cap; a call that still fails is translated to
`ProviderError`.

Missing credentials or model raise `ConfigurationError`. The key is read from
`SecretStr` and never logged.

## Request shape

One request per image, issued concurrently with `asyncio.gather`:

```text
system_instruction = EXTRACTION_INSTRUCTION          # fixed transcription contract
contents           = [prompt text, image part]       # prompt includes "Screenshot reference: <ref>"
config             = GenerateContentConfig(
                        response_mime_type="application/json",
                        response_schema=WireExtraction,
                        temperature=0,
                     )
```

The model is asked for structured output, so the answer is validated by Pydantic
instead of parsed with string surgery. `response.parsed` is used when the SDK provides
it; otherwise the adapter validates `response.text` as JSON.

## Wire schema

`wire.py` describes what the model may say. Every value is wrapped:

```json
{"value": "Miami", "evidence": "Miami, FL 33101"}
```

Rules that shape the schema:

- every field is optional; absence must be expressible;
- numbers are `float`/`int`, never `Decimal` (JSON has no decimal type);
- prices split into `total_usd` and `rate_per_mile_usd`, because load boards publish
  either one or both;
- windows are ISO 8601 **strings**, converted in Python;
- `is_load_offer` and `unreadable` let the model decline a screenshot without inventing
  an empty offer.

The wire models use `extra="ignore"` instead of the project-wide `extra="forbid"`.
Forbidding extra keys emits `additionalProperties: false` into the JSON response
schema, and the API rejects that. Strictness lives in the mapping layer and in the
domain, where an unknown field cannot be smuggled into a value object.

## Prompt contract

The system instruction is a transcription contract. Summary of the enforced rules:

1. Copy only what is visible; never complete, average or "correct" a value.
2. A field that is not visible is `null`, never zero or a placeholder.
3. Every reported value carries a verbatim `evidence` quote.
4. No arithmetic and no unit conversion, at all.
5. No judgement about the offer: extraction is not analysis.
6. Local wall-clock ISO times; a date without an hour is returned as `YYYY-MM-DD`.
7. Equipment labels are copied verbatim; the category mapping happens in Python.
8. Several offers in one screenshot produce several `offers` entries.
9. `contradictions` only for conflicts inside the same screenshot.
10. Not-a-load-offer and unreadable screenshots are declared, not guessed.

The caller's optional `context` is appended after the rules and labelled as *not
evidence*: it may focus attention but can never fill a missing value.

## Mapping rules

`mapping.py` turns one wire payload into one `LoadExtraction`. Every value is rebuilt
through its domain value object, so the invariants live in one place.

| Wire field | Domain type | Notes |
|---|---|---|
| `broker`, `reference_number`, `commodity`, `notes` | `SourcedField[str]` | whitespace collapsed, blank rejected |
| `origin`, `destination` | `SourcedField[USLocation]` | city **and** state required; state validated against the US list |
| `announced_distance_miles` | `SourcedField[Distance]` | miles, non-negative |
| `weight_pounds` | `SourcedField[Weight]` | pounds, strictly positive (tons are not converted) |
| `pieces` | `SourcedField[int]` | `≥ 1` |
| `dimensions` | `SourcedField[Dimensions]` | all three axes or none |
| `pickup_window`, `delivery_window` | `SourcedField[TimeWindow]` | ISO 8601, local wall clock, `end ≥ start` |
| `required_equipment` | `SourcedField[EquipmentType]` | alias table, escalates unknown labels instead of guessing |
| `special_requirements` | `SourcedField[tuple[str, ...]]` | deduplicated, order preserved |
| `price.total_usd` | `SourcedField[Money]` | non-negative, rounded to cents by the domain |
| `price.rate_per_mile_usd` | `SourcedField[Money]` | only with a visible distance; see below |

A value that fails validation is **dropped** and the field is added to
`ambiguous_fields`. It is never floored, clamped, upper-cased into validity or replaced
by a default. A malformed ZIP code does not cost the rest of the offer.

### Derived total from a per-mile rate

Some offers publish only a rate. When the same screenshot also publishes the distance,
the total is computed in Python as `rate × miles`:

- `source` becomes `DataSource.CALCULATED`, not `EXTRACTED`;
- confidence is capped at `MEDIUM`;
- the evidence records both the visible quote and the derivation;
- without a visible distance the price stays unknown and `price_offered` is flagged.

This is the only arithmetic in the adapter, and it multiplies two visible numbers. It
never estimates a rate from a total, never estimates distance, and never touches costs,
profit or RPM.

### Confidence

| Situation | Confidence |
|---|---|
| value plus a non-empty evidence quote | `HIGH` |
| value without evidence | `MEDIUM` |
| derived total | `MEDIUM` |
| disagreement across captures | `LOW` |

### Date-only windows

A window printed as a date (`2026-11-25`) is stored at midnight so the day survives, but
the field is added to `ambiguous_fields`: the hour is unknown, it is not 00:00. Time
zones are never inferred; an aware timestamp is preserved as given and an aware/naive
mix is rejected.

## Multi-image merge

`application/services/extraction_merge.py` combines the per-image results. It is pure
Python, deterministic and independent of Gemini.

| Situation | Result |
|---|---|
| one extraction | returned unchanged |
| every capture agrees | one value, `evidence_refs` union, `HIGH` when a quote exists |
| some captures omit the field | value kept, `MEDIUM`: partial agreement is not proof |
| captures disagree | first reading kept, confidence `LOW`, explicit `Contradiction` listing every variant and its reference |

Values are never averaged. `images_analyzed` sums, `extracted_at` is the latest
timestamp, contradictions and ambiguous fields are deduplicated. When sources agree,
the strongest provenance wins (`USER_PROVIDED` > `EXTRACTED` > `API` > `CALCULATED` >
`ESTIMATED`).

## Failure handling

| Failure | Behaviour |
|---|---|
| no images | `DomainValidationError` |
| more than `MAX_IMAGES_PER_ANALYSIS` | `DomainValidationError`, before any request |
| empty model or missing key | `ConfigurationError` at construction |
| one image fails | logged, reported as `image_failed:<reference>`, other images still analysed |
| every image fails | `ProviderError`; the original cause is preserved |
| SDK/transport exception | `ProviderError` with `provider="gemini"`; vendor classes never escape |
| response is not valid JSON or not the schema | `ProviderError` |

Vendor exception classes are translated broadly on purpose: google-genai changed its
HTTP stack across versions and those classes are not part of this project's contract.

## Limits and open points

- Media types are `image/jpeg`, `image/png`, `image/webp`, each ≤ 8 MiB (contract in
  `application/schemas/extraction.py`). PDFs and HEIC are not accepted.
- No response caching and no token accounting yet; both belong with persistence in
  V0.9.
- Token limits are not enforced per request; an oversized screenshot is bounded only by
  the 8 MiB contract.
- `raw_text` stores the model's JSON answer for one screenshot; across multiple
  screenshots it is `None` to avoid keeping a concatenation of unrelated payloads.
- The equipment alias table covers common US load-board labels. An unknown label is
  flagged, not guessed; the table will grow from real screenshots.

## Live verification

Offline verification (2026-11-24) ran 58 checks through the real adapter with a fake
`generate` function: clean extraction, evidence and confidence, rate-to-total
derivation, every invalid-field rejection, alias normalisation, date-only windows,
multiple offers, not-a-load-offer, unreadable screenshots, merge agreement and conflict,
partial agreement, image-count and input validation, per-image degradation, JSON-text
fallback, and the two configuration failures. `ruff` and `mypy` are clean.

The live call was attempted with a 1×1 PNG and the configured key:

```text
ProviderError: Gemini request failed for 'probe:1x1'
  cause: ClientError 403 Forbidden. {'message': '<!DOCTYPE html> ... Error 403 (Forbidden)!!1 ...'}
```

The same 403 (HTML, not JSON) comes back from a bare `GET /v1beta/models` with the same
key, so it is a credential/account/network restriction, not a schema or prompt failure.
Until a working key is available, the request shape (system instruction, image part,
`response_schema`) is verified against the installed SDK (3.6.1) but not against the
live endpoint.

To unblock: issue a key that is allowed to call `generativelanguage.googleapis.com`
from this network, set `GEMINI_API_KEY`, and re-run an extraction with one real load
screenshot. No code change should be needed.
