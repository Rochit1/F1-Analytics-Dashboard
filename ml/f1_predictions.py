import os
import sys
from pathlib import Path

import pandas as pd
import numpy as np
from sqlalchemy import create_engine
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.ensemble import GradientBoostingRegressor

# =========================
# DATA SOURCE: SUPABASE (POSTGRES)
# =========================
# Reads the same tables that sql/load_to_supabase.py populates every Monday,
# instead of local CSVs. Uses the same DATABASE_URL / SUPABASE_DB_URL secret
# already configured for the rest of the project.
#
# To run this locally, set the env var first, e.g. (PowerShell):
#   $env:DATABASE_URL = "postgresql+psycopg2://postgres:<password>@<host>:5432/postgres"
# or (bash):
#   export DATABASE_URL="postgresql+psycopg2://postgres:<password>@<host>:5432/postgres"

BASE_DIR = Path(__file__).resolve().parent.parent
OUTPUT_FOLDER = BASE_DIR / "ml" / "outputs"
OUTPUT_FOLDER.mkdir(parents=True, exist_ok=True)

DATABASE_URL = os.environ.get("DATABASE_URL")

if not DATABASE_URL:
    print("ERROR: DATABASE_URL environment variable is not set. Aborting.")
    sys.exit(1)

engine = create_engine(DATABASE_URL)

race = pd.read_sql("SELECT * FROM complete_race_results", engine)
qualifying = pd.read_sql("SELECT * FROM qualifying_results", engine)
driver_points = pd.read_sql("SELECT * FROM driver_points_per_round", engine)
constructor = pd.read_sql("SELECT * FROM constructor_standings_current", engine)

#cleaning data
#missing values
print(race.isna().sum())
print(qualifying.isna().sum())
print(driver_points.isna().sum())
print(constructor.isna().sum())

#duplicate rows
print("Race Duplicates: ",race.duplicated().sum())
print("qualifying Duplicates: ",qualifying.duplicated().sum())
print("driver_points Duplicates: ",driver_points.duplicated().sum())
print("constructor Duplicates: ",constructor.duplicated().sum())

#data types
print(race.dtypes)
print(qualifying.dtypes)
print(driver_points.dtypes)
print(constructor.dtypes)

#inspecting columns
print("Race Columns")
print(race.columns.to_list())
print(race.head())

print("qualifying Columns")
print(qualifying.columns.to_list())
print(qualifying.head())

print("driver Columns")
print(driver_points.columns.to_list())
print(driver_points.head())

#checking unique driver codes and rounds
print("race drivers")
print(race["Abbreviation"].unique())
print("race rounds")
print(race["Round"].unique())

print("qualifying drivers")
print(qualifying["Abbreviation"].unique())
print("qualifying rounds")
print(qualifying["Round"].unique())

print("Driver drivers")
print(driver_points["Abbreviation"].unique())
print("Driver rounds")
print(driver_points["Round"].unique())

#race data clean
race_clean=race[
    ["Round","EventName","DriverNumber",
        "Abbreviation",
        "FullName",
        "TeamName",
        "Position",
        "GridPosition",
        "Points",
        "Status"]
].copy()

print(race_clean.head())
print(race_clean.shape)


#qualifying data clean
qualifying_clean = qualifying[
    [
        "Round",
        "DriverNumber",
        "Abbreviation",
        "Position"
    ]
].copy()

qualifying_clean = qualifying_clean.rename(
    columns={"Position": "QualifyingPosition"}
)

print("\nClean qualifying data:")
print(qualifying_clean.head())
print(qualifying_clean.shape)


#driver points data clean
driver_points_clean = driver_points[
    [
        "Round",
        "DriverNumber",
        "Abbreviation",
        "Points"
    ]
].copy()

driver_points_clean = driver_points_clean.rename(
    columns={"Points": "RacePoints"}
)

print("\nClean driver points:")
print(driver_points_clean.head())


#merge qualifying
ml_data = race_clean.merge(
    qualifying_clean,
    on=["Round", "DriverNumber", "Abbreviation"],
    how="left"
)

print("\nAfter qualifying merge:")
print(ml_data.head())
print(ml_data.shape)

#check merge
print("\nMissing qualifying positions:")
print(ml_data["QualifyingPosition"].isna().sum())


# =========================
# SORT CHRONOLOGICALLY
# =========================

