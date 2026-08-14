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

"""Tests for api_coverage_report.py.

Acts as the CI drift guard: the committed Lambda coverage mapping must stay
consistent with both the offtake requirements catalog and the vendored spec.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

_SCRIPT = Path(__file__).resolve().parent.parent / "api_coverage_report.py"
_spec = importlib.util.spec_from_file_location("api_coverage_report", _SCRIPT)
assert _spec and _spec.loader
api_coverage_report = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(api_coverage_report)


def test_committed_lambda_mapping_is_consistent() -> None:
    """`validate --provider lambda` must pass against the committed files (no drift)."""
    assert api_coverage_report.validate("lambda") == 0


def test_lambda_mapping_covers_every_offtake_requirement() -> None:
    """Every offtake req_id must have exactly one Lambda coverage entry (no silent gaps)."""
    reqs = api_coverage_report.load_offtake_requirements()
    coverage = api_coverage_report.load_coverage("lambda")
    mapped = [m["req_id"] for m in coverage["mappings"]]
    assert set(mapped) == set(reqs)
    assert len(mapped) == len(set(mapped))


def test_unknown_provider_raises() -> None:
    """A provider with no mapping file is a clear error, not a silent empty report."""
    import pytest

    with pytest.raises(SystemExit):
        api_coverage_report.load_coverage("does-not-exist")


def test_resolve_evidence_rejects_bad_path() -> None:
    """A path/method that doesn't exist in the spec must fail resolution."""
    fake_spec = {"paths": {"/api/v1/instances": {"get": {}}}, "components": {"schemas": {}}}
    assert api_coverage_report._resolve_evidence("GET /api/v1/instances", fake_spec) is None
    assert api_coverage_report._resolve_evidence("POST /api/v1/instances", fake_spec) is not None
    assert api_coverage_report._resolve_evidence("GET /api/v1/nope", fake_spec) is not None
    assert api_coverage_report._resolve_evidence("schema:Instance", fake_spec) is not None
