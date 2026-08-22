SELECT
    "Abbreviation" AS driver,
    "Round" AS round,
    "Points" AS race_points,

    SUM("Points") OVER (
        PARTITION BY "Abbreviation"
        ORDER BY "Round"
        ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING
    ) AS points_before

FROM complete_race_results

ORDER BY "Abbreviation", "Round";