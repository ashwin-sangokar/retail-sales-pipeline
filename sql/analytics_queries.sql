-- ============================================================
-- analytics_queries.sql
-- Business intelligence queries against the star schema.
-- Written in SQLite dialect (matches db/retail_sales.db);
-- 100% portable to PostgreSQL, and to MySQL 8+ (window functions
-- require MySQL >= 8.0). Differences are noted inline where relevant.
-- ============================================================


-- ------------------------------------------------------------
-- 1. REVENUE TRENDS — Monthly revenue + Month-over-Month growth %
--    Features: CTE, window function (LAG), date dimension join
-- ------------------------------------------------------------
WITH monthly_revenue AS (
    SELECT
        d.year,
        d.month,
        d.month_name,
        SUM(f.net_amount) AS revenue
    FROM fact_sales f
    JOIN dim_date d ON f.date_key = d.date_key
    GROUP BY d.year, d.month, d.month_name
)
SELECT
    year,
    month_name,
    revenue,
    LAG(revenue) OVER (ORDER BY year, month) AS prev_month_revenue,
    ROUND(
        100.0 * (revenue - LAG(revenue) OVER (ORDER BY year, month))
        / LAG(revenue) OVER (ORDER BY year, month), 2
    ) AS mom_growth_percent
FROM monthly_revenue
ORDER BY year, month;


-- ------------------------------------------------------------
-- 2. PROFITABILITY — Profit margin % by category, ranked
--    Features: aggregation, window function (RANK)
-- ------------------------------------------------------------
SELECT
    p.category,
    SUM(f.net_amount)    AS total_revenue,
    SUM(f.profit_amount) AS total_profit,
    ROUND(100.0 * SUM(f.profit_amount) / SUM(f.net_amount), 2) AS profit_margin_percent,
    RANK() OVER (ORDER BY SUM(f.profit_amount) DESC) AS profit_rank
FROM fact_sales f
JOIN dim_product p ON f.product_key = p.product_key
GROUP BY p.category
ORDER BY total_profit DESC;


-- ------------------------------------------------------------
-- 3. PRODUCT PERFORMANCE — Top product per category by revenue
--    Features: CTE, window function (ROW_NUMBER) for "top-N per group"
-- ------------------------------------------------------------
WITH product_sales AS (
    SELECT
        p.category,
        p.product_name,
        SUM(f.net_amount)   AS revenue,
        SUM(f.quantity)     AS units_sold,
        ROW_NUMBER() OVER (PARTITION BY p.category ORDER BY SUM(f.net_amount) DESC) AS rnk
    FROM fact_sales f
    JOIN dim_product p ON f.product_key = p.product_key
    GROUP BY p.category, p.product_name
)
SELECT category, product_name, revenue, units_sold
FROM product_sales
WHERE rnk = 1
ORDER BY revenue DESC;


-- ------------------------------------------------------------
-- 4. REGIONAL SALES ANALYSIS — Revenue & order count by region,
--    with each region's share of total revenue
--    Features: join, aggregation, window function for share-of-total
-- ------------------------------------------------------------
SELECT
    r.region_name,
    COUNT(DISTINCT f.order_id)            AS total_orders,
    SUM(f.net_amount)                     AS total_revenue,
    ROUND(AVG(f.net_amount), 2)           AS avg_order_value,
    ROUND(100.0 * SUM(f.net_amount) / SUM(SUM(f.net_amount)) OVER (), 2) AS pct_of_total_revenue
FROM fact_sales f
JOIN dim_region r ON f.region_key = r.region_key
GROUP BY r.region_name
ORDER BY total_revenue DESC;


-- ------------------------------------------------------------
-- 5. CUSTOMER BEHAVIOR — Repeat vs one-time customers, and
--    simplified RFM-style segmentation (Recency / Frequency / Monetary)
--    Features: CTE, multiple aggregations, CASE-based segmentation
-- ------------------------------------------------------------
WITH customer_metrics AS (
    SELECT
        c.customer_id,
        c.customer_name,
        COUNT(DISTINCT f.order_id)      AS order_count,
        SUM(f.net_amount)               AS lifetime_value,
        MAX(d.full_date)                AS last_purchase_date
    FROM fact_sales f
    JOIN dim_customer c ON f.customer_key = c.customer_key
    JOIN dim_date d     ON f.date_key = d.date_key
    GROUP BY c.customer_id, c.customer_name
)
SELECT
    customer_id,
    customer_name,
    order_count,
    lifetime_value,
    last_purchase_date,
    CASE
        WHEN order_count = 1 THEN 'One-time'
        WHEN order_count BETWEEN 2 AND 4 THEN 'Occasional'
        ELSE 'Loyal'
    END AS customer_segment
FROM customer_metrics
ORDER BY lifetime_value DESC;

-- Quick rollup: what % of customers are repeat buyers, and what % of
-- revenue do they generate? (answers a classic stakeholder question)
WITH customer_metrics AS (
    SELECT c.customer_id, COUNT(DISTINCT f.order_id) AS order_count, SUM(f.net_amount) AS ltv
    FROM fact_sales f JOIN dim_customer c ON f.customer_key = c.customer_key
    GROUP BY c.customer_id
)
SELECT
    SUM(CASE WHEN order_count > 1 THEN 1 ELSE 0 END) * 100.0 / COUNT(*) AS pct_repeat_customers,
    SUM(CASE WHEN order_count > 1 THEN ltv ELSE 0 END) * 100.0 / SUM(ltv) AS pct_revenue_from_repeat
FROM customer_metrics;


-- ------------------------------------------------------------
-- 6. VIEWS — reusable layers for the dashboard / future queries
-- ------------------------------------------------------------

-- A flattened, denormalized view: this is what Power BI will connect to
-- (avoids making the dashboard tool re-join the star schema every time)
DROP VIEW IF EXISTS vw_sales_flat;
CREATE VIEW vw_sales_flat AS
SELECT
    f.sale_key,
    f.order_id,
    d.full_date,
    d.year,
    d.quarter,
    d.month_name,
    d.weekday_name,
    c.customer_id,
    c.customer_name,
    p.product_name,
    p.category,
    r.region_name,
    f.payment_method,
    f.sales_channel,
    f.quantity,
    f.unit_price,
    f.discount_percent,
    f.gross_amount,
    f.discount_amount,
    f.net_amount,
    f.cost_amount,
    f.profit_amount
FROM fact_sales f
JOIN dim_date d     ON f.date_key = d.date_key
JOIN dim_customer c ON f.customer_key = c.customer_key
JOIN dim_product p  ON f.product_key = p.product_key
JOIN dim_region r   ON f.region_key = r.region_key;

-- Pre-aggregated monthly KPI view (for fast dashboard load)
DROP VIEW IF EXISTS vw_monthly_kpis;
CREATE VIEW vw_monthly_kpis AS
SELECT
    d.year,
    d.month,
    d.month_name,
    COUNT(DISTINCT f.order_id) AS orders,
    SUM(f.net_amount)          AS revenue,
    SUM(f.profit_amount)       AS profit,
    ROUND(AVG(f.net_amount), 2) AS avg_order_value
FROM fact_sales f
JOIN dim_date d ON f.date_key = d.date_key
GROUP BY d.year, d.month, d.month_name;
