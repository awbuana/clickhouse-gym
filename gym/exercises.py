"""Exercise bank for the ClickHouse gym.

Every exercise is based on the Real-Time Analytics with ClickHouse course
(lab solutions live in ../realtime-analytics) and runs in the `gym` database.

Exercise fields
  id, section, title, task   what the learner sees
  solution                   reference SQL (hidden until \\s)
  check                      "result"  -> learner's last result must match the solution's result
                             [(sql, message), ...] -> every sql must return 1 after the attempt
  ordered                    for "result": row order matters
  hints                      revealed one at a time with \\h
  setup                      run when the exercise opens; a string, or ("if_empty", table, sql)
"""

import os
from textwrap import dedent

DB = "gym"
PASSWORD = os.environ.get("CH_PASSWORD", "clickhouse")
PRICES_URL = "https://learn-clickhouse.s3.us-east-2.amazonaws.com/uk_property_prices/uk_prices.csv.zst"
RATES_URL = "https://learnclickhouse.s3.us-east-2.amazonaws.com/datasets/mortgage_rates.csv"

SECTIONS = [
    ("I", "Inspect tables"),
    ("Q", "Write queries"),
    ("F", "Common functions"),
    ("E", "Exploratory analysis"),
    ("L", "Load data"),
    ("T", "Create tables"),
    ("U", "Update and delete"),
    ("V", "Materialized views"),
    ("D", "Dictionaries and joins"),
    ("A", "Accelerate queries"),
]

EXERCISES = []


def sql(s):
    return dedent(s).strip()


def ex(id, title, task, solution, check="result", ordered=False, hints=(), setup=(), sets=False):
    EXERCISES.append(dict(
        id=id, section=id[0], title=title, task=sql(task), solution=sql(solution),
        check=check, ordered=ordered, hints=list(hints), setup=list(setup), sets=sets,
    ))


def if_not_exists(ddl):
    """Turn a CREATE statement into an idempotent one for setup steps."""
    for kw in ("CREATE TABLE", "CREATE MATERIALIZED VIEW", "CREATE DICTIONARY"):
        if ddl.startswith(kw) and "IF NOT EXISTS" not in ddl[:60]:
            return ddl.replace(kw, kw + " IF NOT EXISTS", 1)
    return ddl


# ---------- check helpers (each returns (sql, message)) ----------

def _q(s):
    return s.replace("\\", "\\\\").replace("'", "\\'")


def exists(t, engine=None):
    cond = f" AND engine = '{engine}'" if engine else ""
    msg = f"`{t}` should exist" + (f" with engine {engine}" if engine else "")
    return (f"SELECT count() = 1 FROM system.tables WHERE database = '{DB}' AND name = '{t}'{cond}", msg)


def cols(t, spec):
    tuples = ", ".join(f"('{_q(n)}', '{_q(ty)}')" for n, ty in spec)
    n = len(spec)
    return (
        f"SELECT countIf((name, type) IN ({tuples})) = {n} AND count() = {n} "
        f"FROM system.columns WHERE database = '{DB}' AND table = '{t}'",
        f"`{t}` should have exactly these columns: " + ", ".join(f"{a} {b}" for a, b in spec),
    )


def coltype(t, name, allowed):
    """allowed: list of exact types, or a LIKE pattern string."""
    if isinstance(allowed, str):
        cond, want = f"type LIKE '{_q(allowed)}'", allowed.replace("%", "…")
    else:
        cond = "type IN (" + ", ".join(f"'{_q(a)}'" for a in allowed) + ")"
        want = " or ".join(allowed)
    return (f"SELECT {cond} FROM system.columns WHERE database = '{DB}' AND table = '{t}' AND name = '{name}'",
            f"`{name}` should be {want}")


def field(t, name, value, msg):
    return (f"SELECT {name} = '{_q(value)}' FROM system.tables WHERE database = '{DB}' AND name = '{t}'", msg)


def ddl_has(t, pattern, msg):
    return (
        f"SELECT create_table_query ILIKE '%{_q(pattern)}%' FROM system.tables "
        f"WHERE database = '{DB}' AND name = '{t}'",
        msg,
    )


def is_true(s, msg):
    return (sql(s), msg)


# ---------- reusable DDL (also used to prepare later exercises) ----------

PRICES_BY_YEAR_DEST = sql("""
    CREATE TABLE prices_by_year_dest (
        price UInt32,
        date Date,
        addr1 String,
        addr2 String,
        street LowCardinality(String),
        town LowCardinality(String),
        district LowCardinality(String),
        county LowCardinality(String)
    )
    ENGINE = MergeTree
    PRIMARY KEY (town, date)
    PARTITION BY toYear(date)
""")

PRICES_BY_YEAR_FILL = sql("""
    INSERT INTO prices_by_year_dest
        SELECT price, date, addr1, addr2, street, town, district, county
        FROM uk_prices_3
""")

PRICES_BY_YEAR_VIEW = sql("""
    CREATE MATERIALIZED VIEW prices_by_year_view
    TO prices_by_year_dest
    AS
        SELECT price, date, addr1, addr2, street, town, district, county
        FROM uk_prices_3
""")

RATES_MONTHLY = sql("""
    CREATE TABLE rates_monthly (
        month Date,
        variable Decimal32(2),
        fixed Decimal32(2),
        bank Decimal32(2)
    )
    ENGINE = ReplacingMergeTree
    PRIMARY KEY month
""")

RATES_MONTHLY_FILL = sql(f"""
    INSERT INTO rates_monthly
        SELECT toDate(date) AS month, variable, fixed, bank
        FROM s3('{RATES_URL}', NOSIGN, 'CSVWithNames')
""")

RATES_MONTHLY2 = sql("""
    CREATE TABLE rates_monthly2 (
        month Date,
        variable Decimal32(2),
        fixed Decimal32(2),
        bank Decimal32(2),
        version UInt32
    )
    ENGINE = ReplacingMergeTree(version)
    PRIMARY KEY month
""")

RATES_MONTHLY2_FILL = sql("""
    INSERT INTO rates_monthly2
        SELECT month, variable, fixed, bank, 1
        FROM rates_monthly
""")

MESSAGES = sql("""
    CREATE TABLE messages (
        id UInt32,
        day Date,
        message String,
        sign Int8
    )
    ENGINE = CollapsingMergeTree(sign)
    PRIMARY KEY id
""")

PRICES_SUM_DEST = sql("""
    CREATE TABLE prices_sum_dest (
        town LowCardinality(String),
        sum_price UInt64
    )
    ENGINE = SummingMergeTree
    PRIMARY KEY town
""")

PRICES_SUM_VIEW = sql("""
    CREATE MATERIALIZED VIEW prices_sum_view
    TO prices_sum_dest
    AS
        SELECT town, sum(price) AS sum_price
        FROM uk_prices_3
        GROUP BY town
""")

PRICES_SUM_FILL = sql("""
    INSERT INTO prices_sum_dest
        SELECT town, sum(price) AS sum_price
        FROM uk_prices_3
        GROUP BY town
""")

AGGS_DEST = sql("""
    CREATE TABLE uk_prices_aggs_dest (
        month Date,
        min_price SimpleAggregateFunction(min, UInt32),
        max_price SimpleAggregateFunction(max, UInt32),
        volume AggregateFunction(count, UInt32),
        avg_price AggregateFunction(avg, UInt32)
    )
    ENGINE = AggregatingMergeTree
    PRIMARY KEY month
""")

AGGS_VIEW = sql("""
    CREATE MATERIALIZED VIEW uk_prices_aggs_view
    TO uk_prices_aggs_dest
    AS
        WITH toStartOfMonth(date) AS month
        SELECT
            month,
            minSimpleState(price) AS min_price,
            maxSimpleState(price) AS max_price,
            countState(price) AS volume,
            avgState(price) AS avg_price
        FROM uk_prices_3
        GROUP BY month
""")

AGGS_FILL = sql("""
    INSERT INTO uk_prices_aggs_dest
        WITH toStartOfMonth(date) AS month
        SELECT
            month,
            minSimpleState(price) AS min_price,
            maxSimpleState(price) AS max_price,
            countState(price) AS volume,
            avgState(price) AS avg_price
        FROM uk_prices_3
        GROUP BY month
""")

RATES_DICT = sql(f"""
    CREATE DICTIONARY uk_mortgage_rates (
        date DateTime64,
        variable Decimal32(2),
        fixed Decimal32(2),
        bank Decimal32(2)
    )
    PRIMARY KEY date
    SOURCE(HTTP(url '{RATES_URL}' format 'CSVWithNames'))
    LAYOUT(COMPLEX_KEY_HASHED())
    LIFETIME(2628000)
    SETTINGS(date_time_input_format = 'best_effort')
""")

ENSURE_PRICES_BY_YEAR = [
    if_not_exists(PRICES_BY_YEAR_DEST),
    ("if_empty", "prices_by_year_dest", PRICES_BY_YEAR_FILL),
]
ENSURE_RATES_MONTHLY = [
    if_not_exists(RATES_MONTHLY),
    ("if_empty", "rates_monthly", RATES_MONTHLY_FILL),
]
RESET_RATES_MONTHLY2 = ENSURE_RATES_MONTHLY + [
    "DROP TABLE IF EXISTS rates_monthly2",
    RATES_MONTHLY2,
    RATES_MONTHLY2_FILL,
]
ENSURE_PRICES_SUM = [
    if_not_exists(PRICES_SUM_DEST),
    if_not_exists(PRICES_SUM_VIEW),
    ("if_empty", "prices_sum_dest", PRICES_SUM_FILL),
]
ENSURE_AGGS = [
    if_not_exists(AGGS_DEST),
    if_not_exists(AGGS_VIEW),
    ("if_empty", "uk_prices_aggs_dest", AGGS_FILL),
]
ENSURE_DICT = [if_not_exists(RATES_DICT)]

# =====================================================================
# I. Inspect tables
# =====================================================================

ex("I1", "Show a table's DDL",
   "Print the full CREATE statement of `uk_prices_3` (engine, keys and settings).",
   "SHOW CREATE TABLE uk_prices_3",
   hints=["There is a SHOW statement for this.", "SHOW CREATE TABLE <name>"])

ex("I2", "Describe columns",
   "List the columns of `uk_prices_3` with their types, defaults, codecs and TTLs.",
   "DESCRIBE TABLE uk_prices_3",
   ordered=True,
   hints=["DESC or DESCRIBE"])

ex("I3", "List tables",
   "List every table in the current database (`gym`).",
   "SHOW TABLES",
   hints=["SHOW TABLES, optionally FROM <db> LIKE '<pattern>'"])

ex("I4", "Count parts",
   """
   Using system.parts, return the number of active parts and the total row count of
   `uk_prices_3` in the `gym` database, in that column order.
   """,
   "SELECT count(), sum(rows) FROM system.parts WHERE database = 'gym' AND table = 'uk_prices_3' AND active",
   hints=["system.parts has columns database, table, rows, active.",
          "Filter active = 1, otherwise old parts waiting for deletion are counted too.",
          "Your default database also has a uk_prices_3, so filter on database = 'gym'."])

