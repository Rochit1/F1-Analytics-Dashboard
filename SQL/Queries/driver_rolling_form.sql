-- ============================================================================
-- Driver Form: 3-Race Rolling Average Finishing Position
-- ============================================================================
-- Shows how each driver's form is trending, not just their season total.
-- A driver averaging P4 all season looks identical to one who started P10
-- and is now running P1 — this surfaces the trend a season-total hides.
--
-- Technique: window function (AVG ... OVER) with a moving frame, partitioned
-- per driver and ordered by round.
-- ============================================================================

SELECT
    "Abbreviation"      AS driver,
    "TeamName"          AS team,
    "Round"             AS round,
    "EventName"         AS event,
    "Position"          AS finish_position,
    ROUND(
        AVG("Position"::numeric) OVER (
            PARTITION BY "Abbreviation"
            ORDER BY "Round"
            ROWS BETWEEN 2 PRECEDING AND CURRENT ROW
        ), 2
    ) AS rolling_3race_avg_position
FROM complete_race_results
WHERE "Position" IS NOT NULL
ORDER BY driver, round;