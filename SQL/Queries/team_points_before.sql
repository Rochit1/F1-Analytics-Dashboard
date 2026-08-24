WITH team_race_points AS (
    SELECT
        "TeamName",
        "Round",
        SUM("Points") AS race_team_points
    FROM complete_race_results
    GROUP BY "TeamName", "Round"
)

SELECT
    "TeamName",
    "Round",
    race_team_points,

    SUM(race_team_points) OVER (
        PARTITION BY "TeamName"
        ORDER BY "Round"
        ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING
    ) AS team_points_before

FROM team_race_points

ORDER BY "TeamName", "Round";