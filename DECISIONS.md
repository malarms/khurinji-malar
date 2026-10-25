# DECISIONS.md

**Name:** Khurinji Malar M S  
**Email:** malar.khurinji.btech2023@sitpune.edu.in

---

## 01. The Visit

**Station: S07 (Riverbend Farm)**

**What the technician does in one hour:**
1. **First:** Verify the anemometer model and serial number against the spares inventory to confirm which replacement was installed on 2025-03-26.
2. **Second:** Run a 10-minute co-located comparison using a calibrated handheld anemometer at 2 m height alongside the station's mast. Log 1-min averages for wind speed and direction from both instruments.
3. **Third:** Inspect the mounting hardware for alignment, bearing play, and ice/snow clearance. Check the cable connector for water ingress or corrosion.
4. **Fourth:** If the co-located comparison confirms a consistent scaling factor (e.g., new sensor reads 0.58× handheld), record the factor and update the station's calibration metadata. If the factor varies with wind speed/direction, flag for manufacturer consultation.
5. **Fifth:** Swap the wind vane if direction offset exceeds ±10° from handheld reference.

**Why S07 and not the second-best (S02 pressure)?**

| Criterion | S07 (anemometer) | S02 (pressure) |
|-----------|------------------|----------------|
| **Actionable in 1 hour** | Yes — co-located test + mechanical check | Partially — need calibrated barometer, can't correct without reference |
| **Data impact** | Wind speed 4.3× drop (10.9→2.5 km/h) vs 1.4× at nearby stations; direction also shifted | Pressure +8.2 hPa offset; other channels unaffected |
| **Reversible** | Can apply scaling factor post-visit | Cannot correct without calibrated reference |
| **Network priority** | Wind data feeds fire-weather and aviation alerts | Pressure feeds climate summary (less time-sensitive) |

The technician can produce a usable calibration factor for S07 today. For S02, a calibrated reference barometer is needed to correct the +8.2 hPa offset — the volunteer lacks one. S07 is the higher-leverage visit.

---

## 02. Least Certain Call

**The 2-hour "keep" threshold for flatlines**

I set the checker to flag flatlines ≥6 intervals (1 hour) as `keep` and ≥12 intervals (2 hours) as `exclude`. The boundary at exactly 2 hours is the call I'm least sure about.

**Evidence for keeping the 2-hour threshold:**
- Several stations show 6–11 interval flatlines (1–2 hours) that look like natural stability: S04 pressure at 825.9 hPa for 80 min, S04 RH at 47% for 60 min, S07 RH at 82% for 70 min. These values are physically plausible and other channels vary normally.
- Overnight temperature inversions can hold temps steady for 1–2 hours, especially in valleys.
- Pressure can sit steady for hours during stable high-pressure systems.

**Evidence for lowering the threshold (e.g., 90 min):**
- The S03 temp flatline at 6.5°C for 80 hours is an obvious sensor failure, but it started as a 2-hour flatline. Catching it at 2 hours would have saved 78 hours of bad data.
- The S05 RH flatlines at 101–104% (6–20 intervals) were actually supersaturation — the sensor was miscalibrated, not stable. A lower threshold would have caught the pattern earlier.
- The S06 RH flatline at 100% for 140 min post-reboot could be a sensor needing recalibration, not natural stability.

**What would settle it:** A labeled dataset of flatlines from a similar network where someone has manually classified each as "sensor fault" vs "natural stability." Without that, I'm guessing based on physics and a handful of maintenance notes. The 2-hour boundary feels right for now but I'd want to validate it against real fault data before locking it in for 500 stations.

---

## 03. Where the AI Was Wrong

**1. Pressure correction for S02 — AI suggested `correct` with constant offset subtraction**

*AI output:* "Subtract 8.2 hPa from all post-swap readings; offset is constant with std 1.23 hPa."

*Why it was wrong:* The replacement board was **not calibrated** (maintenance log: "Didnt calibrate, didnt have the kit"). Subtracting 8.2 hPa assumes the *old* sensor was correct and the *new* one has a fixed bias. In reality, we don't know which sensor was accurate. The offset could be partly real weather (e.g., a synoptic pressure rise coincident with the swap). Applying a "correction" without a calibrated reference creates false precision.

