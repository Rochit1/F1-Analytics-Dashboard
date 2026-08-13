"""
OpenF1 enrichment for F1-Analytics-Dashboard.

IMPORTANT:
This script deliberately reproduces the COLUMN NAMES and general data
semantics of the existing FastF1-generated CSVs used by the Power BI model.

It replaces only the source of the five failing datasets:
    lap_by_lap_data.csv
    tyre_strategy.csv
    pit_stop_summary.csv
    fastest_laps.csv
    weather_data.csv

The existing seven core CSVs from f1_pipeline.py are untouched.

Source:
    OpenF1 historical API (2023+)
"""

from __future__ import annotations

import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import requests


YEAR = int(os.getenv("F1_YEAR", "2026"))
BASE_URL = "https://api.openf1.org/v1"
DATA_DIR = Path(__file__).resolve().parents[1] / "data"
REQUEST_DELAY = 2.1

session = requests.Session()
session.headers.update({
    "User-Agent": "F1-Analytics-Dashboard/1.0",
    "Accept": "application/json",
})


def api_get(endpoint: str, params: dict[str, Any]) -> list[dict[str, Any]]:
    """GET an OpenF1 endpoint with retries and rate-limit handling.

    Permanent 404/other 4xx errors are not retried.
    """
    url = f"{BASE_URL}/{endpoint}"

    for attempt in range(3):
        try:
            r = session.get(url, params=params, timeout=60)

            if r.status_code == 404:
                print(f"NO DATA (404) {endpoint} {params}")
                return []

            if r.status_code == 429:
                retry_after = int(r.headers.get("Retry-After", "10"))
                print(f"Rate limited; waiting {retry_after}s")
                time.sleep(retry_after)
                continue

            r.raise_for_status()
            data = r.json()

            if not isinstance(data, list):
                raise ValueError(f"Unexpected response from {endpoint}")

            time.sleep(REQUEST_DELAY)
            return data

        except requests.HTTPError as exc:
            status = exc.response.status_code if exc.response is not None else None
            if status is not None and 400 <= status < 500 and status != 429:
                print(f"FAILED {endpoint} {params}: HTTP {status}")
                return []

            if attempt == 2:
                print(f"FAILED {endpoint} {params}: {exc}")
                return []

            wait = 5 * (attempt + 1)
            print(f"Retrying {endpoint} in {wait}s: {exc}")
            time.sleep(wait)

        except Exception as exc:
            if attempt == 2:
                print(f"FAILED {endpoint} {params}: {exc}")
                return []

            wait = 5 * (attempt + 1)
            print(f"Retrying {endpoint} in {wait}s: {exc}")
            time.sleep(wait)

    return []


def elapsed_timedelta(iso_value: Any, session_start: datetime | None):
    """Convert an OpenF1 UTC timestamp to FastF1-like session timedelta."""
    if not iso_value or session_start is None:
        return pd.NaT

    try:
        dt = pd.to_datetime(iso_value, utc=True).to_pydatetime()
        return pd.Timedelta(seconds=(dt - session_start).total_seconds())
    except Exception:
        return pd.NaT


def timedel(seconds: Any):
    """Convert seconds to a pandas Timedelta, matching FastF1 CSV output."""
    if pd.isna(seconds):
        return pd.NaT
    try:
        return pd.to_timedelta(float(seconds), unit="s")
    except Exception:
        return pd.NaT


def get_races() -> pd.DataFrame:
    rows = api_get("sessions", {"year": YEAR})

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows)

    # OpenF1 lists future race sessions too. Only keep races whose
    # session has actually ended.
    now_utc = pd.Timestamp.now(tz="UTC")
    df["date_end"] = pd.to_datetime(df["date_end"], utc=True, errors="coerce")

    races = df[
        (df["session_name"].astype(str).str.lower() == "race")
        & df["date_end"].notna()
        & (df["date_end"] <= now_utc)
    ].copy()

    if "is_cancelled" in races:
        races = races[races["is_cancelled"] != True]  # noqa: E712

    races = races.sort_values("date_start").reset_index(drop=True)
    races["Round"] = range(1, len(races) + 1)

    # meeting_name comes from /meetings, not reliably from /sessions.
    meetings = api_get("meetings", {"year": YEAR})

    if meetings:
        meetings_df = pd.DataFrame(meetings)
        if "meeting_key" in meetings_df.columns and "meeting_name" in meetings_df.columns:
            meeting_names = meetings_df.set_index("meeting_key")["meeting_name"].to_dict()
            races["EventName"] = races["meeting_key"].map(meeting_names)
        else:
            races["EventName"] = "Round " + races["Round"].astype(str)
    else:
        races["EventName"] = "Round " + races["Round"].astype(str)

    races["EventName"] = races["EventName"].fillna(
        "Round " + races["Round"].astype(str)
    )

    return races


