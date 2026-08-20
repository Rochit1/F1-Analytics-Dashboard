-- ============================================================================
-- Championship Race: Cumulative Points After Each Round
-- ============================================================================
-- Recreates the "points progression over the season" that a single standings
-- snapshot can't show — this reveals when a driver actually took the lead,
-- not just where they ended up.
--
-- Technique: CTE to pre-aggregate points per driver/round, then a running-total
-- window function (SUM ... OVER) ordered by round.
-- ============================================================================

WITH points_per_round AS (
    SELECT
        "Round"          AS round,
        "Abbreviation"   AS driver,
        "TeamName"       AS team,
        SUM("Points")    AS round_points
    FROM driver_points_per_round
    GROUP BY "Round", "Abbreviation", "TeamName"
)
SELECT
    round,
    driver,
    team,
    round_points,
    SUM(round_points) OVER (
        PARTITION BY driver
        ORDER BY round
    ) AS cumulative_points
FROM points_per_round
ORDER BY driver, round;
