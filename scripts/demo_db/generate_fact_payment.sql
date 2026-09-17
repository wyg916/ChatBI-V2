SET search_path TO {{schema}};

INSERT INTO fact_payment
SELECT tenant_id,
       row_number() OVER (ORDER BY order_id)::bigint AS payment_id,
       order_id,
       order_date AS invoice_date,
       order_date + (((order_id + {{seed}}) % 45) + 15)::integer AS due_date,
       CASE WHEN order_id % 17 = 0 THEN NULL ELSE order_date + (((order_id + {{seed}}) % 60) + 1)::integer END AS payment_date,
       net_amount AS receivable_amount,
       CASE WHEN order_status IN ('CANCELLED','TEST') THEN 0
            WHEN order_id % 17 = 0 THEN round((net_amount * 0.20)::numeric, 2)
            WHEN order_id % 23 = 0 THEN round((net_amount * 0.65)::numeric, 2)
            ELSE net_amount END AS received_amount,
       CASE WHEN order_status IN ('CANCELLED','TEST') THEN 0
            WHEN order_id % 17 = 0 THEN round((net_amount * 0.80)::numeric, 2)
            WHEN order_id % 23 = 0 THEN round((net_amount * 0.35)::numeric, 2)
            ELSE 0 END AS outstanding_amount,
       CASE WHEN order_id % 17 <> 0 AND order_id % 23 <> 0 THEN 'PAID'
            WHEN ((order_id + {{seed}}) % 120) < 30 THEN '0_30'
            WHEN ((order_id + {{seed}}) % 120) < 60 THEN '31_60'
            WHEN ((order_id + {{seed}}) % 120) < 90 THEN '61_90'
            ELSE '90_PLUS' END AS aging_bucket,
       CASE WHEN order_status IN ('CANCELLED','TEST') THEN 'VOID'
            WHEN order_id % 17 = 0 THEN 'OVERDUE'
            WHEN order_id % 23 = 0 THEN 'PARTIAL'
            ELSE 'PAID' END AS payment_status,
       order_date::timestamp + (((order_id + {{seed}}) % 86400) || ' seconds')::interval
FROM fact_sales
WHERE order_id <= {{payment_count}};
