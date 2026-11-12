# Initial measurement amendment findings (historical)

Two pure in-memory counterexamples in test_reviewer_probes.py demonstrated that the initial required measurement pin did not enforce observer presence or manifest identity outside CLI: the serial runner completed with no timing receipt, or with a successful receipt naming a different manifest. Initial result:75 PASS and one existing CLI terminal-output regression failure,76 tests total; both counterexample tests passed by demonstrating the defects. Replay168 remained USD4.15355688.

These were reported to the author, who applied binding/CLI fixes within the approved scope while review continued. Original probes/XML are preserved as evidence against the initial code and must not be presented as regressions passing against the fixed code. Round2 review checks the remediation separately. The reviewer implemented no source fix.
