"""
etl_pipeline.py
----------------
End-to-end ETL for the Retail Sales Data Pipeline project.

    EXTRACT   -> read raw CSV export
    TRANSFORM -> clean, standardize, validate, derive metrics
    LOAD      -> write into a star-schema database (SQLite locally;
                 schema is identical to the PostgreSQL DDL in sql/schema_postgres.sql
                 so this can be repointed at Postgres/MySQL with minimal change)

Run:  python3 scripts/etl_pipeline.py
"""

import re
import sqlite3
import logging
from pathlib import Path
from datetime import datetime

import pandas as pd

BASE_DIR = Path(__file__).resolve().parent.parent
RAW_PATH = BASE_DIR / "data" / "raw" / "raw_sales_data.csv"
PROCESSED_PATH = BASE_DIR / "data" / "processed" / "cleaned_sales_data.csv"
DQ_REPORT_PATH = BASE_DIR / "reports" / "data_quality_report.txt"
DB_PATH = BASE_DIR / "db" / "retail_sales.db"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    handlers=[logging.StreamHandler()],
)
log = logging.getLogger("etl")


# ----------------------------------------------------------------------
# EXTRACT
# ----------------------------------------------------------------------
def extract(path: Path) -> pd.DataFrame:
    log.info("EXTRACT: reading raw file %s", path)
    df = pd.read_csv(path, dtype=str)  # read as str first; we control type coercion ourselves
    log.info("EXTRACT: %d rows, %d columns read", len(df), len(df.columns))
    return df


# ----------------------------------------------------------------------
# TRANSFORM (data quality checks are accumulated into `dq` for the report)
# ----------------------------------------------------------------------
def parse_date(value: str):
    if pd.isna(value):
        return None
    value = value.strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%m-%d-%Y", "%d-%b-%Y"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    return None  # unparseable -> treated as invalid, dropped/flagged later