ml_data = ml_data.sort_values(
    ["DriverNumber", "Round"]
).reset_index(drop=True)

ml_data["PreviousFinish"] = (
    ml_data.groupby("DriverNumber")["Position"]
    .shift(1)
)

ml_data["AvgFinishBefore"] = (
    ml_data.groupby("DriverNumber")["Position"]
    .transform(lambda x: x.shift(1).expanding().mean())
)

ml_data["RecentForm"] = (
    ml_data.groupby("DriverNumber")["Position"]
    .transform(lambda x: x.shift(1).rolling(3).mean())
)

ml_data["IsDNF"] = (
    ml_data["Status"] != "Finished"
).astype(int)

ml_data["DNFRateBefore"] = (
    ml_data.groupby("DriverNumber")["IsDNF"]
    .transform(lambda x: x.shift(1).expanding().mean())
)

ml_data["PointsBefore"] = (
    ml_data.groupby("DriverNumber")["Points"]
    .transform(lambda x: x.shift(1).cumsum())
)

print(
    ml_data[
        [
            "Round",
            "Abbreviation",
            "Position",
            "PreviousFinish",
            "AvgFinishBefore",
            "RecentForm",
            "DNFRateBefore",
            "PointsBefore"
        ]
    ].head(30)
)


# =========================
# TEAM HISTORICAL FEATURES
# =========================

# Create team-level points for each race
team_race_points = (
    ml_data.groupby(["TeamName", "Round"])["Points"]
    .sum()
    .reset_index()
)

# Sort chronologically
team_race_points = team_race_points.sort_values(
    ["TeamName", "Round"]
)

# Calculate cumulative team points BEFORE each race
team_race_points["TeamPointsBefore"] = (
    team_race_points.groupby("TeamName")["Points"]
    .transform(lambda x: x.shift(1).cumsum())
)

# Merge back into driver-level dataset
ml_data = ml_data.merge(
    team_race_points[
        ["TeamName", "Round", "TeamPointsBefore"]
    ],
    on=["TeamName", "Round"],
    how="left"
)


# =========================
# TEAM AVERAGE FINISH
# =========================

# Average finishing position of the team's drivers in each race
team_race_finish = (
    ml_data.groupby(["TeamName", "Round"])["Position"]
    .mean()
    .reset_index()
)

team_race_finish = team_race_finish.sort_values(
    ["TeamName", "Round"]
)

# Calculate team's historical average BEFORE each race
team_race_finish["TeamAvgFinishBefore"] = (
    team_race_finish.groupby("TeamName")["Position"]
    .transform(lambda x: x.shift(1).expanding().mean())
)

# Merge back
ml_data = ml_data.merge(
    team_race_finish[
        ["TeamName", "Round", "TeamAvgFinishBefore"]
    ],
    on=["TeamName", "Round"],
    how="left"
)

print(
    ml_data[
        [
            "Round",
            "Abbreviation",
            "TeamName",
            "Position",
            "PointsBefore",
            "AvgFinishBefore",
            "RecentForm",
            "DNFRateBefore",
            "TeamPointsBefore",
            "TeamAvgFinishBefore"
        ]
    ].head(30)
)

print("\nMissing values:")
print(
    ml_data[
        [
            "QualifyingPosition",
            "PreviousFinish",
            "AvgFinishBefore",
            "RecentForm",
            "DNFRateBefore",
            "PointsBefore",
            "TeamPointsBefore",
            "TeamAvgFinishBefore"
        ]
    ].isna().sum()
)

print("\nTotal rows:", len(ml_data))

print("\nRows with missing historical features:")
print(
    ml_data[
        [
            "PreviousFinish",
            "AvgFinishBefore",
            "RecentForm",
            "DNFRateBefore",
            "PointsBefore",
            "TeamPointsBefore",
            "TeamAvgFinishBefore"
        ]
    ].isna().sum(axis=1).value_counts()
)

print(
    ml_data[
        ml_data["RecentForm"].isna()
    ][
        ["Round", "Abbreviation", "RecentForm"]
    ].head(30)
)

# =========================
# REMOVE EARLY RACES
# =========================

ml_data = ml_data[
    ml_data["Round"] >= 4
].copy()

print("Rows after removing early races:", len(ml_data))