ex("I5", "Table size on disk",
   """
   Show the compressed and uncompressed size of `uk_prices_3` (gym database) as
   human-readable strings, in that column order.
   """,
   """
   SELECT
       formatReadableSize(sum(data_compressed_bytes)) AS compressed_size,
       formatReadableSize(sum(data_uncompressed_bytes)) AS uncompressed_size
   FROM system.parts
   WHERE database = 'gym' AND table = 'uk_prices_3' AND active = 1
   """,
   hints=["system.parts: data_compressed_bytes, data_uncompressed_bytes",
          "formatReadableSize(sum(...))"])

ex("I6", "Per-column compression",
   """
   For each column of `uk_prices_3` (gym database), return:
     column, compressed size (readable), uncompressed size (readable),
     compression ratio = round(uncompressed bytes / compressed bytes, 2)
   """,
   """
   SELECT
       column,
       formatReadableSize(sum(column_data_compressed_bytes) AS c) AS compressed,
       formatReadableSize(sum(column_data_uncompressed_bytes) AS u) AS uncompressed,
       round(u / c, 2) AS compression_ratio
   FROM system.parts_columns
   WHERE database = 'gym' AND table = 'uk_prices_3' AND active = 1
   GROUP BY column
   """,
   hints=["The per-column numbers live in system.parts_columns.",
          "column_data_compressed_bytes / column_data_uncompressed_bytes",
          "You can name an aggregate inline and reuse it: sum(x) AS c"])

ex("I7", "Keys from system.tables",
   """
   From system.tables, return engine, sorting_key, primary_key and partition_key of
   `uk_prices_3` in the gym database.
   """,
   """
   SELECT engine, sorting_key, primary_key, partition_key
   FROM system.tables
   WHERE database = 'gym' AND name = 'uk_prices_3'
   """,
   hints=["system.tables uses `name`, not `table`, for the table name."])

# =====================================================================
# Q. Write queries (lab 5.1 and friends)
# =====================================================================

ex("Q1", "Million-pound sales",
   "How many properties sold for more than 1,000,000 in 2024?",
   "SELECT count() FROM uk_prices_3 WHERE price > 1_000_000 AND toYear(date) = 2024",
   hints=["toYear(date)", "Numeric literals can use underscores: 1_000_000"])

ex("Q2", "Distinct towns",
   "How many distinct towns are in the dataset? Use the exact count.",
   "SELECT uniqExact(town) FROM uk_prices_3",
   hints=["uniq() is approximate; there's an exact variant."])

ex("Q3", "Busiest town",
   "Return the town with the most sales and its sales count.",
   """
   SELECT town, count() AS c
   FROM uk_prices_3
   GROUP BY town
   ORDER BY c DESC
   LIMIT 1
   """)

ex("Q4", "Top towns, excluding London",
   "Using a single aggregate function with a combinator, return the 10 most frequent towns excluding LONDON (one array).",
   "SELECT topKIf(10)(town, town != 'LONDON') FROM uk_prices_3",
   sets=True,
   hints=["topK(N)(column) returns the most frequent values.",
          "Add the -If combinator: topKIf(N)(column, condition)"])

ex("Q5", "Most expensive towns",
   "Return the 10 towns with the highest average price, highest first (town, avg_price).",
   """
   SELECT town, avg(price) AS avg_price
   FROM uk_prices_3
   GROUP BY town
   ORDER BY avg_price DESC
   LIMIT 10
   """,
   ordered=True)

ex("Q6", "Most expensive address",
   "Return addr1, addr2, street and town of the single most expensive sale.",
   """
   SELECT addr1, addr2, street, town
   FROM uk_prices_3
   ORDER BY price DESC
   LIMIT 1
   """)

ex("Q7", "Average by type (one row)",
   """
   In ONE row, return the average price of detached, semi-detached, terraced, flat
   and other properties (five columns in that order). Use conditional aggregates.
   """,
   """
   SELECT
       avgIf(price, type = 'detached'),
       avgIf(price, type = 'semi-detached'),
       avgIf(price, type = 'terraced'),
       avgIf(price, type = 'flat'),
       avgIf(price, type = 'other')
   FROM uk_prices_3
   """,
   hints=["avg + the -If combinator"])

ex("Q8", "Average by type (one row per type)",
   "Return each property type and its average price, one row per type.",
   "SELECT type, avg(price) AS avg_price FROM uk_prices_3 GROUP BY type")

ex("Q9", "Spend in five counties",
   "Total amount spent on properties in 2024 in AVON, ESSEX, DEVON, KENT and CORNWALL combined.",
   """
   SELECT sum(price)
   FROM uk_prices_3
   WHERE county IN ['AVON', 'ESSEX', 'DEVON', 'KENT', 'CORNWALL']
     AND toYear(date) = 2024
   """,
   hints=["IN accepts a list: county IN ('A', 'B') or an array ['A', 'B']"])

ex("Q10", "Monthly average 2005-2010",
   "Average price per month from 2005 to 2010 inclusive, oldest month first (month, avg_price).",
   """
   SELECT toStartOfMonth(date) AS month, avg(price) AS avg_price
   FROM uk_prices_3
   WHERE toYear(month) BETWEEN 2005 AND 2010
   GROUP BY month
   ORDER BY month ASC
   """,
   ordered=True,
   hints=["toStartOfMonth(date)"])

ex("Q11", "Liverpool daily sales 2020",
   "Number of sales per day in LIVERPOOL during 2020, earliest day first (day, count).",
   """
   SELECT toStartOfDay(date) AS day, count()
   FROM uk_prices_3
   WHERE town = 'LIVERPOOL' AND toYear(date) = 2020
   GROUP BY day
   ORDER BY day ASC
   """,
   ordered=True)

ex("Q12", "Share of the record price",
   """
   For every town, return the town and its max price divided by the overall max price
   of the whole table. Compute the overall max once with a scalar WITH expression.
   """,
   """
   WITH (SELECT max(price) FROM uk_prices_3) AS overall_max
   SELECT town, max(price) / overall_max
   FROM uk_prices_3
   GROUP BY town
   """,
   hints=["WITH (SELECT ...) AS name SELECT ... name ..."])

ex("Q13", "Top 3 per county",
   "Return the 3 highest prices in each county (county, price) using LIMIT ... BY.",
   """
   SELECT county, price
   FROM uk_prices_3
   ORDER BY county, price DESC
   LIMIT 3 BY county
   """,
   hints=["ORDER BY first, then LIMIT n BY column"])

ex("Q14", "Running total of sales",
   """
   Per year: year, number of sales, and the running total of sales from the first year
   up to that year. Oldest year first. Use a window function.
   """,
   """
   SELECT
       toYear(date) AS year,
       count() AS sales,
       sum(count()) OVER (ORDER BY year) AS running_total
   FROM uk_prices_3
   GROUP BY year
   ORDER BY year
   """,
   ordered=True,
   hints=["A window function can wrap an aggregate: sum(count()) OVER (...)",
          "ORDER BY inside OVER makes the sum cumulative."])

ex("Q15", "Running total per county",
   """
   For KENT, ESSEX and DEVON only: county, year, yearly sales, and a running total that
   restarts for each county.
   """,
   """
   SELECT
       county,
       toYear(date) AS year,
       count() AS sales,
       sum(count()) OVER (PARTITION BY county ORDER BY year) AS running_total
   FROM uk_prices_3
   WHERE county IN ('KENT', 'ESSEX', 'DEVON')
   GROUP BY county, year
   """,
   hints=["PARTITION BY restarts the window for each group.",
          "OVER (PARTITION BY county ORDER BY year)"])

ex("Q16", "Year-over-year change",
   """
   Per year: year, avg_price = round(avg(price)), and diff = avg_price minus the previous
   year's avg_price. Use lagInFrame (for the first year it returns 0). Oldest year first.
   """,
   """
   SELECT
       toYear(date) AS year,
       round(avg(price)) AS avg_price,
       avg_price - lagInFrame(avg_price) OVER (ORDER BY year) AS diff
   FROM uk_prices_3
   GROUP BY year
   ORDER BY year
   """,
   ordered=True,
   hints=["lagInFrame(expr) OVER (ORDER BY ...) returns the previous row's value."])

ex("Q17", "Staffordshire, June 2005",
   """
   For STAFFORDSHIRE sales from 2005-06-01 to 2005-06-30: count, max price, average price
   and the 90th percentile price, in that order.
   """,
   """
   SELECT count(), max(price), avg(price), quantile(0.90)(price)
   FROM uk_prices_3
   WHERE county = 'STAFFORDSHIRE'
     AND date >= toDate('2005-06-01') AND date <= toDate('2005-06-30')
   """,
   hints=["Parametric aggregate: quantile(level)(column)"])

ex("Q18", "New-build share",
   "Per year: year and the percentage of sales that were new builds, rounded to 2 decimals. Oldest first.",
   """
   SELECT toYear(date) AS year, round(100 * avg(is_new), 2)
   FROM uk_prices_3
   GROUP BY year
   ORDER BY year
   """,
   ordered=True,
   hints=["is_new is 0/1, so avg(is_new) is already a share."])

ex("Q19", "Town of the record sale per type",
   "For each property type, return the type and the town of its single most expensive sale.",
   "SELECT type, argMax(town, price) FROM uk_prices_3 GROUP BY type",
   hints=["argMax(value, by)"])

ex("Q20", "Freehold vs leasehold 2023",
   "In ONE row: number of freehold sales and number of leasehold sales in 2023.",
   """
   SELECT countIf(duration = 'freehold'), countIf(duration = 'leasehold')
   FROM uk_prices_3
   WHERE toYear(date) = 2023
   """)

# =====================================================================
# L. Load data
# =====================================================================

ex("L1", "Infer a file's schema",
   f"""
   Show the schema ClickHouse infers for the raw price file, without loading it:
     {PRICES_URL}
   (Local OSS server: pass NOSIGN after the URL.)
   """,
   f"DESC s3('{PRICES_URL}', NOSIGN)",
   ordered=True,
   hints=["DESC works on table functions too.", "s3('url', NOSIGN)"])

ex("L2", "Memory table from S3",
   f"""
   Create a table `uk_prices_temp` with the Memory engine, filled with the first 100 rows
   of the raw price file in one statement (CREATE ... AS SELECT):
     {PRICES_URL}
   """,
   f"""
   CREATE OR REPLACE TABLE uk_prices_temp
   ENGINE = Memory
   AS
       SELECT *
       FROM s3('{PRICES_URL}', NOSIGN)
       LIMIT 100
   """,
   check=[exists("uk_prices_temp", "Memory"),
          is_true("SELECT count() = 100 FROM gym.uk_prices_temp", "`uk_prices_temp` should hold exactly 100 rows")],
   setup=["DROP TABLE IF EXISTS uk_prices_temp"],
   hints=["CREATE TABLE ... ENGINE = Memory AS SELECT ...", "No column list is needed: it is inferred."])

