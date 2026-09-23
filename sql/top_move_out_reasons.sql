-- Output grain: one ranked move-out reason per community, up to three rows.
-- Formula: reason move-outs / all completed community move-outs * 100.
-- Tie behavior: larger counts rank first; equal counts sort alphabetically.

WITH completed_move_outs AS (
    SELECT
        community_id,
        move_out_reason
    FROM gold.fact_lease
    WHERE move_out_date IS NOT NULL
      AND move_out_date BETWEEN DATE '2025-01-01' AND DATE '2025-06-30'
),
reason_counts AS (
    SELECT
        community_id,
        move_out_reason,
        count(*) AS move_out_count
    FROM completed_move_outs
    GROUP BY
        community_id,
        move_out_reason
),
ranked_reasons AS (
    SELECT
        community_id,
        move_out_reason,
        move_out_count,
        sum(move_out_count) OVER (
            PARTITION BY community_id
        ) AS community_move_out_count,
        row_number() OVER (
            PARTITION BY community_id
            ORDER BY
                move_out_count DESC,
                move_out_reason ASC
        ) AS reason_rank
    FROM reason_counts
)
SELECT
    ranked.community_id,
    community.community_name,
    ranked.reason_rank,
    ranked.move_out_reason,
    ranked.move_out_count,
    ranked.community_move_out_count,
    round(
        100.0 * ranked.move_out_count
        / nullif(ranked.community_move_out_count, 0),
        2
    ) AS community_move_out_percent
FROM ranked_reasons AS ranked
INNER JOIN gold.dim_community AS community
    ON ranked.community_id = community.community_id
WHERE ranked.reason_rank <= 3
ORDER BY
    ranked.community_id,
    ranked.reason_rank;