print(
    ml_data[
        [
            "QualifyingPosition",
            "PreviousFinish",
            "AvgFinishBefore",
            "RecentForm",
            "DNFRateBefore",
            "PointsBefore",
            "TeamPointsBefore",
            "TeamAvgFinishBefore"
        ]
    ].isna().sum()
)


print("\nFINAL FEATURES")

features = [
    "QualifyingPosition",
    "GridPosition",
    "PreviousFinish",
    "AvgFinishBefore",
    "RecentForm",
    "DNFRateBefore",
    "PointsBefore",
    "TeamPointsBefore",
    "TeamAvgFinishBefore"
]

print(ml_data[features].head(20))

print("\nMissing values:")
print(ml_data[features].isna().sum())
print(
    ml_data[
        ml_data["QualifyingPosition"].isna()
    ][
        [
            "Round",
            "EventName",
            "Abbreviation",
            "TeamName",
            "GridPosition",
            "Position",
            "Status"
        ]
    ]
)

ml_data["QualifyingPosition"] = (
    ml_data["QualifyingPosition"]
    .fillna(ml_data["GridPosition"])
)

# Impute the remaining historical/form features too — not just
# QualifyingPosition. Drivers new to the dataset (or early in their own
# history, even after the Round >= 4 cutoff above) can still have NaN in
# PreviousFinish/AvgFinishBefore/RecentForm/etc. because there's no prior
# race to compute those stats from yet.
#
# RandomForestRegressor (scikit-learn >= 1.4) silently tolerates NaN via its
# native missing-value support, which is why the earlier RandomForest
# sections in this script ran fine on this same data. GradientBoostingRegressor
# has never supported NaN and fails loudly instead — it isn't a new problem,
# just the first model honest about it. Impute here once, so every model
# downstream sees the same clean data instead of results differing by
# model based on which one happens to tolerate gaps.
historical_features = [
    "PreviousFinish",
    "AvgFinishBefore",
    "RecentForm",
    "DNFRateBefore",
    "PointsBefore",
    "TeamPointsBefore",
    "TeamAvgFinishBefore"
]

print("\nImputing remaining historical features with field-wide median:")
print(ml_data[historical_features].isna().sum())

for col in historical_features:
    ml_data[col] = ml_data[col].fillna(ml_data[col].median())

print("\nMissing values after imputation:")
print(ml_data[historical_features].isna().sum())

print(
    ml_data[
        [
            "QualifyingPosition",
            "GridPosition",
            "PreviousFinish",
            "AvgFinishBefore",
            "RecentForm",
            "DNFRateBefore",
            "PointsBefore",
            "TeamPointsBefore",
            "TeamAvgFinishBefore"
        ]
    ].isna().sum()
)


# =========================
# FINAL ML DATASET
# =========================

features = [
    "QualifyingPosition",
    "GridPosition",
    "PreviousFinish",
    "AvgFinishBefore",
    "RecentForm",
    "DNFRateBefore",
    "PointsBefore",
    "TeamPointsBefore",
    "TeamAvgFinishBefore"
]

X = ml_data[features]
y = ml_data["Position"]

print("X shape:", X.shape)
print("y shape:", y.shape)


# =========================
# DYNAMIC ROUND DETECTION
# =========================
# Instead of hardcoding round numbers, work out where the season actually is
# right now. This keeps the script correct as more races complete each week,
# instead of forever re-predicting whatever round was "next" the day this was
# written.

LAST_COMPLETED_ROUND = int(ml_data["Round"].max())
PREDICT_ROUND = LAST_COMPLETED_ROUND + 1

print(f"\nLast completed round in data: {LAST_COMPLETED_ROUND}")
print(f"Will generate predictions for round: {PREDICT_ROUND}")

# Holdout split for a quick sanity-check demo: train on everything except the
# most recently completed round, test on that round (whose real result we
# already know, so we can see how the model would have done).
HOLDOUT_TRAIN_CUTOFF = LAST_COMPLETED_ROUND - 1

# =========================
# CHRONOLOGICAL TRAIN/TEST SPLIT
# =========================

train_data = ml_data[ml_data["Round"] <= HOLDOUT_TRAIN_CUTOFF]
test_data = ml_data[ml_data["Round"] == LAST_COMPLETED_ROUND]

X_train = train_data[features]
y_train = train_data["Position"]

X_test = test_data[features]
y_test = test_data["Position"]

