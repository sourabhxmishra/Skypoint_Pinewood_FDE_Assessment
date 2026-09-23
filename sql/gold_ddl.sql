-- Pinewood Gold logical schema.
-- This DDL documents the model; pipeline/sql/gold/build_gold.sql populates it.

CREATE SCHEMA IF NOT EXISTS gold;

CREATE TABLE IF NOT EXISTS gold.dim_date (
	date DATE PRIMARY KEY,
	year BIGINT NOT NULL,
	quarter BIGINT NOT NULL,
	month_number BIGINT NOT NULL,
	month_name VARCHAR NOT NULL,
	month_start DATE NOT NULL,
	month_end DATE NOT NULL
);

CREATE TABLE IF NOT EXISTS gold.dim_community (
	community_id VARCHAR PRIMARY KEY,
	community_name VARCHAR NOT NULL,
	state_code VARCHAR NOT NULL,
	region VARCHAR NOT NULL,
	geography_is_assumed BOOLEAN NOT NULL
);

CREATE TABLE IF NOT EXISTS gold.dim_care_level (
	care_level VARCHAR PRIMARY KEY,
	display_order INTEGER NOT NULL UNIQUE
);

-- Grain: one active resident on one calendar date.
CREATE TABLE IF NOT EXISTS gold.fact_resident_day (
	resident_id VARCHAR NOT NULL,
	community_id VARCHAR NOT NULL,
	date DATE NOT NULL,
	care_level VARCHAR NOT NULL,
	resident_day_count INTEGER NOT NULL CHECK (resident_day_count = 1),
	PRIMARY KEY (resident_id, date),
	FOREIGN KEY (community_id) REFERENCES gold.dim_community (community_id),
	FOREIGN KEY (date) REFERENCES gold.dim_date (date),
	FOREIGN KEY (care_level) REFERENCES gold.dim_care_level (care_level)
);

-- Grain: one community in one reporting month.
CREATE TABLE IF NOT EXISTS gold.fact_occupancy_monthly (
	community_id VARCHAR NOT NULL,
	month_start DATE NOT NULL,
	month_end DATE NOT NULL,
	occupied_resident_count BIGINT NOT NULL CHECK (occupied_resident_count >= 0),
	valid_unit_count BIGINT NOT NULL CHECK (valid_unit_count > 0),
	occupancy_proxy_percent DOUBLE NOT NULL,
	occupancy_is_proxy BOOLEAN NOT NULL,
	PRIMARY KEY (community_id, month_start),
	FOREIGN KEY (community_id) REFERENCES gold.dim_community (community_id),
	FOREIGN KEY (month_start) REFERENCES gold.dim_date (date),
	FOREIGN KEY (month_end) REFERENCES gold.dim_date (date)
);

-- Grain: one deduplicated lease.
CREATE TABLE IF NOT EXISTS gold.fact_lease (
	lease_id VARCHAR PRIMARY KEY,
	resident_id VARCHAR NOT NULL,
	unit_id VARCHAR NOT NULL,
	community_id VARCHAR NOT NULL,
	move_in_date DATE NOT NULL,
	move_out_date DATE,
	move_out_reason VARCHAR NOT NULL,
	monthly_rate DECIMAL(12, 2) NOT NULL CHECK (monthly_rate >= 0),
	FOREIGN KEY (community_id) REFERENCES gold.dim_community (community_id)
);

-- Grain: one valid incident occurring during a resident stay.
CREATE TABLE IF NOT EXISTS gold.fact_incident (
	incident_id VARCHAR PRIMARY KEY,
	resident_id VARCHAR NOT NULL,
	community_id VARCHAR NOT NULL,
	incident_date DATE NOT NULL,
	care_level VARCHAR NOT NULL,
	incident_type VARCHAR NOT NULL,
	severity INTEGER NOT NULL,
	FOREIGN KEY (community_id) REFERENCES gold.dim_community (community_id),
	FOREIGN KEY (incident_date) REFERENCES gold.dim_date (date),
	FOREIGN KEY (care_level) REFERENCES gold.dim_care_level (care_level)
);
