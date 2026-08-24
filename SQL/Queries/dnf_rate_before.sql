SELECT
    "Abbreviation" AS driver,
    "Round" AS round,
    "Status" AS status,

    CASE
        WHEN "Status" != 'Finished' THEN 1
        ELSE 0
    END AS is_dnf,

    AVG(
        CASE
            WHEN "Status" != 'Finished' THEN 1.0
            ELSE 0.0
        END
    ) OVER (
        PARTITION BY "Abbreviation"
        ORDER BY "Round"
        ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING
    ) AS dnf_rate_before

FROM complete_race_results

ORDER BY
    "Abbreviation",
    "Round";