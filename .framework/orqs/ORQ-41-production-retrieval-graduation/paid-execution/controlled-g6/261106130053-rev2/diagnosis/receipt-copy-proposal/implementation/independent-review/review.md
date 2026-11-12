# C1 receipt-copy implementation independent review

**C1_RECEIPT_COPY_IMPLEMENTATION_INDEPENDENT_REVIEW_PASS**.
No BLOCKER/HIGH/MEDIUM finding was identified in the exact approved scope.

The current source matches the approved revision2 helper plus its three window
copy callsites. Independently removed that helper and restored those exact three
deepcopy expressions in memory; SHA256 matches the frozen original source
`7d66fcbda6e6640033508f4bf0415b13ab91b1158fcae35c3b279da1d21e7c47`.
This proves no other source body, including generic Evidence.snapshot deepcopy,
hashing/counting/caps/locking or best-effort boundary, changed in this increment.

The fast path requires an exact list of distinct exact dictionaries with exact
string keys and exact immutable str/int/bool/None values. It copies the list and
every dictionary; sharing immutable scalar objects is equivalent to deepcopy.
Equal-but-distinct rows remain distinct. Repeated row identities, nested/shared
mutable graphs, cycles, subclasses and unexpected types retain deepcopy and its
alias-preservation/custom-copy/error behavior. Supported runtime builders and
record insertion still execute within the existing per-state RLock. No broader
claim is made for arbitrary external unsynchronized mutation of internal state.

Executed54 tests independently under P2:49 focused existing controls and five
new adversarial probes. All passed. The probes check exact approved source
delta, equal distinct row isolation, shared nested graph alias preservation,
custom deepcopy on a scalar subclass, and original exception identity on a
fallback-copy failure. Existing controls exercise byte/item limits, full ordered
hash chains, truncation, aborted requests, builder/copy failures, retained-record
and snapshot mutation isolation. Their functional results, state validity/closed
flags and hashes match the deepcopy control.

Command: `unshare -rn env -i` with PATH/HOME, nonexistent AWS config/credentials,
metadata disabled, APP_SETTINGS_ENV_FILE empty, PYTHONDONTWRITEBYTECODE=1 and
PYTHONPATH containing the P2 guard and repository; then `.venv/bin/python -m
pytest -q -p no:cacheprovider tests/experiments/test_orq41_c1_receipt_copy.py
tests/experiments/test_orq41_c1_evidence.py <this-directory>/test_adversarial_copy.py
--junitxml=<this-directory>/review.xml`. Result54 passed in0.10s, exit0. The sole
warning concerns cache_dir after disabling pytest's cache plugin. This review
invocation did not configure a separate socket audit log; kernel isolation and
the guard were active, and the reviewed tests execute no external operations.

Only reviewer probes/report/receipt were added. No runtime fix was authored by
the reviewer, nor API/DB/provider operation, new image, G6 rerun or paid campaign
executed. Author's230 broader regression passes are supporting author evidence,
not independently rerun here. Performance remains the prior offline reconstructed
workload result; this review establishes no deployment/G6 speedup, causal timing
share or satisfaction of+5%. CONTROLLED_G6_FAIL and paid-admission block remain.