def transform(df: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    dq = {"input_rows": len(df)}
    df = df.copy()

    # --- 1. Standardize text fields (strip whitespace, fix casing) ---
    text_cols = ["customer_name", "region", "product_name", "category", "payment_method", "sales_channel"]
    for col in text_cols:
        df[col] = df[col].astype(str).str.strip()
        df[col] = df[col].replace({"nan": None, "None": None, "": None})

    df["region"] = df["region"].str.title()
    df["category"] = df["category"].str.strip().str.title()
    # normalize known category typos to a canonical label
    category_map = {
        "Electronic": "Electronics",
        "Beauty & Personal Care": "Beauty",
    }
    df["category"] = df["category"].replace(category_map)
    df["product_name"] = df["product_name"].str.title()

    # --- 2. Parse and standardize dates ---
    df["order_date"] = df["order_date"].apply(parse_date)
    dq["invalid_dates"] = int(df["order_date"].isna().sum())

    # --- 3. Numeric coercion ---
    df["quantity"] = pd.to_numeric(df["quantity"], errors="coerce")
    df["unit_price"] = pd.to_numeric(df["unit_price"], errors="coerce")
    df["discount_percent"] = pd.to_numeric(df["discount_percent"], errors="coerce").fillna(0)

    # --- 4. Data quality: missing values BEFORE imputation ---
    dq["missing_customer_name"] = int(df["customer_name"].isna().sum())
    dq["missing_region"] = int(df["region"].isna().sum())
    dq["missing_quantity"] = int(df["quantity"].isna().sum())
    dq["missing_unit_price"] = int(df["unit_price"].isna().sum())

    # --- 5. Impute / drop based on business rules ---
    # Missing customer name -> "Unknown Customer" (keep the row, ID is still valid)
    df["customer_name"] = df["customer_name"].fillna("Unknown Customer")
    # Missing region -> "Unspecified" rather than dropping a whole sale
    df["region"] = df["region"].fillna("Unspecified")

    # Invalid quantity/price/date are hard data-integrity failures for a sales fact table -> drop
    before = len(df)
    df = df[df["order_date"].notna()]
    df = df[df["quantity"].notna() & (df["quantity"] > 0)]
    df = df[df["unit_price"].notna() & (df["unit_price"] > 0)]
    dq["rows_dropped_invalid"] = before - len(df)

    # --- 6. Outlier guard: absurd unit_price typos (e.g. extra zero entered) ---
    # flag prices > 5x the category median as likely data-entry errors and cap them
    cat_median = df.groupby("category")["unit_price"].median()
    def cap_price(row):
        med = cat_median.get(row["category"], row["unit_price"])
        if med > 0 and row["unit_price"] > med * 5:
            return round(med, 2)
        return row["unit_price"]
    outliers_before = ((df["unit_price"] > df["category"].map(cat_median) * 5)).sum()
    dq["price_outliers_capped"] = int(outliers_before)
    df["unit_price"] = df.apply(cap_price, axis=1)

    # --- 7. Remove duplicate order lines (exact duplicate export rows) ---
    before = len(df)
    df = df.drop_duplicates(subset=["order_id", "customer_id", "product_name", "order_date", "quantity", "unit_price"])
    dq["duplicate_rows_removed"] = before - len(df)

    # --- 8. Derived columns ---
    df["gross_amount"] = (df["quantity"] * df["unit_price"]).round(2)
    df["discount_amount"] = (df["gross_amount"] * df["discount_percent"] / 100).round(2)
    df["net_amount"] = (df["gross_amount"] - df["discount_amount"]).round(2)
    # assumed cost ratio for margin analysis (cost = 60-70% of price, modeled deterministically per category)
    cost_ratio_by_category = {
        "Electronics": 0.68, "Apparel": 0.55, "Home & Kitchen": 0.62,
        "Beauty": 0.50, "Sports": 0.58,
    }
    df["cost_ratio"] = df["category"].map(cost_ratio_by_category).fillna(0.60)
    df["cost_amount"] = (df["gross_amount"] * df["cost_ratio"]).round(2)
    df["profit_amount"] = (df["net_amount"] - df["cost_amount"]).round(2)

    dq["output_rows"] = len(df)
    log.info("TRANSFORM: %s", dq)
    return df.reset_index(drop=True), dq


# ----------------------------------------------------------------------
# LOAD  (star schema: dim_customer, dim_product, dim_date, dim_region, fact_sales)
# ----------------------------------------------------------------------
SCHEMA_SQL = """
DROP TABLE IF EXISTS fact_sales;
DROP TABLE IF EXISTS dim_customer;
DROP TABLE IF EXISTS dim_product;
DROP TABLE IF EXISTS dim_region;
DROP TABLE IF EXISTS dim_date;

CREATE TABLE dim_customer (
    customer_key INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_id   TEXT UNIQUE NOT NULL,
    customer_name TEXT NOT NULL
);

CREATE TABLE dim_product (
    product_key  INTEGER PRIMARY KEY AUTOINCREMENT,
    product_name TEXT UNIQUE NOT NULL,
    category     TEXT NOT NULL
);

CREATE TABLE dim_region (
    region_key INTEGER PRIMARY KEY AUTOINCREMENT,
    region_name TEXT UNIQUE NOT NULL
);

CREATE TABLE dim_date (
    date_key   INTEGER PRIMARY KEY,   -- YYYYMMDD
    full_date  TEXT NOT NULL,
    year       INTEGER NOT NULL,
    quarter    INTEGER NOT NULL,
    month      INTEGER NOT NULL,
    month_name TEXT NOT NULL,
    day        INTEGER NOT NULL,
    weekday_name TEXT NOT NULL
);

CREATE TABLE fact_sales (
    sale_key         INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id         TEXT NOT NULL,
    customer_key     INTEGER NOT NULL REFERENCES dim_customer(customer_key),
    product_key      INTEGER NOT NULL REFERENCES dim_product(product_key),
    region_key       INTEGER NOT NULL REFERENCES dim_region(region_key),
    date_key         INTEGER NOT NULL REFERENCES dim_date(date_key),
    payment_method   TEXT,
    sales_channel    TEXT,
    quantity         INTEGER NOT NULL CHECK (quantity > 0),
    unit_price       REAL NOT NULL CHECK (unit_price > 0),
    discount_percent REAL NOT NULL DEFAULT 0,
    gross_amount     REAL NOT NULL,
    discount_amount  REAL NOT NULL,
    net_amount       REAL NOT NULL,
    cost_amount      REAL NOT NULL,
    profit_amount    REAL NOT NULL
);

CREATE INDEX idx_fact_date     ON fact_sales(date_key);
CREATE INDEX idx_fact_customer ON fact_sales(customer_key);
CREATE INDEX idx_fact_product  ON fact_sales(product_key);
CREATE INDEX idx_fact_region   ON fact_sales(region_key);
"""

WEEKDAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
MONTH_NAMES = ["", "January", "February", "March", "April", "May", "June",
               "July", "August", "September", "October", "November", "December"]


def load(df: pd.DataFrame, db_path: Path):
    log.info("LOAD: building star schema at %s", db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.executescript(SCHEMA_SQL)

    # dim_customer
    customers = df[["customer_id", "customer_name"]].drop_duplicates(subset=["customer_id"])
    customers.to_sql("dim_customer", conn, if_exists="append", index=False)

    # dim_product
    products = df[["product_name", "category"]].drop_duplicates(subset=["product_name"])
    products.to_sql("dim_product", conn, if_exists="append", index=False)

    # dim_region
    regions = pd.DataFrame({"region_name": df["region"].drop_duplicates()})
    regions.to_sql("dim_region", conn, if_exists="append", index=False)

    # dim_date
    dates = pd.DataFrame({"full_date": df["order_date"].drop_duplicates()})
    dates["date_key"] = dates["full_date"].apply(lambda d: int(d.strftime("%Y%m%d")))
    dates["year"] = dates["full_date"].apply(lambda d: d.year)
    dates["quarter"] = dates["full_date"].apply(lambda d: (d.month - 1) // 3 + 1)
    dates["month"] = dates["full_date"].apply(lambda d: d.month)
    dates["month_name"] = dates["month"].apply(lambda m: MONTH_NAMES[m])
    dates["day"] = dates["full_date"].apply(lambda d: d.day)
    dates["weekday_name"] = dates["full_date"].apply(lambda d: WEEKDAY_NAMES[d.weekday()])
    dates["full_date"] = dates["full_date"].astype(str)
    dates[["date_key", "full_date", "year", "quarter", "month", "month_name", "day", "weekday_name"]].to_sql(
        "dim_date", conn, if_exists="append", index=False
    )

    # lookup maps for foreign keys
    cust_map = pd.read_sql("SELECT customer_key, customer_id FROM dim_customer", conn).set_index("customer_id")["customer_key"]
    prod_map = pd.read_sql("SELECT product_key, product_name FROM dim_product", conn).set_index("product_name")["product_key"]
    reg_map = pd.read_sql("SELECT region_key, region_name FROM dim_region", conn).set_index("region_name")["region_key"]

    fact = pd.DataFrame({
        "order_id": df["order_id"],
        "customer_key": df["customer_id"].map(cust_map),
        "product_key": df["product_name"].map(prod_map),
        "region_key": df["region"].map(reg_map),
        "date_key": df["order_date"].apply(lambda d: int(d.strftime("%Y%m%d"))),
        "payment_method": df["payment_method"],
        "sales_channel": df["sales_channel"],
        "quantity": df["quantity"].astype(int),
        "unit_price": df["unit_price"],
        "discount_percent": df["discount_percent"],
        "gross_amount": df["gross_amount"],
        "discount_amount": df["discount_amount"],
        "net_amount": df["net_amount"],
        "cost_amount": df["cost_amount"],
        "profit_amount": df["profit_amount"],
    })
    fact.to_sql("fact_sales", conn, if_exists="append", index=False)

    conn.commit()
    counts = {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
              for t in ["dim_customer", "dim_product", "dim_region", "dim_date", "fact_sales"]}
    log.info("LOAD complete: %s", counts)
    conn.close()
    return counts


def write_dq_report(dq: dict, load_counts: dict, path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        f.write("RETAIL SALES PIPELINE — DATA QUALITY REPORT\n")
        f.write(f"Generated: {datetime.now().isoformat(timespec='seconds')}\n")
        f.write("=" * 50 + "\n\n")
        f.write("-- Transform stage findings --\n")
        for k, v in dq.items():
            f.write(f"{k:30s}: {v}\n")
        f.write("\n-- Final row counts loaded into warehouse --\n")
        for k, v in load_counts.items():
            f.write(f"{k:30s}: {v}\n")
    log.info("Data quality report written to %s", path)


def main():
    df_raw = extract(RAW_PATH)
    df_clean, dq = transform(df_raw)

    PROCESSED_PATH.parent.mkdir(parents=True, exist_ok=True)
    df_clean.to_csv(PROCESSED_PATH, index=False)
    log.info("Cleaned data written to %s", PROCESSED_PATH)

    load_counts = load(df_clean, DB_PATH)
    write_dq_report(dq, load_counts, DQ_REPORT_PATH)


if __name__ == "__main__":
    main()
