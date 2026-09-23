CREATE SCHEMA IF NOT EXISTS silver;

CREATE OR REPLACE MACRO silver.parse_date(value) AS (
    coalesce(
        try_cast(nullif(trim(value), '') AS DATE),
        cast(try_strptime(nullif(trim(value), ''), '%m/%d/%Y') AS DATE)
    )
);

CREATE OR REPLACE MACRO silver.normalize_care_level(value) AS (
    CASE lower(trim(value))
        WHEN 'il' THEN 'Independent Living'
        WHEN 'independent' THEN 'Independent Living'
        WHEN 'independent living' THEN 'Independent Living'
        WHEN 'al' THEN 'Assisted Living'
        WHEN 'assisted' THEN 'Assisted Living'
        WHEN 'assisted living' THEN 'Assisted Living'
        WHEN 'mc' THEN 'Memory Care'
        WHEN 'memory' THEN 'Memory Care'
        WHEN 'memory care' THEN 'Memory Care'
        ELSE NULL
    END
);

CREATE OR REPLACE TABLE silver._resident_candidates AS
WITH typed AS (
    SELECT
        trim(resident_id) AS resident_id,
        trim(community_id) AS community_id,
        nullif(trim(first_name), '') AS first_name,
        nullif(trim(last_name), '') AS last_name,
        silver.parse_date(dob) AS dob,
        nullif(trim(gender), '') AS gender,
        silver.parse_date(admit_date) AS admit_date,
        silver.parse_date(discharge_date) AS discharge_date,
        silver.normalize_care_level(care_level) AS care_level,
        CASE
            WHEN try_cast(acuity_score AS INTEGER) BETWEEN 1 AND 10
                THEN try_cast(acuity_score AS INTEGER)
            ELSE NULL
        END AS acuity_score,
        acuity_score AS acuity_score_raw,
        CASE
            WHEN nullif(trim(acuity_score), '') IS NOT NULL
                 AND NOT (try_cast(acuity_score AS INTEGER) BETWEEN 1 AND 10)
                THEN true
            ELSE false
        END AS invalid_acuity_flag,
        nullif(trim(mobility_status), '') AS mobility_status,
        cast(strptime(concat(_source_month, '_01'), '%Y_%m_%d') AS DATE) AS snapshot_month,
        _source_file,
        _source_table,
        _source_month,
        _row_number,
        _ingested_at_utc
    FROM bronze.pcc_residents
),
scored AS (
    SELECT
        *,
        count(*) OVER (
            PARTITION BY
                resident_id,
                community_id,
                lower(first_name),
                lower(last_name),
                dob,
                gender,
                admit_date
        ) AS supporting_snapshot_count
    FROM typed
)
SELECT
    *,
    row_number() OVER (
        PARTITION BY resident_id, snapshot_month
        ORDER BY supporting_snapshot_count DESC, _row_number
    ) AS candidate_rank,
    count(*) OVER (
        PARTITION BY resident_id, snapshot_month
    ) AS candidate_count
FROM scored;

CREATE OR REPLACE TABLE silver.pcc_residents AS
SELECT * EXCLUDE (
    supporting_snapshot_count,
    candidate_rank,
    candidate_count
)
FROM silver._resident_candidates
WHERE candidate_rank = 1;

CREATE OR REPLACE TABLE silver.pcc_care_history AS
SELECT
    trim(resident_id) AS resident_id,
    silver.parse_date(change_date) AS change_date,
    silver.normalize_care_level(previous_level) AS previous_level,
    silver.normalize_care_level(new_level) AS new_level,
    nullif(trim(reason), '') AS reason,
    _source_file,
    _source_table,
    _source_month,
    _row_number,
    _ingested_at_utc
FROM bronze.pcc_care_history;

CREATE OR REPLACE TABLE silver.yardi_units AS
SELECT
    trim(unit_id) AS unit_id,
    trim(community_id) AS community_id,
    silver.normalize_care_level(unit_type) AS unit_type,
    try_cast(monthly_rent AS DECIMAL(12, 2)) AS monthly_rent,
    silver.parse_date(snapshot_date) AS snapshot_date,
    NOT regexp_full_match(trim(community_id), 'C0(0[1-9]|1[0-4])')
        AS invalid_community_flag,
    _source_file,
    _source_table,
    _source_month,
    _row_number,
    _ingested_at_utc
FROM bronze.yardi_units;

CREATE OR REPLACE TABLE silver._lease_candidates AS
WITH typed AS (
    SELECT
        trim(lease_id) AS lease_id,
        trim(resident_id) AS resident_id,
        trim(unit_id) AS unit_id,
        trim(community_id) AS community_id,
        silver.parse_date(move_in_date) AS move_in_date,
        silver.parse_date(move_out_date) AS move_out_date,
        nullif(trim(move_out_reason), '') AS move_out_reason,
        try_cast(monthly_rate AS DECIMAL(12, 2)) AS monthly_rate,
        _source_file,
        _source_table,
        _source_month,
        _row_number,
        _ingested_at_utc
    FROM bronze.yardi_leases
)
SELECT
    *,
    row_number() OVER (
        PARTITION BY lease_id
        ORDER BY
            (move_out_date IS NOT NULL) DESC,
            _source_month DESC,
            _row_number DESC
    ) AS lease_rank,
    count(*) OVER (PARTITION BY lease_id) AS lease_version_count
