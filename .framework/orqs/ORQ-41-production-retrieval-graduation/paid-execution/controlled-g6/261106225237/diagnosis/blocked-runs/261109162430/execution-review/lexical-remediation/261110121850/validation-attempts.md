# Local validation attempts

All attempts use the existing pinned application image and an isolated,
disposable real PostgreSQL instance. The host adapter is unchanged. No API or
provider operation is executed.

1. `reference-error-fixture.xml`: launcher failure before any database query.
   The application image did not contain the repository pytest configuration;
   the async fixture ran in strict mode. Mounting the existing `pytest.ini`
   read-only fixed the launcher without changing global configuration.
2. `reference-error-fixture-corrected.xml`: the proposed 8,192-lexeme input did
   not produce a computational error. It was rejected as insufficient coverage.
3. `error-fixture-probe.json`: bounded direct local probes at 16,384, 32,768,
   65,536 and 131,072 lexemes. The last input returns SQLSTATE `54000`.
4. `reference-computational-error.xml`: the frozen original retrieval SQL
   returns the expected real computational error for the corrected input.
5. `candidate-1-error-parity.xml`: 31 pass, one failure. With both an invalid
   vector dimension and the oversized lexical query, a visible tenant and
   `force_generic_plan`, the original returns `22000` and candidate 1 returns
   `54000`. Candidate 1 is rejected; this is not an accepted contract change.
6. `reference-plan-guard-red.xml`: expected failure against the original query.
   The actual generic plan still contains `plainto_tsquery` outside a dedicated
   materialized lexical producer. The guard detects the mechanism being fixed.

Error equality compares SQLSTATE, driver exception type and the SHA-256 of the
complete original server error message. Hashing avoids placing a multi-megabyte
query in failed test output; it does not weaken exact message comparison.

No failed validation is erased or classified as a successful remediation.
