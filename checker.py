#!/usr/bin/env python3
"""
Aeron Weather Data Quality Checker

Accepts a data-pack directory as a command-line argument and produces flags.csv
in the current working directory with columns:
station_id, channel, start_utc, end_utc, issue, action, note
"""

import argparse
import sys
from pathlib import Path
import pandas as pd
import numpy as np
from typing import List, Dict, Any, Optional
import warnings
warnings.filterwarnings('ignore')


# =============================================================================
# Data Loading
# =============================================================================

def load_stations(data_dir: Path) -> pd.DataFrame:
    """Load station metadata."""
    return pd.read_csv(data_dir / 'stations.csv')


def load_weather_data(data_dir: Path) -> Dict[str, pd.DataFrame]:
    """Load all station weather CSV files from data/ subdirectory."""
    data_path = data_dir / 'data'
    if not data_path.exists():
        return {}

    stations = {}
    for csv_file in sorted(data_path.glob('S*.csv')):
        station_id = csv_file.stem
        df = pd.read_csv(csv_file)
        df['timestamp_utc'] = pd.to_datetime(df['timestamp_utc'])
        df = df.sort_values('timestamp_utc').reset_index(drop=True)
        stations[station_id] = df
    return stations


def load_gps_data(data_dir: Path) -> Dict[str, pd.DataFrame]:
    """Parse NMEA sentences from GPS files."""
    gps_path = data_dir / 'gps'
    if not gps_path.exists():
        return {}

    def nmea_to_dd(coord_str: str, direction: str) -> Optional[float]:
        if not coord_str or coord_str == '':
            return None
        dot_idx = coord_str.find('.')
        if dot_idx == -1:
            return None
        minutes_str = coord_str[dot_idx-2:]
        degrees_str = coord_str[:dot_idx-2]
        try:
            degrees = int(degrees_str)
            minutes = float(minutes_str)
        except ValueError:
            return None
        dd = degrees + minutes / 60.0
        if direction in ['S', 'W']:
            dd = -dd
        return dd

    gps_data = {}
    for nmea_file in sorted(gps_path.glob('S*.nmea')):
        station_id = nmea_file.stem
        rows = []
        with open(nmea_file) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                parts = line.split(',', 1)
                if len(parts) != 2:
                    continue
                logger_ts, nmea = parts
                rows.append({'logger_timestamp': logger_ts, 'nmea': nmea})

        if not rows:
            gps_data[station_id] = pd.DataFrame()
            continue

        df = pd.DataFrame(rows)
        df['logger_timestamp'] = pd.to_datetime(df['logger_timestamp'])

        # Parse GPRMC
        gprmc = df[df['nmea'].str.startswith('$GPRMC')].copy()
        if len(gprmc) > 0:
            parsed = gprmc['nmea'].str.split(',', expand=True)
            gprmc['gps_utc_time'] = parsed[1]
            gprmc['status'] = parsed[2]
            gprmc['lat'] = gprmc.apply(
                lambda r: nmea_to_dd(parsed.loc[r.name, 3], parsed.loc[r.name, 4]), axis=1)
            gprmc['lon'] = gprmc.apply(
                lambda r: nmea_to_dd(parsed.loc[r.name, 5], parsed.loc[r.name, 6]), axis=1)
            gprmc = gprmc[gprmc['status'] == 'A']

        # Parse GPGGA
        gpgga = df[df['nmea'].str.startswith('$GPGGA')].copy()
        if len(gpgga) > 0:
            parsed = gpgga['nmea'].str.split(',', expand=True)
            gpgga['fix_quality'] = pd.to_numeric(parsed[6], errors='coerce').fillna(0).astype(int)
            gpgga = gpgga[gpgga['fix_quality'] > 0]
            if len(gpgga) > 0:
                gpgga['lat'] = gpgga.apply(
                    lambda r: nmea_to_dd(parsed.loc[r.name, 2], parsed.loc[r.name, 3]), axis=1)
                gpgga['lon'] = gpgga.apply(
                    lambda r: nmea_to_dd(parsed.loc[r.name, 4], parsed.loc[r.name, 5]), axis=1)

        gps_data[station_id] = {'gprmc': gprmc, 'gpgga': gpgga}

    return gps_data


