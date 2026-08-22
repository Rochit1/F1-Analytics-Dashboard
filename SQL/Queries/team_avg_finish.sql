WITH team_race_finish AS (
    SELECT
        "TeamName",
        "Round",
        AVG("Position") AS team_avg_finish
    FROM complete_race_results
    GROUP BY "TeamName", "Round"
)

SELECT
    "TeamName",
    "Round",
    team_avg_finish,

    AVG(team_avg_finish) OVER (
        PARTITION BY "TeamName"
        ORDER BY "Round"
        ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING
    ) AS team_avg_finish_before

FROM team_race_finish

ORDER BY "TeamName", "Round";