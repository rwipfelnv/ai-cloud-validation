# API-shape coverage analysis

A prototype: does an NCP's public API even expose a surface that could satisfy
our offtake requirements, judged by reading its OpenAPI spec alone - no live
account, no test run. This is useful for API-first providers (e.g. Lambda
Cloud) where there's no Terraform provider to point the existing test harness
at, and it's cheap enough to run before any account/credentials exist.

## What this is (and isn't)

This is a **static structural** check: "is there a path/schema that plausibly
covers this requirement." It is not a substitute for `isvtest`/`isvctl`, which
validate *behavior* against a live account. A field existing in a schema
doesn't mean the feature works correctly, only that the provider built
*something* in that shape. Treat `present`/`partial` as "worth a live
follow-up test," and `absent` as "worth a direct question to the provider" -
per Brad's framing, a real absence here is informative in itself.

## Files

| File | Role |
| ---- | ---- |
| `<provider>.yaml` | Curated mapping: per offtake `req_id`, a `status` (`present`/`partial`/`absent`/`not_applicable`) with `evidence` pointing into the vendored spec. The judgment call is made by a human/AI reading the spec; this is the actual analysis artifact. |
| `specs/<provider>-openapi.json` | Vendored snapshot of the provider's OpenAPI spec, fetched at the date recorded in the mapping's `fetched` field. Re-fetch and re-review periodically - the mapping doesn't auto-update. |
| `../../scripts/api_coverage_report.py` | `validate` (every requirement mapped once, every evidence reference resolves in the spec) and `report` (per-section coverage table + score). |

## Usage

```bash
uv run python scripts/api_coverage_report.py validate --provider lambda
uv run python scripts/api_coverage_report.py report --provider lambda
```

## Adding a provider

1. Fetch and commit the OpenAPI spec to `specs/<provider>-openapi.json`.
2. Read `../offtake-requirements.yaml` requirement by requirement against the
   spec's paths and `components.schemas`, and write `<provider>.yaml` with one
   entry per `req_id`. Use `not_applicable` for anything that isn't a
   discoverable API-shape question at all (compliance attestations, physical
   DC/network properties, performance SLAs) rather than `absent`, which
   should mean "the capability could exist in this API's shape but doesn't."
3. `validate` will fail loudly if a requirement is missing or an evidence
   reference is stale/wrong - fix until it's clean.
