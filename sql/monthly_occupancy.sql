-- Output grain: one community per reporting month.
-- Formula: month-end active residents / valid inventory units * 100.
-- Assumption: one active resident represents one occupied unit; therefore this
-- is a provisional occupancy proxy, not confirmed occupied-unit occupancy.

SELECT
    occupancy.community_id,
    community.community_name,
    occupancy.month_start,
    occupancy.month_end,
    occupancy.occupied_resident_count,
    occupancy.valid_unit_count,
    round(
        100.0 * occupancy.occupied_resident_count
        / nullif(occupancy.valid_unit_count, 0),
        2
    ) AS occupancy_proxy_percent
FROM gold.fact_occupancy_monthly AS occupancy
INNER JOIN gold.dim_community AS community
    ON occupancy.community_id = community.community_id
ORDER BY
    occupancy.month_start,
    occupancy.community_id;