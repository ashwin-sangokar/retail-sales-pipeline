import sqlite3
import pandas as pd

conn = sqlite3.connect("/home/claude/retail-pipeline/db/retail_sales.db")
pd.set_option("display.max_columns", None)
pd.set_option("display.width", 140)

queries = {
"1. Monthly revenue + MoM growth": """
WITH monthly_revenue AS (
    SELECT d.year, d.month, d.month_name, SUM(f.net_amount) AS revenue
    FROM fact_sales f JOIN dim_date d ON f.date_key = d.date_key
    GROUP BY d.year, d.month, d.month_name
)
SELECT year, month_name, revenue,
       LAG(revenue) OVER (ORDER BY year, month) AS prev_month_revenue,
       ROUND(100.0*(revenue-LAG(revenue) OVER (ORDER BY year, month))/LAG(revenue) OVER (ORDER BY year, month),2) AS mom_growth_percent
FROM monthly_revenue ORDER BY year, month LIMIT 6;
""",
"2. Profitability by category": """
SELECT p.category, SUM(f.net_amount) AS total_revenue, SUM(f.profit_amount) AS total_profit,
       ROUND(100.0*SUM(f.profit_amount)/SUM(f.net_amount),2) AS profit_margin_percent,
       RANK() OVER (ORDER BY SUM(f.profit_amount) DESC) AS profit_rank
FROM fact_sales f JOIN dim_product p ON f.product_key=p.product_key
GROUP BY p.category ORDER BY total_profit DESC;
""",
"3. Top product per category": """
WITH product_sales AS (
    SELECT p.category, p.product_name, SUM(f.net_amount) AS revenue, SUM(f.quantity) AS units_sold,
           ROW_NUMBER() OVER (PARTITION BY p.category ORDER BY SUM(f.net_amount) DESC) AS rnk
    FROM fact_sales f JOIN dim_product p ON f.product_key=p.product_key
    GROUP BY p.category, p.product_name
)
SELECT category, product_name, revenue, units_sold FROM product_sales WHERE rnk=1 ORDER BY revenue DESC;
""",
"4. Regional sales analysis": """
SELECT r.region_name, COUNT(DISTINCT f.order_id) AS total_orders, SUM(f.net_amount) AS total_revenue,
       ROUND(AVG(f.net_amount),2) AS avg_order_value,
       ROUND(100.0*SUM(f.net_amount)/SUM(SUM(f.net_amount)) OVER (),2) AS pct_of_total_revenue
FROM fact_sales f JOIN dim_region r ON f.region_key=r.region_key
GROUP BY r.region_name ORDER BY total_revenue DESC;
""",
"5. Customer segmentation (top 5 by LTV)": """
WITH customer_metrics AS (
    SELECT c.customer_id, c.customer_name, COUNT(DISTINCT f.order_id) AS order_count,
           SUM(f.net_amount) AS lifetime_value, MAX(d.full_date) AS last_purchase_date
    FROM fact_sales f JOIN dim_customer c ON f.customer_key=c.customer_key
    JOIN dim_date d ON f.date_key=d.date_key
    GROUP BY c.customer_id, c.customer_name
)
SELECT customer_id, customer_name, order_count, lifetime_value, last_purchase_date,
       CASE WHEN order_count=1 THEN 'One-time' WHEN order_count BETWEEN 2 AND 4 THEN 'Occasional' ELSE 'Loyal' END AS customer_segment
FROM customer_metrics ORDER BY lifetime_value DESC LIMIT 5;
""",
"5b. Repeat customer revenue share": """
WITH customer_metrics AS (
    SELECT c.customer_id, COUNT(DISTINCT f.order_id) AS order_count, SUM(f.net_amount) AS ltv
    FROM fact_sales f JOIN dim_customer c ON f.customer_key=c.customer_key GROUP BY c.customer_id
)
SELECT SUM(CASE WHEN order_count>1 THEN 1 ELSE 0 END)*100.0/COUNT(*) AS pct_repeat_customers,
       SUM(CASE WHEN order_count>1 THEN ltv ELSE 0 END)*100.0/SUM(ltv) AS pct_revenue_from_repeat
FROM customer_metrics;
""",
}

for title, q in queries.items():
    print(f"\n=== {title} ===")
    print(pd.read_sql(q, conn).to_string(index=False))

# Views
conn.executescript(open("/home/claude/retail-pipeline/sql/analytics_queries.sql").read().split("-- 6. VIEWS")[1].replace("-- A flattened", "-- A flattened").split("------------------------------------------------------------\n", 1)[1])
print("\n=== Views created OK ===")
print(pd.read_sql("SELECT * FROM vw_monthly_kpis LIMIT 3", conn).to_string(index=False))
print(pd.read_sql("SELECT * FROM vw_sales_flat LIMIT 2", conn).to_string(index=False))
conn.close()