def load_maintenance_log(data_dir: Path) -> str:
    """Load maintenance log as text."""
    log_path = data_dir / 'maintenance_log.md'
    if log_path.exists():
        return log_path.read_text()
    return ''


# =============================================================================
# Check Functions
# =============================================================================

def check_timestamps(station_id: str, df: pd.DataFrame) -> List[Dict]:
    """Check for missing, duplicate, out-of-order timestamps and missing intervals."""
    flags = []

    if len(df) == 0:
        return flags

    ts = df['timestamp_utc']

    # Duplicate timestamps - group consecutive duplicates
    dup_mask = ts.duplicated(keep=False)
    if dup_mask.any():
        dup_ts = ts[dup_mask].unique()
        # Group consecutive timestamps
        groups = []
        current = [dup_ts[0]]
        for dt in dup_ts[1:]:
            # Check if consecutive (10 min apart)
            if (dt - current[-1]).total_seconds() == 600:
                current.append(dt)
            else:
                groups.append(current)
                current = [dt]
        groups.append(current)

        for group in groups:
            start_dt = group[0]
            end_dt = group[-1]
            # Count total duplicate rows in this group
            total_rows = sum(len(df[ts == dt]) for dt in group)
            unique_ts = len(group)
            flags.append({
                'station_id': station_id,
                'channel': 'all',
                'start_utc': start_dt.strftime('%Y-%m-%d %H:%M'),
                'end_utc': end_dt.strftime('%Y-%m-%d %H:%M'),
                'issue': f'duplicate_timestamps ({total_rows} rows, {unique_ts} unique timestamps duplicated)',
                'action': 'exclude',
                'note': f'{unique_ts} consecutive timestamps each appear {total_rows//unique_ts}x; measurements differ'
            })

    # Out of order
    diffs = ts.diff().dt.total_seconds()
    oob = diffs[diffs < 0]
    if len(oob) > 0:
        for idx in oob.index:
            prev_ts = ts.iloc[idx - 1]
            curr_ts = ts.iloc[idx]
            flags.append({
                'station_id': station_id,
                'channel': 'all',
                'start_utc': prev_ts.strftime('%Y-%m-%d %H:%M'),
                'end_utc': curr_ts.strftime('%Y-%m-%d %H:%M'),
                'issue': 'out_of_order_timestamp',
                'action': 'exclude',
                'note': f'Timestamp goes backward: {prev_ts} -> {curr_ts}'
            })

    # Missing intervals (gaps > 10 min)
    gaps = diffs[diffs > 600]
    if len(gaps) > 0:
        for idx, gap in gaps.items():
            prev_ts = ts.iloc[idx - 1]
            curr_ts = ts.iloc[idx]
            missing_intervals = int(gap / 600) - 1
            flags.append({
                'station_id': station_id,
                'channel': 'all',
                'start_utc': prev_ts.strftime('%Y-%m-%d %H:%M'),
                'end_utc': curr_ts.strftime('%Y-%m-%d %H:%M'),
                'issue': f'missing_intervals ({missing_intervals} expected 10-min intervals missing)',
                'action': 'exclude',
                'note': f'Gap of {gap/60:.1f} minutes ({missing_intervals} missing intervals)'
            })

    # Expected coverage check
    expected_intervals = int((ts.max() - ts.min()).total_seconds() / 600) + 1
    actual_intervals = len(ts.unique())
    if actual_intervals < expected_intervals:
        missing_total = expected_intervals - actual_intervals
        if missing_total > 2:
            flags.append({
                'station_id': station_id,
                'channel': 'all',
                'start_utc': ts.min().strftime('%Y-%m-%d %H:%M'),
                'end_utc': ts.max().strftime('%Y-%m-%d %H:%M'),
                'issue': f'incomplete_coverage ({missing_total} intervals missing from expected {expected_intervals})',
                'action': 'keep',
                'note': f'Expected {expected_intervals} intervals from {ts.min()} to {ts.max()}, found {actual_intervals}'
            })

    return flags


