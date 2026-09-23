from pathlib import Path
import subprocess
import sys

import duckdb
import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATABASE_PATH = PROJECT_ROOT / "data" / "output" / "pinewood.duckdb"
GOLD_OUTPUT_DIR = PROJECT_ROOT / "data" / "output" / "gold"
SQL_DIR = PROJECT_ROOT / "sql"

EXPECTED_BRONZE_ROWS = {
    "pcc_residents": 4_152,
    "pcc_incidents": 411,
    "pcc_care_history": 303,
    "yardi_units": 5_490,
    "yardi_leases": 346,
    "adp_shifts": 68_071,
    "gbp_reviews": 424,
    "hubspot_leads": 830,
}

EXPECTED_SILVER_ROWS = {
    "pcc_residents": 4_149,
    "pcc_incidents": 411,
    "pcc_care_history": 303,
    "yardi_units": 5_490,
    "yardi_leases": 302,
    "adp_shifts": 68_071,
    "gbp_reviews": 424,
    "hubspot_leads": 828,
}

EXPECTED_QUARANTINE_ROWS = {
    "resident_conflicts": 3,
    "invalid_unit_communities": 30,
    "conflicting_leads": 2,
    "incidents_outside_residency": 12,
}

EXPECTED_GOLD_ROWS = {
    "dim_date": 181,
    "dim_community": 14,
    "dim_care_level": 3,
    "fact_resident_day": 120_533,
    "fact_occupancy_monthly": 84,
    "fact_lease": 302,
    "fact_incident": 399,
}

REQUIRED_SQL_ROWS = {
    "monthly_occupancy.sql": 84,
    "top_move_out_reasons.sql": 37,
    "incident_rate.sql": 42,
}


