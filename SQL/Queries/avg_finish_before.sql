SELECT
    "Abbreviation" AS driver,
    "Round" AS round,
    "Position" AS finish_position,

    AVG("Position") OVER (
        PARTITION BY "Abbreviation"
        ORDER BY "Round"
        ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING
    ) AS avg_finish_before

FROM complete_race_results

ORDER BY
    "Abbreviation",
    "Round";