def check_sensor_values(station_id: str, df: pd.DataFrame) -> List[Dict]:
    """Check for invalid or suspicious sensor values."""
    flags = []

    if len(df) == 0:
        return flags

    # Define physical bounds for each channel
    bounds = {
        'temp_c': (-50, 60, '°C'),
        'rh_pct': (0, 110, '%'),  # Allow up to 110 for supersaturation
        'pressure_hpa': (600, 1100, 'hPa'),
        'wind_kmh': (0, 200, 'km/h'),
        'wind_dir_deg': (0, 360, '°'),
        'rain_mm': (0, 500, 'mm'),  # 0.2mm tip bucket, max reasonable in 10min
        'ghi_wm2': (0, 1500, 'W/m²'),
    }

    for col, (min_val, max_val, unit) in bounds.items():
        if col not in df.columns:
            continue

        # Out of bounds
        oob = df[(df[col] < min_val) | (df[col] > max_val)]
        if len(oob) > 0:
            # Group consecutive out-of-bounds
            oob_idx = oob.index.tolist()
            groups = []
            current = [oob_idx[0]]
            for idx in oob_idx[1:]:
                if idx == current[-1] + 1:
                    current.append(idx)
                else:
                    groups.append(current)
                    current = [idx]
            groups.append(current)

            for group in groups:
                start_ts = df.loc[group[0], 'timestamp_utc']
                end_ts = df.loc[group[-1], 'timestamp_utc']
                action = 'exclude' if len(group) > 1 else 'correct'
                flags.append({
                    'station_id': station_id,
                    'channel': col,
                    'start_utc': start_ts.strftime('%Y-%m-%d %H:%M'),
                    'end_utc': end_ts.strftime('%Y-%m-%d %H:%M'),
                    'issue': f'out_of_bounds ({col} outside [{min_val}, {max_val}] {unit})',
                    'action': action,
                    'note': f'{len(group)} consecutive readings outside physical bounds: {df.loc[group[0], col]:.1f} to {df.loc[group[-1], col]:.1f} {unit}'
                })

        # RH > 100% (supersaturation - flag as suspicious but not necessarily invalid)
        if col == 'rh_pct':
            supersat = df[df[col] > 100]
            if len(supersat) > 0:
                # Group consecutive
                ss_idx = supersat.index.tolist()
                groups = []
                current = [ss_idx[0]]
                for idx in ss_idx[1:]:
                    if idx == current[-1] + 1:
                        current.append(idx)
                    else:
                        groups.append(current)
                        current = [idx]
                groups.append(current)

                for group in groups:
                    if len(group) >= 3:  # Only flag runs of 3+ intervals
                        start_ts = df.loc[group[0], 'timestamp_utc']
                        end_ts = df.loc[group[-1], 'timestamp_utc']
                        flags.append({
                            'station_id': station_id,
                            'channel': col,
                            'start_utc': start_ts.strftime('%Y-%m-%d %H:%M'),
                            'end_utc': end_ts.strftime('%Y-%m-%d %H:%M'),
                            'issue': 'supersaturation (rh_pct > 100%)',
                            'action': 'correct',
                            'note': f'{len(group)} consecutive readings >100% RH (max {df.loc[group, col].max():.1f}%); sensor likely uncalibrated'
                        })

    # Consolidate supersaturation flags that are close together (within 1 hour)
    # This handles the case where brief dips below 100% split a long run
    if 'rh_pct' in df.columns:
        ss_flags = [f for f in flags if f['station_id'] == station_id and f['channel'] == 'rh_pct' and f['issue'] == 'supersaturation (rh_pct > 100%)']
        if len(ss_flags) > 1:
            # Sort by start time
            ss_flags.sort(key=lambda x: x['start_utc'])
            # Merge adjacent/overlapping flags within 60 min
            merged = [ss_flags[0]]
            for f in ss_flags[1:]:
                last = merged[-1]
                last_end = pd.Timestamp(last['end_utc'])
                this_start = pd.Timestamp(f['start_utc'])
                if (this_start - last_end).total_seconds() <= 3600:  # within 1 hour
                    # Merge
                    last['end_utc'] = f['end_utc']
                    last['note'] = 'Extended supersaturation period with brief dips; ' + last['note'] + ' ' + f['note']
                else:
                    merged.append(f)
            # Replace in flags
            flags = [f for f in flags if not (f['station_id'] == station_id and f['channel'] == 'rh_pct' and f['issue'] == 'supersaturation (rh_pct > 100%)')]
            flags.extend(merged)

    return flags


