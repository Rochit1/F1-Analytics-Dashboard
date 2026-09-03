import logging
from pathlib import Path
from datetime import datetime
import pandas as pd
import fastf1
from fastf1.ergast import Ergast

# ==============================================================================
# SECTION 1: LOGGING & CONFIGURATION
# ==============================================================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler()]
)

YEAR = 2026  # Championship season year to process

# Anchor paths to the REPO ROOT, not the current working directory.
# This script lives at <repo_root>/python/f1_pipeline.py, so parent.parent = repo root.
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_FOLDER = BASE_DIR / "data"
CACHE_FOLDER = BASE_DIR / "f1_cache"

# Ensure destination directories exist
DATA_FOLDER.mkdir(parents=True, exist_ok=True)
CACHE_FOLDER.mkdir(parents=True, exist_ok=True)

# Enable disk caching to store raw API payloads locally (speeds up subsequent runs)
fastf1.Cache.enable_cache(str(CACHE_FOLDER))

logging.info(f"Starting F1 {YEAR} Season ETL Pipeline")
logging.info(f"Data folder: {DATA_FOLDER}")

# Initialize Ergast API client for dimensional metadata and standings
ergast = Ergast()


# ==============================================================================
# HELPER FUNCTIONS FOR POWER BI CLEANING
# ==============================================================================
def convert_timedelta_to_seconds(df, column_name):
    """
    Converts a pandas Timedelta column into a float representing total seconds.
    Power BI handles numeric seconds much more effectively than raw duration strings.
    """
    if column_name in df.columns:
        df[f"{column_name}_Seconds"] = df[column_name].dt.total_seconds()
    return df


# ==============================================================================
# SECTION 2: SCHEDULE & DIMENSION TABLES (MASTER DATA)
# ==============================================================================
logging.info("--- Extracting Schedule and Dimensional Data ---")

# 1. Season Schedule
try:
    schedule = fastf1.get_event_schedule(YEAR)
    # Filter out pre-season testing and ensure UTC timezone parity for comparison
    completed_races = schedule[schedule['EventFormat'] != 'testing'].copy()
    completed_races['Session1DateUtc'] = pd.to_datetime(completed_races['Session1DateUtc'], utc=True)
    today_utc = pd.Timestamp.now(tz='UTC')
    completed_races = completed_races[completed_races['Session1DateUtc'] < today_utc]

    schedule = schedule[schedule["RoundNumber"] > 0].copy()
    schedule.to_csv(DATA_FOLDER / "season_schedule.csv", index=False)
    logging.info(f"Saved schedule with {len(completed_races)} completed races.")
except Exception as e:
    logging.error(f"Failed to fetch event schedule: {e}")
    completed_races = pd.DataFrame()

# 2. Driver Master & Constructor Master Tables (Dimensional Modeling)
try:
    drivers_resp = ergast.get_driver_info(season=YEAR)
    if drivers_resp.content:
        driver_master = drivers_resp.content[0]
        driver_master.to_csv(DATA_FOLDER / "driver_master.csv", index=False)
        logging.info("Saved driver_master.csv")

    constructors_resp = ergast.get_constructor_info(season=YEAR)
    if constructors_resp.content:
        constructor_master = constructors_resp.content[0]
        constructor_master.to_csv(DATA_FOLDER / "constructor_master.csv", index=False)
        logging.info("Saved constructor_master.csv")
except Exception as e:
    logging.error(f"Failed to fetch Ergast master tables: {e}")

# 3. Current Standings Snapshots
try:
    driver_standings_resp = ergast.get_driver_standings(season=YEAR)
    if driver_standings_resp.content:
        driver_standings_snap = driver_standings_resp.content[0]
        driver_standings_snap.to_csv(DATA_FOLDER / "driver_standings_current.csv", index=False)
        logging.info("Saved driver_standings_current.csv")

    constructor_standings_resp = ergast.get_constructor_standings(season=YEAR)
    if constructor_standings_resp.content:
        constructor_standings_snap = constructor_standings_resp.content[0]
        constructor_standings_snap.to_csv(DATA_FOLDER / "constructor_standings_current.csv", index=False)

        # Constructor Points Breakdown
        constructor_points = constructor_standings_snap[['position', 'points', 'constructorName', 'constructorId']]
        constructor_points.to_csv(DATA_FOLDER / "constructor_points_breakdown.csv", index=False)
        logging.info("Saved constructor_points_breakdown.csv")
except Exception as e:
    logging.error(f"Failed to fetch standings snapshots: {e}")


# ==============================================================================
# SECTION 3: RACE & QUALIFYING SESSION DATA EXTRACTION
# ==============================================================================
logging.info("--- Extracting Round-by-Round Session Data ---")

