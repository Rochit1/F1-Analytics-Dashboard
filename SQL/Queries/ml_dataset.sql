CREATE OR REPLACE VIEW ml_dataset AS
-- our combined query
WITH base_race AS (
    SELECT
        "DriverNumber",
        "Abbreviation",
        "FullName",
        "TeamName",
        "Round",
        "EventName",
        "Position" AS finish_position,
        "GridPosition",
        "Points",
        "Status"
    FROM complete_race_results
),

driver_features AS (
    SELECT
        *,
        
        -- Previous race finishing position
        LAG(finish_position) OVER (
            PARTITION BY "DriverNumber"
            ORDER BY "Round"
        ) AS previous_finish,

        -- Average finish before current race
        AVG(finish_position) OVER (
            PARTITION BY "DriverNumber"
            ORDER BY "Round"
            ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING
        ) AS avg_finish_before,

        -- Average of previous 3 finishes
        AVG(finish_position) OVER (
            PARTITION BY "DriverNumber"
            ORDER BY "Round"
            ROWS BETWEEN 3 PRECEDING AND 1 PRECEDING
        ) AS recent_form,

        -- DNF rate before current race
        AVG(
            CASE
                WHEN "Status" != 'Finished' THEN 1.0
                ELSE 0.0
            END
        ) OVER (
            PARTITION BY "DriverNumber"
            ORDER BY "Round"
            ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING
        ) AS dnf_rate_before,

        -- Driver points before current race
        SUM("Points") OVER (
            PARTITION BY "DriverNumber"
            ORDER BY "Round"
            ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING
        ) AS points_before

    FROM base_race
),

team_race AS (
    SELECT
        "TeamName",
        "Round",
        SUM("Points") AS team_race_points,
        AVG(finish_position) AS team_race_avg_finish
    FROM driver_features
    GROUP BY "TeamName", "Round"
),

team_features AS (
    SELECT
        *,
        
        -- Team points before current race
        SUM(team_race_points) OVER (
            PARTITION BY "TeamName"
            ORDER BY "Round"
            ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING
        ) AS team_points_before,

        -- Team average finish before current race
        AVG(team_race_avg_finish) OVER (
            PARTITION BY "TeamName"
            ORDER BY "Round"
            ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING
        ) AS team_avg_finish_before

    FROM team_race
),

qualifying_data AS (
    SELECT
        "DriverNumber",
        "Abbreviation",
        "Round",
        "Position" AS qualifying_position
    FROM qualifying_results
)

SELECT
    r."Round" AS round,
    r."EventName" AS event,
    r."DriverNumber" AS driver_number,
    r."Abbreviation" AS driver,
    r."FullName" AS driver_name,
    r."TeamName" AS team,

    -- ML target
    r.finish_position,

    -- Race / qualifying information
    COALESCE(q.qualifying_position, r."GridPosition")
        AS qualifying_position,

    r."GridPosition" AS grid_position,

    -- Driver historical features
    r.previous_finish,
    r.avg_finish_before,
    r.recent_form,
    r.dnf_rate_before,
    r.points_before,

    -- Team historical features
    t.team_points_before,
    t.team_avg_finish_before

FROM driver_features r

LEFT JOIN team_features t
    ON r."TeamName" = t."TeamName"
    AND r."Round" = t."Round"

LEFT JOIN qualifying_data q
    ON r."DriverNumber" = q."DriverNumber"
    AND r."Abbreviation" = q."Abbreviation"
    AND r."Round" = q."Round"

ORDER BY
    r."Round",
    r.finish_position;