-- Output grain: one community and care-level combination.
-- Formula: valid incidents / resident-days * 100.
-- Admission and discharge dates both contribute a resident-day.

WITH resident_days AS (
    SELECT
        community_id,
        care_level,
        sum(resident_day_count) AS resident_days
    FROM gold.fact_resident_day
    GROUP BY
        community_id,
        care_level
),
incident_counts AS (
    SELECT
        community_id,
        care_level,
        count(*) AS incident_count
    FROM gold.fact_incident
    GROUP BY
        community_id,
        care_level
)
SELECT
    days.community_id,
    community.community_name,
    days.care_level,
    coalesce(incidents.incident_count, 0) AS incident_count,
    days.resident_days,
    round(
        100.0 * coalesce(incidents.incident_count, 0)
        / nullif(days.resident_days, 0),
        4
    ) AS incidents_per_100_resident_days
FROM resident_days AS days
LEFT JOIN incident_counts AS incidents
    ON days.community_id = incidents.community_id
   AND days.care_level = incidents.care_level
INNER JOIN gold.dim_community AS community
    ON days.community_id = community.community_id
ORDER BY
    days.community_id,
    days.care_level;