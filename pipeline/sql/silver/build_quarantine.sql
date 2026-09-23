CREATE SCHEMA IF NOT EXISTS quarantine;

CREATE OR REPLACE TABLE quarantine.resident_conflicts AS
SELECT
	*,
	'Unsupported duplicate resident/month candidate' AS _quarantine_reason,
	current_timestamp AS _quarantined_at_utc
FROM silver._resident_candidates
WHERE candidate_rank > 1;

CREATE OR REPLACE TABLE quarantine.invalid_unit_communities AS
SELECT
	*,
	'Community ID outside C001-C014' AS _quarantine_reason,
	current_timestamp AS _quarantined_at_utc
FROM silver.yardi_units
WHERE invalid_community_flag;

CREATE OR REPLACE TABLE quarantine.conflicting_leads AS
SELECT
	*,
	'Conflicting records share the same lead ID' AS _quarantine_reason,
	current_timestamp AS _quarantined_at_utc
FROM silver._lead_candidates
WHERE lead_version_count > 1;

CREATE OR REPLACE TABLE quarantine.incidents_outside_residency AS
SELECT
	*,
	'Incident date outside resident stay interval' AS _quarantine_reason,
	current_timestamp AS _quarantined_at_utc
FROM silver.pcc_incidents
WHERE outside_residency_flag;

CREATE OR REPLACE VIEW quarantine.rejection_summary AS
SELECT 'resident_conflicts' AS category, count(*) AS row_count
FROM quarantine.resident_conflicts
UNION ALL
SELECT 'invalid_unit_communities', count(*)
FROM quarantine.invalid_unit_communities
UNION ALL
SELECT 'conflicting_leads', count(*)
FROM quarantine.conflicting_leads
UNION ALL
SELECT 'incidents_outside_residency', count(*)
FROM quarantine.incidents_outside_residency;
