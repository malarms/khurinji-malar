import pandas as pd
from pathlib import Path

data_dir = Path('/Users/malar/aeron_assignment/assignment_data/data')

flatlines_to_find = [
    ('S01', 'pressure_hpa', 8),
    ('S03', 'temp_c', 7),
    ('S03', 'temp_c', 6),
    ('S04', 'rh_pct', 6),
    ('S04', 'rh_pct', 6),
    ('S04', 'pressure_hpa', 8),
    ('S04', 'pressure_hpa', 6),
    ('S05', 'rh_pct', 6),
    ('S05', 'rh_pct', 6),
    ('S06', 'pressure_hpa', 7),
    ('S06', 'pressure_hpa', 6),
    ('S06', 'pressure_hpa', 6),
    ('S07', 'rh_pct', 7),
    ('S07', 'rh_pct', 6),
    ('S07', 'pressure_hpa', 6),
    ('S07', 'pressure_hpa', 6),
    ('S08', 'rh_pct', 10),
    ('S08', 'rh_pct', 11),
    ('S08', 'pressure_hpa', 6),
    ('S08', 'pressure_hpa', 6),
    ('S08', 'pressure_hpa', 7),
    ('S08', 'wind_kmh', 7),
]

for station_id, channel, expected_intervals in flatlines_to_find:
    df = pd.read_csv(data_dir / f'{station_id}.csv')
    df['timestamp_utc'] = pd.to_datetime(df['timestamp_utc'])
    diffs = df[channel].diff()
    flat = (diffs == 0).astype(int)
    runs = (flat != flat.shift()).cumsum()
    lengths = df[flat == 1].groupby(runs[flat == 1]).size()

    matching_runs = lengths[lengths == expected_intervals]
    for run_id in matching_runs.index:
        rows = df[(flat == 1) & (runs == run_id)]
        value = rows[channel].iloc[0]
        start_ts = rows['timestamp_utc'].iloc[0]
        end_ts = rows['timestamp_utc'].iloc[-1]
        print(f'{station_id},{channel},{start_ts.strftime("%Y-%m-%d %H:%M")},{end_ts.strftime("%Y-%m-%d %H:%M")},prolonged_flatline ({expected_intervals} intervals, {expected_intervals*10} minutes at {value:.1f}),keep,{channel} constant at {value:.1f} for {expected_intervals} consecutive 10-min intervals')