print("Training rows:", len(X_train))
print("Testing rows:", len(X_test))

# =========================
# RANDOM FOREST MODEL
# =========================

model = RandomForestRegressor(
    n_estimators=300,
    random_state=42,
    max_depth=8,
    min_samples_leaf=2
)
model.fit(X_train, y_train)
y_pred = model.predict(X_test)
print("\nPredictions:")
print(y_pred)

results = test_data[
    ["Round", "Abbreviation", "TeamName", "Position"]
].copy()

results["PredictedPosition"] = y_pred

print(results.to_string(index=False))

mae = mean_absolute_error(y_test, y_pred)
rmse = np.sqrt(mean_squared_error(y_test, y_pred))
r2 = r2_score(y_test, y_pred)

print("\nModel Performance")
print("MAE:", mae)
print("RMSE:", rmse)
print("R²:", r2)

# =========================
# WALK-FORWARD VALIDATION
# =========================

validation_results = []

# Validate on the last 4 completed rounds (or fewer if the season is early),
# instead of a hardcoded range that goes stale as more races happen.
VALIDATION_START_ROUND = max(ml_data["Round"].min() + 1, LAST_COMPLETED_ROUND - 3)

for test_round in range(VALIDATION_START_ROUND, LAST_COMPLETED_ROUND + 1):

    # Train only on races before the test race
    train_data = ml_data[ml_data["Round"] < test_round]
    test_data = ml_data[ml_data["Round"] == test_round]

    X_train = train_data[features]
    y_train = train_data["Position"]

    X_test = test_data[features]
    y_test = test_data["Position"]

    # Create a fresh model
    model = RandomForestRegressor(
        n_estimators=300,
        random_state=42,
        max_depth=8,
        min_samples_leaf=2
    )

    # Train
    model.fit(X_train, y_train)

    # Predict
    y_pred = model.predict(X_test)

    # Evaluate
    mae = mean_absolute_error(y_test, y_pred)
    rmse = np.sqrt(mean_squared_error(y_test, y_pred))
    r2 = r2_score(y_test, y_pred)

    validation_results.append({
        "Round": test_round,
        "MAE": mae,
        "RMSE": rmse,
        "R2": r2
    })


# Convert results to DataFrame
validation_results = pd.DataFrame(validation_results)

print("\nWALK-FORWARD VALIDATION")
print(validation_results.to_string(index=False))

print("\nAverage MAE:",
      validation_results["MAE"].mean())

print("Average RMSE:",
      validation_results["RMSE"].mean())

print("Average R²:",
      validation_results["R2"].mean())


# =========================
# FEATURE IMPORTANCE
# =========================

importance = pd.DataFrame({
    "Feature": features,
    "Importance": model.feature_importances_
}).sort_values(
    "Importance",
    ascending=False
)

print("\nFeature Importance:")
print(importance.to_string(index=False))

print("\nFeature Correlations:")

print(
    ml_data[features + ["Position"]]
    .corr()["Position"]
    .sort_values()
)

# =========================
# RANDOM FOREST TUNING
# =========================

configs = [
    {"n_estimators": 200, "max_depth": 5,  "min_samples_leaf": 2},
    {"n_estimators": 300, "max_depth": 6,  "min_samples_leaf": 2},
    {"n_estimators": 300, "max_depth": 8,  "min_samples_leaf": 2},
    {"n_estimators": 500, "max_depth": 8,  "min_samples_leaf": 2},
    {"n_estimators": 300, "max_depth": 10, "min_samples_leaf": 2},
    {"n_estimators": 300, "max_depth": 8,  "min_samples_leaf": 3},
    {"n_estimators": 500, "max_depth": 10, "min_samples_leaf": 3}
]

tuning_results = []

for config in configs:

    round_maes = []

    for test_round in range(VALIDATION_START_ROUND, LAST_COMPLETED_ROUND + 1):

        train_data = ml_data[
            ml_data["Round"] < test_round
        ]

        test_data = ml_data[
            ml_data["Round"] == test_round
        ]

        X_train = train_data[features]
        y_train = train_data["Position"]

        X_test = test_data[features]
        y_test = test_data["Position"]

        model = RandomForestRegressor(
            n_estimators=config["n_estimators"],
            max_depth=config["max_depth"],
            min_samples_leaf=config["min_samples_leaf"],
            random_state=42
        )

        model.fit(X_train, y_train)

        y_pred = model.predict(X_test)

        mae = mean_absolute_error(y_test, y_pred)

        round_maes.append(mae)

    tuning_results.append({
        **config,
        "Average_MAE": np.mean(round_maes)
    })