FROM typed;

CREATE OR REPLACE TABLE silver.yardi_leases AS
SELECT * EXCLUDE (lease_rank, lease_version_count)
FROM silver._lease_candidates
WHERE lease_rank = 1;

CREATE OR REPLACE TABLE silver.adp_shifts AS
WITH parsed AS (
    SELECT
        trim(shift_id) AS shift_id,
        trim(community_id) AS community_id,
        trim(employee_id) AS employee_id,
        trim(role) AS role,
        silver.parse_date(shift_date) AS shift_date,
        try_cast(hours_worked AS DECIMAL(10, 2)) AS hours_worked,
        hourly_rate AS hourly_rate_raw,
        try_cast(
            json_extract_string(
                try_cast(replace(hourly_rate, chr(39), chr(34)) AS JSON),
                concat(chr(36), chr(46), trim(role))
            ) AS DECIMAL(10, 2)
        ) AS hourly_rate,
        _source_file,
        _source_table,
        _source_month,
        _row_number,
        _ingested_at_utc
    FROM bronze.adp_shifts
)
SELECT
    *,
    true AS hourly_rate_repaired_flag,
    hourly_rate IS NULL OR hourly_rate NOT BETWEEN 0 AND 200
        AS hourly_rate_invalid_flag
FROM parsed;

CREATE OR REPLACE TABLE silver.gbp_reviews AS
SELECT
    trim(review_id) AS review_id,
    trim(community_id) AS community_id,
    silver.parse_date(review_date) AS review_date,
    try_cast(rating AS INTEGER) AS rating,
    nullif(trim(review_text), '') AS review_text,
    nullif(trim(response_text), '') AS response_text,
    try_cast(nullif(trim(responded_at), '') AS TIMESTAMP) AS responded_at,
    _source_file,
    _source_table,
    _source_month,
    _row_number,
    _ingested_at_utc
FROM bronze.gbp_reviews;

CREATE OR REPLACE TABLE silver._lead_candidates AS
WITH typed AS (
    SELECT
        trim(lead_id) AS lead_id,
        trim(community_id) AS community_id,
        nullif(trim(lead_source), '') AS lead_source,
        silver.parse_date(created_date) AS created_date,
        silver.parse_date(tour_date) AS tour_date,
        silver.parse_date(deposit_date) AS deposit_date,
        silver.parse_date(move_in_date) AS move_in_date,
        nullif(trim(status), '') AS status,
        nullif(trim(lost_reason), '') AS lost_reason,
        _source_file,
        _source_table,
        _source_month,
        _row_number,
        _ingested_at_utc
    FROM bronze.hubspot_leads
)
SELECT
    *,
    count(*) OVER (PARTITION BY lead_id) AS lead_version_count,
    deposit_date IS NOT NULL
        AND tour_date IS NOT NULL
        AND deposit_date < tour_date AS deposit_before_tour_flag,
    move_in_date IS NOT NULL
        AND deposit_date IS NOT NULL
        AND move_in_date < deposit_date AS move_in_before_deposit_flag
FROM typed;

CREATE OR REPLACE TABLE silver.hubspot_leads AS
SELECT * EXCLUDE (lead_version_count)
FROM silver._lead_candidates
WHERE lead_version_count = 1;

CREATE OR REPLACE TABLE silver.pcc_incidents AS
WITH resident_stays AS (
    SELECT
        resident_id,
        min(admit_date) AS admit_date,
        max(discharge_date) AS discharge_date
    FROM silver.pcc_residents
    GROUP BY resident_id
),
typed AS (
    SELECT
        trim(i.incident_id) AS incident_id,
        trim(i.resident_id) AS resident_id,
        trim(i.community_id) AS community_id,
        silver.parse_date(i.incident_date) AS incident_date,
        nullif(trim(i.incident_type), '') AS incident_type,
        try_cast(i.severity AS INTEGER) AS severity,
        nullif(trim(i.reported_by), '') AS reported_by,
        s.admit_date,
        s.discharge_date,
        i._source_file,
        i._source_table,
        i._source_month,
        i._row_number,
        i._ingested_at_utc
    FROM bronze.pcc_incidents AS i
    LEFT JOIN resident_stays AS s
        ON trim(i.resident_id) = s.resident_id
)
SELECT
    *,
    admit_date IS NULL
        OR incident_date < admit_date
        OR (discharge_date IS NOT NULL AND incident_date > discharge_date)
        AS outside_residency_flag
FROM typed;