ex("L3", "Query a CSV in place",
   f"""
   Without creating a table, return date and variable for the 5 most recent rows of:
     {RATES_URL}
   Newest first. The file has a header row.
   """,
   f"""
   SELECT date, variable
   FROM s3('{RATES_URL}', NOSIGN, 'CSVWithNames')
   ORDER BY date DESC
   LIMIT 5
   """,
   ordered=True,
   hints=["Format CSVWithNames uses the header row as column names.",
          "url('...', 'CSVWithNames') works too."])

# =====================================================================
# T. Create tables
# =====================================================================

ex("T1", "Partitioned MergeTree",
   """
   Create `prices_by_year_dest`:
     price UInt32, date Date, addr1 String, addr2 String, and LowCardinality(String)
     columns street, town, district, county.
   MergeTree, primary key (town, date), partitioned by year of date.
   """,
   PRICES_BY_YEAR_DEST,
   check=[exists("prices_by_year_dest", "MergeTree"),
          cols("prices_by_year_dest", [("price", "UInt32"), ("date", "Date"), ("addr1", "String"),
                                       ("addr2", "String"), ("street", "LowCardinality(String)"),
                                       ("town", "LowCardinality(String)"), ("district", "LowCardinality(String)"),
                                       ("county", "LowCardinality(String)")]),
          field("prices_by_year_dest", "sorting_key", "town, date", "Primary key / ORDER BY should be (town, date)"),
          field("prices_by_year_dest", "partition_key", "toYear(date)", "PARTITION BY should be toYear(date)")],
   setup=["DROP VIEW IF EXISTS prices_by_year_view", "DROP TABLE IF EXISTS prices_by_year_dest"],
   hints=["PRIMARY KEY (...) without ORDER BY makes ORDER BY the same.", "PARTITION BY toYear(date)"])

ex("T2", "Fill a table from another",
   "Copy every row of `uk_prices_3` into `prices_by_year_dest` (only the columns it has).",
   PRICES_BY_YEAR_FILL,
   check=[is_true("SELECT (SELECT count() FROM gym.prices_by_year_dest) = (SELECT count() FROM gym.uk_prices_3)",
                  "`prices_by_year_dest` should have the same row count as `uk_prices_3`")],
   setup=["DROP VIEW IF EXISTS prices_by_year_view", if_not_exists(PRICES_BY_YEAR_DEST),
          "TRUNCATE TABLE prices_by_year_dest"],
   hints=["INSERT INTO target SELECT col1, col2, ... FROM source"])

ex("T3", "ReplacingMergeTree from a CSV",
   f"""
   Create `rates_monthly` (month Date, variable, fixed, bank all Decimal32(2)),
   ReplacingMergeTree with primary key month. Then load it from:
     {RATES_URL}
   (header row; convert the file's `date` to a Date called month)
   """,
   RATES_MONTHLY + ";\n\n" + RATES_MONTHLY_FILL,
   check=[exists("rates_monthly", "ReplacingMergeTree"),
          cols("rates_monthly", [("month", "Date"), ("variable", "Decimal(9, 2)"),
                                 ("fixed", "Decimal(9, 2)"), ("bank", "Decimal(9, 2)")]),
          field("rates_monthly", "sorting_key", "month", "Primary key should be month"),
          is_true(f"SELECT (SELECT count() FROM gym.rates_monthly) = (SELECT count() FROM s3('{RATES_URL}', NOSIGN, 'CSVWithNames'))",
                  "`rates_monthly` should hold every row of the CSV")],
   setup=["DROP TABLE IF EXISTS rates_monthly"],
   hints=["You can send both statements at once, separated by ;",
          "toDate(date) AS month"])

ex("T4", "Codecs and TTL",
   """
   Create `prices_2` with:
     price UInt32 compressed with T64 then LZ4
     date Date compressed with DoubleDelta then ZSTD
     postcode1 String, postcode2 String
     is_new UInt8 compressed with LZ4HC
   MergeTree ordered by date, and rows expire 5 years after date.
   """,
   """
   CREATE TABLE prices_2 (
       price UInt32 CODEC(T64, LZ4),
       date Date CODEC(DoubleDelta, ZSTD),
       postcode1 String,
       postcode2 String,
       is_new UInt8 CODEC(LZ4HC)
   )
   ENGINE = MergeTree
   ORDER BY date
   TTL date + INTERVAL 5 YEAR
   """,
   check=[exists("prices_2", "MergeTree"),
          field("prices_2", "sorting_key", "date", "ORDER BY should be date"),
          is_true("SELECT compression_codec ILIKE '%T64%LZ4%' FROM system.columns WHERE database = 'gym' AND table = 'prices_2' AND name = 'price'",
                  "price should use CODEC(T64, LZ4)"),
          is_true("SELECT compression_codec ILIKE '%DoubleDelta%ZSTD%' FROM system.columns WHERE database = 'gym' AND table = 'prices_2' AND name = 'date'",
                  "date should use CODEC(DoubleDelta, ZSTD)"),
          is_true("SELECT compression_codec ILIKE '%LZ4HC%' FROM system.columns WHERE database = 'gym' AND table = 'prices_2' AND name = 'is_new'",
                  "is_new should use CODEC(LZ4HC)"),
          ddl_has("prices_2", "TTL date + toIntervalYear(5)", "Table TTL should be date + INTERVAL 5 YEAR")],
   setup=["DROP TABLE IF EXISTS prices_2"],
   hints=["Column codec syntax: col Type CODEC(A, B)", "Table TTL goes after ORDER BY: TTL date + INTERVAL 5 YEAR"])

ex("T5", "CollapsingMergeTree table",
   """
   Create `messages` (id UInt32, day Date, message String, sign Int8) using the engine
   that cancels rows with sign -1 against rows with sign 1. Primary key id.
   """,
   MESSAGES,
   check=[exists("messages", "CollapsingMergeTree"),
          cols("messages", [("id", "UInt32"), ("day", "Date"), ("message", "String"), ("sign", "Int8")]),
          ddl_has("messages", "CollapsingMergeTree(sign)", "The engine needs the sign column: CollapsingMergeTree(sign)"),
          field("messages", "sorting_key", "id", "Primary key should be id")],
   setup=["DROP TABLE IF EXISTS messages"])

# =====================================================================
# U. Update and delete
# =====================================================================

ex("U1", "Replace a row, read it with FINAL",
   """
   `rates_monthly` is a ReplacingMergeTree keyed on month. Insert a new row for
   2022-05-31 with variable 3.2, fixed 3.0, bank 1.1. Then select that month so that only
   the latest version comes back, even before a merge.
   """,
   """
   INSERT INTO rates_monthly VALUES ('2022-05-31', 3.2, 3.0, 1.1);

   SELECT * FROM rates_monthly FINAL WHERE month = '2022-05-31'
   """,
   check=[is_true("SELECT count() >= 2 FROM gym.rates_monthly WHERE month = '2022-05-31'",
                  "Insert a second row for 2022-05-31 (the original is still there until a merge)"),
          is_true("SELECT count() = 1 AND any(variable) = 3.2 FROM gym.rates_monthly FINAL WHERE month = '2022-05-31'",
                  "With FINAL, 2022-05-31 should return one row with variable 3.2")],
   setup=["DROP TABLE IF EXISTS rates_monthly"] + ENSURE_RATES_MONTHLY,
   hints=["Without FINAL you may see both rows.", "SELECT ... FROM t FINAL WHERE ..."])

ex("U2", "ReplacingMergeTree with a version",
   """
   Create `rates_monthly2`: the same columns as rates_monthly plus version UInt32,
   ReplacingMergeTree that keeps the row with the highest version, primary key month.
   Fill it from rates_monthly with version = 1.
   """,
   RATES_MONTHLY2 + ";\n\n" + RATES_MONTHLY2_FILL,
   check=[exists("rates_monthly2", "ReplacingMergeTree"),
          ddl_has("rates_monthly2", "ReplacingMergeTree(version)", "The engine should be ReplacingMergeTree(version)"),
          cols("rates_monthly2", [("month", "Date"), ("variable", "Decimal(9, 2)"), ("fixed", "Decimal(9, 2)"),
                                  ("bank", "Decimal(9, 2)"), ("version", "UInt32")]),
          is_true("SELECT (SELECT uniqExact(month) FROM gym.rates_monthly2) = (SELECT uniqExact(month) FROM gym.rates_monthly)",
                  "Copy every month of rates_monthly"),
          is_true("SELECT min(version) = 1 AND max(version) = 1 FROM gym.rates_monthly2", "Every copied row should have version 1")],
   setup=ENSURE_RATES_MONTHLY + ["DROP TABLE IF EXISTS rates_monthly2"],
   hints=["ReplacingMergeTree(version_column)", "INSERT INTO ... SELECT month, variable, fixed, bank, 1 FROM ..."])

ex("U3", "Out-of-order versions",
   """
   In `rates_monthly2`, insert for 2022-04-30 first (3.1, 2.6, 1.1) with version 10, then
   (2.9, 2.4, 0.9) with version 5, as two separate INSERTs. Then query that month so the
   winning version is returned.
   """,
   """
   INSERT INTO rates_monthly2 VALUES ('2022-04-30', 3.1, 2.6, 1.1, 10);
   INSERT INTO rates_monthly2 VALUES ('2022-04-30', 2.9, 2.4, 0.9, 5);

   SELECT * FROM rates_monthly2 FINAL WHERE month = '2022-04-30'
   """,
   check=[is_true("SELECT countIf(version = 10) >= 1 AND countIf(version = 5) >= 1 FROM gym.rates_monthly2 WHERE month = '2022-04-30'",
                  "Insert both versions (10 and 5) for 2022-04-30"),
          is_true("SELECT count() = 1 AND any(version) = 10 AND any(variable) = 3.1 FROM gym.rates_monthly2 FINAL WHERE month = '2022-04-30'",
                  "With FINAL, version 10 (variable 3.1) must win even though it was inserted first")],
   setup=RESET_RATES_MONTHLY2,
   hints=["The highest version wins, regardless of insert order."])

ex("U4", "Update and delete with sign rows",
   """
   `messages` is a CollapsingMergeTree(sign) table (empty). Make the collapsed result be:
     id 1 'Hello' (2024-07-04) and id 2 'Goodbye' (2024-07-05), and nothing else.
   Do it by first inserting (1 'Hello'), (2 'Hi'), (3 'Bonjour') on 2024-07-04, then
   changing id 2 and removing id 3 only with further INSERTs. Check with FINAL.
   """,
   """
   INSERT INTO messages VALUES
       (1, '2024-07-04', 'Hello', 1),
       (2, '2024-07-04', 'Hi', 1),
       (3, '2024-07-04', 'Bonjour', 1);

   INSERT INTO messages VALUES
       (2, '2024-07-04', 'Hi', -1),
       (2, '2024-07-05', 'Goodbye', 1);

   INSERT INTO messages (id, sign) VALUES (3, -1);

   SELECT * FROM messages FINAL
   """,
   check=[is_true("SELECT count() >= 6 FROM gym.messages", "Do the changes with INSERTs of sign rows, not ALTER/DELETE"),
          is_true("SELECT groupArray((id, message)) = [(1, 'Hello'), (2, 'Goodbye')] FROM (SELECT id, message FROM gym.messages FINAL ORDER BY id)",
                  "SELECT ... FINAL should return exactly (1, 'Hello') and (2, 'Goodbye')")],
   setup=["DROP TABLE IF EXISTS messages", MESSAGES],
   hints=["Cancel a row by inserting the same key with sign = -1.",
          "An update = cancel row (-1) + new row (1).",
          "For a delete only the key and sign matter: INSERT INTO messages (id, sign) VALUES (3, -1)"])

