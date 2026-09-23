CREATE SCHEMA IF NOT EXISTS gold;

CREATE OR REPLACE TABLE gold.dim_date AS
SELECT
	cast(day_value AS DATE) AS date,
	year(day_value) AS year,
	quarter(day_value) AS quarter,
	month(day_value) AS month_number,
	strftime(day_value, '%B') AS month_name,
	cast(date_trunc('month', day_value) AS DATE) AS month_start,
	last_day(day_value) AS month_end
FROM generate_series(
	DATE '2025-01-01',
	DATE '2025-06-30',
	INTERVAL 1 DAY
) AS dates(day_value);

CREATE OR REPLACE TABLE gold.dim_community AS
SELECT
	community_id,
	concat('Community ', community_id) AS community_name,
	state_code,
	region,
	true AS geography_is_assumed
FROM (
	VALUES
		('C001', 'OR', 'Pacific Northwest'),
		('C002', 'OR', 'Pacific Northwest'),
		('C003', 'OR', 'Pacific Northwest'),
		('C004', 'OR', 'Pacific Northwest'),
		('C005', 'OR', 'Pacific Northwest'),
		('C006', 'AZ', 'Southwest'),
		('C007', 'AZ', 'Southwest'),
		('C008', 'AZ', 'Southwest'),
		('C009', 'AZ', 'Southwest'),
		('C010', 'TX', 'South'),
		('C011', 'TX', 'South'),
		('C012', 'TX', 'South'),
		('C013', 'TX', 'South'),
		('C014', 'TX', 'South')
) AS mapping(community_id, state_code, region);

CREATE OR REPLACE TABLE gold.dim_care_level AS
SELECT care_level, display_order
FROM (
	VALUES
		('Independent Living', 1),
		('Assisted Living', 2),
		('Memory Care', 3)
) AS levels(care_level, display_order);

CREATE OR REPLACE TABLE gold.fact_resident_day AS
WITH resident_stays AS (
	SELECT
		resident_id,
		arg_max(community_id, snapshot_month) AS community_id,
		min(admit_date) AS admit_date,
		max(discharge_date) AS discharge_date
	FROM silver.pcc_residents
	GROUP BY resident_id
),
resident_days AS (
	SELECT
		stays.resident_id,
		stays.community_id,
		cast(days.day_value AS DATE) AS date
	FROM resident_stays AS stays
	CROSS JOIN LATERAL generate_series(
		greatest(stays.admit_date, DATE '2025-01-01'),
		least(
			coalesce(stays.discharge_date, DATE '2025-06-30'),
			DATE '2025-06-30'
		),
		INTERVAL 1 DAY
	) AS days(day_value)
),
with_snapshot_level AS (
	SELECT
		days.*,
		snapshots.care_level AS snapshot_care_level
	FROM resident_days AS days
	LEFT JOIN silver.pcc_residents AS snapshots
		ON days.resident_id = snapshots.resident_id
	   AND date_trunc('month', days.date) = snapshots.snapshot_month
)
SELECT
	resident_id,
	community_id,
	date,
	coalesce(
		(
			SELECT arg_max(history.new_level, history.change_date)
			FROM silver.pcc_care_history AS history
			WHERE history.resident_id = with_snapshot_level.resident_id
			  AND history.change_date <= with_snapshot_level.date
		),
		snapshot_care_level
	) AS care_level,
	1 AS resident_day_count
FROM with_snapshot_level;

CREATE OR REPLACE TABLE gold.fact_occupancy_monthly AS
WITH months AS (
	SELECT DISTINCT month_start, month_end
	FROM gold.dim_date
),
resident_counts AS (
	SELECT
		community_id,
		date AS month_end,
		count(DISTINCT resident_id) AS occupied_resident_count
	FROM gold.fact_resident_day
	WHERE date = last_day(date)
	GROUP BY community_id, date
),
unit_counts AS (
	SELECT
		community_id,
		snapshot_date AS month_start,
		count(DISTINCT unit_id) AS valid_unit_count
	FROM silver.yardi_units
	WHERE NOT invalid_community_flag
	GROUP BY community_id, snapshot_date
)
SELECT
	communities.community_id,
	months.month_start,
	months.month_end,
	coalesce(residents.occupied_resident_count, 0) AS occupied_resident_count,
	coalesce(units.valid_unit_count, 0) AS valid_unit_count,
	100.0 * coalesce(residents.occupied_resident_count, 0)
		/ nullif(units.valid_unit_count, 0) AS occupancy_proxy_percent,
	true AS occupancy_is_proxy
FROM gold.dim_community AS communities
CROSS JOIN months
LEFT JOIN resident_counts AS residents
	ON communities.community_id = residents.community_id
   AND months.month_end = residents.month_end
LEFT JOIN unit_counts AS units
	ON communities.community_id = units.community_id
   AND months.month_start = units.month_start;

CREATE OR REPLACE TABLE gold.fact_lease AS
SELECT
	lease_id,
	resident_id,
	unit_id,
	community_id,
	move_in_date,
	move_out_date,
	coalesce(move_out_reason, 'Unknown') AS move_out_reason,
	monthly_rate
FROM silver.yardi_leases;

CREATE OR REPLACE TABLE gold.fact_incident AS
SELECT
	incidents.incident_id,
	incidents.resident_id,
	incidents.community_id,
	incidents.incident_date,
	resident_days.care_level,
	incidents.incident_type,
	incidents.severity
FROM silver.pcc_incidents AS incidents
INNER JOIN gold.fact_resident_day AS resident_days
	ON incidents.resident_id = resident_days.resident_id
   AND incidents.incident_date = resident_days.date
WHERE NOT incidents.outside_residency_flag;
