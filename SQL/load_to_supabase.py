"""
Loads every CSV in data/ into a Supabase (Postgres) database, one table per file.
Table name = CSV filename without extension (e.g. complete_race_results.csv -> complete_race_results).

Runs after the CSV pipeline as part of the weekly GitHub Action, so the database
always mirrors the latest data/ folder. Uses if_exists='replace' — simplest and
safest approach for a small personal project (no need to hand-manage migrations).

Requires the DATABASE_URL environment variable, e.g.:
postgresql+psycopg2://postgres:<password>@<host>:5432/postgres

Get this connection string from your Supabase project:
Project Settings -> Database -> Connection string -> URI
(swap postgresql:// for postgresql+psycopg2:// so SQLAlchemy uses the right driver)
"""

import logging
import os
import sys
from pathlib import Path

import pandas as pd
from sqlalchemy import create_engine

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler()]
)

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_FOLDER = BASE_DIR / "data"

DATABASE_URL = os.environ.get("DATABASE_URL")

if not DATABASE_URL:
    logging.error("DATABASE_URL environment variable is not set. Aborting.")
    sys.exit(1)

logging.info("Connecting to Supabase Postgres database...")
engine = create_engine(DATABASE_URL)

csv_files = sorted(DATA_FOLDER.glob("*.csv"))

if not csv_files:
    logging.warning(f"No CSV files found in {DATA_FOLDER}. Nothing to load.")
    sys.exit(0)

for csv_path in csv_files:
    table_name = csv_path.stem  # filename without .csv extension

    try:
        df = pd.read_csv(csv_path)
        if df.empty:
            logging.warning(f"{csv_path.name} is empty — skipping.")
            continue

        df.to_sql(table_name, engine, if_exists="replace", index=False)
        logging.info(f"Loaded {csv_path.name} -> table '{table_name}' ({len(df)} rows)")
    except Exception as e:
        logging.error(f"Failed to load {csv_path.name} into table '{table_name}': {e}")

logging.info("Supabase load complete.")