ex("U5", "Lightweight delete",
   "Delete every row of `rates_monthly2` with a month before 2010-01-01 using a lightweight delete.",
   "DELETE FROM rates_monthly2 WHERE month < '2010-01-01'",
   check=[is_true("SELECT countIf(month < '2010-01-01') = 0 AND count() > 0 FROM gym.rates_monthly2",
                  "No rows before 2010 should remain (and later rows should stay)")],
   setup=RESET_RATES_MONTHLY2,
   hints=["Lightweight: DELETE FROM t WHERE ...", "Heavy mutation alternative: ALTER TABLE t DELETE WHERE ..."])

ex("U6", "Update with a mutation",
   """
   Set bank = 0.5 for every 2021 row of `rates_monthly2` using an ALTER TABLE mutation,
   and make the statement wait until the mutation has finished.
   """,
   "ALTER TABLE rates_monthly2 UPDATE bank = 0.5 WHERE toYear(month) = 2021 SETTINGS mutations_sync = 1",
   check=[is_true("SELECT countIf(toYear(month) = 2021 AND bank != 0.5) = 0 AND countIf(toYear(month) = 2021) > 0 FROM gym.rates_monthly2",
                  "Every 2021 row should have bank = 0.5")],
   setup=RESET_RATES_MONTHLY2,
   hints=["ALTER TABLE t UPDATE col = value WHERE ...", "SETTINGS mutations_sync = 1 waits for completion.",
          "Key columns (month here) cannot be updated."])

# =====================================================================
# V. Materialized views
# =====================================================================

ex("V1", "Incremental MV into an existing table",
   """
   Create the materialized view `prices_by_year_view` that writes every new row of
   `uk_prices_3` into the existing table `prices_by_year_dest` (all of its columns).
   """,
   PRICES_BY_YEAR_VIEW,
   check=[exists("prices_by_year_view", "MaterializedView"),
          ddl_has("prices_by_year_view", "TO gym.prices_by_year_dest", "The view should write TO prices_by_year_dest"),
          ddl_has("prices_by_year_view", "FROM gym.uk_prices_3", "The view should read FROM uk_prices_3")],
   setup=["DROP VIEW IF EXISTS prices_by_year_view"] + ENSURE_PRICES_BY_YEAR,
   hints=["CREATE MATERIALIZED VIEW name TO target AS SELECT ...",
          "An MV only sees new inserts; backfilling is a separate INSERT ... SELECT."])

ex("V2", "SummingMergeTree rollup + MV",
   """
   Create `prices_sum_dest` (town LowCardinality(String), sum_price UInt64), a
   SummingMergeTree with primary key town. Then create `prices_sum_view` that keeps it
   updated with the total price per town from new rows of `uk_prices_3`.
   """,
   PRICES_SUM_DEST + ";\n\n" + PRICES_SUM_VIEW,
   check=[exists("prices_sum_dest", "SummingMergeTree"),
          cols("prices_sum_dest", [("town", "LowCardinality(String)"), ("sum_price", "UInt64")]),
          field("prices_sum_dest", "sorting_key", "town", "Primary key should be town"),
          exists("prices_sum_view", "MaterializedView"),
          ddl_has("prices_sum_view", "TO gym.prices_sum_dest", "The view should write TO prices_sum_dest"),
          ddl_has("prices_sum_view", "GROUP BY town", "The view should GROUP BY town")],
   setup=["DROP VIEW IF EXISTS prices_sum_view", "DROP TABLE IF EXISTS prices_sum_dest"],
   hints=["The MV's SELECT runs per insert block: SELECT town, sum(price) AS sum_price ... GROUP BY town"])

ex("V3", "Backfill the rollup",
   "`prices_sum_dest` and its MV exist but the table is empty. Backfill it from the existing rows of `uk_prices_3`.",
   PRICES_SUM_FILL,
   check=[is_true("SELECT (SELECT sum(sum_price) FROM gym.prices_sum_dest) = (SELECT sum(price) FROM gym.uk_prices_3)",
                  "The total of sum_price should equal sum(price) of uk_prices_3"),
          is_true("SELECT (SELECT uniqExact(town) FROM gym.prices_sum_dest) = (SELECT uniqExact(town) FROM gym.uk_prices_3)",
                  "Every town should be present")],
   setup=[if_not_exists(PRICES_SUM_DEST), if_not_exists(PRICES_SUM_VIEW), "TRUNCATE TABLE prices_sum_dest"],
   hints=["Same SELECT as the view, as an INSERT INTO prices_sum_dest SELECT ..."])

ex("V4", "Query a SummingMergeTree correctly",
   """
   From `prices_sum_dest` (not uk_prices_3), return LONDON's town and total price as one
   row. Your query must be correct even when parts haven't merged yet.
   """,
   """
   SELECT town, sum(sum_price) AS sum
   FROM prices_sum_dest
   WHERE town = 'LONDON'
   GROUP BY town
   """,
   setup=ENSURE_PRICES_SUM + [
       ("if_empty_where", "uk_prices_3", "street = 'My Street1'",
        "INSERT INTO uk_prices_3 (price, date, town, street) VALUES (4294967295, toDate('1994-01-01'), 'LONDON', 'My Street1')")],
   hints=["Rows are only summed during merges; several rows per town can exist.",
          "Always aggregate again on read: sum(sum_price) ... GROUP BY town"])

ex("V5", "Watch the MV fire",
   """
   Insert one sale into `uk_prices_3`: price 250000, date today, town 'GYM TOWN'.
   Then query `prices_sum_dest` for GYM TOWN to see the MV picked it up.
   """,
   """
   INSERT INTO uk_prices_3 (price, date, town) VALUES (250000, today(), 'GYM TOWN');

   SELECT town, sum(sum_price) FROM prices_sum_dest WHERE town = 'GYM TOWN' GROUP BY town
   """,
   check=[is_true("SELECT (SELECT sum(price) FROM gym.uk_prices_3 WHERE town = 'GYM TOWN') > 0",
                  "Insert a row for town 'GYM TOWN' into uk_prices_3"),
          is_true("SELECT (SELECT sum(sum_price) FROM gym.prices_sum_dest WHERE town = 'GYM TOWN') = (SELECT sum(price) FROM gym.uk_prices_3 WHERE town = 'GYM TOWN')",
                  "prices_sum_dest should contain GYM TOWN's total")],
   setup=ENSURE_PRICES_SUM,
   hints=["List only the columns you set: INSERT INTO t (price, date, town) VALUES (...)"])

ex("V6", "AggregatingMergeTree + MV",
   """
   Create `uk_prices_aggs_dest`, an AggregatingMergeTree with primary key month:
     month Date
     min_price  SimpleAggregateFunction(min, UInt32)
     max_price  SimpleAggregateFunction(max, UInt32)
     volume     AggregateFunction(count, UInt32)
     avg_price  AggregateFunction(avg, UInt32)
   Then create `uk_prices_aggs_view` that fills it per month (toStartOfMonth(date))
   from new rows of `uk_prices_3`.
   """,
   AGGS_DEST + ";\n\n" + AGGS_VIEW,
   check=[exists("uk_prices_aggs_dest", "AggregatingMergeTree"),
          cols("uk_prices_aggs_dest", [("month", "Date"),
                                       ("min_price", "SimpleAggregateFunction(min, UInt32)"),
                                       ("max_price", "SimpleAggregateFunction(max, UInt32)"),
                                       ("volume", "AggregateFunction(count, UInt32)"),
                                       ("avg_price", "AggregateFunction(avg, UInt32)")]),
          field("uk_prices_aggs_dest", "sorting_key", "month", "Primary key should be month"),
          exists("uk_prices_aggs_view", "MaterializedView"),
          ddl_has("uk_prices_aggs_view", "TO gym.uk_prices_aggs_dest", "The view should write TO uk_prices_aggs_dest"),
          ddl_has("uk_prices_aggs_view", "avgState", "Write avg_price with avgState(price)"),
          ddl_has("uk_prices_aggs_view", "countState", "Write volume with countState(price)")],
   setup=["DROP VIEW IF EXISTS uk_prices_aggs_view", "DROP TABLE IF EXISTS uk_prices_aggs_dest"],
   hints=["SimpleAggregateFunction columns take minSimpleState / maxSimpleState (or plain min/max).",
          "AggregateFunction columns need the -State combinator: countState(price), avgState(price)."])

ex("V7", "Backfill with -State",
   "`uk_prices_aggs_dest` exists but is empty. Backfill it from all existing rows of `uk_prices_3`.",
   AGGS_FILL,
   check=[is_true("SELECT (SELECT countMerge(volume) FROM gym.uk_prices_aggs_dest) = (SELECT count() FROM gym.uk_prices_3)",
                  "countMerge(volume) over the table should equal count() of uk_prices_3"),
          is_true("SELECT (SELECT max(max_price) FROM gym.uk_prices_aggs_dest) = (SELECT max(price) FROM gym.uk_prices_3)",
                  "max_price should be filled")],
   setup=[if_not_exists(AGGS_DEST), if_not_exists(AGGS_VIEW), "TRUNCATE TABLE uk_prices_aggs_dest"],
   hints=["Reuse the view's SELECT: INSERT INTO uk_prices_aggs_dest WITH ... SELECT ..."])

ex("V8", "Read SimpleAggregateFunction columns",
   "From `uk_prices_aggs_dest`: month, min price, max price for each month of 2023, newest first.",
   """
   SELECT month, min(min_price), max(max_price)
   FROM uk_prices_aggs_dest
   WHERE month >= toDate('2023-01-01') AND month < toDate('2024-01-01')
   GROUP BY month
   ORDER BY month DESC
   """,
   ordered=True,
   setup=ENSURE_AGGS,
   hints=["SimpleAggregateFunction columns are read with the plain function: min(min_price)"])

ex("V9", "Read AggregateFunction states",
   "From `uk_prices_aggs_dest`: month and average price for each month of 2020, oldest first.",
   """
   SELECT month, avgMerge(avg_price)
   FROM uk_prices_aggs_dest
   WHERE toYear(month) = 2020
   GROUP BY month
   ORDER BY month
   """,
   ordered=True,
   setup=ENSURE_AGGS,
   hints=["States are finalized with the -Merge combinator."])

ex("V10", "Count from states",
   "From `uk_prices_aggs_dest`: the total number of sales in 2020 (one number).",
   "SELECT countMerge(volume) FROM uk_prices_aggs_dest WHERE toYear(month) = 2020",
   setup=ENSURE_AGGS)

