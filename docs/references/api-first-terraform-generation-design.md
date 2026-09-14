# Generating a "standard" Terraform integration for API-first NCPs — design sketch

Status: draft, not yet committed/reviewed. Companion to the Lambda API-shape
analysis in `docs/requirements/api-coverage/`.

## Problem

Some NCPs (Lambda, Together AI, Mistral) don't ship a Terraform provider and
have said they don't want to build one. NVIDIA leadership (Bob) doesn't want
to force TF on providers where it's unnatural, but still needs the equivalent
capability: declarative, dependency-ordered, create/destroy-able infrastructure,
invokable the same way as our existing CSP integrations. Question: can *we*
generate that Terraform integration on the NCP's behalf, from their public API,
well enough to plug into the same pattern NKX already uses for AWS/Azure/GCP/OCI?

## What "the standard" is

Reverse-engineered from `terraform-at-nvidia` (gitlab-master), not a written
spec. Every mature CSP integration is four separately-versioned modules,
composed by a per-account "blueprint":

| Layer | Responsibility | Example |
| ----- | --------------- | ------- |
| `iam` | roles / service accounts / policies | `terraform-aws-iam` |
| `vpc` / network | network, subnets, security groups | `terraform-aws-vpc` |
| cluster | managed K8s control plane | `terraform-aws-eks`, `terraform-oci-oke` |
| `compute` | node pools / instances | `terraform-aws-compute` |

A blueprint (`project-templates/terraform-<csp>-<k8s>` →
`dgxcloud/platform/infra/blueprints/*`) wires these four together per
account/environment; NKX actuates the blueprint. `project-templates/terraform-module`
only defines project hygiene (CI, testing, terraform-docs, semver) - not the
resource shape.

**Precedent this already works for API-first NCPs:**

- **Mistral**: `terraform-mistral-compute` / `terraform-mistral-iam` call a
  custom Terraform provider NVIDIA privately published
  (`sw-dgxcloud-terraform-provider/mistralai/mistral-compute`), against a
  hand-maintained API reference (`terraform-provider-v1.md`).
- **Together AI**: `terraform-provider-together` is a hand-written
  `terraform-plugin-framework` provider. Its README documents the actual
  bootstrap path: start with HashiCorp's generic `restapi` provider
  (schema-less REST-to-TF bridge, zero custom code) for early operation,
  then replace it with a native provider once the shape stabilizes.

Local reference copies (generic module/provider code only, no
account-specific `deployments/`): `~/git/terraform-at-nvidia/` (not
committed to this repo - internal GitLab source, kept out of the public repo
deliberately).

## Proposed three-phase approach

### Phase 1 - static feasibility (done, for Lambda)

`docs/requirements/api-coverage/<provider>.yaml` + `scripts/api_coverage_report.py`:
per offtake requirement, does the provider's OpenAPI spec even expose a
plausible surface. No live account, no code generation. Answers "is this
worth attempting at all" cheaply, before investing in provider code.

**Gap this phase has today:** it scores per *requirement*, not per *module
layer*. To decide "build a `compute` module for provider X," we need to know
whether the `absent` requirements cluster entirely inside one layer (e.g. all
of `cluster` is absent but `vpc`/`compute`/`iam` are present/partial) or are
scattered - only the former is a clean go/no-go per layer.

### Phase 2 - module-layer rollup (proposed, not started)

Add a mapping from each offtake `req_id` to one of `{iam, network, cluster,
compute, other}` (many requirements, e.g. `CNP08` stable identifiers, apply
to more than one layer - allow multi-tag). Roll up the existing
`present`/`partial`/`absent` scores per layer to a per-layer verdict. Output:
for a given provider, which of the four standard layers are buildable today.

This is additive to the existing `lambda.yaml` - no rework of Phase 1 data,
just a new grouping key and a rollup report mode in `api_coverage_report.py`.

### Phase 3 - prototype (conditional on Phase 2 saying "go" for >=1 layer)

For each layer scored buildable, produce a real Terraform module matching the
standard's boundary (same variable/output *shape* as the peer
`terraform-<csp>-compute`/`vpc` modules, not necessarily identical field
names). Two implementation strategies, both with working precedent above:

1. **Bridge** - generic `restapi` provider wrapping the raw REST calls.
   Fastest, ~zero custom Go code, good for validating the module boundary
   and unblocking a blueprint end-to-end before investing further.
2. **Native** - hand/AI-written `terraform-plugin-framework` provider (the
   Together AI pattern), optionally bootstrapped from HashiCorp's
   `terraform-plugin-codegen-openapi` (schema+CRUD scaffold from an OpenAPI
   3.x spec) - unused in this org so far, worth prototyping given Lambda's
   spec is clean OpenAPI 3.

Layers Phase 2 scores `absent` are explicitly out of scope for Phase 3 - no
attempt to fabricate capability the provider's API doesn't expose (e.g.
Lambda's `cluster` layer: no K8s API surface at all, confirmed both by the
requirements analysis and by Lambda's own docs stating Managed Kubernetes is
console-provisioned only).

## Non-goals

- Not attempting full TF feature parity (drift detection, import, complex
  dependency graphs) in a first prototype - just enough CRUD to prove the
  module-boundary fit.
- Not modifying `isvctl`/`isvtest` in this phase - this is infrastructure
  tooling to *produce* a Terraform integration, separate from the validation
  suite that would eventually test one.
- Not publishing vendored internal `terraform-at-nvidia` deployment code
  (account IDs, resource groups, etc.) into this public repo.

## Open questions

- Where does generated/prototyped provider code live - this repo, a new
  `terraform-at-nvidia/terraform-provider-<ncp>` repo, or somewhere else?
- Who owns the module-layer taxonomy going forward as offtake requirements
  change - same reconciliation process as `docs/requirements/README.md`?
- Should Phase 2's rollup become part of `validate`'s CI guardrail, or stay
  report-only until more providers exist?

## Context

Written by Claude with the context of prior work on
`docs/requirements/api-coverage/` (this repo, branch
`feat/api-coverage-analysis`) plus access to all of the Terraform code under
`https://gitlab-master.nvidia.com/terraform-at-nvidia` plus this starting
point prompt for some back/forth discussion:

> I am told that all of those repos represent the "shape" of terraform
> integration for each NCP/neocloud. We need to somehow use what's there
> (maybe in templates) to determine what that "standard terraform"
> integration looks like, then we need to see if it's theoretically possible
> to generate terraform from any NCP/neocloud per that standard, given the
> APIs they have instead of terraform. Our goal is to see if we can develop
> what we consider to be the ideal Terraform integration on behalf of
> NCP/neoclouds that are API first and don't have their own terraform. Our
> requirement is to be able to invoke Terraform per the pattern of our
> existing integrations.