all_qualifying_results = []
all_race_results = []
all_driver_points = []
all_laps = []
all_tyre_strategies = []
all_weather = []
all_fastest_laps = []
all_pit_stops = []

for idx, event in completed_races.iterrows():
    round_num = event['RoundNumber']
    event_name = event['EventName']
    logging.info(f"Processing Round {round_num}: {event_name}")

    # --------------------------------------------------------------------------
    # A. QUALIFYING SESSION EXTRACTION
    # --------------------------------------------------------------------------
    try:
        quali_session = fastf1.get_session(YEAR, round_num, 'Q')
        quali_session.load(laps=True, telemetry=False, weather=False, messages=False)

        q_results = quali_session.results[['DriverNumber', 'Abbreviation', 'FullName', 'TeamName', 'Position', 'Q1', 'Q2', 'Q3']].copy()
        q_results['Round'] = round_num
        q_results['EventName'] = event_name

        for col in ['Q1', 'Q2', 'Q3']:
            q_results = convert_timedelta_to_seconds(q_results, col)

        all_qualifying_results.append(q_results)
    except Exception as e:
        logging.warning(f"  Qualifying data missing/failed for Round {round_num}: {e}")

    # --------------------------------------------------------------------------
    # B. RACE SESSION EXTRACTION (RESULTS, LAPS, TYRES, PIT STOPS, WEATHER)
    # --------------------------------------------------------------------------
    try:
        race_session = fastf1.get_session(YEAR, round_num, 'R')

        # Load laps/results WITHOUT weather first. Weather is requested
        # separately below — bundling it into this call meant a single weather
        # API hiccup (common for recently-published sessions) could abort the
        # whole load() before laps ever got marked as loaded, silently costing
        # us laps/tyre/pit-stop/fastest-lap data for the entire round even
        # though only weather actually failed.
        race_session.load(laps=True, telemetry=False, weather=False, messages=False)

        # 1. Complete Race Results & Points per Round
        r_results = race_session.results[['DriverNumber', 'Abbreviation', 'FullName', 'TeamName', 'Position', 'GridPosition', 'Points', 'Status', 'Time']].copy()
        r_results['Round'] = round_num
        r_results['EventName'] = event_name
        r_results = convert_timedelta_to_seconds(r_results, 'Time')

        # Add Sprint points if this is a Sprint weekend
        #
        # We deliberately attempt to fetch the Sprint session for every round.
        # A normal race weekend will simply fail the get_session/load call and
        # continue without Sprint points.
        #
        # IMPORTANT:
        # reset_index(drop=True) prevents Pandas ambiguity when DriverNumber
        # exists both as an index level and as a column (this occurred on the
        # GitHub Actions environment).
        try:
            sprint_session = fastf1.get_session(YEAR, round_num, "S")
            sprint_session.load(
                laps=False,
                telemetry=False,
                weather=False,
                messages=False
            )
            # Copy first, then reset the index.
            # This avoids:
            # "'DriverNumber' is both an index level and a column label"
            sprint_results = sprint_session.results.copy()
            if 'DriverNumber' in sprint_results.index.names:
                sprint_results.index = sprint_results.index.rename(
                    None,
                    level=sprint_results.index.names.index('DriverNumber')
                )
            sprint_results = sprint_results[
                ['DriverNumber', 'Abbreviation', 'TeamName', 'Points']
            ].copy()
            # Make DriverNumber consistent between race and sprint data
            r_results['DriverNumber'] = (
                r_results['DriverNumber']
                .astype(str)
                .str.strip()
            )
            sprint_results['DriverNumber'] = (
                sprint_results['DriverNumber']
                .astype(str)
                .str.strip()
            )
            # Sprint points should never be NaN
            sprint_results['Points'] = (
                sprint_results['Points']
                .fillna(0)
                .astype(float)
            )
            # A driver should appear only once in Sprint results.
            # Prevent a many-to-one merge from accidentally multiplying rows.
            sprint_results = sprint_results.drop_duplicates(
                subset=['DriverNumber'],
                keep='first'
            )
            rows_before = len(r_results)
            # Merge Sprint points into race results
            r_results = r_results.merge(
                sprint_results[['DriverNumber', 'Points']],
                on='DriverNumber',
                how='left',
                suffixes=('', '_Sprint'),
                validate='one_to_one'
            )
            # The merge must NEVER change the number of race-result rows.
            if len(r_results) != rows_before:
                raise RuntimeError(
                    f"Round {round_num}: Sprint merge changed row count "
                    f"from {rows_before} to {len(r_results)}."
                )
            # Drivers who did not score Sprint points get zero
            r_results['Points_Sprint'] = (
                r_results['Points_Sprint']
                .fillna(0)
                .astype(float)
            )
            # Total round points = Race + Sprint
            r_results['Points'] = (
                r_results['Points'] +
                r_results['Points_Sprint']
            )
            r_results.drop(
                columns=['Points_Sprint'],
                inplace=True
            )
            logging.info(
                f"Added Sprint points for Round {round_num}"
            )
        except Exception as e:
            # If there is no Sprint session, this is a normal weekend.
            #
            # DO NOT let an arbitrary exception silently create incorrect
            # points. Log the exact reason and continue.
            logging.error(
                f"No Sprint session for Round {round_num}: {e}"
            ) 
            raise

        all_race_results.append(r_results)
        all_driver_points.append(r_results[['Round', 'EventName', 'DriverNumber', 'Abbreviation', 'TeamName', 'Position', 'Points']])

        # 2. Lap-by-Lap Data & Tyre Strategy
        laps_df = race_session.laps[['Driver', 'DriverNumber', 'LapNumber', 'LapTime', 'Stint', 'Compound', 'TyreLife', 'FreshTyre', 'Sector1Time', 'Sector2Time', 'Sector3Time', 'IsAccurate', 'PitOutTime', 'PitInTime']].copy()
        laps_df['Round'] = round_num
        laps_df['EventName'] = event_name

        for col in ['LapTime', 'Sector1Time', 'Sector2Time', 'Sector3Time']:
            laps_df = convert_timedelta_to_seconds(laps_df, col)

        all_laps.append(laps_df)

        # Extract Tyre Strategy (grouped per stint)
        stints = laps_df.groupby(['Round', 'EventName', 'Driver', 'Stint', 'Compound']).agg(
            StintStartLap=('LapNumber', 'min'),
            StintEndLap=('LapNumber', 'max'),
            TotalLapsOnStint=('LapNumber', 'count')
        ).reset_index()
        all_tyre_strategies.append(stints)

        # 3. Pit Stop Summary
        pits = laps_df[laps_df['PitInTime'].notna() | laps_df['PitOutTime'].notna()].copy()
        if not pits.empty:
            all_pit_stops.append(pits[['Round', 'EventName', 'Driver', 'LapNumber', 'Stint', 'Compound', 'PitInTime', 'PitOutTime']])

        # 4. Fastest Laps per Driver
        fastest = laps_df.loc[laps_df.groupby('Driver')['LapTime_Seconds'].idxmin().dropna()]
        all_fastest_laps.append(fastest[['Round', 'EventName', 'Driver', 'LapNumber', 'Compound', 'LapTime_Seconds']])

        # 5. Weather Data
        # Loaded as its own isolated attempt, separate from the laps/results
        # load() call above — so a weather API failure (e.g. data not yet
        # published for a very recent session) only costs us weather data for
        # this round, not the round's laps/tyre/pit-stop/fastest-lap data too.
        try:
            race_session.load(laps=False, telemetry=False, weather=True, messages=False)
        except Exception as e:
            logging.warning(f"  Weather data unavailable for Round {round_num}: {e}")

        if hasattr(race_session, 'weather_data') and race_session.weather_data is not None:
            w_df = race_session.weather_data.copy()
            w_df['Round'] = round_num
            w_df['EventName'] = event_name
            w_df = convert_timedelta_to_seconds(w_df, 'Time')
            all_weather.append(w_df)

    except Exception as e:
        logging.error(f"  Race data missing/failed for Round {round_num}: {e}")


# ==============================================================================
# SECTION 4: DATA AGGREGATION & EXPORT TO CLEAN CSVs
# ==============================================================================
logging.info("--- Exporting Aggregated Datasets to CSV ---")

exports = [
    ("qualifying_results.csv", all_qualifying_results),
    ("complete_race_results.csv", all_race_results),
    ("driver_points_per_round.csv", all_driver_points),
    ("lap_by_lap_data.csv", all_laps),
    ("tyre_strategy.csv", all_tyre_strategies),
    ("pit_stop_summary.csv", all_pit_stops),
    ("fastest_laps.csv", all_fastest_laps),
    ("weather_data.csv", all_weather)
]

for filename, dataset_list in exports:
    if dataset_list:
        combined_df = pd.concat(dataset_list, ignore_index=True)
        combined_df.to_csv(DATA_FOLDER / filename, index=False)
        logging.info(f"Successfully saved {filename} ({len(combined_df)} rows)")
    else:
        logging.warning(f"No data captured for {filename}")

logging.info("==================================================")
logging.info("--- ETL PIPELINE COMPLETED SUCCESSFULLY ---")
logging.info("==================================================")