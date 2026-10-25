#!/usr/bin/env python3
"""Tests for the Aeron Weather Data Quality Checker - run from project root."""

import tempfile
import shutil
from pathlib import Path
import pandas as pd
import numpy as np
import sys

# Add the checker module
sys.path.insert(0, '/Users/malar/aeron_assignment')
from checker import (
    check_timestamps,
    check_sensor_values,
    check_flatlines,
    check_gps_discrepancy,
    load_gps_data,
    load_stations,
    load_weather_data,
    load_maintenance_log,
)


def create_test_data_dir():
    """Create a temporary data directory with synthetic test data."""
    tmpdir = Path(tempfile.mkdtemp())

    # Create stations.csv
    stations = pd.DataFrame({
        'station_id': ['S01', 'S02', 'S03'],
        'name': ['Test Station 1', 'Test Station 2', 'Test Station 3'],
        'lat': [39.0, 40.0, 41.0],
        'lon': [-105.0, -106.0, -107.0],
        'elevation_m': [1500, 1600, 1700],
        'installed': ['2023-01-01', '2023-01-01', '2023-01-01'],
        'logger_interval_min': [10, 10, 10]
    })
    stations.to_csv(tmpdir / 'stations.csv', index=False)

    # Create data/ directory
    data_dir = tmpdir / 'data'
    data_dir.mkdir()

    # S01: Normal data
    dates = pd.date_range('2025-03-01', '2025-03-02', freq='10min')
    s01 = pd.DataFrame({
        'timestamp_utc': dates,
        'temp_c': np.random.normal(10, 5, len(dates)),
        'rh_pct': np.random.uniform(30, 80, len(dates)),
        'pressure_hpa': np.random.normal(850, 10, len(dates)),
        'wind_kmh': np.random.uniform(0, 20, len(dates)),
        'wind_dir_deg': np.random.uniform(0, 360, len(dates)),
        'rain_mm': 0.0,
        'ghi_wm2': np.random.uniform(0, 800, len(dates))
    })
    s01.to_csv(data_dir / 'S01.csv', index=False)

    # S02: With duplicate timestamps
    dates = pd.date_range('2025-03-01', '2025-03-02', freq='10min')
    s02 = pd.DataFrame({
        'timestamp_utc': list(dates) + [dates[10], dates[11]],  # Add duplicates
        'temp_c': list(np.random.normal(10, 5, len(dates))) + [999, 888],
        'rh_pct': list(np.random.uniform(30, 80, len(dates))) + [50, 50],
        'pressure_hpa': list(np.random.normal(850, 10, len(dates))) + [850, 850],
        'wind_kmh': list(np.random.uniform(0, 20, len(dates))) + [5, 5],
        'wind_dir_deg': list(np.random.uniform(0, 360, len(dates))) + [180, 180],
        'rain_mm': [0.0] * (len(dates) + 2),
        'ghi_wm2': list(np.random.uniform(0, 800, len(dates))) + [100, 100]
    })
    s02.to_csv(data_dir / 'S02.csv', index=False)

    # S03: With gap
    dates1 = pd.date_range('2025-03-01', '2025-03-01 12:00', freq='10min')
    dates2 = pd.date_range('2025-03-01 14:00', '2025-03-02', freq='10min')  # 2 hour gap
    dates = dates1.union(dates2)
    s03 = pd.DataFrame({
        'timestamp_utc': dates,
        'temp_c': np.random.normal(10, 5, len(dates)),
        'rh_pct': np.random.uniform(30, 80, len(dates)),
        'pressure_hpa': np.random.normal(850, 10, len(dates)),
        'wind_kmh': np.random.uniform(0, 20, len(dates)),
        'wind_dir_deg': np.random.uniform(0, 360, len(dates)),
        'rain_mm': 0.0,
        'ghi_wm2': np.random.uniform(0, 800, len(dates))
    })
    s03.to_csv(data_dir / 'S03.csv', index=False)

    # Create gps/ directory
    gps_dir = tmpdir / 'gps'
    gps_dir.mkdir()

    # S01 GPS - matches metadata (39.0, -105.0)
    with open(gps_dir / 'S01.nmea', 'w') as f:
        for i in range(24):
            f.write(f"2025-03-01 {i:02d}:00:00,\$GPRMC,{i:02d}0000.00,A,3900.0000,N,10500.0000,W,0.0,0.0,010325,,,A*00\n")

    # S02 GPS - matches metadata (40.0, -106.0)
    with open(gps_dir / 'S02.nmea', 'w') as f:
        for i in range(24):
            f.write(f"2025-03-01 {i:02d}:00:00,\$GPRMC,{i:02d}0000.00,A,4000.0000,N,10600.0000,W,0.0,0.0,010325,,,A*00\n")

    # S03 GPS - DISCREPANT: metadata says 41.0, -107.0 but GPS says 41.0, -105.0
    with open(gps_dir / 'S03.nmea', 'w') as f:
        for i in range(24):
            f.write(f"2025-03-01 {i:02d}:00:00,\$GPRMC,{i:02d}0000.00,A,4100.0000,N,10500.0000,W,0.0,0.0,010325,,,A*00\n")

    # Create maintenance_log.md
    (tmpdir / 'maintenance_log.md').write_text("""
2025-03-01 S02 Pressure board swapped around 11:00
2025-03-01 S03 Battery replaced
""")

    return tmpdir