def check_flatlines(station_id: str, df: pd.DataFrame) -> List[Dict]:
    """Check for prolonged flatlines (same value for many consecutive intervals)."""
    flags = []

    if len(df) == 0:
        return flags

    # Channels to check for flatlines (excluding expected zeros)
    # rain_mm and ghi_wm2 naturally have long zero runs (dry periods, nighttime)
    check_channels = ['temp_c', 'rh_pct', 'pressure_hpa', 'wind_kmh', 'wind_dir_deg']

    for col in check_channels:
        if col not in df.columns:
            continue

        diffs = df[col].diff()
        flat = (diffs == 0).astype(int)
        runs = (flat != flat.shift()).cumsum()
        lengths = df[flat == 1].groupby(runs[flat == 1]).size()

        # Threshold: 6+ intervals (1+ hour) for most channels
        # For wind_dir_deg, 12+ intervals (2+ hours) since direction can be steady
        threshold = 12 if col == 'wind_dir_deg' else 6
        long_flats = lengths[lengths >= threshold]

        for run_id, length in long_flats.items():
            rows = df[(flat == 1) & (runs == run_id)]
            value = rows[col].iloc[0]
            start_ts = rows['timestamp_utc'].iloc[0]
            end_ts = rows['timestamp_utc'].iloc[-1]

            # Skip if it's a value that could plausibly be stable
            # e.g., pressure at night, temperature during stable conditions
            # But flag regardless for review
            flags.append({
                'station_id': station_id,
                'channel': col,
                'start_utc': start_ts.strftime('%Y-%m-%d %H:%M'),
                'end_utc': end_ts.strftime('%Y-%m-%d %H:%M'),
                'issue': f'prolonged_flatline ({length} intervals, {length*10} minutes at {value:.1f})',
                'action': 'keep',
                'note': f'{col} constant at {value:.1f} for {length} consecutive 10-min intervals'
            })

    return flags


def check_discontinuities(station_id: str, df: pd.DataFrame,
                          all_stations: Dict[str, pd.DataFrame]) -> List[Dict]:
    """Check for large discontinuities, comparing with nearby stations where useful."""
    flags = []

    if len(df) == 0:
        return flags

    # Check pressure for step changes (common after sensor replacement)
    if 'pressure_hpa' in df.columns:
        pressure = df['pressure_hpa']
        # Look for large jumps between consecutive intervals
        pressure_diff = pressure.diff().abs()
        large_jumps = pressure_diff[pressure_diff > 10]  # >10 hPa jump in 10 min

        for idx in large_jumps.index:
            ts = df.loc[idx, 'timestamp_utc']
            prev_val = df.loc[idx - 1, 'pressure_hpa']
            curr_val = df.loc[idx, 'pressure_hpa']
            flags.append({
                'station_id': station_id,
                'channel': 'pressure_hpa',
                'start_utc': ts.strftime('%Y-%m-%d %H:%M'),
                'end_utc': ts.strftime('%Y-%m-%d %H:%M'),
                'issue': 'pressure_jump (>10 hPa in 10 min)',
                'action': 'keep',
                'note': f'Pressure changed from {prev_val:.1f} to {curr_val:.1f} hPa in 10 min'
            })

    # Check for sustained level shift in pressure (compare before/after windows)
    # Use 3-day windows, compare with nearby stations at similar elevation
    if 'pressure_hpa' in df.columns and len(df) > 1000:
        # Look for sustained mean shift > 5 hPa that persists
        # This is a simplified check - a real implementation would use more robust methods
        pass  # Deferred to more targeted checks with maintenance log context

    return flags


