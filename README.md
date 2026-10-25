Khurinji Malar M S  
malar.khurinji.btech2023@sitpune.edu.in  
Video: https://youtu.be/your-video-link-here  
Run: python3 checker.py assignment_data

---

# Aeron Weather Data Quality Checker

This repository contains the code and outputs for the Aeron AI Research Engineer Intern assignment.

## Repository Structure

```
├── checker.py              # Main data quality checker
├── flags.csv               # Data quality flags for the supplied pack
├── flags_baseline.csv      # Baseline flags before manual corrections
├── find_flatlines.py       # Helper script to locate flatline timestamps
├── test_checker.py         # Unit tests for the checker
├── DECISIONS.md            # Written answers to assignment questions
├── report.html             # One-page network health report
├── assignment_data/        # Supplied data pack (not committed, gitignored)
├── ai_logs/                # AI conversation logs
│   ├── chatgptchat.url     # ChatGPT conversation link
│   └── claudechat.json     # This conversation log
└── README.md               # This file
```

## What the Checker Does

The checker (`checker.py`) reads a data pack directory and produces `flags.csv` with these columns:
- `station_id` — e.g., `S03`
- `channel` — data column name (`temp_c`, `rh_pct`, etc.), or `all`, or `metadata`
- `start_utc`, `end_utc` — affected time range (`YYYY-MM-DD HH:MM`)
- `issue` — brief description
- `action` — `exclude`, `correct`, or `keep` (keep = looks odd but is real)
- `note` — one sentence of evidence; if `correct`, states the correction

### Checks Implemented

1. **Timestamp integrity** — duplicates, out-of-order, gaps, missing at start/end of expected window (2025-03-01 00:00 to 2025-04-11 23:50, 10-min cadence)
2. **Sensor value bounds** — physically implausible readings (e.g., temp_c outside [-50, 60]°C, RH > 110%)
3. **Supersaturation detection** — RH > 100% runs (flagged as `correct` since sensor is uncalibrated)
4. **Prolonged flatlines** — same value for 6+ intervals (1+ hour), or 12+ for wind direction; flagged as `keep` if ≤2 hours, `exclude` if >2 hours
5. **Pressure level shifts** — sustained offsets after documented sensor swaps
6. **Anemometer changes** — wind speed/distribution shifts after replacement
7. **GPS vs metadata** — coordinate discrepancies >1 km
8. **Cross-station comparison** — level shifts assessed against nearby stations at similar elevation

### What Was Not Implemented

- Rate-of-change spike detection (e.g., pressure jumps >10 hPa in 10 min)
- Cross-channel physical consistency checks (e.g., dew point vs RH)
- Nighttime zero GHI / dry-period zero rain filtering (kept as `keep` flatlines)
- Automated correction of pressure offsets (requires calibration reference)
- Structured maintenance log parsing (currently keyword-based)

## How to Run

```bash
python3 checker.py assignment_data
```

This writes `flags.csv` to the current working directory.

## Test Suite

```bash
python3 test_checker.py
```

Tests cover: timestamp checks (duplicates, gaps, out-of-order), sensor bounds, supersaturation, flatlines, GPS discrepancies, and read-only verification.