*How I noticed:* The maintenance log explicitly says "not calibrated." The AI treated the offset as a known bias to remove, but the log says the opposite — the new sensor's accuracy is unknown.

**2. Anemometer replacement — AI initially flagged as `keep` with broad time range**

*AI output:* "wind_speed_drop_after_anemometer_swap (10.9 → 2.5 km/h mean); keep; full post-swap period."

*Why it was wrong:* The 4.3× drop vs 1.4× at nearby stations is strong evidence of a calibration mismatch, not just weather. The `keep` action left unreliable data in the climate summary. The time range also extended to the end of the dataset (2025-04-11), diluting the specificity.

*How I noticed:* Cross-station comparison (S03, S08 at similar elevation) showed only 1.4× drop. The 4.3× vs 1.4× ratio is too large for synoptic weather alone. Narrowed to first week and changed to `exclude`.

---

## 04. Next Year: 500 Stations, Unattended

If I had to run this checker on 500 stations with no human reviewing every flag, here's what I'd change:

**What I'd drop:**
- Per-flag human review — replace with automated severity scoring (critical/major/minor) so the coordinator only sees a daily top-10 work list.
- Individual flatline flags for ≤2 hours — too noisy. Instead, aggregate into a daily "stuck sensor score" per station (how many channels flatlined, for how long). One number per station per day is reviewable.
- Per-station GPS discrepancy flags — too many false positives from multipath. Replace with a fleet-wide median position check: if a station's GPS drifts >1 km from the fleet median, flag it.

**What I'd add:**
- Automated cross-station consistency checks using median absolute deviation. If S02 pressure drifts from the network median by >5 hPa for >24 hours, flag it — no maintenance log needed.
- Time-series change-point detection (CUSUM or Pelt) for level shifts in all channels. Catches sensor swaps even without maintenance logs.
- Per-channel plausibility rules with adaptive thresholds. Example: RH max should be a function of temp_c (warmer air holds more moisture). Fixed 0–110% bounds miss this.

**What I'd refuse to automate:**
- Pressure correction without a calibrated reference — always `exclude`. The S02 case proves you can't assume which sensor was right.
- Attribution of level shifts to specific maintenance events without structured log parsing. Free-text logs are too ambiguous.
- Any `correct` action that requires a physical constant (calibration factor, scaling) not derivable from the data alone. If the data alone can't tell you the factor, the correction is a guess.

The unattended system should output three things daily: a network health scorecard (one page), a prioritized work order list for technicians, and a quarantine list for `exclude` data. No `correct` actions without human sign-off.

---

## 05. Solar Noon at S04 on 20 March 2025 (by hand)

**Given:**
- S04 location: 39.7540° N, 105.1460° W (from `stations.csv`)
- Date: 20 March 2025 (vernal equinox, solar declination δ ≈ 0°)
- Time zone: UTC-6 (MDT, assuming DST started 9 March 2025)

**Step 1: Equation of Time (EoT) on 20 March**
- Near equinox, EoT ≈ -7.5 minutes (sun lags mean solar time)

**Step 2: Longitude correction**
- Standard meridian for MDT: 105° W
- S04 longitude: 105.1460° W
- Difference: 0.1460° × 4 min/° = 0.584 min ≈ 35 seconds (sun later at S04)

**Step 3: Solar noon (local apparent time)**
- Mean solar noon at standard meridian: 12:00 MDT = 18:00 UTC
- Add EoT: 18:00 - 7.5 min = 17:52:30 UTC
- Add longitude correction: 17:52:30 + 0:00:35 ≈ **17:53:05 UTC**

**Answer:** Solar noon at S04 on 20 March 2025 ≈ **17:53 UTC** (11:53 MDT).

**Useful for:** Converting GHI measurements to clear-sky index (GHI / GHI_clear) for the climate summary — the clear-sky model peaks at solar noon, so timing errors directly bias the index.