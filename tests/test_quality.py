from decimal import Decimal
from pathlib import Path

import duckdb
import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SILVER_SQL_PATH = PROJECT_ROOT / "pipeline" / "sql" / "silver" / "transform_silver.sql"

HOURLY_RATE_QUERY = """
SELECT try_cast(
    json_extract_string(
        try_cast(replace(?, chr(39), chr(34)) AS JSON),
        concat(chr(36), chr(46), trim(?))
    ) AS DECIMAL(10, 2)
)
"""


@pytest.fixture
def quality_connection():
    """Load the production Silver macros into an isolated database."""
    connection = duckdb.connect()
    silver_sql = SILVER_SQL_PATH.read_text(encoding="utf-8")
    macro_sql = silver_sql.split(
        "CREATE OR REPLACE TABLE silver._resident_candidates",
        maxsplit=1,
    )[0]
    connection.execute(macro_sql)

    try:
        yield connection
    finally:
        connection.close()


@pytest.mark.parametrize(
    ("raw_value", "expected"),
    [
        ("IL", "Independent Living"),
        ("independent", "Independent Living"),
        ("Independent Living", "Independent Living"),
        ("AL", "Assisted Living"),
        ("assisted", "Assisted Living"),
        ("Assisted Living", "Assisted Living"),
        ("MC", "Memory Care"),
        ("memory", "Memory Care"),
        ("Memory Care", "Memory Care"),
    ],
)
def test_normalize_all_care_level_variants(
    quality_connection,
    raw_value,
    expected,
):
    actual = quality_connection.execute(
        "SELECT silver.normalize_care_level(?)",
        [raw_value],
    ).fetchone()[0]

    assert actual == expected


def test_unknown_care_level_returns_null(quality_connection):
    actual = quality_connection.execute(
        "SELECT silver.normalize_care_level(?)",
        ["unsupported level"],
    ).fetchone()[0]

    assert actual is None


@pytest.mark.parametrize(
    ("raw_value", "expected"),
    [
        ("2025-03-17", "2025-03-17"),
        ("03/17/2025", "2025-03-17"),
    ],
)
def test_parse_supported_date_formats(
    quality_connection,
    raw_value,
    expected,
):
    actual = quality_connection.execute(
        "SELECT cast(silver.parse_date(?) AS VARCHAR)",
        [raw_value],
    ).fetchone()[0]

    assert actual == expected


@pytest.mark.parametrize("raw_value", [None, "", "not-a-date"])
def test_invalid_date_returns_null(quality_connection, raw_value):
    actual = quality_connection.execute(
        "SELECT silver.parse_date(?)",
        [raw_value],
    ).fetchone()[0]

    assert actual is None


@pytest.mark.parametrize(
    ("raw_value", "role", "expected"),
    [
        ("{'CNA': 24.50, 'RN': 42.00}", "CNA", Decimal("24.50")),
        ("{'CNA': 24.50, 'RN': 42.00}", "RN", Decimal("42.00")),
    ],
)
def test_valid_adp_rate_selects_role_value(raw_value, role, expected):
    connection = duckdb.connect()
    try:
        actual = connection.execute(
            HOURLY_RATE_QUERY,
            [raw_value, role],
        ).fetchone()[0]
    finally:
        connection.close()

    assert actual == expected


@pytest.mark.parametrize(
    ("raw_value", "role"),
    [
        ("not a dictionary", "CNA"),
        ("{'CNA': 'not numeric'}", "CNA"),
        ("{'CNA': 24.50}", "RN"),
    ],
)
def test_invalid_adp_rate_returns_null(raw_value, role):
    connection = duckdb.connect()
    try:
        actual = connection.execute(
            HOURLY_RATE_QUERY,
            [raw_value, role],
        ).fetchone()[0]
    finally:
        connection.close()

    assert actual is None


def test_malicious_looking_adp_text_is_never_executed(tmp_path):
    marker_path = tmp_path / "should_not_exist.txt"
    payload = (
        "__import__('pathlib').Path(" 
        f"r'{marker_path}'"
        ").write_text('executed')"
    )

    connection = duckdb.connect()
    try:
        actual = connection.execute(
            HOURLY_RATE_QUERY,
            [payload, "CNA"],
        ).fetchone()[0]
    finally:
        connection.close()

    assert actual is None
    assert not marker_path.exists()