-- ============================================================================
-- Constructor Momentum: Recent Form vs Season-Long Standing
-- ============================================================================
-- Compares each constructor's points from just the last 3 rounds against
-- their full-season standing position. A team currently 3rd overall but
-- scoring like a top-1 team recently is trending up — this catches that
-- before it shows up in the headline standings.
--
-- Technique: CTE for recent-form aggregation, joined back to the season
-- standings snapshot.
-- ============================================================================

WITH recent_form AS (
    SELECT
        "TeamName"     AS team,
        SUM("Points")  AS points_last_3_rounds
    FROM driver_points_per_round
    WHERE "Round" > (SELECT MAX("Round") - 3 FROM driver_points_per_round)
    GROUP BY "TeamName"
)
SELECT
    s."constructorName"          AS team,          -- NOTE: adjust column name if your
    s."position"                 AS season_position, --       Ergast export uses different casing
    s."points"                   AS season_points,
    rf.points_last_3_rounds
FROM constructor_standings_current s
LEFT JOIN recent_form rf
    ON s."constructorName" = rf.team
ORDER BY season_position;