def driver_map(session_key: int) -> dict[int, str]:
    """OpenF1 driver number -> three-letter acronym."""
    rows = api_get("drivers", {"session_key": session_key})
    result = {}

    for row in rows:
        number = row.get("driver_number")
        acronym = row.get("name_acronym")
        if number is not None and acronym:
            result[int(number)] = str(acronym)

    return result


def stint_lookup(stints: pd.DataFrame, driver_number: int, lap_number: int):
    """Return the OpenF1 stint covering a particular driver/lap."""
    if stints.empty:
        return None

    x = stints[
        (stints["driver_number"] == driver_number)
        & (stints["lap_start"] <= lap_number)
        & (stints["lap_end"] >= lap_number)
    ]

    if x.empty:
        return None

    return x.iloc[0]


def main():
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    races = get_races()

    if races.empty:
        raise RuntimeError("No completed race sessions returned by OpenF1.")

    print(f"Found {len(races)} completed races for {YEAR}")

    laps_out = []
    tyres_out = []
    pits_out = []
    fastest_out = []
    weather_out = []

    for _, race in races.iterrows():
        round_no = int(race["Round"])
        event = str(race["EventName"])
        session_key = int(race["session_key"])

        session_start = pd.to_datetime(
            race["date_start"], utc=True
        ).to_pydatetime()

        print(f"\nRound {round_no}: {event}")

        # ------------------------------------------------------------
        # DRIVER MAP
        # ------------------------------------------------------------
        drivers = driver_map(session_key)

        # ------------------------------------------------------------
        # STINTS / TYRES
        # ------------------------------------------------------------
        stint_rows = api_get("stints", {"session_key": session_key})
        stints = pd.DataFrame(stint_rows)

        if not stints.empty:
            tyre = pd.DataFrame({
                "Round": round_no,
                "EventName": event,
                "Driver": stints["driver_number"].map(drivers),
                "Stint": stints["stint_number"].astype(float),
                "Compound": stints["compound"],
                "StintStartLap": stints["lap_start"].astype(float),
                "StintEndLap": stints["lap_end"].astype(float),
            })

            tyre["TotalLapsOnStint"] = (
                tyre["StintEndLap"] - tyre["StintStartLap"] + 1
            ).astype(int)

            tyre = tyre[
                [
                    "Round",
                    "EventName",
                    "Driver",
                    "Stint",
                    "Compound",
                    "StintStartLap",
                    "StintEndLap",
                    "TotalLapsOnStint",
                ]
            ]

            tyres_out.append(tyre)

            print(f"  tyre_strategy: {len(tyre)}")

        # ------------------------------------------------------------
        # LAPS
        # ------------------------------------------------------------
        lap_rows = api_get("laps", {"session_key": session_key})
        laps = pd.DataFrame(lap_rows)

        if not laps.empty:
            records = []

            for _, lap in laps.iterrows():
                num = int(lap["driver_number"])
                lap_no = float(lap["lap_number"])

                stint = stint_lookup(
                    stints,
                    num,
                    int(lap_no),
                )

                compound = (
                    stint["compound"]
                    if stint is not None
                    else None
                )

                stint_no = (
                    float(stint["stint_number"])
                    if stint is not None
                    else float("nan")
                )

                tyre_age = (
                    float(stint["tyre_age_at_start"])
                    + (lap_no - float(stint["lap_start"]))
                    if stint is not None
                    and pd.notna(stint.get("tyre_age_at_start"))
                    else float("nan")
                )

                # OpenF1 exposes the lap start timestamp. FastF1's
                # PitOutTime/PitInTime are populated separately below.
                records.append({
                    "Driver": drivers.get(num),
                    "DriverNumber": num,
                    "LapNumber": lap_no,
                    "LapTime": timedel(lap.get("lap_duration")),
                    "Stint": stint_no,
                    "Compound": compound,
                    "TyreLife": tyre_age,
                    "FreshTyre": (
                        True
                        if stint is not None
                        and float(stint.get("tyre_age_at_start", 0) or 0) == 0
                        else False
                    ),
                    "Sector1Time": timedel(lap.get("duration_sector_1")),
                    "Sector2Time": timedel(lap.get("duration_sector_2")),
                    "Sector3Time": timedel(lap.get("duration_sector_3")),
                    "IsAccurate": (
                        pd.notna(lap.get("lap_duration"))
                        and pd.notna(lap.get("duration_sector_1"))
                        and pd.notna(lap.get("duration_sector_2"))
                        and pd.notna(lap.get("duration_sector_3"))
                    ),
                    "PitOutTime": pd.NaT,
                    "PitInTime": pd.NaT,
                    "Round": round_no,
                    "EventName": event,
                    "LapTime_Seconds": lap.get("lap_duration"),
                    "Sector1Time_Seconds": lap.get("duration_sector_1"),
                    "Sector2Time_Seconds": lap.get("duration_sector_2"),
                    "Sector3Time_Seconds": lap.get("duration_sector_3"),
                })

            lap_df = pd.DataFrame(records)

            # --------------------------------------------------------
            # PIT TIMES INTO THE SAME LAP SCHEMA AS THE OLD CSV
            # --------------------------------------------------------
            pit_rows = api_get("pit", {"session_key": session_key})
            pits = pd.DataFrame(pit_rows)

            if not pits.empty:
                pits["driver_number"] = pits["driver_number"].astype(int)
                pits["lap_number"] = pits["lap_number"].astype(int)

                for _, pit in pits.iterrows():
                    d = int(pit["driver_number"])
                    lap_no = int(pit["lap_number"])

                    # FastF1's existing file stores pit-in on the
                    # preceding lap and pit-out on the following lap.
                    in_time = elapsed_timedelta(
                        pit.get("date"), session_start
                    )

                    lane_duration = pit.get("lane_duration")
                    out_time = (
                        in_time + pd.to_timedelta(
                            float(lane_duration), unit="s"
                        )
                        if pd.notna(in_time) and pd.notna(lane_duration)
                        else pd.NaT
                    )

                    mask_in = (
                        (lap_df["DriverNumber"] == d)
                        & (lap_df["LapNumber"] == float(lap_no))
                    )
                    mask_out = (
                        (lap_df["DriverNumber"] == d)
                        & (lap_df["LapNumber"] == float(lap_no + 1))
                    )

                    lap_df.loc[mask_in, "PitInTime"] = in_time
                    lap_df.loc[mask_out, "PitOutTime"] = out_time

            laps_out.append(lap_df)

            print(f"  lap_by_lap_data: {len(lap_df)}")

            # --------------------------------------------------------
            # FASTEST LAP — SAME 6-COLUMN STRUCTURE
            # --------------------------------------------------------
            valid = lap_df.dropna(subset=["LapTime_Seconds"]).copy()

            if not valid.empty:
                idx = valid.groupby("Driver")["LapTime_Seconds"].idxmin()
                fastest = valid.loc[
                    idx,
                    [
                        "Round",
                        "EventName",
                        "Driver",
                        "LapNumber",
                        "Compound",
                        "LapTime_Seconds",
                    ],
                ].copy()

                fastest_out.append(fastest)

                print(f"  fastest_laps: {len(fastest)}")

        # ------------------------------------------------------------
        # PIT STOP SUMMARY — SAME 8-COLUMN STRUCTURE
        # ------------------------------------------------------------
        if "pits" not in locals() or pits.empty:
            pits_rows = api_get("pit", {"session_key": session_key})
            pits = pd.DataFrame(pits_rows)

        if not pits.empty:
            pit_records = []

            for _, pit in pits.iterrows():
                num = int(pit["driver_number"])
                lap_no = float(pit["lap_number"])

                stint = stint_lookup(
                    stints,
                    num,
                    int(lap_no),
                )

                pit_records.append({
                    "Round": round_no,
                    "EventName": event,
                    "Driver": drivers.get(num),
                    "LapNumber": lap_no,
                    "Stint": (
                        float(stint["stint_number"])
                        if stint is not None
                        else float("nan")
                    ),
                    "Compound": (
                        stint["compound"]
                        if stint is not None
                        else None
                    ),
                    "PitInTime": elapsed_timedelta(
                        pit.get("date"), session_start
                    ),
                    "PitOutTime": (
                        elapsed_timedelta(
                            pit.get("date"), session_start
                        )
                        + pd.to_timedelta(
                            float(pit["lane_duration"]), unit="s"
                        )
                        if pd.notna(
                            elapsed_timedelta(
                                pit.get("date"), session_start
                            )
                        )
                        and pd.notna(pit.get("lane_duration"))
                        else pd.NaT
                    ),
                })

            pit_df = pd.DataFrame(pit_records)[
                [
                    "Round",
                    "EventName",
                    "Driver",
                    "LapNumber",
                    "Stint",
                    "Compound",
                    "PitInTime",
                    "PitOutTime",
                ]
            ]

            pits_out.append(pit_df)
            print(f"  pit_stop_summary: {len(pit_df)}")

        # ------------------------------------------------------------
        # WEATHER — SAME 11-COLUMN STRUCTURE
        # ------------------------------------------------------------
        weather_rows = api_get(
            "weather",
            {"session_key": session_key},
        )

        if weather_rows:
            w = pd.DataFrame(weather_rows)

            weather = pd.DataFrame({
                "Time": [
                    elapsed_timedelta(x, session_start)
                    for x in w["date"]
                ],
                "AirTemp": w["air_temperature"].astype(float),
                "Humidity": w["humidity"].astype(float),
                "Pressure": w["pressure"].astype(float),
                "Rainfall": w["rainfall"].astype(bool),
                "TrackTemp": w["track_temperature"].astype(float),
                "WindDirection": w["wind_direction"].astype(int),
                "WindSpeed": w["wind_speed"].astype(float),
                "Round": round_no,
                "EventName": event,
            })

            weather["Time_Seconds"] = (
                weather["Time"].dt.total_seconds()
            )

            weather = weather[
                [
                    "Time",
                    "AirTemp",
                    "Humidity",
                    "Pressure",
                    "Rainfall",
                    "TrackTemp",
                    "WindDirection",
                    "WindSpeed",
                    "Round",
                    "EventName",
                    "Time_Seconds",
                ]
            ]

            weather_out.append(weather)
            print(f"  weather_data: {len(weather)}")


    # ------------------------------------------------------------
    # EXPORT — EXACT EXISTING FILENAMES
    # ------------------------------------------------------------
    def export(frames, filename, columns):
        if not frames:
            print(f"WARNING: no data for {filename}; existing file preserved.")
            return

        df = pd.concat(frames, ignore_index=True)

        # Force exact column order.
        df = df.reindex(columns=columns)

        # Do not let pandas add an index.
        df.to_csv(DATA_DIR / filename, index=False)

        print(f"Saved {filename}: {len(df)} rows")

    export(
        laps_out,
        "lap_by_lap_data.csv",
        [
            "Driver", "DriverNumber", "LapNumber", "LapTime", "Stint",
            "Compound", "TyreLife", "FreshTyre", "Sector1Time",
            "Sector2Time", "Sector3Time", "IsAccurate", "PitOutTime",
            "PitInTime", "Round", "EventName", "LapTime_Seconds",
            "Sector1Time_Seconds", "Sector2Time_Seconds",
            "Sector3Time_Seconds",
        ],
    )

    export(
        tyres_out,
        "tyre_strategy.csv",
        [
            "Round", "EventName", "Driver", "Stint", "Compound",
            "StintStartLap", "StintEndLap", "TotalLapsOnStint",
        ],
    )

    export(
        pits_out,
        "pit_stop_summary.csv",
        [
            "Round", "EventName", "Driver", "LapNumber", "Stint",
            "Compound", "PitInTime", "PitOutTime",
        ],
    )

    export(
        fastest_out,
        "fastest_laps.csv",
        [
            "Round", "EventName", "Driver", "LapNumber", "Compound",
            "LapTime_Seconds",
        ],
    )

    export(
        weather_out,
        "weather_data.csv",
        [
            "Time", "AirTemp", "Humidity", "Pressure", "Rainfall",
            "TrackTemp", "WindDirection", "WindSpeed", "Round",
            "EventName", "Time_Seconds",
        ],
    )

    print("\nOpenF1 enrichment finished.")
    print("Existing Power BI-facing filenames and column schemas were preserved.")


if __name__ == "__main__":
    main()
