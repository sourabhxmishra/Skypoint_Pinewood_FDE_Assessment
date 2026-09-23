CREATE SCHEMA IF NOT EXISTS bronze;

CREATE OR REPLACE TABLE bronze.{{TABLE_NAME}} AS
SELECT
    * EXCLUDE (filename),
    parse_filename(filename) AS _source_file,
    '{{SOURCE_TABLE}}' AS _source_table,
    regexp_extract(filename, '([0-9]{4}_[0-9]{2})[.]csv$', 1) AS _source_month,
    row_number() OVER (PARTITION BY filename) AS _row_number,
    current_timestamp AS _ingested_at_utc
FROM read_csv(
    '{{FILE_GLOB}}',
    header = true,
    all_varchar = true,
    union_by_name = true,
    filename = true,
    null_padding = true
);
