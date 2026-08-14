# ORQ-29 Gate 1 development calibration report

**Status:** DEVELOPMENT_ONLY — no held-out generated or accessed

- Run ID: `8cb8b2c1-eb64-43e6-a1b7-d38faeef404e`
- Manifest SHA-256: `31c3d6cc8ffeda2152e97627216e804448a6baea701c0a6090a8b311feaf7791`
- Development dataset SHA-256: `318a52c342ca714220155f1a77a29f3c9dc7c90796bb0431fa8a43e76ed2089d`
- Origin commit verified: `e640cd3c7cf5c7668d0b017000e28a606c35cf0f`
- Selected retrieval profile: `profile-02`
- Selected S*: `E-EVT`
- Selected E*: `E-EVT`
- Selected semantic confidence: `0.6`
- Selected fallback policy: `deictic_or_no_result`

## Development quality

| Arm | Recall | Consistency | Input tokens | p95 TTFT ms | Estimated API cost |
|---|---:|---:|---:|---:|---:|
| A | 0.0000 | 0.0000 | 3506 | 1024.13 | 0.00071010 |
| B | 1.0000 | 1.0000 | 15658 | 916.68 | 0.00268890 |
| C | 0.0000 | 0.0000 | 5339 | 905.95 | 0.00103485 |
| D-EVT | 0.3750 | 0.3750 | 7374 | 1212.48 | 0.00158940 |
| E-EVT | 1.0000 | 1.0000 | 23091 | 1432.22 | 0.00380745 |
| F-MSG | 0.8750 | 0.8750 | 20624 | 1076.30 | 0.00363326 |
| F-EVT | 1.0000 | 1.0000 | 23095 | 1051.36 | 0.00400215 |
| G-SEM | 1.0000 | 1.0000 | 36823 | 1613.91 | 0.01612215 |
| G-ADAPT | 1.0000 | 1.0000 | 36823 | 1280.42 | 0.01611795 |
| G-FALLBACK | 1.0000 | 1.0000 | 30993 | 912.23 | 0.01524105 |
| R | 0.7083 | 0.7083 | 13702 | 1191.74 | 0.00252366 |

## External call ledger

- Generation calls: `528 / 528`
- Semantic extraction calls: `144 / 144`
- Grouped embedding calls: `4 / 120`
- Total external calls: `676 / 792`

## Boundary

This is unblinded development calibration, not a final pre-registration and not a Gate 1 hypothesis verdict. The new held-out seed, path, hash, and bundle remain null. No Gate 2, Gate 3, or production work is authorized.
