# Read-only CPU observation during administrative preparation

2026-11-10. No benchmark or host mutation. Initial sandbox process view showed
only3processes, so it was not used to attribute host consumption. Parent then
obtained approved read-only host visibility and sampled /proc CPU-tick deltas
over3.009seconds, seeing622processes. Names only, no arguments or environment.

100% below means one logical CPU, not the whole32CPU machine. Highest observed:
code7.6%, code5.0%, gnome-shell3.3%, codex2.0%, additional code1.7/1.3/1.0%,
ChatGPT1.0% and smaller background/kernel workers. This is a short snapshot;
it omits processes that started/exited between reads and is not a historical
causal explanation or proof of exclusive CPU ownership.

Separate Docker stats snapshot: orq41-paid-pg0.00%, orq41-env-otel0.00%,
orq41-env-redis0.25%, orq41-env-pg0.36%. No container stopped or updated.
Initial /proc/stat snapshot reported about1.1% aggregate busy across32CPUs;
the process and aggregate observations are adjacent, not simultaneous datasets.
Low averages do not exclude bursts relevant to15ms latency measurements.
