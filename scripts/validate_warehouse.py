"""
validate_warehouse.py
-----------------------
Post-load data integrity checks against the warehouse. Run this after
etl_pipeline.py to confirm the loaded data meets business rules.
Exits non-zero if any check fails (suitable for a CI / cron pipeline).
"""

import sqlite3
import sys
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "db" / "retail_sales.db"


CHECKS = [
    ("No NULL customer keys in fact_sales",
     "SELECT COUNT(*) FROM fact_sales WHERE customer_key IS NULL"),
    ("No NULL product keys in fact_sales",
     "SELECT COUNT(*) FROM fact_sales WHERE product_key IS NULL"),
    ("No negative or zero quantity",
     "SELECT COUNT(*) FROM fact_sales WHERE quantity <= 0"),
    ("No negative or zero unit_price",
     "SELECT COUNT(*) FROM fact_sales WHERE unit_price <= 0"),
    ("No net_amount mismatched with gross - discount",
     "SELECT COUNT(*) FROM fact_sales WHERE ABS(net_amount - (gross_amount - discount_amount)) > 0.01"),
    ("No duplicate (order_id, product_key, date_key) lines",
     """SELECT COUNT(*) FROM (
            SELECT order_id, product_key, date_key, COUNT(*) c
            FROM fact_sales GROUP BY order_id, product_key, date_key HAVING c > 1
        )"""),
    ("Every fact row's customer_key exists in dim_customer",
     """SELECT COUNT(*) FROM fact_sales f
        LEFT JOIN dim_customer c ON f.customer_key = c.customer_key
        WHERE c.customer_key IS NULL"""),
    ("Every fact row's product_key exists in dim_product",
     """SELECT COUNT(*) FROM fact_sales f
        LEFT JOIN dim_product p ON f.product_key = p.product_key
        WHERE p.product_key IS NULL"""),
]


def main():
    conn = sqlite3.connect(DB_PATH)
    failures = 0
    print(f"Validating {DB_PATH} ...\n")
    for name, sql in CHECKS:
        count = conn.execute(sql).fetchone()[0]
        status = "PASS" if count == 0 else "FAIL"
        if count != 0:
            failures += 1
        print(f"[{status}] {name} (violations: {count})")
    conn.close()

    print(f"\n{len(CHECKS) - failures}/{len(CHECKS)} checks passed.")
    if failures:
        sys.exit(1)


if __name__ == "__main__":
    main()
