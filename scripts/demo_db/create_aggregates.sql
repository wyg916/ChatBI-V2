SET search_path TO {{schema}};

DROP MATERIALIZED VIEW IF EXISTS agg_receivable_aging;
DROP MATERIALIZED VIEW IF EXISTS agg_customer_contribution;
DROP MATERIALIZED VIEW IF EXISTS agg_region_product;
DROP MATERIALIZED VIEW IF EXISTS agg_monthly_sales;

CREATE MATERIALIZED VIEW agg_monthly_sales AS
SELECT tenant_id, date_trunc('month', order_date)::date AS month_start,
       count(*) FILTER (WHERE order_status IN ('VALID','PARTIAL_REFUND','REFUNDED')) AS valid_order_count,
       round(sum(net_amount - refund_amount)::numeric, 2) AS net_sales,
       round(sum(profit_amount - refund_amount)::numeric, 2) AS net_profit
FROM fact_sales
WHERE order_status <> 'TEST'
GROUP BY tenant_id, date_trunc('month', order_date);
CREATE UNIQUE INDEX ON agg_monthly_sales (tenant_id, month_start);

CREATE MATERIALIZED VIEW agg_region_product AS
SELECT tenant_id, region_id, product_id, date_trunc('month', order_date)::date AS month_start,
       count(*) AS order_count, round(sum(net_amount - refund_amount)::numeric, 2) AS net_sales
FROM fact_sales
WHERE order_status IN ('VALID','PARTIAL_REFUND','REFUNDED')
GROUP BY tenant_id, region_id, product_id, date_trunc('month', order_date);
CREATE UNIQUE INDEX ON agg_region_product (tenant_id, region_id, product_id, month_start);

CREATE MATERIALIZED VIEW agg_customer_contribution AS
SELECT tenant_id, customer_id, date_trunc('month', order_date)::date AS month_start,
       count(*) AS order_count, round(sum(net_amount - refund_amount)::numeric, 2) AS net_sales
FROM fact_sales
WHERE order_status IN ('VALID','PARTIAL_REFUND','REFUNDED')
GROUP BY tenant_id, customer_id, date_trunc('month', order_date);
CREATE UNIQUE INDEX ON agg_customer_contribution (tenant_id, customer_id, month_start);

CREATE MATERIALIZED VIEW agg_receivable_aging AS
SELECT tenant_id, aging_bucket, date_trunc('month', invoice_date)::date AS month_start,
       count(*) AS invoice_count, round(sum(outstanding_amount)::numeric, 2) AS outstanding_amount
FROM fact_payment
GROUP BY tenant_id, aging_bucket, date_trunc('month', invoice_date);
CREATE UNIQUE INDEX ON agg_receivable_aging (tenant_id, aging_bucket, month_start);