ex("V11", "Refreshable MV",
   """
   Create `uk_averages_by_day` (day Date, average_price UInt32), MergeTree with primary
   key day. Then create `uk_averages_by_day_mv`, a materialized view that every 12 hours
   recomputes the average price per day for 2025 onwards into that table.
   """,
   """
   CREATE TABLE uk_averages_by_day (
       day Date,
       average_price UInt32
   )
   ENGINE = MergeTree
   PRIMARY KEY day;

   CREATE MATERIALIZED VIEW uk_averages_by_day_mv
   REFRESH EVERY 12 HOURS
   TO uk_averages_by_day
   AS
       SELECT toDate(date) AS day, avg(price) AS average_price
       FROM uk_prices_3
       WHERE toYear(date) >= 2025
       GROUP BY day
   """,
   check=[exists("uk_averages_by_day", "MergeTree"),
          cols("uk_averages_by_day", [("day", "Date"), ("average_price", "UInt32")]),
          exists("uk_averages_by_day_mv", "MaterializedView"),
          is_true("SELECT count() = 1 FROM system.view_refreshes WHERE database = 'gym' AND view = 'uk_averages_by_day_mv'",
                  "uk_averages_by_day_mv should be a refreshable view (REFRESH EVERY ...)"),
          ddl_has("uk_averages_by_day_mv", "EVERY 12 HOUR", "Refresh interval should be 12 hours"),
          is_true("SELECT count() > 0 FROM gym.uk_averages_by_day", "After the first refresh the table should have rows")],
   setup=["DROP VIEW IF EXISTS uk_averages_by_day_mv", "DROP TABLE IF EXISTS uk_averages_by_day"],
   hints=["CREATE MATERIALIZED VIEW name REFRESH EVERY 12 HOURS TO target AS SELECT ...",
          "The first refresh runs right after creation."])

# =====================================================================
# D. Dictionaries and joins
# =====================================================================

ex("D1", "Dictionary from an HTTP source",
   f"""
   Create the dictionary `uk_mortgage_rates` (date DateTime64, variable, fixed, bank all
   Decimal32(2)) keyed on date, loaded over HTTP from:
     {RATES_URL}
   (CSV with header). Use the COMPLEX_KEY_HASHED layout and refresh about once a month
   (LIFETIME 2628000 seconds). On local OSS add SETTINGS(date_time_input_format = 'best_effort').
   """,
   RATES_DICT,
   check=[exists("uk_mortgage_rates", "Dictionary"),
          ddl_has("uk_mortgage_rates", "SOURCE(HTTP", "The source should be HTTP(url ... format 'CSVWithNames')"),
          ddl_has("uk_mortgage_rates", "COMPLEX_KEY_HASHED", "Layout should be COMPLEX_KEY_HASHED()"),
          ddl_has("uk_mortgage_rates", "LIFETIME", "Set a LIFETIME"),
          is_true("SELECT count() > 200 FROM gym.uk_mortgage_rates", "The dictionary should load all rows from the CSV")],
   setup=["DROP DICTIONARY IF EXISTS uk_mortgage_rates"],
   hints=["CREATE DICTIONARY name (cols) PRIMARY KEY ... SOURCE(...) LAYOUT(...) LIFETIME(...)",
          "SOURCE(HTTP(url '...' format 'CSVWithNames'))",
          "A non-integer key needs a COMPLEX_KEY_* layout."])

ex("D2", "Read a dictionary",
   "Return all columns of the 5 most recent rows of the `uk_mortgage_rates` dictionary, newest first.",
   "SELECT * FROM uk_mortgage_rates ORDER BY date DESC LIMIT 5",
   ordered=True,
   setup=ENSURE_DICT,
   hints=["A dictionary can be queried like a table."])

ex("D3", "Join sales with rates",
   """
   Join `uk_prices_3` with the `uk_mortgage_rates` dictionary on month
   (toStartOfMonth of each side's date). Per month return: month, number of sales,
   and the variable rate (any()).
   """,
   """
   WITH toStartOfMonth(uk_prices_3.date) AS month
   SELECT month, count(), any(variable)
   FROM uk_prices_3
   JOIN uk_mortgage_rates
   ON month = toStartOfMonth(uk_mortgage_rates.date)
   GROUP BY month
   """,
   setup=ENSURE_DICT,
   hints=["Dictionaries can be the right side of a JOIN.",
          "Qualify the ambiguous column: uk_prices_3.date vs uk_mortgage_rates.date"])

ex("D4", "Correlation with the variable rate",
   """
   Using the per-month join from the previous exercise, return the correlation between
   monthly sales count and the variable rate (convert both to Float32).
   """,
   """
   SELECT corr(toFloat32(count), toFloat32(variable))
   FROM (
       WITH toStartOfMonth(uk_prices_3.date) AS month
       SELECT month, count() AS count, any(variable) AS variable
       FROM uk_prices_3
       JOIN uk_mortgage_rates
       ON month = toStartOfMonth(uk_mortgage_rates.date)
       GROUP BY month
   )
   """,
   setup=ENSURE_DICT,
   hints=["corr(x, y) over a subquery"])

ex("D5", "Correlation with the fixed rate since 2000",
   "Same as before, but with the fixed rate and only months from 2000-01-01 onwards.",
   """
   SELECT corr(toFloat32(count), toFloat32(fixed))
   FROM (
       WITH toStartOfMonth(uk_prices_3.date) AS month
       SELECT month, count() AS count, any(fixed) AS fixed
       FROM uk_prices_3
       JOIN uk_mortgage_rates
       ON month = toStartOfMonth(uk_mortgage_rates.date)
       WHERE month >= toDate('2000-01-01')
       GROUP BY month
   )
   """,
   setup=ENSURE_DICT)

ex("D6", "Point lookup with dictGet",
   """
   Without a JOIN, return the fixed rate from `uk_mortgage_rates` for the key 2022-05-31
   using dictGet. (A complex-key dictionary takes the key as a tuple.)
   """,
   "SELECT dictGet('uk_mortgage_rates', 'fixed', tuple(toDateTime64('2022-05-31', 3)))",
   setup=ENSURE_DICT,
   hints=["dictGet('dict_name', 'attribute', key)",
          "Complex key: tuple(...), and the type must match DateTime64(3)."])

# =====================================================================
# A. Accelerate queries
# =====================================================================

ex("A1", "See index usage",
   "Show which parts and granules the primary key keeps for: SELECT count() FROM uk_prices_3 WHERE postcode1 = 'LU1'",
   "EXPLAIN indexes = 1 SELECT count() FROM uk_prices_3 WHERE postcode1 = 'LU1'",
   ordered=True,
   hints=["EXPLAIN has an option for this.", "EXPLAIN indexes = 1 <query>"])

ex("A2", "Bloom filter skipping index",
   """
   Add a skipping index `county_index` on the county column of `uk_prices_3`, type
   bloom_filter, granularity 1, and build it for the existing data (wait until done).
   """,
   """
   ALTER TABLE uk_prices_3
       ADD INDEX county_index county
       TYPE bloom_filter
       GRANULARITY 1;

   ALTER TABLE uk_prices_3 MATERIALIZE INDEX county_index SETTINGS mutations_sync = 1
   """,
   check=[is_true("SELECT count() = 1 FROM system.data_skipping_indices WHERE database = 'gym' AND table = 'uk_prices_3' AND name = 'county_index' AND type = 'bloom_filter' AND expr = 'county' AND granularity = 1",
                  "county_index should be a bloom_filter index on county with GRANULARITY 1"),
          is_true("SELECT min(secondary_indices_compressed_bytes) > 0 FROM system.parts WHERE database = 'gym' AND table = 'uk_prices_3' AND active",
                  "MATERIALIZE INDEX so existing parts get the index")],
   setup=["ALTER TABLE uk_prices_3 DROP INDEX IF EXISTS county_index"],
   hints=["ALTER TABLE t ADD INDEX name expr TYPE type GRANULARITY n",
          "New indexes only cover new parts until: ALTER TABLE t MATERIALIZE INDEX name",
          "SETTINGS mutations_sync = 1 makes the ALTER wait."])

ex("A3", "Projection with a different sort order",
   """
   Add a projection `town_date_projection` to `uk_prices_3` that stores town, date and
   price sorted by town, date. Then build it for the existing data (wait until done).
   """,
   """
   ALTER TABLE uk_prices_3
       ADD PROJECTION town_date_projection (
           SELECT town, date, price
           ORDER BY town, date
       );

   ALTER TABLE uk_prices_3 MATERIALIZE PROJECTION town_date_projection SETTINGS mutations_sync = 1
   """,
   check=[ddl_has("uk_prices_3", "PROJECTION town_date_projection", "Add PROJECTION town_date_projection"),
          is_true("SELECT count() > 0 FROM system.projection_parts WHERE database = 'gym' AND table = 'uk_prices_3' AND name = 'town_date_projection' AND active",
                  "MATERIALIZE PROJECTION so existing parts get it")],
   setup=["ALTER TABLE uk_prices_3 DROP PROJECTION IF EXISTS town_date_projection"],
   hints=["ALTER TABLE t ADD PROJECTION name (SELECT ... ORDER BY ...)",
          "ALTER TABLE t MATERIALIZE PROJECTION name"])

ex("A4", "Aggregating projection",
   """
   Add a projection `handy_aggs_projection` to `uk_prices_3` holding avg(price),
   max(price) and sum(price) grouped by town, then materialize it (wait until done).
   """,
   """
   ALTER TABLE uk_prices_3
       ADD PROJECTION handy_aggs_projection (
           SELECT avg(price), max(price), sum(price)
           GROUP BY town
       );

   ALTER TABLE uk_prices_3 MATERIALIZE PROJECTION handy_aggs_projection SETTINGS mutations_sync = 1
   """,
   check=[ddl_has("uk_prices_3", "PROJECTION handy_aggs_projection", "Add PROJECTION handy_aggs_projection"),
          ddl_has("uk_prices_3", "GROUP BY town", "The projection should GROUP BY town"),
          is_true("SELECT count() > 0 FROM system.projection_parts WHERE database = 'gym' AND table = 'uk_prices_3' AND name = 'handy_aggs_projection' AND active",
                  "MATERIALIZE PROJECTION so existing parts get it")],
   setup=["ALTER TABLE uk_prices_3 DROP PROJECTION IF EXISTS handy_aggs_projection"],
   hints=["Aggregating projection: (SELECT agg(...), ... GROUP BY col)"])

ex("A5", "Change retention",
   "Change the table TTL of `prices_2` so rows expire 10 years after date.",
   "ALTER TABLE prices_2 MODIFY TTL date + INTERVAL 10 YEAR",
   check=[ddl_has("prices_2", "TTL date + toIntervalYear(10)", "prices_2 TTL should be date + INTERVAL 10 YEAR")],
   setup=["DROP TABLE IF EXISTS prices_2",
          "CREATE TABLE prices_2 (price UInt32 CODEC(T64, LZ4), date Date CODEC(DoubleDelta, ZSTD), "
          "postcode1 String, postcode2 String, is_new UInt8 CODEC(LZ4HC)) "
          "ENGINE = MergeTree ORDER BY date TTL date + INTERVAL 5 YEAR"],
   hints=["ALTER TABLE t MODIFY TTL <expr>", "ALTER TABLE t MATERIALIZE TTL applies it to existing parts."])

