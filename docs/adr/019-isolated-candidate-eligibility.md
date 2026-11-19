# ADR-019: Isolated Candidate Eligibility Against Trusted Records

**Date:** 2026-11-18

**Status:** Accepted - isolated preparation only

**ORQ reference:** ORQ-42, AC12 and AC15
**Supersedes / Amends:** Complements ADR-014 and ADR-015

## Context

The Vertex adapter has independent settings and hermetic contract tests, while
runtime Vertex selection remains disabled. Syntax validation alone cannot show
that a candidate supports a project, location, transport or output limit.
The dormant deterministic policy consumes assessments but does not calculate
model capacity. Real candidate identities, certificates and quality evidence
have not been approved.

## Decision

Add an isolated fail-closed eligibility matcher over immutable snapshots of
caller-trusted capability records. It matches exact model, project, location
and transport and checks positive configured and requested output values
against the supplied bound. Malformed or duplicate records invalidate the
snapshot. A certification identifier is a binding label, not proof of issuer
authenticity. No record is loaded from a request or constructed automatically.

Keep the matcher disconnected from provider composition, request handling and
the Vertex adapter. Do not change the ProviderPort contract or activate a
provider. Tests use synthetic records. Test-only arbitrary capacity units also
exercise the dormant rule at a boundary and in a finite fixture where the
alternative cannot occur; they are not model token counts or capacity proof.

## Consequences

- Missing, malformed or mismatched supplied configuration fails closed in the
  isolated matcher; caller trust and provenance remain external obligations.
- The component does not enforce adapter output serialization, authenticate
  issuers, verify real model/location support, IAM, quota, health or quality.
- The synthetic unreachable result applies only to its defined finite fixture;
  real trigger reachability remains unknown. KEEP_STATIC remains operational.

## Alternatives Considered

Inferring support from a model name or syntactic location was rejected: neither
establishes a capability. Selecting a real model or adding a tokenizer solely
to produce a boundary was deferred pending a separate candidate/evidence decision.

## Evidence

The owner joint hermetic regression passed 395 tests with `-W error`; the fresh
native independent review passed 102 focused tests under `-W error`, with reduced
same-provider independence. A fresh validator found the two test findings
addressed in synthetic scope, subject to formal validation. No
live inference or deployment was performed.