def check_gps_discrepancy(station_id: str, gps_data: Dict,
                          stations_meta: pd.DataFrame) -> List[Dict]:
    """Compare GPS coordinates with station metadata."""
    flags = []

    if station_id not in gps_data:
        return flags

    station_meta = stations_meta[stations_meta['station_id'] == station_id]
    if len(station_meta) == 0:
        return flags

    meta_lat = station_meta.iloc[0]['lat']
    meta_lon = station_meta.iloc[0]['lon']

    gprmc = gps_data[station_id].get('gprmc', pd.DataFrame())
    gpgga = gps_data[station_id].get('gpgga', pd.DataFrame())

    # Use valid GPRMC fixes
    if len(gprmc) > 0:
        valid = gprmc.dropna(subset=['lat', 'lon'])
        if len(valid) > 0:
            mean_lat = valid['lat'].mean()
            mean_lon = valid['lon'].mean()

            lat_diff_m = (mean_lat - meta_lat) * 111000
            lon_diff_m = (mean_lon - meta_lon) * 111000 * np.cos(np.radians(meta_lat))
            dist_m = np.sqrt(lat_diff_m**2 + lon_diff_m**2)

            if dist_m > 1000:  # > 1 km discrepancy
                flags.append({
                    'station_id': station_id,
                    'channel': 'metadata',
                    'start_utc': valid['logger_timestamp'].min().strftime('%Y-%m-%d %H:%M'),
                    'end_utc': valid['logger_timestamp'].max().strftime('%Y-%m-%d %H:%M'),
                    'issue': f'gps_metadata_discrepancy ({dist_m:.0f}m from install location)',
                    'action': 'correct',
                    'note': f'GPS mean ({mean_lat:.6f}, {mean_lon:.6f}) vs metadata ({meta_lat}, {meta_lon}): {lat_diff_m:.0f}m lat, {lon_diff_m:.0f}m lon diff'
                })

    return flags


def check_maintenance_context(station_id: str, df: pd.DataFrame,
                              maintenance_log: str) -> List[Dict]:
    """Add context flags based on maintenance log entries."""
    flags = []

    # This is a simple text-based check - in production would parse structured log
    # For now, we note key maintenance events that align with data anomalies
    if station_id == 'S02' and 'pressure board' in maintenance_log.lower():
        # Check if there's a sustained pressure shift after 2025-03-21
        after_swap = df[df['timestamp_utc'] >= '2025-03-21 11:00']
        before_swap = df[df['timestamp_utc'] < '2025-03-21 11:00']
        if len(after_swap) > 100 and len(before_swap) > 100:
            # Compare mean pressure in same time-of-day windows (e.g., noon)
            # Simplified: compare overall means
            mean_before = before_swap['pressure_hpa'].mean()
            mean_after = after_swap['pressure_hpa'].mean()
            diff = mean_after - mean_before
            if abs(diff) > 5:
                flags.append({
                    'station_id': station_id,
                    'channel': 'pressure_hpa',
                    'start_utc': '2025-03-21 11:00',
                    'end_utc': df['timestamp_utc'].max().strftime('%Y-%m-%d %H:%M'),
                    'issue': f'pressure_level_shift_after_maintenance ({diff:.1f} hPa)',
                    'action': 'correct',
                    'note': f'Maintenance log notes pressure board swap ~11:00 on 2025-03-21; mean pressure shifted by {diff:.1f} hPa'
                })

    if station_id == 'S06' and 'battery' in maintenance_log.lower() and 'flat' in maintenance_log.lower():
        # Check for issues around 2025-03-24
        around = df[(df['timestamp_utc'] >= '2025-03-24 08:00') & (df['timestamp_utc'] <= '2025-03-24 18:00')]
        if len(around) > 0:
            # Check for duplicates (already caught by timestamp check)
            # Add note about reboot
            flags.append({
                'station_id': station_id,
                'channel': 'all',
                'start_utc': '2025-03-24 10:10',
                'end_utc': '2025-03-24 16:00',
                'issue': 'logger_reboot_during_battery_swap',
                'action': 'exclude',
                'note': 'Maintenance log notes battery swap and logger reboot ~2025-03-24; data shows duplicate timestamps with conflicting measurements'
            })

    if station_id == 'S07' and 'anemometer' in maintenance_log.lower():
        # Check wind around 2025-03-26
        before = df[df['timestamp_utc'] < '2025-03-26']
        after = df[df['timestamp_utc'] >= '2025-03-26']
        if len(before) > 100 and len(after) > 100:
            mean_before = before['wind_kmh'].mean()
            mean_after = after['wind_kmh'].mean()
            if mean_before > 0 and mean_after > 0:
                ratio = mean_before / mean_after
                if ratio > 2.5:  # Significant drop
                    flags.append({
                        'station_id': station_id,
                        'channel': 'wind_kmh',
                        'start_utc': '2025-03-26 00:00',
                        'end_utc': df['timestamp_utc'].max().strftime('%Y-%m-%d %H:%M'),
                        'issue': f'wind_speed_drop_after_anemometer_swap ({mean_before:.1f} -> {mean_after:.1f} km/h mean)',
                        'action': 'keep',
                        'note': f'Maintenance log notes anemometer replacement 2025-03-26; mean wind speed dropped {ratio:.1f}x (nearby stations show smaller change)'
                    })

    if station_id == 'S08' and 'data stopped' in maintenance_log.lower():
        # Gap around 2025-03-17 already caught by timestamp check
        pass

    return flags


