CREATE SCHEMA IF NOT EXISTS {{schema}};
SET search_path TO {{schema}};

CREATE TABLE IF NOT EXISTS dim_date (
    date_key date PRIMARY KEY,
    calendar_year smallint NOT NULL,
    calendar_quarter smallint NOT NULL,
    calendar_month smallint NOT NULL,
    month_name varchar(16) NOT NULL,
    week_of_year smallint NOT NULL,
    day_of_month smallint NOT NULL,
    fiscal_year smallint NOT NULL,
    fiscal_period smallint NOT NULL,
    is_weekend boolean NOT NULL
);

CREATE TABLE IF NOT EXISTS dim_region (
    region_id integer PRIMARY KEY,
    region_code varchar(16) NOT NULL UNIQUE,
    region_name varchar(64) NOT NULL,
    province varchar(64) NOT NULL,
    city varchar(64) NOT NULL,
    region_group varchar(24) NOT NULL
);

CREATE TABLE IF NOT EXISTS dim_product (
    product_id integer PRIMARY KEY,
    product_code varchar(24) NOT NULL UNIQUE,
    product_name varchar(96) NOT NULL,
    category varchar(48) NOT NULL,
    brand varchar(48) NOT NULL,
    unit_cost numeric(12,2) NOT NULL,
    list_price numeric(12,2) NOT NULL,
    lifecycle_status varchar(20) NOT NULL
);

CREATE TABLE IF NOT EXISTS dim_customer (
    customer_id integer PRIMARY KEY,
    customer_code varchar(24) NOT NULL UNIQUE,
    customer_name varchar(96) NOT NULL,
    customer_tier varchar(16) NOT NULL,
    industry varchar(48) NOT NULL,
    registered_region_id integer NOT NULL,
    registered_at date NOT NULL,
    email varchar(128),
    phone varchar(32)
);

CREATE TABLE IF NOT EXISTS fact_sales (
    tenant_id integer NOT NULL,
    order_id bigint NOT NULL,
    external_order_no varchar(32) NOT NULL,
    order_date date NOT NULL,
    customer_id integer NOT NULL,
    product_id integer NOT NULL,
    region_id integer NOT NULL,
    quantity integer NOT NULL,
    unit_price numeric(12,2) NOT NULL,
    discount_rate numeric(7,4),
    gross_amount numeric(16,2) NOT NULL,
    net_amount numeric(16,2) NOT NULL,
    cost_amount numeric(16,2) NOT NULL,
    profit_amount numeric(16,2) NOT NULL,
    order_status varchar(24) NOT NULL,
    refund_amount numeric(16,2) NOT NULL,
    sales_channel varchar(24) NOT NULL,
    salesperson_id integer NOT NULL,
    created_at timestamp NOT NULL,
    PRIMARY KEY (tenant_id, order_date, order_id)
) PARTITION BY RANGE (order_date);

CREATE TABLE IF NOT EXISTS fact_payment (
    tenant_id integer NOT NULL,
    payment_id bigint NOT NULL,
    order_id bigint NOT NULL,
    invoice_date date NOT NULL,
    due_date date NOT NULL,
    payment_date date,
    receivable_amount numeric(16,2) NOT NULL,
    received_amount numeric(16,2) NOT NULL,
    outstanding_amount numeric(16,2) NOT NULL,
    aging_bucket varchar(24) NOT NULL,
    payment_status varchar(24) NOT NULL,
    created_at timestamp NOT NULL,
    PRIMARY KEY (tenant_id, invoice_date, payment_id)
) PARTITION BY RANGE (invoice_date);

CREATE TABLE IF NOT EXISTS golden_expected_result (
    case_id varchar(40) PRIMARY KEY,
    question text NOT NULL,
    sql_text text NOT NULL,
    expected_json jsonb NOT NULL,
    result_signature varchar(64) NOT NULL,
    data_signature varchar(64) NOT NULL,
    generated_at timestamptz NOT NULL DEFAULT now()
);