# =====================================================================
# F. Common functions (strings, dates, numbers, conditionals, arrays)
# =====================================================================

ex("F1", "Lower case and length",
   "For every distinct town starting with 'NEW': town, the town in lower case, and its length in characters.",
   """
   SELECT DISTINCT town, lower(town), length(town)
   FROM uk_prices_3
   WHERE startsWith(town, 'NEW')
   """,
   hints=["startsWith(s, prefix) or LIKE 'NEW%'", "lower(), upper(), length() (bytes) / lengthUTF8() (characters)"])

ex("F2", "Build an address string",
   """
   For the 5 most expensive sales (ties: street A to Z): price and one address string in the
   form 'STREET, TOWN'. Highest price first.
   """,
   """
   SELECT price, concat(street, ', ', town) AS address
   FROM uk_prices_3
   ORDER BY price DESC, street ASC
   LIMIT 5
   """,
   ordered=True,
   hints=["concat(a, b, c) or a || b || c"])

ex("F3", "Postcode areas with a regex",
   """
   The postcode area is the leading letters of postcode1 ('LU' for 'LU1', 'B' for 'B77').
   How many distinct non-empty postcode areas are there?
   """,
   """
   SELECT uniqExact(extract(postcode1, '^[A-Z]+'))
   FROM uk_prices_3
   WHERE postcode1 != ''
   """,
   hints=["extract(haystack, regex) returns the first match.", "Regex: '^[A-Z]+'"])

ex("F4", "Case-insensitive search",
   "How many sales are on a street whose name contains 'abbey' in any letter case?",
   "SELECT countIf(street ILIKE '%abbey%') FROM uk_prices_3",
   hints=["ILIKE is the case-insensitive LIKE.", "positionCaseInsensitive(street, 'abbey') > 0 also works."])

ex("F5", "Prefix match",
   "How many sales are on streets that start with 'HIGH '?",
   "SELECT count() FROM uk_prices_3 WHERE startsWith(street, 'HIGH ')")

ex("F6", "Replace characters",
   "For every distinct county starting with 'WEST': the county and the county with spaces replaced by underscores.",
   """
   SELECT DISTINCT county, replaceAll(county, ' ', '_')
   FROM uk_prices_3
   WHERE county LIKE 'WEST%'
   """,
   hints=["replaceAll(s, from, to); replaceRegexpAll for regexes"])

ex("F7", "Sales by weekday",
   "In 2020, the number of sales per day of the week (1 = Monday … 7 = Sunday), Monday first.",
   """
   SELECT toDayOfWeek(date) AS dow, count()
   FROM uk_prices_3
   WHERE toYear(date) = 2020
   GROUP BY dow
   ORDER BY dow
   """,
   ordered=True,
   hints=["toDayOfWeek(date) returns 1..7 with Monday = 1."])

ex("F8", "Format dates as text",
   "Sales count per month of 2022 with the month as text like '2022-01'. Oldest first.",
   """
   SELECT formatDateTime(date, '%Y-%m') AS ym, count()
   FROM uk_prices_3
   WHERE toYear(date) = 2022
   GROUP BY ym
   ORDER BY ym
   """,
   ordered=True,
   hints=["formatDateTime(date, '%Y-%m')"])

ex("F9", "Days covered",
   "How many days lie between the earliest and the latest sale in the table?",
   "SELECT dateDiff('day', min(date), max(date)) FROM uk_prices_3",
   hints=["dateDiff('unit', start, end)"])

ex("F10", "Last 12 months of data",
   "How many sales happened in the 12 months before the latest sale date in the table (date > max_date - 12 months)?",
   """
   WITH (SELECT max(date) FROM uk_prices_3) AS max_date
   SELECT count()
   FROM uk_prices_3
   WHERE date > max_date - INTERVAL 12 MONTH
   """,
   hints=["Compute the latest date with a scalar subquery.", "date - INTERVAL 12 MONTH"])

ex("F11", "Quarterly volume",
   "Sales count per quarter of 2023 (quarter start date, count). Oldest first.",
   """
   SELECT toStartOfQuarter(date) AS q, count()
   FROM uk_prices_3
   WHERE toYear(date) = 2023
   GROUP BY q
   ORDER BY q
   """,
   ordered=True,
   hints=["toStartOfQuarter(date)"])

ex("F12", "Round to thousands",
   "Average price per property type, rounded to the nearest 1,000.",
   "SELECT type, round(avg(price), -3) FROM uk_prices_3 GROUP BY type",
   hints=["round(x, -3) rounds to thousands."])

ex("F13", "Price bands with integer division",
   """
   London sales in 2023 under 1,000,000, grouped into 100,000-wide price bands:
   band start (0, 100000, …) and count. Lowest band first.
   """,
   """
   SELECT intDiv(price, 100000) * 100000 AS band, count()
   FROM uk_prices_3
   WHERE town = 'LONDON' AND toYear(date) = 2023 AND price < 1000000
   GROUP BY band
   ORDER BY band
   """,
   ordered=True,
   hints=["intDiv(a, b) is integer division."])

ex("F14", "Readable big numbers",
   "Total value of all 2023 sales as a human-readable quantity (e.g. '123.45 billion').",
   "SELECT formatReadableQuantity(sum(price)) FROM uk_prices_3 WHERE toYear(date) = 2023",
   hints=["formatReadableQuantity(), formatReadableSize() for bytes"])

ex("F15", "Labels with multiIf",
   """
   Label each 2023 sale 'budget' (< 200,000), 'mid' (< 500,000) or 'premium' (otherwise).
   Return label and count.
   """,
   """
   SELECT multiIf(price < 200000, 'budget', price < 500000, 'mid', 'premium') AS label, count()
   FROM uk_prices_3
   WHERE toYear(date) = 2023
   GROUP BY label
   """,
   hints=["multiIf(cond1, then1, cond2, then2, else)"])

ex("F16", "CASE expression",
   "Using CASE, label 2023 sales 'new' when is_new = 1 and 'existing' otherwise. Return label and count.",
   """
   SELECT CASE WHEN is_new = 1 THEN 'new' ELSE 'existing' END AS label, count()
   FROM uk_prices_3
   WHERE toYear(date) = 2023
   GROUP BY label
   """)

ex("F17", "Collect values into an array",
   "In one array, the 5 highest prices in the WESTMINSTER district, highest first.",
   "SELECT arraySlice(arrayReverseSort(groupArray(price)), 1, 5) FROM uk_prices_3 WHERE district = 'WESTMINSTER'",
   hints=["groupArray(col) collects values into an array.",
          "arrayReverseSort sorts descending; arraySlice(arr, 1, 5) keeps the first five."])

ex("F18", "Explode arrays into rows",
   """
   Split the street names of sales in WINDSOR into words (by space) and return the 5 most
   common words with their counts. Ties: word A to Z. Most common first.
   """,
   """
   SELECT arrayJoin(splitByChar(' ', street)) AS word, count() AS c
   FROM uk_prices_3
   WHERE town = 'WINDSOR' AND street != ''
   GROUP BY word
   ORDER BY c DESC, word ASC
   LIMIT 5
   """,
   ordered=True,
   hints=["splitByChar(' ', s) returns an array.", "arrayJoin(array) turns each element into a row."])

ex("F19", "Distinct values as a sorted array",
   "The property types sold in ASCOT, as one alphabetically sorted array of distinct values.",
   "SELECT arraySort(groupUniqArray(toString(type))) FROM uk_prices_3 WHERE town = 'ASCOT'",
   hints=["groupUniqArray collects distinct values.", "type is an Enum: toString(type) sorts by name."])

ex("F20", "Empty strings",
   "In one row: how many sales have an empty addr2, and how many have a non-empty locality.",
   "SELECT countIf(empty(addr2)), countIf(notEmpty(locality)) FROM uk_prices_3",
   hints=["empty(s) / notEmpty(s)"])

ex("F21", "Convert types",
   "Return the date (as Date, without time) of the single most expensive sale.",
   "SELECT toDate(argMax(date, price)) FROM uk_prices_3",
   hints=["argMax(date, price)", "toDate() drops the time part."])

# =====================================================================
# E. Exploratory analysis (data-scientist style questions)
# =====================================================================

ex("E1", "Summary statistics",
   """
   For 2023 prices, in one row: count, min, max, average, exact median and population
   standard deviation.
   """,
   """
   SELECT count(), min(price), max(price), avg(price), medianExact(price), stddevPop(price)
   FROM uk_prices_3
   WHERE toYear(date) = 2023
   """,
   hints=["median() is approximate; medianExact() is exact.", "stddevPop / stddevSamp"])

ex("E2", "Quartiles",
   "For 2023 prices, the exact 25th, 50th, 75th and 90th percentiles as one array.",
   "SELECT quantilesExact(0.25, 0.5, 0.75, 0.9)(price) FROM uk_prices_3 WHERE toYear(date) = 2023",
   hints=["quantilesExact(l1, l2, ...)(col) returns an array."])

ex("E3", "Share of total",
   """
   For 2023: each property type, its sales count, and its percentage of all 2023 sales
   rounded to 2 decimals. Use a window function for the total.
   """,
   """
   SELECT type, count() AS c, round(100 * c / sum(c) OVER (), 2) AS pct
   FROM uk_prices_3
   WHERE toYear(date) = 2023
   GROUP BY type
   """,
   hints=["sum(x) OVER () is the total over all result rows."])

ex("E4", "Best town per county",
   """
   For 2023, considering only towns with at least 50 sales: for each county, the town with
   the highest average price. Return county, town, average price.
   """,
   """
   SELECT county, town, avg_price
   FROM (
       SELECT county, town, avg(price) AS avg_price,
              row_number() OVER (PARTITION BY county ORDER BY avg(price) DESC) AS rn
       FROM uk_prices_3
       WHERE toYear(date) = 2023
       GROUP BY county, town
       HAVING count() >= 50
   )
   WHERE rn = 1
   """,
   hints=["HAVING filters groups after aggregation.",
          "row_number() OVER (PARTITION BY county ORDER BY ...) then keep rn = 1",
          "QUALIFY rn = 1 also works instead of a subquery."])

ex("E5", "Moving average",
   """
   For 2022 and 2023: month, monthly average price rounded to whole pounds, and the 3-month
   moving average of that value (current + 2 previous months) rounded to 2 decimals. Oldest first.
   """,
   """
   SELECT
       toStartOfMonth(date) AS month,
       round(avg(price)) AS avg_price,
       round(avg(avg_price) OVER (ORDER BY month ROWS BETWEEN 2 PRECEDING AND CURRENT ROW), 2) AS moving_avg
   FROM uk_prices_3
   WHERE toYear(date) IN (2022, 2023)
   GROUP BY month
   ORDER BY month
   """,
   ordered=True,
   hints=["Window frame: ROWS BETWEEN 2 PRECEDING AND CURRENT ROW"])

ex("E6", "Peak year",
   "Which year had the most sales? Return just the year.",
   """
   SELECT argMax(year, c)
   FROM (SELECT toYear(date) AS year, count() AS c FROM uk_prices_3 GROUP BY year)
   """,
   hints=["argMax(year, count) over a per-year subquery, or ORDER BY ... LIMIT 1"])

