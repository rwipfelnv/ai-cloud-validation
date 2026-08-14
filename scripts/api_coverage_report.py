#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Static API-shape coverage: offtake requirements vs. a provider's OpenAPI spec.

Answers "does this provider's public API even expose a surface that could satisfy
our requirements" without a live account or a test run - a much cheaper first pass
than the pytest validation suite, useful for API-first providers (e.g. Lambda
Cloud) that have no Terraform provider to test against.

Inputs, both offline/committed:

* ``docs/requirements/offtake-requirements.yaml`` - the requirement catalog
  (same source ``reqtrace.py`` uses).
* ``docs/requirements/api-coverage/<provider>.yaml`` - a curated, per-requirement
  ``status`` (present/partial/absent/not_applicable) with ``evidence`` pointing
  into a vendored copy of the provider's OpenAPI spec
  (``docs/requirements/api-coverage/specs/<provider>-openapi.json`` or similar,
  named by the mapping's own ``spec`` field).

The curated judgment call (does this endpoint really satisfy this requirement) is
made by a human/AI reading the spec - this script does not attempt semantic
matching. What it *does* check mechanically:

* every requirement has exactly one mapping entry (no silent gaps in the analysis
  itself, no duplicates);
* every mapping's evidence resolves to a real path+method or schema (name or
  ``schema:Name.field``) in the vendored spec - catches stale/hallucinated claims
  as the provider's API evolves.

Usage:
    python3 scripts/api_coverage_report.py validate --provider lambda
    python3 scripts/api_coverage_report.py report --provider lambda
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
REQ_DIR = REPO_ROOT / "docs" / "requirements"
OFFTAKE_DOC = REQ_DIR / "offtake-requirements.yaml"
COVERAGE_DIR = REQ_DIR / "api-coverage"

STATUSES = {"present", "partial", "absent", "not_applicable"}


def _load_yaml(path: Path) -> Any:
    """Parse a YAML file."""
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _load_json(path: Path) -> Any:
    """Parse a JSON file."""
    import json  # stdlib, only needed here

    return json.loads(path.read_text(encoding="utf-8"))


def load_offtake_requirements() -> dict[str, dict[str, Any]]:
    """Return offtake requirements keyed by ``req_id``."""
    doc = _load_yaml(OFFTAKE_DOC)
    return {r["req_id"]: r for r in doc["requirements"]}


def load_coverage(provider: str) -> dict[str, Any]:
    """Load the curated coverage mapping for ``provider``."""
    path = COVERAGE_DIR / f"{provider}.yaml"
    if not path.exists():
        raise SystemExit(f"no coverage mapping for provider '{provider}' (expected {path})")
    return _load_yaml(path)


def load_spec(coverage: dict[str, Any], provider: str) -> dict[str, Any]:
    """Load the vendored OpenAPI spec referenced by a coverage mapping."""
    spec_path = COVERAGE_DIR / coverage["spec"]
    if not spec_path.exists():
        raise SystemExit(f"spec file for provider '{provider}' not found: {spec_path}")
    return _load_json(spec_path)


def _resolve_evidence(ref: str, spec: dict[str, Any]) -> str | None:
    """Return an error message if ``ref`` doesn't resolve against ``spec``, else None."""
    if ref.startswith("schema:"):
        name = ref[len("schema:") :].split(".", 1)[0]
        if name not in spec.get("components", {}).get("schemas", {}):
            return f"schema '{name}' not found in spec"
        return None

    parts = ref.split(" ", 1)
    if len(parts) != 2:
        return f"evidence '{ref}' is neither 'METHOD /path' nor 'schema:Name'"
    method, path = parts
    path_item = spec.get("paths", {}).get(path)
    if path_item is None:
        return f"path '{path}' not found in spec"
    if method.lower() not in path_item:
        return f"method '{method}' not found on path '{path}' in spec"
    return None


def validate(provider: str) -> int:
    """Cross-check a provider's coverage mapping against requirements and its spec."""
    reqs = load_offtake_requirements()
    coverage = load_coverage(provider)
    spec = load_spec(coverage, provider)
    mappings = coverage["mappings"]

    errors: list[str] = []
    seen: set[str] = set()
    for m in mappings:
        req_id = m["req_id"]
        if req_id in seen:
            errors.append(f"{req_id}: duplicate mapping entry")
        seen.add(req_id)
        if req_id not in reqs:
            errors.append(f"{req_id}: not a known offtake req_id")
        if m["status"] not in STATUSES:
            errors.append(f"{req_id}: unknown status '{m['status']}' (expected one of {sorted(STATUSES)})")
        for ref in m.get("evidence", []):
            err = _resolve_evidence(ref, spec)
            if err:
                errors.append(f"{req_id}: evidence '{ref}' invalid ({err})")

    missing = sorted(set(reqs) - seen)
    for req_id in missing:
        errors.append(f"{req_id}: no coverage mapping entry (analysis gap, not an API gap)")

    if errors:
        print(f"validate FAILED for provider '{provider}': {len(errors)} issue(s)")
        for e in errors:
            print(f"  - {e}")
        return 1

    print(f"validate OK for provider '{provider}': {len(mappings)} requirements mapped, all evidence resolved.")
    return 0


def report(provider: str) -> int:
    """Print a per-section coverage report grouped by offtake section."""
    reqs = load_offtake_requirements()
    coverage = load_coverage(provider)
    mappings = {m["req_id"]: m for m in coverage["mappings"]}

    print(f"# API-shape coverage: {coverage.get('spec_title', provider)} vs. offtake requirements v2.3.1")
    print(f"# spec: {coverage.get('spec_source', '?')} (fetched {coverage.get('fetched', '?')})")
    for caveat in coverage.get("caveats", []):
        print(f"# CAVEAT: {caveat}")
    print()

    totals = dict.fromkeys(STATUSES, 0)
    sections: dict[str, list[str]] = {}
    for req_id, req in reqs.items():
        sections.setdefault(req["section"], []).append(req_id)

    for section in sections:
        print(f"## {section}")
        for req_id in sections[section]:
            m = mappings.get(req_id)
            status = m["status"] if m else "unmapped"
            totals[status] = totals.get(status, 0) + 1
            area = reqs[req_id]["area"] or reqs[req_id]["subsection"]
            print(f"  {req_id:<10} {status:<15} {area}")
        print()

    print("## Summary")
    for status in ("present", "partial", "absent", "not_applicable"):
        print(f"  {status:<15} {totals.get(status, 0)}")
    if totals.get("unmapped"):
        print(f"  {'unmapped':<15} {totals['unmapped']}")

    checkable = totals["present"] + totals["partial"] + totals["absent"]
    if checkable:
        score = (totals["present"] + 0.5 * totals["partial"]) / checkable
        print(
            f"\n  API-shape coverage score (excludes not_applicable/unmapped): {score:.0%} of {checkable} checkable requirements"
        )
    return 0


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    for name, help_text in (
        ("validate", "cross-check a provider's coverage mapping against requirements and its spec"),
        ("report", "print a per-section coverage report"),
    ):
        p = sub.add_parser(name, help=help_text)
        p.add_argument(
            "--provider",
            required=True,
            help="provider name, e.g. 'lambda' (docs/requirements/api-coverage/<provider>.yaml)",
        )
    args = parser.parse_args()

    if args.command == "validate":
        sys.exit(validate(args.provider))
    if args.command == "report":
        sys.exit(report(args.provider))


if __name__ == "__main__":
    main()
