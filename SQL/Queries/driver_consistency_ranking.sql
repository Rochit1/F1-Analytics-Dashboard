-- ============================================================================
-- Driver Consistency Ranking
-- ============================================================================
-- Ranks drivers by how consistent their finishing position is (low standard
-- deviation = reliably around the same spot every race; high = boom-or-bust).
-- Two drivers can have the same average finish but wildly different
-- consistency — this surfaces that difference.
--
-- Technique: aggregate + STDDEV, then RANK() window function on top.
-- ============================================================================

WITH driver_stats AS (
    SELECT
        "Abbreviation"                       AS driver,
        "TeamName"                            AS team,
        COUNT(*)                              AS races_completed,
        ROUND(AVG("Position"::numeric), 2)    AS avg_finish,
        ROUND(STDDEV("Position"::numeric), 2) AS finish_stddev
    FROM complete_race_results
    WHERE "Position" IS NOT NULL
    GROUP BY "Abbreviation", "TeamName"
    HAVING COUNT(*) >= 5   -- exclude drivers with too few races for a meaningful stddev
)
SELECT
    driver,
    team,
    races_completed,
    avg_finish,
    finish_stddev,
    RANK() OVER (ORDER BY finish_stddev ASC) AS consistency_rank
FROM driver_stats
ORDER BY consistency_rank;