def test_check_timestamps():
    """Test timestamp checks."""
    print("Testing check_timestamps...")

    # Create test DataFrame with duplicates
    dates = pd.date_range('2025-03-01', periods=10, freq='10min')
    df = pd.DataFrame({'timestamp_utc': dates})
    # Add duplicate
    df = pd.concat([df, pd.DataFrame({'timestamp_utc': [dates[5]]})], ignore_index=True)

    flags = check_timestamps('S01', df)
    dup_flags = [f for f in flags if f['issue'].startswith('duplicate_timestamps')]
    assert len(dup_flags) == 1
    assert dup_flags[0]['action'] == 'exclude'
    print("  ✓ duplicate test passed")

    # Test gap detection
    dates = pd.date_range('2025-03-01', periods=5, freq='10min')
    dates = dates.append(pd.DatetimeIndex([dates[-1] + pd.Timedelta(minutes=40)]))  # 30 min gap
    df = pd.DataFrame({'timestamp_utc': dates})

    flags = check_timestamps('S01', df)
    gap_flags = [f for f in flags if 'missing_intervals' in f['issue']]
    assert len(gap_flags) == 1
    assert gap_flags[0]['action'] == 'exclude'
    print("  ✓ gap test passed")

    # Test out of order
    dates = pd.date_range('2025-03-01', periods=5, freq='10min')
    dates = dates.insert(3, dates[2])  # Out of order
    df = pd.DataFrame({'timestamp_utc': dates})

    flags = check_timestamps('S01', df)
    oob_flags = [f for f in flags if f['issue'] == 'out_of_order_timestamp']
    assert len(oob_flags) == 1
    print("  ✓ out-of-order test passed")


def test_check_sensor_values():
    """Test sensor value checks."""
    print("Testing check_sensor_values...")

    dates = pd.date_range('2025-03-01', periods=20, freq='10min')
    df = pd.DataFrame({
        'timestamp_utc': dates,
        'temp_c': [10.0] * 20,
        'rh_pct': [50.0] * 20,
        'pressure_hpa': [850.0] * 20,
        'wind_kmh': [5.0] * 20,
        'wind_dir_deg': [180.0] * 20,
        'rain_mm': [0.0] * 20,
        'ghi_wm2': [100.0] * 20
    })
    # Add out of bounds temp
    df.loc[5, 'temp_c'] = 999.0
    df.loc[6, 'temp_c'] = 888.0  # consecutive

    flags = check_sensor_values('S01', df)
    oob_flags = [f for f in flags if f['issue'].startswith('out_of_bounds') and f['channel'] == 'temp_c']
    assert len(oob_flags) == 1  # Should be grouped
    assert oob_flags[0]['action'] == 'exclude'  # 2 consecutive
    print("  ✓ out_of_bounds test passed")

    # Test supersaturation
    df = pd.DataFrame({
        'timestamp_utc': dates,
        'temp_c': [10.0] * 20,
        'rh_pct': [50.0] * 20,
        'pressure_hpa': [850.0] * 20,
        'wind_kmh': [5.0] * 20,
        'wind_dir_deg': [180.0] * 20,
        'rain_mm': [0.0] * 20,
        'ghi_wm2': [100.0] * 20
    })
    df.loc[5:10, 'rh_pct'] = 101.0  # 6 intervals > 100

    flags = check_sensor_values('S01', df)
    ss_flags = [f for f in flags if f['issue'] == 'supersaturation (rh_pct > 100%)']
    assert len(ss_flags) == 1
    assert ss_flags[0]['action'] == 'correct'
    print("  ✓ supersaturation test passed")


def test_check_flatlines():
    """Test flatline detection."""
    print("Testing check_flatlines...")

    dates = pd.date_range('2025-03-01', periods=20, freq='10min')
    df = pd.DataFrame({
        'timestamp_utc': dates,
        'temp_c': [10.0] * 10,  # 10 intervals flat
        'rh_pct': [50.0] * 20,
        'pressure_hpa': [850.0] * 20,
        'wind_kmh': [5.0] * 20,
        'wind_dir_deg': [180.0] * 20,
        'rain_mm': [0.0] * 20,
        'ghi_wm2': [100.0] * 20
    })

    flags = check_flatlines('S01', df)
    flat_flags = [f for f in flags if f['issue'].startswith('prolonged_flatline') and f['channel'] == 'temp_c']
    assert len(flat_flags) == 1
    assert '10 intervals' in flat_flags[0]['issue']
    assert flat_flags[0]['action'] == 'keep'
    print("  ✓ flatlines test passed")