ex("E7", "Outliers",
   "How many 2023 sales have a price above the 2023 average plus 3 population standard deviations?",
   """
   WITH (SELECT avg(price) + 3 * stddevPop(price) FROM uk_prices_3 WHERE toYear(date) = 2023) AS threshold
   SELECT count()
   FROM uk_prices_3
   WHERE toYear(date) = 2023 AND price > threshold
   """,
   hints=["Compute the threshold with a scalar WITH (SELECT ...) AS name."])

ex("E8", "Correlation",
   "For sales from 2015 onwards, the Pearson correlation between the year (as Float64) and the price (as Float64).",
   "SELECT corr(toFloat64(toYear(date)), toFloat64(price)) FROM uk_prices_3 WHERE toYear(date) >= 2015",
   hints=["corr(x, y)"])

ex("E9", "Subtotals with ROLLUP",
   """
   For 2023 sales in KENT and ESSEX: count by county and type, plus subtotals per county and a
   grand total, using ROLLUP.
   """,
   """
   SELECT county, type, count()
   FROM uk_prices_3
   WHERE toYear(date) = 2023 AND county IN ('KENT', 'ESSEX')
   GROUP BY ROLLUP(county, type)
   """,
   hints=["GROUP BY ROLLUP(a, b) or GROUP BY a, b WITH ROLLUP"])

ex("E10", "Duplicate check",
   "Data quality: how many ids appear more than once in uk_prices_3?",
   """
   SELECT count()
   FROM (SELECT id FROM uk_prices_3 GROUP BY id HAVING count() > 1)
   """,
   hints=["GROUP BY id HAVING count() > 1, then count those rows."])

ex("E11", "Missing-value profile",
   """
   In one row, the percentage (rounded to 2 decimals) of rows with an empty postcode1,
   an empty street and an empty locality.
   """,
   """
   SELECT
       round(100 * countIf(empty(postcode1)) / count(), 2),
       round(100 * countIf(empty(street)) / count(), 2),
       round(100 * countIf(empty(locality)) / count(), 2)
   FROM uk_prices_3
   """)

ex("E12", "New-build premium",
   """
   For each year from 2015: year and the ratio of the average new-build price to the average
   price of existing properties, rounded to 3 decimals. Oldest first.
   """,
   """
   SELECT toYear(date) AS year, round(avgIf(price, is_new = 1) / avgIf(price, is_new = 0), 3)
   FROM uk_prices_3
   WHERE year >= 2015
   GROUP BY year
   ORDER BY year
   """,
   ordered=True,
   hints=["avgIf(price, is_new = 1) / avgIf(price, is_new = 0)"])

ex("E13", "London's market share",
   "Per year: year and London's share of all UK sales in percent, rounded to 2 decimals. Oldest first.",
   """
   SELECT toYear(date) AS year, round(100 * countIf(town = 'LONDON') / count(), 2)
   FROM uk_prices_3
   GROUP BY year
   ORDER BY year
   """,
   ordered=True)

ex("E14", "Rank towns",
   """
   Rank the towns of GREATER MANCHESTER by number of 2023 sales (1 = most). Return town, count
   and rank, where equal counts share a rank and the next rank is not skipped.
   """,
   """
   SELECT town, count() AS c, dense_rank() OVER (ORDER BY count() DESC) AS rnk
   FROM uk_prices_3
   WHERE county = 'GREATER MANCHESTER' AND toYear(date) = 2023
   GROUP BY town
   """,
   hints=["rank() skips after ties, dense_rank() does not, row_number() never ties."])

ex("E15", "Year-over-year volume change",
   """
   Per year from 2015: year, number of sales, and the percentage change versus the previous
   year rounded to 1 decimal (use lagInFrame; leave the first year as computed). Oldest first.
   """,
   """
   SELECT
       year,
       c,
       round(100 * (c - prev) / prev, 1) AS pct_change
   FROM (
       SELECT toYear(date) AS year, count() AS c,
              lagInFrame(count()) OVER (ORDER BY year) AS prev
       FROM uk_prices_3
       WHERE year >= 2015
       GROUP BY year
   )
   ORDER BY year
   """,
   ordered=True,
   hints=["lagInFrame(count()) OVER (ORDER BY year) gives last year's count (0 for the first year)."])

# =====================================================================
# Certification objectives not covered above
# (https://clickhouse.com/learn/certification)
# =====================================================================

ex("T0", "Create a database",
   "Create a new database named `sandbox`.",
   "CREATE DATABASE sandbox",
   check=[("SELECT count() = 1 FROM system.databases WHERE name = 'sandbox'", "Database `sandbox` should exist")],
   setup=["DROP DATABASE IF EXISTS sandbox"],
   hints=["CREATE DATABASE [IF NOT EXISTS] name"])

ex("T6", "Choose efficient data types",
   """
   The raw price file has these columns (all text in the file):
     id        GUID like '{5BBE9CB3-6332-4EB0-9CD3-8737CEA4A65A}' (braces stripped on insert)
     price     whole pounds, never negative, below 4 billion
     date      '1995-12-21 00:00'
     postcode1, postcode2   a few thousand distinct values each
     type      one of terraced, semi-detached, detached, flat, other
     is_new    yes/no flag
     duration  one of freehold, leasehold, unknown
     addr1, addr2, street   free text, high cardinality
     locality, town, district, county   a few thousand distinct values or fewer
   Create `uk_prices_typed` (MergeTree, primary key (postcode1, postcode2)) choosing the
   most efficient type for each column.
   """,
   """
   CREATE TABLE uk_prices_typed (
       id UUID,
       price UInt32,
       date DateTime,
       postcode1 LowCardinality(String),
       postcode2 LowCardinality(String),
       type Enum8('terraced' = 1, 'semi-detached' = 2, 'detached' = 3, 'flat' = 4, 'other' = 0),
       is_new UInt8,
       duration Enum8('freehold' = 1, 'leasehold' = 2, 'unknown' = 0),
       addr1 String,
       addr2 String,
       street String,
       locality LowCardinality(String),
       town LowCardinality(String),
       district LowCardinality(String),
       county LowCardinality(String)
   )
   ENGINE = MergeTree
   PRIMARY KEY (postcode1, postcode2)
   """,
   check=[exists("uk_prices_typed", "MergeTree"),
          field("uk_prices_typed", "sorting_key", "postcode1, postcode2", "Primary key should be (postcode1, postcode2)")]
   + [coltype("uk_prices_typed", c, t) for c, t in [
       ("id", ["UUID"]), ("price", ["UInt32"]), ("date", ["DateTime", "Date"]),
       ("postcode1", ["LowCardinality(String)"]), ("postcode2", ["LowCardinality(String)"]),
       ("type", "Enum8(%"), ("is_new", ["UInt8", "Bool"]), ("duration", "Enum8(%"),
       ("addr1", ["String"]), ("addr2", ["String"]), ("street", ["String", "LowCardinality(String)"]),
       ("locality", ["LowCardinality(String)"]), ("town", ["LowCardinality(String)"]),
       ("district", ["LowCardinality(String)"]), ("county", ["LowCardinality(String)"])]],
   setup=["DROP TABLE IF EXISTS uk_prices_typed"],
   hints=["A GUID fits UUID (16 bytes) instead of a 38-character String.",
          "Fixed sets of labels: Enum8. Repeating strings: LowCardinality(String).",
          "Prices below 4 billion fit UInt32. Avoid Nullable unless NULL is meaningful."])

ex("T7", "Pick the primary key from the queries",
   """
   Queries on `sales_by_county` always filter on county, usually also on type, and sometimes
   on a date range. Create it as a MergeTree with columns
     county LowCardinality(String), type Enum8('terraced' = 1, 'semi-detached' = 2,
     'detached' = 3, 'flat' = 4, 'other' = 0), date Date, price UInt32
   and the most efficient primary key for those queries.
   """,
   """
   CREATE TABLE sales_by_county (
       county LowCardinality(String),
       type Enum8('terraced' = 1, 'semi-detached' = 2, 'detached' = 3, 'flat' = 4, 'other' = 0),
       date Date,
       price UInt32
   )
   ENGINE = MergeTree
   PRIMARY KEY (county, type, date)
   """,
   check=[exists("sales_by_county", "MergeTree"),
          is_true("SELECT sorting_key IN ('county, type, date', 'county, type') FROM system.tables WHERE database = 'gym' AND name = 'sales_by_county'",
                  "Put the always-filtered column first, then the usually-filtered one, then the range column: (county, type, date)")],
   setup=["DROP TABLE IF EXISTS sales_by_county"],
   hints=["Order key columns by how often queries filter on them.",
          "Range filters (dates) usually go last in the key."])

ex("D7", "Dictionary from a ClickHouse table",
   f"""
   The table `town_county` (town, county) exists. Create the dictionary `town_dict` keyed on
   town that returns county, sourced from that table (ClickHouse source; locally it needs
   USER 'default' PASSWORD '{PASSWORD}'), COMPLEX_KEY_HASHED layout, refreshed every
   0 to 300 seconds. Then return the county of 'WINDSOR' with dictGet.
   """,
   f"""
   CREATE DICTIONARY town_dict (
       town String,
       county String
   )
   PRIMARY KEY town
   SOURCE(CLICKHOUSE(TABLE 'town_county' USER 'default' PASSWORD '{PASSWORD}'))
   LAYOUT(COMPLEX_KEY_HASHED())
   LIFETIME(MIN 0 MAX 300);

   SELECT dictGet('town_dict', 'county', tuple('WINDSOR'))
   """,
   check=[exists("town_dict", "Dictionary"),
          ddl_has("town_dict", "SOURCE(CLICKHOUSE", "Use a CLICKHOUSE(TABLE ...) source"),
          ddl_has("town_dict", "LIFETIME(MIN 0 MAX 300)", "LIFETIME(MIN 0 MAX 300)"),
          is_true("SELECT dictGet('gym.town_dict', 'county', tuple('WINDSOR')) = (SELECT county FROM gym.town_county WHERE town = 'WINDSOR')",
                  "dictGet('town_dict', 'county', tuple('WINDSOR')) should return WINDSOR's county")],
   setup=["DROP DICTIONARY IF EXISTS town_dict",
          "CREATE TABLE IF NOT EXISTS town_county ENGINE = MergeTree ORDER BY town AS "
          "SELECT town, any(county) AS county FROM uk_prices_3 GROUP BY town"],
   hints=["SOURCE(CLICKHOUSE(TABLE 'name' USER '...' PASSWORD '...'))",
          "A String key needs a COMPLEX_KEY_* layout; pass the key to dictGet as tuple('WINDSOR').",
          "LIFETIME(MIN 0 MAX 300)"])