tuning_results = pd.DataFrame(tuning_results)

print("\nRANDOM FOREST TUNING RESULTS")
print(
    tuning_results.sort_values(
        "Average_MAE"
    ).to_string(index=False)
)

# =========================
# GRADIENT BOOSTING
# =========================

gb_results = []

for test_round in range(VALIDATION_START_ROUND, LAST_COMPLETED_ROUND + 1):

    train_data = ml_data[ml_data["Round"] < test_round]
    test_data = ml_data[ml_data["Round"] == test_round]

    X_train = train_data[features]
    y_train = train_data["Position"]

    X_test = test_data[features]
    y_test = test_data["Position"]

    model = GradientBoostingRegressor(
        n_estimators=200,
        learning_rate=0.05,
        max_depth=3,
        min_samples_leaf=3,
        random_state=42
    )

    model.fit(X_train, y_train)

    y_pred = model.predict(X_test)

    mae = mean_absolute_error(y_test, y_pred)
    rmse = np.sqrt(mean_squared_error(y_test, y_pred))
    r2 = r2_score(y_test, y_pred)

    gb_results.append({
        "Round": test_round,
        "MAE": mae,
        "RMSE": rmse,
        "R2": r2
    })


gb_results = pd.DataFrame(gb_results)

print("\nGRADIENT BOOSTING VALIDATION")
print(gb_results.to_string(index=False))

print("\nAverage MAE:",
      gb_results["MAE"].mean())

print("Average RMSE:",
      gb_results["RMSE"].mean())

print("Average R²:",
      gb_results["R2"].mean())

RandomForestRegressor(
    n_estimators=300,
    max_depth=8,
    min_samples_leaf=3,
    random_state=42
)

print("Latest completed round in data:", LAST_COMPLETED_ROUND)
print("Rounds available:", sorted(ml_data["Round"].unique()))
print("Generating predictions for round:", PREDICT_ROUND)

# =========================
# BUILD THE UPCOMING-ROUND FEATURE ROW
# =========================
# This is the genuinely tricky part: PREDICT_ROUND hasn't happened yet, so it
# has no row in ml_data (which only contains completed races). We build one
# driver row per current grid entry, using ONLY information that's actually
# known before the race:
#   - historical form features, computed from all rounds up to and including
#     LAST_COMPLETED_ROUND (no leakage from the race we're predicting)
#   - qualifying position for PREDICT_ROUND, IF it's already in the database
#     (qualifying usually happens just 1-2 days before the race, so on most
#     Monday runs it won't be available yet for the *next* race — in that
#     case we fall back to each driver's own recent average as an estimate)

driver_roster = (
    ml_data[ml_data["Round"] == LAST_COMPLETED_ROUND]
    [["DriverNumber", "Abbreviation", "FullName", "TeamName"]]
    .drop_duplicates()
    .copy()
)

upcoming = driver_roster.copy()

# Historical form features — built strictly from completed rounds only.
upcoming["PreviousFinish"] = (
    ml_data[ml_data["Round"] == LAST_COMPLETED_ROUND]
    .set_index("DriverNumber")["Position"]
    .reindex(upcoming["DriverNumber"])
    .values
)

upcoming["AvgFinishBefore"] = (
    ml_data.groupby("DriverNumber")["Position"]
    .mean()
    .reindex(upcoming["DriverNumber"])
    .values
)

recent_form = (
    ml_data.sort_values("Round")
    .groupby("DriverNumber")["Position"]
    .apply(lambda x: x.tail(3).mean())
)
upcoming["RecentForm"] = (
    recent_form.reindex(upcoming["DriverNumber"]).values
)

dnf_rate = ml_data.groupby("DriverNumber")["IsDNF"].mean()
upcoming["DNFRateBefore"] = (
    dnf_rate.reindex(upcoming["DriverNumber"]).values
)

points_before = ml_data.groupby("DriverNumber")["Points"].sum()
upcoming["PointsBefore"] = (
    points_before.reindex(upcoming["DriverNumber"]).values
)

