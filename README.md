# F1 Analytics Dashboard (2026 Season)

Automated F1 data pipeline (FastF1 + Ergast API) feeding a Power BI dashboard,
kept up to date via GitHub Actions on a weekly schedule.

## Architecture

```
FastF1 / Ergast API
      ↓
python/f1_pipeline.py
      ↓
data/*.csv
      ↓
GitHub Actions (every Monday, or manual trigger)
      ↓
Commit updated CSVs back to this repo
      ↓
Power BI reads the GitHub raw CSV URLs
```

## Repo layout

```
F1-Analytics-Dashboard/
├── data/                       # generated CSVs (committed by the workflow)
├── python/
│   └── f1_pipeline.py          # the ETL pipeline
├── .github/workflows/
│   └── update_f1.yml           # scheduled + manual automation
├── requirements.txt
└── README.md
```

## One-time setup

1. **Push this folder to a new GitHub repo** (public, so Power BI can read raw CSV
   URLs without auth — see Power BI section below).
2. **Enable workflow write access**: repo → Settings → Actions → General →
   "Workflow permissions" → select **Read and write permissions** → Save.
   Without this, the workflow can run the pipeline but will fail to push the
   commit.
3. Nothing else to configure — no secrets/API keys are needed since FastF1/Ergast
   are public APIs.

## Testing the GitHub Action manually

1. Push the repo to GitHub.
2. Go to the **Actions** tab → select **Update F1 Data** in the left sidebar.
3. Click **Run workflow** (this is the `workflow_dispatch` trigger) → **Run workflow**.
4. Watch the run: expand "Run F1 data pipeline" to see the same log output you'd
   see locally. Expand "Commit and push updated CSVs" to confirm it committed
   (or correctly reported "No data changes to commit" if nothing changed).
5. Check the `data/` folder in the repo — file timestamps/commit history should
   reflect the run.

If it fails on the commit step with a permissions error, revisit step 2 above.

## Switching Power BI from local CSVs to GitHub

Your raw CSV URL format is:

```
https://raw.githubusercontent.com/<username>/<repo>/<branch>/data/<file>.csv
```

e.g. `https://raw.githubusercontent.com/yourname/F1-Analytics-Dashboard/main/data/complete_race_results.csv`

**Test with one CSV first:**

1. Open your existing `.pbix` file.
2. Home → Transform Data (opens Power Query Editor).
3. Select the query for one table (e.g. `complete_race_results`).
4. In the **Applied Steps** pane (right side), click the gear icon next to the
   first step (usually `Source`).
5. Change the source type from *File* to **Web**, and paste the raw GitHub URL.
6. Click OK. Power Query will re-parse the CSV from the web — your existing
   steps below `Source` (renames, type changes, merges) should re-apply
   automatically since the column structure is unchanged.
7. Click **Close & Apply** and confirm the visuals on that page still render
   correctly with the same data.

**Once confirmed working, repeat the same "edit Source step" process for the
remaining queries** (`qualifying_results`, `driver_points_per_round`,
`constructor_standings_current`, plus any of the newer files you want to bring
in later like `lap_by_lap_data`). You are only ever touching the `Source` step
— all downstream transforms, DAX measures, relationships, visuals, slicers,
and formatting stay exactly as they are.

**Refreshing later:** Home → Refresh in Power BI Desktop will re-pull the
latest raw CSVs from GitHub. If you publish to the Power BI Service, you can
set a scheduled refresh there too (Settings → Scheduled refresh) — no
credentials needed since the source is a public unauthenticated URL.

## End-to-end checklist

- [ ] Repo pushed to GitHub (public)
- [ ] Workflow permissions set to "Read and write" (Settings → Actions → General)
- [ ] Manually triggered the workflow once via Actions tab → confirmed it ran green
- [ ] Confirmed CSVs in `data/` were updated/committed by the bot
- [ ] Opened one raw CSV URL in a browser to confirm it loads as plain CSV text
- [ ] Repointed one Power BI query's Source step to that raw URL — data refreshes correctly, visuals unchanged
- [ ] Repointed remaining Power BI queries the same way
- [ ] Full dashboard refresh in Power BI Desktop pulls current GitHub data with no errors
- [ ] (Optional) Scheduled refresh configured if published to Power BI Service
- [ ] Waited for/confirmed a real Monday scheduled run (or just trust the manual test — cron will fire the same code path)