def test_gps_discrepancy():
    """Test GPS vs metadata check."""
    print("Testing check_gps_discrepancy...")

    tmpdir = create_test_data_dir()
    try:
        stations_meta = load_stations(tmpdir)
        gps_data = load_gps_data(tmpdir)

        # S03 should have discrepancy (GPS at 41.0, -105.0 vs metadata 41.0, -107.0)
        flags = check_gps_discrepancy('S03', gps_data, stations_meta)
        assert len(flags) == 1
        assert flags[0]['issue'].startswith('gps_metadata_discrepancy')
        assert flags[0]['action'] == 'correct'
        print("  ✓ discrepancy flag test passed")

        # S01 should NOT have discrepancy
        flags = check_gps_discrepancy('S01', gps_data, stations_meta)
        assert len(flags) == 0
        print("  ✓ no-flag test passed")
    finally:
        shutil.rmtree(tmpdir)


def test_output_format():
    """Test that flags.csv has correct columns."""
    print("Testing output format...")

    tmpdir = create_test_data_dir()
    try:
        stations_meta = load_stations(tmpdir)
        weather_data = load_weather_data(tmpdir)
        gps_data = load_gps_data(tmpdir)
        maintenance_log = load_maintenance_log(tmpdir)

        all_flags = []
        for station_id, df in weather_data.items():
            all_flags.extend(check_timestamps(station_id, df))
            all_flags.extend(check_sensor_values(station_id, df))
            all_flags.extend(check_flatlines(station_id, df))
            all_flags.extend(check_gps_discrepancy(station_id, gps_data, stations_meta))

        flags_df = pd.DataFrame(all_flags, columns=[
            'station_id', 'channel', 'start_utc', 'end_utc', 'issue', 'action', 'note'
        ])

        # Check columns
        expected_cols = ['station_id', 'channel', 'start_utc', 'end_utc', 'issue', 'action', 'note']
        assert list(flags_df.columns) == expected_cols, f"Columns: {list(flags_df.columns)}"

        # Check action values
        valid_actions = {'exclude', 'correct', 'keep'}
        assert set(flags_df['action'].unique()).issubset(valid_actions)

        # Check timestamp format
        for ts_col in ['start_utc', 'end_utc']:
            pd.to_datetime(flags_df[ts_col], format='%Y-%m-%d %H:%M')

        print("  ✓ output format test passed")
    finally:
        shutil.rmtree(tmpdir)


def test_real_data_readonly():
    """Verify the checker doesn't modify assignment_data."""
    print("Testing read-only...")
    import os
    # Get mtimes before
    mtimes_before = {}
    for root, dirs, files in os.walk('/Users/malar/aeron_assignment/assignment_data'):
        for f in files:
            path = os.path.join(root, f)
            mtimes_before[path] = os.path.getmtime(path)

    # Run checker (just the data loading part)
    stations_meta = load_stations(Path('/Users/malar/aeron_assignment/assignment_data'))
    weather_data = load_weather_data(Path('/Users/malar/aeron_assignment/assignment_data'))
    gps_data = load_gps_data(Path('/Users/malar/aeron_assignment/assignment_data'))
    maintenance_log = load_maintenance_log(Path('/Users/malar/aeron_assignment/assignment_data'))

    # Check mtimes after
    for path, mtime in mtimes_before.items():
        assert os.path.getmtime(path) == mtime, f"File {path} was modified!"

    print("  ✓ read-only test passed")


def test_integration_with_real_data():
    """Test the checker with actual assignment data."""
    print("Testing integration with real data...")

    from checker import main
    import argparse

    # Just test that it runs and produces valid output
    data_dir = Path('/Users/malar/aeron_assignment/assignment_data')
    output_file = Path('/Users/malar/aeron_assignment/test_flags.csv')

    stations_meta = load_stations(data_dir)
    weather_data = load_weather_data(data_dir)
    gps_data = load_gps_data(data_dir)
    maintenance_log = load_maintenance_log(data_dir)

    all_flags = []
    for station_id, df in weather_data.items():
        all_flags.extend(check_timestamps(station_id, df))
        all_flags.extend(check_sensor_values(station_id, df))
        all_flags.extend(check_flatlines(station_id, df))
        all_flags.extend(check_gps_discrepancy(station_id, gps_data, stations_meta))
        all_flags.extend(check_gps_discrepancy(station_id, gps_data, stations_meta))  # duplicate call should be fine

    from checker import deduplicate_flags
    all_flags = deduplicate_flags(all_flags)

    flags_df = pd.DataFrame(all_flags, columns=[
        'station_id', 'channel', 'start_utc', 'end_utc', 'issue', 'action', 'note'
    ])

    flags_df.to_csv(output_file, index=False)

    # Verify output
    assert output_file.exists()
    result = pd.read_csv(output_file)
    assert len(result) > 0
    assert list(result.columns) == ['station_id', 'channel', 'start_utc', 'end_utc', 'issue', 'action', 'note']

    # Clean up
    output_file.unlink()

    print("  ✓ integration test passed")


if __name__ == '__main__':
    test_check_timestamps()
    test_check_sensor_values()
    test_check_flatlines()
    test_gps_discrepancy()
    test_output_format()
    test_real_data_readonly()
    test_integration_with_real_data()
    print("\n✅ All tests passed!")