# ClickHouse gym

A terminal shell for practising SQL for the
[ClickHouse Certified Developer exam](https://clickhouse.com/learn/certification).
It uses the datasets from *Real-Time Analytics with ClickHouse*: UK property prices
loaded from the course's S3 file (`uk_prices_3`, built as in the course deep-dive lab 4.1) and the UK
mortgage rates. Its exercises follow the course labs and the exam objectives.

You write the SQL. The gym runs it on your local ClickHouse and checks it:

- **Query exercises** compare your result with the reference query's result. Column
  names don't matter; values, row count and, where it matters, row order do.
- **Statement exercises** (CREATE DATABASE / TABLE / MATERIALIZED VIEW / DICTIONARY,
  INSERT, ALTER, DELETE) inspect `system.*` tables and the data afterwards.

## Start

```bash
make up      # start ClickHouse and a single-node Kafka (docker-compose.yml)
make gym     # first run loads the `gym` database from S3 (~30M rows, a few minutes)
```

Everything happens in a separate `gym` database, so your `default` tables are untouched.
Progress and input history are kept in `~/.clickhouse_gym/`. Local files for the
`FROM INFILE` exercises are generated in `gym/data/`.

## Topics (113 exercises)

| | Topic | Covers |
|---|---|---|
| I | Inspect tables (7) | SHOW CREATE, DESCRIBE, system.parts / parts_columns / tables |
| Q | Write queries (20) | filters, -If combinators, topK, LIMIT BY, window functions, argMax, quantile |
| F | Common functions (21) | strings, regex, LIKE/ILIKE, dates and intervals, rounding, multiIf/CASE, arrays, arrayJoin |
| E | Exploratory analysis (15) | summary stats, percentiles, share of total, ranking, moving averages, outliers, ROLLUP, data quality |
| L | Load data (7) | `s3()` inference, local CSV / TSV / Parquet with `FROM INFILE`, transforms on insert |
| T | Create tables (8) | databases, data types, primary keys, partitions, Replacing/CollapsingMergeTree, codecs, TTL |
| U | Update and delete (6) | FINAL, versions, sign rows, lightweight DELETE, ALTER UPDATE |
| V | Materialized views (11) | incremental MVs, SummingMergeTree, AggregatingMergeTree (-State / -Merge), backfills, refreshable MVs |
| D | Dictionaries and joins (7) | HTTP and ClickHouse-table sources, joins with a dictionary, dictGet |
| A | Accelerate queries (7) | EXPLAIN indexes, bloom_filter / minmax / set indexes, projections, TTL changes |
| K | Kafka streaming (4) | Kafka engine table, Kafka → MV → MergeTree, virtual columns (_offset, _partition …), dead-letter table |

## Exam objectives → exercises

| Objective | Exercises |
|---|---|
| **Modeling data** | |
| Create a new database | T0 |
| Create a table that meets criteria or matches a file format | T1, T3, T4, L2, L5 |
| Choose efficient data types | T6, T1, T3 |
| Define an efficient primary key for given queries | T7, T1 |
| Define and query a dictionary | D1–D7 |
| **Inserting data** | |
| Insert a local file | L4, L5, L6 |
| Insert a file from cloud storage | T3, L7, L2 |
| Insert Parquet, CSV or TSV | L5 (Parquet), L4 (CSV), L6 (TSV) |
| Transform columns while inserting | L7, T3 |
| Insert from one table into another | T2, U2, V3, V7 |
| **Analyzing data** | |
| Query that satisfies criteria | Q1–Q20 |
| Regular functions (substrings, time intervals…) | F1–F21, Q10, Q11 |
| Aggregate functions (max/min/sum/avg, uniq, quantile) | Q2, Q7, Q17, E1, E2 |
| GROUP BY buckets over a timeframe or criteria | Q10, Q11, F7, F8, F11, F13, E5 |
| **Optimizing query performance** | |
| MV storing a non-aggregation query | V1 |
| MV with AggregatingMergeTree or SummingMergeTree | V2–V10 |
| Projection | A3, A4 |
| set or minmax skipping index | A6 (minmax), A7 (set), A2 (bloom_filter) |
| **Deduplication and mutations** | |
| Lightweight delete | U5 |
| Upserts with ReplacingMergeTree | U1, U2, U3 |
| Frequent updates with CollapsingMergeTree | T5, U4 |

## Commands

| Command | |
|---|---|
| `SQL;` | attempt the exercise (multi-line and several statements are fine) |
| `? SQL;` | run SQL without checking (explore) |
| `\focus` | choose topics to practise (menu), or `\focus V D` directly; `\focus all` clears |
| `\l [topic\|all]` | list exercises: ✓ passed, ✗ failed, ? solution seen, · new |
| `\g Q5` | go to an exercise |
| `\n` / `\p` | next / previous (inside the focused topics) |
| `\t` `\h` `\s` | task, next hint, reference solution |
| `\r` | reset the exercise (re-runs its setup so you can retype it from memory) |
| `\drill` | spaced repetition: exercises you failed or peeked at come up most |
| `\exam 12 60` | timed mock: 12 random exercises in 60 minutes, no hints (uses the focus) |
| `\stats` | progress per topic |
| `\setup` | wipe the gym database and reload the data |

Start focused from the shell: `python3 gym/gym.py --topic=V,D`.

## Suggested routine

1. Work through each topic with `\focus`, using `\h` before `\s`.
2. After seeing a solution, `\r` and type it again from memory.
3. Daily: `\drill` for 15 minutes.
4. Weekly: `\exam` (the real exam is 10–12 hands-on tasks in 2 hours, docs allowed, 70% to pass).
5. Also practise in `make client`: the exam uses clickhouse-client on ClickHouse Cloud.

## Notes

- Local OSS ClickHouse refuses `s3()` with server credentials, so add `NOSIGN`:
  `s3('https://…', NOSIGN, 'CSVWithNames')`. ClickHouse Cloud doesn't need it.
- `INSERT … FROM INFILE 'path' FORMAT …` works in the gym like in clickhouse-client:
  the gym reads the local file and sends it to the server.
- Connection settings: `CH_HOST`, `CH_PORT` (HTTP, default 8123), `CH_USER`, `CH_PASSWORD`
  (defaults match `docker-compose.yml`).
- The K exercises use the `kafka` service (`kafka:9092` from the ClickHouse container;
  override with `CH_KAFKA`). Their checks inspect the tables and views you create, so
  they don't wait for messages.
- `python3 gym/gym.py --selftest` runs every reference solution through the checker.
- Exercises live in `gym/exercises.py`; add your own with `ex(...)`.