ex("L4", "Insert a local CSV file",
   """
   The local file gym/data/london_sales.csv (CSV with a header row) holds London sales.
   Insert it into the existing table `london_sales` the way you would in clickhouse-client.
   """,
   "INSERT INTO london_sales FROM INFILE 'gym/data/london_sales.csv' FORMAT CSVWithNames",
   check=[is_true("SELECT (SELECT count() FROM gym.london_sales) = (SELECT count() FROM (SELECT 1 FROM gym.uk_prices_3 WHERE town = 'LONDON' AND toYear(date) = 2000 LIMIT 5000)) AND (SELECT count() FROM gym.london_sales) > 0",
                  "london_sales should contain every row of the file (once)")],
   setup=[("file", "gym/data/london_sales.csv",
           "SELECT toDate(date) AS date, price, street, type FROM uk_prices_3 "
           "WHERE town = 'LONDON' AND toYear(date) = 2000 ORDER BY date, price LIMIT 5000 FORMAT CSVWithNames"),
          "DROP TABLE IF EXISTS london_sales",
          "CREATE TABLE london_sales (date Date, price UInt32, street String, type LowCardinality(String)) "
          "ENGINE = MergeTree ORDER BY date"],
   hints=["INSERT INTO table FROM INFILE 'path' FORMAT <format>",
          "A header row means CSVWithNames.",
          "From a shell: clickhouse-client --query \"INSERT INTO t FORMAT CSVWithNames\" < file.csv"])

ex("L5", "Table for a Parquet file",
   """
   The local Parquet file gym/data/town_stats.parquet has the columns town (String),
   year (UInt16), sales (UInt64) and avg_price (Float64). Create the table `town_stats` with
   exactly those columns (MergeTree ordered by (town, year)) and insert the file.
   """,
   """
   CREATE TABLE town_stats (
       town String,
       year UInt16,
       sales UInt64,
       avg_price Float64
   )
   ENGINE = MergeTree
   ORDER BY (town, year);

   INSERT INTO town_stats FROM INFILE 'gym/data/town_stats.parquet' FORMAT Parquet
   """,
   check=[cols("town_stats", [("town", "String"), ("year", "UInt16"), ("sales", "UInt64"), ("avg_price", "Float64")]),
          field("town_stats", "sorting_key", "town, year", "ORDER BY should be (town, year)"),
          is_true("SELECT (SELECT count() FROM gym.town_stats) = (SELECT uniqExact(town) FROM gym.uk_prices_3 WHERE toYear(date) = 2000) AND (SELECT count() FROM gym.town_stats) > 0",
                  "town_stats should contain every row of the Parquet file (once)")],
   setup=[("file", "gym/data/town_stats.parquet",
           "SELECT toString(town) AS town, toYear(date) AS year, count() AS sales, avg(price) AS avg_price "
           "FROM uk_prices_3 WHERE year = 2000 GROUP BY town, year FORMAT Parquet"),
          "DROP TABLE IF EXISTS town_stats"],
   hints=["FORMAT Parquet; the file carries its own schema.", "INSERT INTO t FROM INFILE 'path' FORMAT Parquet"])

ex("L6", "Insert a local TSV file",
   """
   The local file gym/data/rates.tsv is tab-separated with a header row (month, variable,
   fixed). Insert it into the existing table `rates_tsv`.
   """,
   "INSERT INTO rates_tsv FROM INFILE 'gym/data/rates.tsv' FORMAT TabSeparatedWithNames",
   check=[is_true(f"SELECT (SELECT count() FROM gym.rates_tsv) = (SELECT count() FROM s3('{RATES_URL}', NOSIGN, 'CSVWithNames'))",
                  "rates_tsv should contain every row of the file (once)")],
   setup=[("file", "gym/data/rates.tsv",
           f"SELECT toDate(date) AS month, variable, fixed FROM s3('{RATES_URL}', NOSIGN, 'CSVWithNames') "
           "ORDER BY month FORMAT TabSeparatedWithNames"),
          "DROP TABLE IF EXISTS rates_tsv",
          "CREATE TABLE rates_tsv (month Date, variable Decimal32(2), fixed Decimal32(2)) ENGINE = MergeTree ORDER BY month"],
   hints=["Tab-separated with a header: TabSeparatedWithNames (alias TSVWithNames)."])

ex("L7", "Transform columns while inserting",
   f"""
   Create `rates_spread` (month Date, variable Decimal32(2), spread Decimal32(2)), MergeTree
   ordered by month. Fill it from the mortgage CSV at
     {RATES_URL}
   with month = the file's date as a Date, spread = fixed - bank, and only months from
   2010-01-01 onwards. The spreads must be exact (e.g. 5.39 - 0.50 = 4.89, not 4.88).
   """,
   f"""
   CREATE TABLE rates_spread (
       month Date,
       variable Decimal32(2),
       spread Decimal32(2)
   )
   ENGINE = MergeTree
   ORDER BY month;

   INSERT INTO rates_spread
       SELECT toDate(date) AS month, variable, fixed - bank AS spread
       FROM s3('{RATES_URL}', NOSIGN, 'CSVWithNames')
       WHERE month >= '2010-01-01'
       SETTINGS schema_inference_hints = 'variable Decimal32(2), fixed Decimal32(2), bank Decimal32(2)'
   """,
   check=[cols("rates_spread", [("month", "Date"), ("variable", "Decimal(9, 2)"), ("spread", "Decimal(9, 2)")]),
          is_true(f"SELECT (SELECT count() FROM gym.rates_spread) = (SELECT count() FROM s3('{RATES_URL}', NOSIGN, 'CSVWithNames') WHERE toDate(date) >= '2010-01-01')",
                  "Insert exactly the months from 2010-01-01 onwards"),
          is_true(f"SELECT (SELECT groupArray(spread) FROM (SELECT spread FROM gym.rates_spread ORDER BY month)) = (SELECT groupArray(s) FROM (SELECT fixed - bank AS s FROM s3('{RATES_URL}', NOSIGN, 'CSVWithNames') WHERE toDate(date) >= '2010-01-01' ORDER BY date SETTINGS schema_inference_hints = 'fixed Decimal32(2), bank Decimal32(2)'))",
                  "spread should be exactly fixed - bank. Check a row like 2010-01-31: 5.39 - 0.50 = 4.89")],
   setup=["DROP TABLE IF EXISTS rates_spread"],
   hints=["INSERT INTO t SELECT <expressions> FROM s3(...) WHERE ...",
          "The file's numbers are inferred as Float64, and 5.39 - 0.5 = 4.8899999… gets truncated to 4.88 in a Decimal.",
          "Read them as Decimal: SETTINGS schema_inference_hints = 'fixed Decimal32(2), bank Decimal32(2)', or pass a structure to s3()."])

ex("A6", "minmax skipping index",
   """
   Add a minmax skipping index `price_minmax` on the price column of `uk_prices_3` with
   GRANULARITY 4, and build it for the existing data (wait until done).
   """,
   """
   ALTER TABLE uk_prices_3 ADD INDEX price_minmax price TYPE minmax GRANULARITY 4;

   ALTER TABLE uk_prices_3 MATERIALIZE INDEX price_minmax SETTINGS mutations_sync = 1
   """,
   check=[is_true("SELECT count() = 1 FROM system.data_skipping_indices WHERE database = 'gym' AND table = 'uk_prices_3' AND name = 'price_minmax' AND type = 'minmax' AND expr = 'price' AND granularity = 4",
                  "price_minmax should be a minmax index on price with GRANULARITY 4"),
          is_true("SELECT min(secondary_indices_compressed_bytes) > 0 FROM system.parts WHERE database = 'gym' AND table = 'uk_prices_3' AND active",
                  "MATERIALIZE INDEX so existing parts get it")],
   setup=["ALTER TABLE uk_prices_3 DROP INDEX IF EXISTS price_minmax"],
   hints=["TYPE minmax stores the min and max of each block of granules.",
          "It helps when values correlate with the sort order."])

ex("A7", "set skipping index",
   """
   Add a set skipping index `type_set` on the type column of `uk_prices_3` that stores up to
   10 distinct values per block, GRANULARITY 4, and build it (wait until done).
   """,
   """
   ALTER TABLE uk_prices_3 ADD INDEX type_set type TYPE set(10) GRANULARITY 4;

   ALTER TABLE uk_prices_3 MATERIALIZE INDEX type_set SETTINGS mutations_sync = 1
   """,
   check=[is_true("SELECT count() = 1 FROM system.data_skipping_indices WHERE database = 'gym' AND table = 'uk_prices_3' AND name = 'type_set' AND type = 'set' AND expr = 'type' AND granularity = 4",
                  "type_set should be a set index on type with GRANULARITY 4"),
          ddl_has("uk_prices_3", "TYPE set(10)", "Use TYPE set(10)"),
          is_true("SELECT min(secondary_indices_compressed_bytes) > 0 FROM system.parts WHERE database = 'gym' AND table = 'uk_prices_3' AND active",
                  "MATERIALIZE INDEX so existing parts get it")],
   setup=["ALTER TABLE uk_prices_3 DROP INDEX IF EXISTS type_set"],
   hints=["TYPE set(max_rows): 0 means unlimited distinct values.",
          "Good for low-cardinality columns within each block."])

# Keep exercises grouped in SECTIONS order.
_ORDER = {code: i for i, (code, _) in enumerate(SECTIONS)}
EXERCISES.sort(key=lambda e: (_ORDER[e["section"]], int(e["id"][1:])))

# ---------- data setup for the gym database ----------

BASE_TABLE = sql("""
    CREATE TABLE IF NOT EXISTS gym.uk_prices_3
    (
        id UUID,
        price UInt32,
        date DateTime,
        postcode1 String,
        postcode2 String,
        type Enum8('terraced' = 1, 'semi-detached' = 2, 'detached' = 3, 'flat' = 4, 'other' = 0),
        is_new UInt8,
        duration Enum8('freehold' = 1, 'leasehold' = 2, 'unknown' = 0),
        addr1 String,
        addr2 String,
        street String,
        locality LowCardinality(String),
        town LowCardinality(String),
        district LowCardinality(String),
        county LowCardinality(String)
    )
    ENGINE = MergeTree
    PRIMARY KEY (postcode1, postcode2)
""")

# Source of truth: the course's raw S3 file (deep-dive/01_getting_started/lab_1.2.sql),
# transformed the same way as uk_prices_3 in deep-dive/04_modeling_data/lab_4.1.sql.
LOAD_FROM_S3 = sql(f"""
    INSERT INTO gym.uk_prices_3
    WITH splitByChar(' ', postcode) AS postcodes
    SELECT
        toUUID(replaceRegexpAll(id, '[{{}}]', '')) AS id,
        toUInt32(price) AS price,
        parseDateTimeBestEffort(date) AS date,
        postcodes[1] AS postcode1,
        postcodes[2] AS postcode2,
        transform(type, ['T', 'S', 'D', 'F', 'O'], ['terraced', 'semi-detached', 'detached', 'flat', 'other'], 'other') AS type,
        is_new = 'Y' AS is_new,
        transform(duration, ['F', 'L', 'U'], ['freehold', 'leasehold', 'unknown'], 'unknown') AS duration,
        addr1, addr2, street, locality, town, district, county
    FROM s3('{PRICES_URL}', NOSIGN, 'CSVWithNames',
        'id String, price String, date String, postcode String, type String, is_new String,
         duration String, addr1 String, addr2 String, street String, locality String,
         town String, district String, county String, column15 String, column16 String')
""")
