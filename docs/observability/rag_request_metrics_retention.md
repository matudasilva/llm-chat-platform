# `rag_request_metrics` retention statement (ORQ-37 §Diseño 6)

**This is an operational procedure, not automated code.** No scheduler, cron
entry, lease, watchdog, or background worker exists anywhere in this codebase
for retention (operator directive, R19). The statement below is run
explicitly by the contract's owner, exactly as a database migration is
(invariant 5).

## The statement

Run as the `chat_ops_retention` credential — the **only** credential with
`DELETE` on this table. `chat_ops` (the runtime role) holds `INSERT` only and
cannot execute this.

```sql
DELETE FROM rag_request_metrics
WHERE created_at < now() - make_interval(days => :retention_days);
```

`:retention_days` is `rag_request_metrics_retention_days` (default `30`),
read from the running deployment's configuration at the time of the run — not
hardcoded, so a changed setting does not silently diverge from what actually
gets deleted.

**Deletes exactly the rows older than the configured window and nothing
else**: the predicate is a single column comparison, no join, no `LIMIT`, no
implicit ordering dependency.

## The operational retention contract (§Diseño 6's six required terms)

| Term | Value |
|---|---|
| **Window** | `rag_request_metrics_retention_days`, default **30 days** |
| **Owner** | **Platform Operations** — a named organizational role, not "the team". Assigned by operator decision on 2026-09-12, which is what ADR-012 requires before production enablement; the assignment is the operator's to make, not this ORQ's. Gate B2 production readiness requires this field to hold a real name before enablement (§Diseño 6). |
| **Procedure** | The statement above, run explicitly, exactly like a migration |
| **Maximum cadence** | At least once every **7 days** |
| **Maximum tolerated delay** | **37 days** (the window plus one cadence period) — an **operator-auditable breach threshold**, not application-enforced. Nothing in the running system observes a breach; ORQ-37 introduces no detection mechanism, by operator directive |
| **Evidence of execution** | Each run appends one entry to the retention log below: timestamp, operator, rows deleted, oldest surviving `created_at` |

## Retention log

| Run timestamp (UTC) | Operator | Rows deleted | Oldest surviving `created_at` |
|---|---|---|---|
| 2026-09-12 13:34 | Platform Operations | 2 | 2026-09-10T13:34:48.874620+00:00 |

> **What that first entry exercised, stated plainly.** It is a real run: the
> published statement above, executed as `chat_ops_retention` against the dev
> database and **committed**, not rolled back. `rag_request_metrics_enabled`
> has never been on in that environment, so the table was empty; three rows
> aged 45, 31 and 2 days were written first **by `chat_ops`**, the runtime
> role, exercising the same INSERT-only path production uses. The two rows
> past the 30-day window were deleted and the one inside it survived, which
> is the number recorded above.
>
> Those rows were seeded to exercise the procedure. They are not production
> telemetry, and this entry should not be read as evidence that retention has
> run against real traffic.

## What this contract does NOT do

It gates **enablement**, not **continuation**. Once `rag_request_metrics_enabled`
is turned on in production, rows accumulate past the retention window
indefinitely if the owner above misses a run — every acceptance criterion in
ORQ-37 stays green regardless (R19, disclosed in ADR-012). `rag_request_metrics_enabled`
remains `false` by default, so this accumulation cannot begin without a
deliberate operator action.

## Status

`rag_request_metrics_enabled` is `false`. This statement has never been run in
production. Per §Diseño 6, enabling the flag in production **requires** this
document to carry an assigned owner and at least one logged execution first —
until then, production privacy readiness fails and the flag stays `false`.
