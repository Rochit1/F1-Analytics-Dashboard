-- ============================================================================
-- Qualifying vs Race: Who Gains, Who Loses Places
-- ============================================================================
-- Joins qualifying results to race results per driver/round to compute how
-- many places each driver gained or lost between grid and finish. Positive
-- numbers = overtook their way up; negative = lost ground.
--
-- Technique: JOIN across two tables on driver + round, simple arithmetic.
-- ============================================================================

SELECT
    r."Round"                                  AS round,
    r."EventName"                              AS event,
    r."Abbreviation"                           AS driver,
    r."TeamName"                               AS team,
    q."Position"                               AS grid_position,
    r."Position"                               AS finish_position,
    (q."Position" - r."Position")              AS places_gained
FROM complete_race_results r
JOIN qualifying_results q
    ON r."Abbreviation" = q."Abbreviation"
   AND r."Round" = q."Round"
WHERE r."Position" IS NOT NULL
  AND q."Position" IS NOT NULL
ORDER BY places_gained DESC;