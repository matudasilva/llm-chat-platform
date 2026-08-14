# ADR-010: Close ORQ-27 and Evaluate ORQ-29 as a Gated Successor

**Date:** 2026-08-13
**Status:** Accepted
**ORQ reference:** ORQ-27 and ORQ-29
**Superseded by / Supersedes:** —

---

## Context

ORQ-27 executed one valid, pre-registered offline held-out evaluation of its
selected D1 episodic-memory strategy. The run completed correctly and returned
`NO_GO`: 16 of 20 conjunctive clauses passed, while registered recall
preservation, fact-consistency preservation, ambiguous-follow-up recall, and
p95 time-to-first-token criteria failed.

The result is evidence against D1 under that protocol. It is not evidence
against every episodic-memory design or against structured semantic memory.
ORQ-27 changed no production chat runtime and its consumed held-out is sealed.

ORQ-29 proposes a new hypothesis rather than a retry: conversation-event
episodic memory, exact dense and BM25 retrieval with deterministic fusion,
structured semantic memory, contextual querying, adaptive injection, and
bounded-history replay as an explicit low-confidence fallback.

## Decision

1. ORQ-27 is `CLOSED / VALIDATED — Gate 1 NO_GO — hypothesis not supported`.
   It must not reopen, and its held-out must not be rerun, inspected for
   successor selection, or reused as hidden evidence.
2. ORQ-29 is the independently reserved successor. It owns a new hypothesis,
   new synthetic dataset, new held-out, new pre-registration, and new verdict.
3. Delivery is split into three independent gates:
   - **Gate 1:** offline experiment only. It may STOP without changing
     production. A protocol charter is required before development.
   - **Gate 2:** default-off runtime integration only after a valid Gate 1 GO
     and explicit operator approval.
   - **Gate 3:** operational productization only after Gate 2 demonstrates
     operational value and receives a separate design and approval.
4. A GO at one gate never authorizes the next gate. This ADR does not authorize
   memory implementation, `/chat` changes, migrations, or held-out execution.

## ORQ-29 outcome update — 2026-08-14

ORQ-29 completed only its separately authorized development calibration and is
closed locally as `DEVELOPMENT INCONCLUSIVE — TARGET LONG-CONTEXT REGIME NOT
EXERCISED`. B truncated in `0/48` evaluation steps, retained all required gold
evidence in `48/48`, and reached only `13.34%` maximum usable-capacity pressure.
The development evidence therefore cannot decide the registered long-context
hypothesis.

No final pre-registration was created; no held-out was generated, accessed, or
executed; and no Gate 1 `GO/NO_GO` verdict exists. Gate 2 and Gate 3 remain
unauthorized. Results are frozen against post-hoc recalibration or
reinterpretation. A successor requires a separately reserved ORQ, different
approved hypothesis and protocol, and completely new held-out.

## Consequences

### Positive

- A valid negative result remains first-class portfolio evidence.
- ORQ-29 cannot tune against or relabel ORQ-27's consumed held-out.
- Scientific, runtime, and operational risks are approved independently.
- Existing provider, persistence, streaming, documentary RAG, and cache
  invariants remain untouched until evidence supports integration.

### Negative / Trade-offs

- ORQ-29 required a new dataset and incurred a new experimental cost.
- Governance and protocol-charter work preceded development.
- The broader dual-memory hypothesis required more ablations than ORQ-27.

## Alternatives Considered

### Reopen ORQ-27 and tune D1

Rejected. The held-out is consumed and the terminal NO_GO is part of the
scientific record.

### Implement ORQ-27 Gate 2 despite NO_GO

Rejected. It would introduce production complexity without the required
quality–cost evidence.

### Treat NO_GO as rejection of all conversational memory

Rejected. The experiment tested one strategy and did not evaluate the
successor's hybrid episodic, semantic, adaptive, or fallback components.

## Evidence

- ORQ-27 technical range on `main`: `95ce39a` through `e640cd3`.
- Formal closure:
  `.framework/orqs/ORQ-27-conversational-memory-rag/closure.md`.
- Frozen registration SHA-256:
  `1a28938563d21413fd80b2e33b2ff43ad019f396ff15a82fc7004a19fba85edd`.
- Consumed held-out SHA-256:
  `ea6bbcc631451758f18640073a5cc04aabafa9ef5ea8ffb5269150a7fa55a64f`.
- Raw run SHA-256:
  `17aeb473088b33ea215cdd8e02c67a31cfe298f8b5e8ca05bb22c49c27b7234a`.
- ORQ-29 plan:
  `.framework/orqs/ORQ-29-dual-conversational-memory/spec.md`.
