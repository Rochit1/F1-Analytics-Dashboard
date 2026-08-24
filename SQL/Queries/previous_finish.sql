SELECT
    "Abbreviation" AS driver,
    "Round" AS round,
    "Position" AS finish_position,

    LAG("Position") OVER (
        PARTITION BY "Abbreviation"
        ORDER BY "Round"
    ) AS previous_finish

FROM complete_race_results

ORDER BY
    "Abbreviation",
    "Round";