team_points = ml_data.groupby("TeamName")["Points"].sum()
upcoming["TeamPointsBefore"] = upcoming["TeamName"].map(team_points)

team_avg_finish = ml_data.groupby("TeamName")["Position"].mean()
upcoming["TeamAvgFinishBefore"] = upcoming["TeamName"].map(team_avg_finish)

# Driver-level average qualifying position, used as the fallback estimate
# when real qualifying data for PREDICT_ROUND isn't available yet.
avg_quali_position = (
    qualifying.groupby("Abbreviation")["Position"].mean()
)

next_round_quali = qualifying[qualifying["Round"] == PREDICT_ROUND]

if not next_round_quali.empty:
    print(f"\nReal qualifying data found for round {PREDICT_ROUND} — using actual grid positions.")
    quali_map = next_round_quali.set_index("Abbreviation")["Position"]
    upcoming["QualifyingPosition"] = upcoming["Abbreviation"].map(quali_map)
    upcoming["QualifyingIsEstimated"] = False
else:
    print(
        f"\nNo qualifying data yet for round {PREDICT_ROUND} "
        "(quali usually happens a day or two before the race) — "
        "using each driver's season-average qualifying position as an estimate."
    )
    upcoming["QualifyingPosition"] = upcoming["Abbreviation"].map(avg_quali_position)
    upcoming["QualifyingIsEstimated"] = True

# GridPosition mirrors qualifying position in almost all cases (barring
# penalties, which aren't knowable in advance) — use the same value.
upcoming["GridPosition"] = upcoming["QualifyingPosition"]

# Fill any remaining gaps (e.g. a driver with no qualifying history at all)
# with the field-wide median for that feature, so the model always has a
# usable number rather than crashing on a NaN.
for col in features:
    if col not in upcoming.columns:
        continue
    upcoming[col] = upcoming[col].fillna(ml_data[col].median())

print(
    upcoming[
        [
            "Abbreviation",
            "TeamName",
            "QualifyingPosition",
            "QualifyingIsEstimated",
            "PreviousFinish",
            "AvgFinishBefore",
            "RecentForm",
            "DNFRateBefore",
            "PointsBefore",
            "TeamPointsBefore",
            "TeamAvgFinishBefore"
        ]
    ].to_string(index=False)
)

# =========================
# UPCOMING ROUND PREDICTION
# =========================
# Train on every completed round available — there's no held-out "test" here
# because PREDICT_ROUND hasn't happened, so there's nothing to score against.
# (The walk-forward validation above is what tells you how accurate this
# kind of prediction has been recently.)

X_train = ml_data[features]
y_train = ml_data["Position"]

final_model = RandomForestRegressor(
    n_estimators=300,
    max_depth=8,
    min_samples_leaf=3,
    random_state=42
)

final_model.fit(X_train, y_train)

predictions = final_model.predict(upcoming[features])

prediction_df = upcoming[
    ["Abbreviation", "FullName", "TeamName", "QualifyingIsEstimated"]
].copy()

prediction_df.insert(0, "Round", PREDICT_ROUND)
prediction_df["PredictedPosition"] = predictions

# Predicted ranking (1 = predicted winner)
prediction_df = prediction_df.sort_values(
    "PredictedPosition"
).reset_index(drop=True)

prediction_df["PredictedRank"] = prediction_df.index + 1

print(f"\nROUND {PREDICT_ROUND} PREDICTIONS (upcoming race — no result exists yet)")
print(
    prediction_df[
        [
            "Abbreviation",
            "TeamName",
            "PredictedPosition",
            "PredictedRank",
            "QualifyingIsEstimated"
        ]
    ].to_string(index=False)
)

prediction_df.to_csv(
    OUTPUT_FOLDER / "f1_prediction_results.csv",
    index=False
)

print(f"\nPrediction file saved to {OUTPUT_FOLDER / 'f1_prediction_results.csv'}")

feature_importance = pd.DataFrame({
    "Feature": features,
    "Importance": final_model.feature_importances_
})

feature_importance = feature_importance.sort_values(
    "Importance",
    ascending=False
)

feature_importance.to_csv(
    OUTPUT_FOLDER / "f1_feature_importance.csv",
    index=False
)

print(f"Feature importance file saved to {OUTPUT_FOLDER / 'f1_feature_importance.csv'}")