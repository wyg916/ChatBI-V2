SET search_path TO {{schema}};

CREATE INDEX IF NOT EXISTS ix_fact_sales_tenant_date ON fact_sales (tenant_id, order_date);
CREATE INDEX IF NOT EXISTS ix_fact_sales_tenant_region_date ON fact_sales (tenant_id, region_id, order_date);
CREATE INDEX IF NOT EXISTS ix_fact_sales_tenant_product_date ON fact_sales (tenant_id, product_id, order_date);
CREATE INDEX IF NOT EXISTS ix_fact_sales_tenant_customer_date ON fact_sales (tenant_id, customer_id, order_date);
CREATE INDEX IF NOT EXISTS ix_fact_sales_valid_orders ON fact_sales (tenant_id, order_date, net_amount) WHERE order_status IN ('VALID','PARTIAL_REFUND');
CREATE INDEX IF NOT EXISTS ix_fact_payment_tenant_date ON fact_payment (tenant_id, invoice_date);
CREATE INDEX IF NOT EXISTS ix_fact_payment_unsettled ON fact_payment (tenant_id, due_date, outstanding_amount) WHERE outstanding_amount > 0;

ALTER TABLE fact_sales DROP CONSTRAINT IF EXISTS fk_fact_sales_customer;
ALTER TABLE fact_sales ADD CONSTRAINT fk_fact_sales_customer FOREIGN KEY (customer_id) REFERENCES dim_customer(customer_id) NOT VALID;
ALTER TABLE fact_sales DROP CONSTRAINT IF EXISTS fk_fact_sales_product;
ALTER TABLE fact_sales ADD CONSTRAINT fk_fact_sales_product FOREIGN KEY (product_id) REFERENCES dim_product(product_id) NOT VALID;
ALTER TABLE fact_sales DROP CONSTRAINT IF EXISTS fk_fact_sales_region;
ALTER TABLE fact_sales ADD CONSTRAINT fk_fact_sales_region FOREIGN KEY (region_id) REFERENCES dim_region(region_id) NOT VALID;

CREATE STATISTICS IF NOT EXISTS st_fact_sales_tenant_region_date (dependencies, ndistinct)
ON tenant_id, region_id, order_date FROM fact_sales;
CREATE STATISTICS IF NOT EXISTS st_fact_sales_tenant_product_date (dependencies, ndistinct)
ON tenant_id, product_id, order_date FROM fact_sales;
