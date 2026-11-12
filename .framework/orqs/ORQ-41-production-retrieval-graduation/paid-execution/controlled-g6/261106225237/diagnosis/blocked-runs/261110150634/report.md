# Prepared lexical-image A/A packet

**PREPARED_AWAITING_INDEPENDENT_PACKET_REVIEW**. Source implementation and
independent source review passed; this report is a pre-review snapshot.

The new approved image775d925 is fixed in both full-C1 labels. The old contract,
image/default pins and historical FAILs remain unchanged. The only technical
changes are the approved strict binding in blocked_latency.py and its tests.
Source review2e8b7ca7 preceded all environment preparation.219P2 regressions pass;
the copied controls.xml is not a rerun. Worker/timing/aggregation are unchanged.

Fresh isolated services and two paired PostgreSQL databases are prepared.
Each contains720conversations,17,280exact histories and P3(124docs/2146chunks).
Source schema/locale/roles/P3/RLS, exact histories/UUIDs/tenant/sequence, paired
config/seed41/resources, original seven-table ANALYZE and plannerauto are proven.
Source environment before/after identity is unchanged. Collector/Redis are
loopback-only in the network-none PG namespace, with no publishedports or
external credentials; no API lifespan, provider request or benchmark ran.

The byte-identical prior independent prepared verifier passed via parent-run
READONLY SQL/config probes. It verifies the11CHECKtruthcases and source/restore
equivalence as well as all prepared state. This is parent infrastructure
execution, not an independent reviewer database attestation. The exact-packet
review is still required; its result must be read separately from this snapshot.

Future volume remains1440localrequests(800measured+640warmups),32serialworkers,
fourcells/fourblocks, R1/oneattempt, pooledp95/symmetric5%,request300s/cleanup10s.
Current executed calibration/warmup requests0; no execution authorization/start
or result exists. No G6 PASS, causal latency claim or paid readiness is inferred.
USD0; original failures, P5 and campaign cap/accounting remain untouched.

Only local evidence, approved two-file harness/test change and minimal planning
references are modified. No app/newimage/schema/grant/globalenv/model/threshold/
provider/retry/SSE/persistence/G9/Notion/commit/deploy change in this step.
