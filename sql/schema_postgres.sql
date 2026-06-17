-- ============================================================
-- schema_postgres.sql
-- Star-schema DDL for the Retail Sales Data Warehouse
-- Target: PostgreSQL (also valid, with trivial AUTO_INCREMENT
-- syntax changes, for MySQL)
-- ============================================================

DROP TABLE IF EXISTS fact_sales;
DROP TABLE IF EXISTS dim_customer;
DROP TABLE IF EXISTS dim_product;
DROP TABLE IF EXISTS dim_region;
DROP TABLE IF EXISTS dim_date;

CREATE TABLE dim_customer (
    customer_key   SERIAL PRIMARY KEY,
    customer_id    VARCHAR(20) UNIQUE NOT NULL,
    customer_name  VARCHAR(150) NOT NULL
);

CREATE TABLE dim_product (
    product_key    SERIAL PRIMARY KEY,
    product_name   VARCHAR(150) UNIQUE NOT NULL,
    category       VARCHAR(80) NOT NULL
);

CREATE TABLE dim_region (
    region_key     SERIAL PRIMARY KEY,
    region_name    VARCHAR(80) UNIQUE NOT NULL
);

CREATE TABLE dim_date (
    date_key       INT PRIMARY KEY,            -- YYYYMMDD
    full_date      DATE NOT NULL,
    year           SMALLINT NOT NULL,
    quarter        SMALLINT NOT NULL,
    month          SMALLINT NOT NULL,
    month_name     VARCHAR(20) NOT NULL,
    day            SMALLINT NOT NULL,
    weekday_name   VARCHAR(20) NOT NULL
);

CREATE TABLE fact_sales (
    sale_key          BIGSERIAL PRIMARY KEY,
    order_id          VARCHAR(30) NOT NULL,
    customer_key      INT NOT NULL REFERENCES dim_customer(customer_key),
    product_key       INT NOT NULL REFERENCES dim_product(product_key),
    region_key        INT NOT NULL REFERENCES dim_region(region_key),
    date_key          INT NOT NULL REFERENCES dim_date(date_key),
    payment_method    VARCHAR(40),
    sales_channel     VARCHAR(20),
    quantity          INT NOT NULL CHECK (quantity > 0),
    unit_price        NUMERIC(12,2) NOT NULL CHECK (unit_price > 0),
    discount_percent  NUMERIC(5,2) NOT NULL DEFAULT 0,
    gross_amount      NUMERIC(14,2) NOT NULL,
    discount_amount   NUMERIC(14,2) NOT NULL,
    net_amount        NUMERIC(14,2) NOT NULL,
    cost_amount       NUMERIC(14,2) NOT NULL,
    profit_amount     NUMERIC(14,2) NOT NULL
);

CREATE INDEX idx_fact_date     ON fact_sales(date_key);
CREATE INDEX idx_fact_customer ON fact_sales(customer_key);
CREATE INDEX idx_fact_product  ON fact_sales(product_key);
CREATE INDEX idx_fact_region   ON fact_sales(region_key);

-- ============================================================
-- Notes for porting:
-- MySQL: replace SERIAL -> INT AUTO_INCREMENT, BIGSERIAL -> BIGINT AUTO_INCREMENT,
--        NUMERIC -> DECIMAL (same precision/scale args work).
-- The ETL's load() step targets SQLite for local dev; repointing it to
-- Postgres only requires swapping sqlite3.connect() for a SQLAlchemy
-- engine, e.g. create_engine("postgresql+psycopg2://user:pwd@host/db")
-- and passing that engine to pandas.to_sql() instead of the sqlite3 conn.
-- ============================================================