def run_pipeline() -> str:
    """Run the production entry point with this pytest interpreter."""
    result = subprocess.run(
        [sys.executable, "-m", "pipeline.main"],
        cwd=PROJECT_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout


def table_counts(schema_name: str, expected: dict[str, int]) -> dict[str, int]:
    connection = duckdb.connect(str(DATABASE_PATH), read_only=True)
    try:
        return {
            table_name: connection.execute(
                f"SELECT count(*) FROM {schema_name}.{table_name}"
            ).fetchone()[0]
            for table_name in expected
        }
    finally:
        connection.close()


def complete_snapshot() -> dict[str, dict[str, int]]:
    return {
        "bronze": table_counts("bronze", EXPECTED_BRONZE_ROWS),
        "silver": table_counts("silver", EXPECTED_SILVER_ROWS),
        "quarantine": table_counts(
            "quarantine",
            EXPECTED_QUARANTINE_ROWS,
        ),
        "gold": table_counts("gold", EXPECTED_GOLD_ROWS),
    }


@pytest.fixture(scope="session", autouse=True)
def rebuilt_pipeline() -> str:
    """Give every integration test a freshly rebuilt database."""
    return run_pipeline()


def test_pipeline_reports_success(rebuilt_pipeline):
    assert "Status            : SUCCESS" in rebuilt_pipeline
    assert "Silver status      : SUCCESS" in rebuilt_pipeline
    assert "Gold quality checks: SUCCESS" in rebuilt_pipeline
    assert "Gold status        : SUCCESS" in rebuilt_pipeline


def test_bronze_inventory_and_total():
    actual = table_counts("bronze", EXPECTED_BRONZE_ROWS)

    assert actual == EXPECTED_BRONZE_ROWS
    assert sum(actual.values()) == 80_027


def test_silver_quarantine_and_gold_counts():
    assert table_counts("silver", EXPECTED_SILVER_ROWS) == EXPECTED_SILVER_ROWS
    assert (
        table_counts("quarantine", EXPECTED_QUARANTINE_ROWS)
        == EXPECTED_QUARANTINE_ROWS
    )
    assert table_counts("gold", EXPECTED_GOLD_ROWS) == EXPECTED_GOLD_ROWS


def test_dimension_keys_are_unique():
    connection = duckdb.connect(str(DATABASE_PATH), read_only=True)
    try:
        duplicates = connection.execute(
            """
            SELECT
                (SELECT count(*) - count(DISTINCT date)
                 FROM gold.dim_date),
                (SELECT count(*) - count(DISTINCT community_id)
                 FROM gold.dim_community),
                (SELECT count(*) - count(DISTINCT care_level)
                 FROM gold.dim_care_level)
            """
        ).fetchone()
    finally:
        connection.close()

    assert duplicates == (0, 0, 0)


def test_fact_grains_are_unique():
    connection = duckdb.connect(str(DATABASE_PATH), read_only=True)
    try:
        duplicates = connection.execute(
            """
            SELECT
                (SELECT count(*) - count(DISTINCT (resident_id, date))
                 FROM gold.fact_resident_day),
                (SELECT count(*) - count(DISTINCT (community_id, month_start))
                 FROM gold.fact_occupancy_monthly),
                (SELECT count(*) - count(DISTINCT lease_id)
                 FROM gold.fact_lease),
                (SELECT count(*) - count(DISTINCT incident_id)
                 FROM gold.fact_incident)
            """
        ).fetchone()
    finally:
        connection.close()

    assert duplicates == (0, 0, 0, 0)


def test_fact_dimension_keys_have_no_orphans():
    connection = duckdb.connect(str(DATABASE_PATH), read_only=True)
    try:
        orphan_counts = connection.execute(
            """
            SELECT
                (SELECT count(*)
                 FROM gold.fact_resident_day AS fact
                 LEFT JOIN gold.dim_community AS dimension USING (community_id)
                 WHERE dimension.community_id IS NULL),
                (SELECT count(*)
                 FROM gold.fact_resident_day AS fact
                 LEFT JOIN gold.dim_care_level AS dimension USING (care_level)
                 WHERE dimension.care_level IS NULL),
                (SELECT count(*)
                 FROM gold.fact_incident AS fact
                 LEFT JOIN gold.dim_community AS dimension USING (community_id)
                 WHERE dimension.community_id IS NULL),
                (SELECT count(*)
                 FROM gold.fact_incident AS fact
                 LEFT JOIN gold.dim_care_level AS dimension USING (care_level)
                 WHERE dimension.care_level IS NULL)
            """
        ).fetchone()
    finally:
        connection.close()

    assert orphan_counts == (0, 0, 0, 0)


def test_business_benchmarks_reconcile():
    connection = duckdb.connect(str(DATABASE_PATH), read_only=True)
    try:
        actual = connection.execute(
            """
            SELECT
                (SELECT count(*) FROM gold.fact_resident_day),
                (SELECT count(*)
                 FROM gold.fact_lease
                 WHERE move_out_date IS NOT NULL),
                (SELECT count(*) FROM gold.fact_incident),
                (SELECT count(*)
                 FROM quarantine.incidents_outside_residency),
                (SELECT count(*)
                 FROM silver.pcc_residents
                 WHERE invalid_acuity_flag)
            """
        ).fetchone()
    finally:
        connection.close()

    assert actual == (120_533, 75, 399, 12, 18)


def test_required_sql_queries_execute_and_match_grains():
    connection = duckdb.connect(str(DATABASE_PATH), read_only=True)
    try:
        for file_name, expected_rows in REQUIRED_SQL_ROWS.items():
            query = (SQL_DIR / file_name).read_text(encoding="utf-8")
            actual_rows = connection.execute(query).fetchall()
            assert len(actual_rows) == expected_rows, file_name
    finally:
        connection.close()


def test_gold_parquet_exports_are_readable():
    connection = duckdb.connect()
    try:
        actual = {
            table_name: connection.execute(
                "SELECT count(*) FROM read_parquet(?)",
                [str(GOLD_OUTPUT_DIR / f"{table_name}.parquet")],
            ).fetchone()[0]
            for table_name in EXPECTED_GOLD_ROWS
        }
    finally:
        connection.close()

    assert actual == EXPECTED_GOLD_ROWS


def test_pipeline_is_idempotent():
    first_snapshot = complete_snapshot()
    second_output = run_pipeline()
    second_snapshot = complete_snapshot()

    assert "Gold status        : SUCCESS" in second_output
    assert second_snapshot == first_snapshot
