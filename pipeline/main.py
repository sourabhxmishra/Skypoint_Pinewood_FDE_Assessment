from pathlib import Path
import duckdb


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIR = PROJECT_ROOT / "data" / "source"
OUTPUT_DIR = PROJECT_ROOT / "data" / "output"
DATABASE_PATH = OUTPUT_DIR / "pinewood.duckdb"
BRONZE_SQL_PATH = PROJECT_ROOT / "pipeline" / "sql" / "bronze" / "load_bronze.sql"
SILVER_SQL_PATH = PROJECT_ROOT / "pipeline" / "sql" / "silver" / "transform_silver.sql"
QUARANTINE_SQL_PATH = (
    PROJECT_ROOT / "pipeline" / "sql" / "silver" / "build_quarantine.sql"
)
GOLD_SQL_PATH = PROJECT_ROOT / "pipeline" / "sql" / "gold" / "build_gold.sql"
GOLD_OUTPUT_DIR = OUTPUT_DIR / "gold"

EXPECTED_FILE_COUNT = 48
EXPECTED_TOTAL_ROWS = 80_027

TABLE_CONFIG = {
    "pcc_residents": ("pcc_residents_*.csv", 4_152),
    "pcc_incidents": ("pcc_incidents_*.csv", 411),
    "pcc_care_history": ("pcc_care_history_*.csv", 303),
    "yardi_units": ("yardi_units_*.csv", 5_490),
    "yardi_leases": ("yardi_leases_*.csv", 346),
    "adp_shifts": ("adp_shifts_*.csv", 68_071),
    "gbp_reviews": ("gbp_reviews_*.csv", 424),
    "hubspot_leads": ("hubspot_leads_*.csv", 830),
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


def validate_source_files() -> None:
    """Fail early when the expected assessment inputs are incomplete."""
    source_files = sorted(SOURCE_DIR.glob("*.csv"))

    if len(source_files) != EXPECTED_FILE_COUNT:
        raise RuntimeError(
            f"Expected {EXPECTED_FILE_COUNT} CSV files in {SOURCE_DIR}, "
            f"but found {len(source_files)}."
        )

    dictionary_path = SOURCE_DIR / "DATA_DICTIONARY.md"
    if not dictionary_path.exists():
        raise RuntimeError(f"Missing data dictionary: {dictionary_path}")

    for table_name, (file_pattern, _) in TABLE_CONFIG.items():
        monthly_files = sorted(SOURCE_DIR.glob(file_pattern))
        if len(monthly_files) != 6:
            raise RuntimeError(
                f"Expected 6 files for {table_name}, but found {len(monthly_files)}."
            )


def sql_string(value: str) -> str:
    """Escape a value before placing it inside a SQL string literal."""
    return value.replace("'", "''")


def render_bronze_sql(
    template: str,
    table_name: str,
    file_pattern: str,
) -> str:
    """Fill the three placeholders in the reusable Bronze SQL template."""
    file_glob = (SOURCE_DIR / file_pattern).as_posix()

    return (
        template.replace("{{TABLE_NAME}}", table_name)
        .replace("{{SOURCE_TABLE}}", sql_string(table_name))
        .replace("{{FILE_GLOB}}", sql_string(file_glob))
    )


def load_bronze(connection: duckdb.DuckDBPyConnection) -> dict[str, int]:
    """Build all Bronze tables and return their row counts."""
    sql_template = BRONZE_SQL_PATH.read_text(encoding="utf-8")
    row_counts: dict[str, int] = {}

    for table_name, (file_pattern, expected_rows) in TABLE_CONFIG.items():
        sql = render_bronze_sql(sql_template, table_name, file_pattern)
        connection.execute(sql)

        actual_rows = connection.execute(
            f"SELECT count(*) FROM bronze.{table_name}"
        ).fetchone()[0]

        if actual_rows != expected_rows:
            raise RuntimeError(
                f"bronze.{table_name}: expected {expected_rows:,} rows, "
                f"but loaded {actual_rows:,}."
            )

        row_counts[table_name] = actual_rows

    return row_counts


def print_run_summary(row_counts: dict[str, int]) -> None:
    """Print a short summary suitable for local validation and the walkthrough."""
    total_rows = sum(row_counts.values())

    print("\nPinewood Bronze ingestion summary")
    print("-" * 42)
    print(f"Source directory : {SOURCE_DIR}")
    print(f"Database         : {DATABASE_PATH}")
    print(f"CSV files        : {EXPECTED_FILE_COUNT}")

    for table_name, row_count in row_counts.items():
        print(f"bronze.{table_name:<20} {row_count:>8,} rows")

    print("-" * 42)
    print(f"Total                         {total_rows:>8,} rows")

    if total_rows != EXPECTED_TOTAL_ROWS:
        raise RuntimeError(
            f"Expected {EXPECTED_TOTAL_ROWS:,} total rows, but loaded {total_rows:,}."
        )

    print("Status            : SUCCESS")


def execute_sql_file(
    connection: duckdb.DuckDBPyConnection,
    sql_path: Path,
) -> None:
    """Execute one UTF-8 SQL file against the current database."""
    connection.execute(sql_path.read_text(encoding="utf-8"))


def validate_table_counts(
    connection: duckdb.DuckDBPyConnection,
    schema_name: str,
    expected_counts: dict[str, int],
) -> dict[str, int]:
    """Return actual counts and fail when a required table does not reconcile."""
    actual_counts: dict[str, int] = {}

    for table_name, expected_rows in expected_counts.items():
        actual_rows = connection.execute(
            f"SELECT count(*) FROM {schema_name}.{table_name}"
        ).fetchone()[0]

        if actual_rows != expected_rows:
            raise RuntimeError(
                f"{schema_name}.{table_name}: expected {expected_rows:,} rows, "
                f"but found {actual_rows:,}."
            )

        actual_counts[table_name] = actual_rows

    return actual_counts


def load_silver(
    connection: duckdb.DuckDBPyConnection,
) -> tuple[dict[str, int], dict[str, int]]:
    """Build typed Silver tables and visible quarantine outputs."""
    execute_sql_file(connection, SILVER_SQL_PATH)
    execute_sql_file(connection, QUARANTINE_SQL_PATH)

    silver_counts = validate_table_counts(
        connection,
        "silver",
        EXPECTED_SILVER_ROWS,
    )
    quarantine_counts = validate_table_counts(
        connection,
        "quarantine",
        EXPECTED_QUARANTINE_ROWS,
    )

    return silver_counts, quarantine_counts


def print_silver_summary(
    connection: duckdb.DuckDBPyConnection,
    silver_counts: dict[str, int],
    quarantine_counts: dict[str, int],
) -> None:
    """Print cleaning, deduplication, repair, and quarantine results."""
    invalid_acuity = connection.execute(
        "SELECT count(*) FROM silver.pcc_residents WHERE invalid_acuity_flag"
    ).fetchone()[0]
    invalid_adp_rates = connection.execute(
        "SELECT count(*) FROM silver.adp_shifts WHERE hourly_rate_invalid_flag"
    ).fetchone()[0]
    lease_versions_removed = (
        connection.execute("SELECT count(*) FROM bronze.yardi_leases").fetchone()[0]
        - silver_counts["yardi_leases"]
    )

    if invalid_acuity != 18:
        raise RuntimeError(
            f"Expected 18 invalid acuity rows, but found {invalid_acuity}."
        )
    if invalid_adp_rates != 0:
        raise RuntimeError(
            f"Expected 0 invalid ADP rates, but found {invalid_adp_rates}."
        )
    if lease_versions_removed != 44:
        raise RuntimeError(
            f"Expected 44 removed lease versions, but found {lease_versions_removed}."
        )

    print("\nPinewood Silver transformation summary")
    print("-" * 48)

    for table_name, row_count in silver_counts.items():
        print(f"silver.{table_name:<24} {row_count:>8,} rows")

    print("-" * 48)
    print(f"Invalid acuity flagged          {invalid_acuity:>8,} rows")
    print(f"Invalid ADP rates               {invalid_adp_rates:>8,} rows")
    print(f"Lease versions removed          {lease_versions_removed:>8,} rows")

    for category, row_count in quarantine_counts.items():
        print(f"quarantine.{category:<20} {row_count:>8,} rows")

    print("Silver status      : SUCCESS")


def load_gold(
    connection: duckdb.DuckDBPyConnection,
) -> dict[str, int]:
    """Build and validate the Gold star schema."""
    execute_sql_file(connection, GOLD_SQL_PATH)
    gold_counts = validate_table_counts(connection, "gold", EXPECTED_GOLD_ROWS)
    validate_gold_quality(connection)
    return gold_counts


def validate_gold_quality(connection: duckdb.DuckDBPyConnection) -> None:
    """Fail when a Gold grain, dimension relationship, or assumption is invalid."""
    zero_expected_checks = {
        "resident-day duplicate grains": (
            "SELECT count(*) - count(DISTINCT (resident_id, date)) "
            "FROM gold.fact_resident_day"
        ),
        "occupancy duplicate grains": (
            "SELECT count(*) - count(DISTINCT (community_id, month_start)) "
            "FROM gold.fact_occupancy_monthly"
        ),
        "lease duplicate grains": (
            "SELECT count(*) - count(DISTINCT lease_id) FROM gold.fact_lease"
        ),
        "incident duplicate grains": (
            "SELECT count(*) - count(DISTINCT incident_id) FROM gold.fact_incident"
        ),
        "resident-day orphan communities": (
            "SELECT count(*) FROM gold.fact_resident_day AS fact "
            "LEFT JOIN gold.dim_community AS dimension USING (community_id) "
            "WHERE dimension.community_id IS NULL"
        ),
        "resident-day orphan care levels": (
            "SELECT count(*) FROM gold.fact_resident_day AS fact "
            "LEFT JOIN gold.dim_care_level AS dimension USING (care_level) "
            "WHERE dimension.care_level IS NULL"
        ),
        "incident orphan communities": (
            "SELECT count(*) FROM gold.fact_incident AS fact "
            "LEFT JOIN gold.dim_community AS dimension USING (community_id) "
            "WHERE dimension.community_id IS NULL"
        ),
        "incident orphan care levels": (
            "SELECT count(*) FROM gold.fact_incident AS fact "
            "LEFT JOIN gold.dim_care_level AS dimension USING (care_level) "
            "WHERE dimension.care_level IS NULL"
        ),
        "occupancy rows without valid units": (
            "SELECT count(*) FROM gold.fact_occupancy_monthly "
            "WHERE valid_unit_count IS NULL OR valid_unit_count = 0"
        ),
        "communities not marked as assumed geography": (
            "SELECT count(*) FROM gold.dim_community "
            "WHERE NOT geography_is_assumed"
        ),
        "occupancy rows not marked as proxy": (
            "SELECT count(*) FROM gold.fact_occupancy_monthly "
            "WHERE NOT occupancy_is_proxy"
        ),
    }

    for check_name, query in zero_expected_checks.items():
        issue_count = connection.execute(query).fetchone()[0]
        if issue_count != 0:
            raise RuntimeError(
                f"Gold quality check failed for {check_name}: "
                f"found {issue_count:,} issue rows."
            )

    completed_move_outs = connection.execute(
        "SELECT count(*) FROM gold.fact_lease WHERE move_out_date IS NOT NULL"
    ).fetchone()[0]
    if completed_move_outs != 75:
        raise RuntimeError(
            f"Expected 75 completed move-outs, but found {completed_move_outs:,}."
        )


def export_gold(
    connection: duckdb.DuckDBPyConnection,
    gold_counts: dict[str, int],
) -> None:
    """Export every Gold table as a deterministic Parquet artifact."""
    GOLD_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    for table_name in gold_counts:
        output_path = GOLD_OUTPUT_DIR / f"{table_name}.parquet"
        if output_path.exists():
            output_path.unlink()

        escaped_path = sql_string(output_path.as_posix())
        connection.execute(
            f"COPY gold.{table_name} TO '{escaped_path}' "
            "(FORMAT PARQUET, COMPRESSION ZSTD)"
        )


def print_gold_summary(gold_counts: dict[str, int]) -> None:
    """Print the validated Gold table counts."""
    print("\nPinewood Gold star-schema summary")
    print("-" * 48)
    for table_name, row_count in gold_counts.items():
        print(f"gold.{table_name:<28} {row_count:>8,} rows")
    print("Gold quality checks: SUCCESS")
    print("Gold status        : SUCCESS")


def main() -> None:
    """Rebuild and validate Bronze, Silver, quarantine, and Gold outputs."""
    validate_source_files()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    connection = duckdb.connect(str(DATABASE_PATH))
    try:
        row_counts = load_bronze(connection)
        print_run_summary(row_counts)
        silver_counts, quarantine_counts = load_silver(connection)
        print_silver_summary(connection, silver_counts, quarantine_counts)
        gold_counts = load_gold(connection)
        export_gold(connection, gold_counts)
        print_gold_summary(gold_counts)
    finally:
        connection.close()


if __name__ == "__main__":
    main()