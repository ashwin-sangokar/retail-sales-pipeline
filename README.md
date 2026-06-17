# Retail Sales Data Pipeline & Business Intelligence Platform

End-to-end ETL pipeline that takes a messy raw retail sales export, cleans
and validates it, loads it into a star-schema warehouse, and exposes
analytics-ready SQL views for a BI dashboard.

## Project structure

```
retail-pipeline/
├── data/
│   ├── raw/raw_sales_data.csv          # simulated messy POS export (input)
│   └── processed/
│       ├── cleaned_sales_data.csv      # output of TRANSFORM stage
│       └── powerbi_sales_export.csv    # flat, denormalized export for Power BI
├── db/
│   └── retail_sales.db                 # SQLite warehouse (star schema)
├── sql/
│   ├── schema_postgres.sql             # production DDL (Postgres/MySQL)
│   └── analytics_queries.sql           # business insight queries + views
├── scripts/
│   ├── generate_raw_data.py            # synthetic raw data generator
│   ├── etl_pipeline.py                 # EXTRACT -> TRANSFORM -> LOAD
│   ├── validate_warehouse.py           # post-load data integrity checks
│   └── test_queries.py                 # runs/previews all analytics queries
└── reports/
    └── data_quality_report.txt         # auto-generated after each ETL run
```

## How to run

```bash
pip install pandas faker

python3 scripts/generate_raw_data.py   # only needed once, or to regenerate sample data
python3 scripts/etl_pipeline.py        # extract -> clean -> validate -> load
python3 scripts/validate_warehouse.py  # post-load integrity checks
python3 scripts/test_queries.py        # see all analytics queries run live
```

## What the ETL actually cleans

The raw data simulates real POS/e-commerce export problems:

| Issue | Handling |
|---|---|
| Mixed date formats (`2024-06-01`, `01/12/2024`, `15-Aug-2025`) | Parsed against multiple known formats, standardized to ISO |
| Missing customer name / region | Imputed to `"Unknown Customer"` / `"Unspecified"` rather than dropping the sale |
| Missing/invalid quantity, price, or unparseable date | Dropped — these break revenue math, so they're hard failures, logged in the DQ report |
| Inconsistent casing/whitespace (`"north"`, `" North"`) | Stripped + title-cased |
| Category typos (`"Electronic"`, `"beauty"`) | Mapped to canonical labels |
| Price outliers (e.g. an extra zero typed in) | Capped at 5x the category median, flagged |
| Exact duplicate order lines | Removed via `drop_duplicates` on the natural key |

Every run produces `reports/data_quality_report.txt` with exact counts for
each issue found — this is the artifact you'd hand to a stakeholder to prove
the pipeline is trustworthy.

## Schema (star schema)

- `fact_sales` — one row per order line (quantity, price, discount, gross/net/cost/profit)
- `dim_customer`, `dim_product`, `dim_region`, `dim_date` — descriptive dimensions

This is intentionally a star schema (not normalized OLTP) because the goal is
fast analytical querying and a clean Power BI model, not transactional writes.

## Moving from SQLite (demo) to PostgreSQL/MySQL (production)

The SQLite file is just for local development/portfolio purposes. To go to
Postgres:

1. Run `sql/schema_postgres.sql` against your Postgres instance.
2. In `etl_pipeline.py`, replace the `sqlite3.connect(db_path)` call with a
   SQLAlchemy engine: `create_engine("postgresql+psycopg2://user:pwd@host/db")`
   — `pandas.to_sql()` accepts either, so no other code changes are needed.
3. `sql/analytics_queries.sql` runs as-is on Postgres (and on MySQL 8+, which
   also supports window functions and CTEs).

## Connecting Power BI

Two options, both already prepared:

- **Easiest**: import `data/processed/powerbi_sales_export.csv` directly
  (it's the flattened `vw_sales_flat` view — one row per sale, all dimension
  attributes already joined in, no relationships to model).
- **Live connection**: use Power BI's "ODBC" or "PostgreSQL" connector once
  you've migrated to Postgres, point it at `vw_sales_flat` and
  `vw_monthly_kpis`, and build visuals directly off those views.

Suggested dashboard pages: **Revenue Trends** (line chart of `vw_monthly_kpis`,
MoM growth as a KPI card), **Profitability** (category profit margin bar
chart), **Product Performance** (top products table + treemap by category),
**Regional Analysis** (map or bar chart of region revenue share), **Customer
Behavior** (segment donut chart: One-time / Occasional / Loyal, + repeat
customer revenue % as a card).
