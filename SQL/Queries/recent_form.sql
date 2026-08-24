SELECT
    "Abbreviation" AS driver,
    "Round" AS round,
    "Position" AS finish_position,

    AVG("Position") OVER (
        PARTITION BY "Abbreviation"
        ORDER BY "Round"
        ROWS BETWEEN 3 PRECEDING AND 1 PRECEDING
    ) AS recent_form

FROM complete_race_results

ORDER BY "Abbreviation", "Round";