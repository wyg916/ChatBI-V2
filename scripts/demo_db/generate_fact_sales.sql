SET search_path TO {{schema}};

INSERT INTO fact_sales
WITH source AS (
    SELECT i,
           date '{{date_start}}' + ((i * 37 + {{seed}}) % (date '{{date_end}}' - date '{{date_start}}' + 1))::integer AS order_date,
           ((i * 11 + {{seed}}) % {{tenant_count}})::integer + 1 AS tenant_id,
           ((i * 17 + {{seed}}) % {{customer_count}})::integer + 1 AS customer_id,
           ((i * 29 + {{seed}}) % {{product_count}})::integer + 1 AS product_id,
           ((i * 31 + {{seed}}) % 50)::integer + 1 AS region_id,
           ((i * 7 + {{seed}}) % 8)::integer + 1 AS base_quantity,
           round((120 + ((i * 53 + {{seed}}) % 150000) / 10.0)::numeric, 2) AS unit_price,
           CASE
             WHEN i % 100003 = 0 THEN 1.0000::numeric
             WHEN i % 997 = 0 THEN 0.9500::numeric
             WHEN i % 37 = 0 THEN 0.2500::numeric
             ELSE round((((i * 13 + {{seed}}) % 1800) / 10000.0)::numeric, 4)
           END AS discount_rate
    FROM generate_series(1, {{sales_count}}::bigint) AS s(i)
), shaped AS (
    SELECT *,
           CASE
             WHEN extract(month from order_date) IN (11, 12) THEN base_quantity + 2
             WHEN order_date BETWEEN date '2025-07-01' AND date '2025-07-31' AND region_id IN (7, 12) THEN greatest(1, base_quantity / 2)
             ELSE base_quantity
           END AS quantity,
           CASE
             WHEN i % 1009 = 0 THEN 'TEST'
             WHEN i % 97 = 0 THEN 'CANCELLED'
             WHEN i % 89 = 0 THEN 'REFUNDED'
             WHEN i % 53 = 0 THEN 'PARTIAL_REFUND'
             ELSE 'VALID'
           END AS order_status
    FROM source
), money AS (
    SELECT *, round((quantity * unit_price)::numeric, 2) AS gross_amount
    FROM shaped
)
SELECT tenant_id,
       i AS order_id,
       'EXT-' || lpad((((i - 1) % greatest(1, {{sales_count}} - 500000)) + 1)::text, 12, '0') AS external_order_no,
       order_date,
       customer_id,
       product_id,
       region_id,
       quantity,
       unit_price,
       discount_rate,
       gross_amount,
       CASE WHEN order_status IN ('CANCELLED','TEST') THEN 0 ELSE round((gross_amount * (1 - discount_rate))::numeric, 2) END AS net_amount,
       round((gross_amount * (0.55 + ((i + {{seed}}) % 1800) / 10000.0))::numeric, 2) AS cost_amount,
       CASE WHEN order_status IN ('CANCELLED','TEST') THEN 0 ELSE round((gross_amount * (1 - discount_rate) - gross_amount * (0.55 + ((i + {{seed}}) % 1800) / 10000.0))::numeric, 2) END AS profit_amount,
       order_status,
       CASE WHEN order_status = 'REFUNDED' THEN round((gross_amount * (1 - discount_rate))::numeric, 2)
            WHEN order_status = 'PARTIAL_REFUND' THEN round((gross_amount * (1 - discount_rate) * 0.30)::numeric, 2)
            ELSE 0 END AS refund_amount,
       (ARRAY['DIRECT','PARTNER','ONLINE','FIELD'])[((i + {{seed}}) % 4) + 1],
       ((i * 43 + {{seed}}) % 5000)::integer + 1,
       order_date::timestamp + (((i + {{seed}}) % 86400) || ' seconds')::interval
FROM money;