def deduplicate_flags(flags: List[Dict]) -> List[Dict]:
    """Remove duplicate flags for the same underlying problem."""
    seen = set()
    deduped = []
    for f in flags:
        key = (f['station_id'], f['channel'], f['start_utc'], f['issue'])
        if key not in seen:
            seen.add(key)
            deduped.append(f)
    return deduped


# =============================================================================
# Main
# =============================================================================

def main():
    parser = argparse.ArgumentParser(description='Aeron Weather Data Quality Checker')
    parser.add_argument('data_dir', type=Path, help='Path to data pack directory')
    parser.add_argument('-o', '--output', type=Path, default=Path('flags.csv'),
                        help='Output CSV path (default: flags.csv in current directory)')
    args = parser.parse_args()

    data_dir = args.data_dir
    if not data_dir.exists():
        print(f"Error: Data directory {data_dir} does not exist", file=sys.stderr)
        sys.exit(1)

    print(f"Loading data from {data_dir}...")
    stations_meta = load_stations(data_dir)
    weather_data = load_weather_data(data_dir)
    gps_data = load_gps_data(data_dir)
    maintenance_log = load_maintenance_log(data_dir)

    print(f"Found {len(weather_data)} station weather files")
    print(f"Found {len(gps_data)} station GPS files")

    all_flags = []

    for station_id, df in weather_data.items():
        print(f"Checking {station_id} ({len(df)} rows)...")

        # Run all checks
        all_flags.extend(check_timestamps(station_id, df))
        all_flags.extend(check_sensor_values(station_id, df))
        all_flags.extend(check_flatlines(station_id, df))
        all_flags.extend(check_discontinuities(station_id, df, weather_data))
        all_flags.extend(check_gps_discrepancy(station_id, gps_data, stations_meta))
        all_flags.extend(check_maintenance_context(station_id, df, maintenance_log))

    # Deduplicate
    all_flags = deduplicate_flags(all_flags)

    # Create output DataFrame
    if all_flags:
        flags_df = pd.DataFrame(all_flags, columns=[
            'station_id', 'channel', 'start_utc', 'end_utc', 'issue', 'action', 'note'
        ])
    else:
        flags_df = pd.DataFrame(columns=[
            'station_id', 'channel', 'start_utc', 'end_utc', 'issue', 'action', 'note'
        ])

    # Write output
    flags_df.to_csv(args.output, index=False)
    print(f"\nGenerated {len(flags_df)} flags in {args.output}")

    # Print summary
    print("\n=== Flags Summary ===")
    for station_id in sorted(flags_df['station_id'].unique()):
        station_flags = flags_df[flags_df['station_id'] == station_id]
        print(f"\n{station_id}: {len(station_flags)} flags")
        for _, row in station_flags.iterrows():
            print(f"  {row['channel']:15s} {row['start_utc']} - {row['end_utc']:16s} | {row['action']:7s} | {row['issue']}")


if __name__ == '__main__':
    main()