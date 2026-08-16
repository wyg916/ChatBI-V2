SET search_path TO demo_business;

CREATE TABLE regions (
    region_id integer PRIMARY KEY,
    region_code varchar(16) NOT NULL UNIQUE,
    region_name varchar(64) NOT NULL,
    province varchar(64) NOT NULL
);

CREATE TABLE customers (
    customer_id integer PRIMARY KEY,
    customer_name varchar(96) NOT NULL,
    region_id integer NOT NULL REFERENCES regions(region_id),
    customer_type varchar(24) NOT NULL,
    joined_at date NOT NULL
);

CREATE TABLE products (
    product_id integer PRIMARY KEY,
    product_name varchar(96) NOT NULL,
    category varchar(48) NOT NULL,
    unit_price numeric(12,2) NOT NULL,
    unit_cost numeric(12,2) NOT NULL
);

CREATE TABLE stations (
    station_id integer PRIMARY KEY,
    station_code varchar(24) NOT NULL UNIQUE,
    station_name varchar(96) NOT NULL,
    region_id integer NOT NULL REFERENCES regions(region_id),
    capacity_kw numeric(12,2) NOT NULL,
    status varchar(20) NOT NULL
);

CREATE TABLE orders (
    order_id bigint PRIMARY KEY,
    customer_id integer NOT NULL REFERENCES customers(customer_id),
    product_id integer NOT NULL REFERENCES products(product_id),
    region_id integer NOT NULL REFERENCES regions(region_id),
    order_date date NOT NULL,
    quantity integer NOT NULL,
    revenue numeric(14,2) NOT NULL,
    cost numeric(14,2) NOT NULL,
    status varchar(20) NOT NULL
);

CREATE TABLE charging_sessions (
    session_id bigint PRIMARY KEY,
    station_id integer NOT NULL REFERENCES stations(station_id),
    customer_id integer NOT NULL REFERENCES customers(customer_id),
    started_at timestamp NOT NULL,
    ended_at timestamp NOT NULL,
    electricity_kwh numeric(14,4) NOT NULL,
    status varchar(20) NOT NULL
);

CREATE TABLE charging_orders (
    charging_order_id bigint PRIMARY KEY,
    session_id bigint NOT NULL REFERENCES charging_sessions(session_id),
    station_id integer NOT NULL REFERENCES stations(station_id),
    region_id integer NOT NULL REFERENCES regions(region_id),
    finish_time timestamp NOT NULL,
    order_amount numeric(14,2) NOT NULL,
    electricity_kwh numeric(14,4) NOT NULL,
    order_status varchar(20) NOT NULL
);

CREATE TABLE payments (
    payment_id bigint PRIMARY KEY,
    order_id bigint NOT NULL REFERENCES orders(order_id),
    paid_at timestamp NOT NULL,
    amount numeric(14,2) NOT NULL,
    payment_method varchar(24) NOT NULL,
    status varchar(20) NOT NULL
);

CREATE TABLE daily_kpi (
    kpi_date date NOT NULL,
    region_id integer NOT NULL REFERENCES regions(region_id),
    order_count integer NOT NULL,
    revenue numeric(14,2) NOT NULL,
    cost numeric(14,2) NOT NULL,
    charging_kwh numeric(14,4) NOT NULL,
    PRIMARY KEY (kpi_date, region_id)
);

COMMENT ON TABLE charging_orders IS '充电订单明细';
COMMENT ON COLUMN charging_orders.order_amount IS '订单金额';
COMMENT ON COLUMN charging_orders.electricity_kwh IS '充电电量';

INSERT INTO regions VALUES
  (1, 'NORTH', '华北', '北京'), (2, 'EAST', '华东', '上海'),
  (3, 'SOUTH', '华南', '广东'), (4, 'WEST', '西部', '四川'),
  (5, 'CENTRAL', '华中', '湖北');

INSERT INTO products VALUES
  (1, '家用充电桩', '充电设备', 2899, 1900), (2, '商用充电桩', '充电设备', 12800, 8600),
  (3, '储能柜', '储能设备', 68000, 51000), (4, '能源管理终端', '软件与终端', 5200, 2700),
  (5, '运维服务包', '服务', 3600, 1200);

INSERT INTO customers
SELECT i, '客户-' || lpad(i::text, 3, '0'), ((i - 1) % 5) + 1,
       (ARRAY['企业','个人','渠道'])[((i - 1) % 3) + 1],
       date '2025-01-01' + ((i * 7) % 365)
FROM generate_series(1, 60) AS s(i);

INSERT INTO stations
SELECT i, 'ST-' || lpad(i::text, 3, '0'), '示范充电站-' || lpad(i::text, 2, '0'),
       ((i - 1) % 5) + 1, 120 + i * 30, 'ACTIVE'
FROM generate_series(1, 10) AS s(i);

INSERT INTO orders
SELECT i, ((i - 1) % 60) + 1, ((i - 1) % 5) + 1, ((i - 1) % 5) + 1,
       current_date - 364 + ((i - 1) / 3), 1 + (i % 4),
       round((300 + (i % 70) * 37.5)::numeric, 2), round((210 + (i % 55) * 24.5)::numeric, 2),
       CASE WHEN i % 19 = 0 THEN 'REFUNDED' ELSE 'PAID' END
FROM generate_series(1, 1095) AS s(i);

INSERT INTO charging_sessions
SELECT i, ((i - 1) % 10) + 1, ((i - 1) % 60) + 1,
       (current_date - 364 + ((i - 1) / 2))::timestamp + ((i % 18) || ' hours')::interval,
       (current_date - 364 + ((i - 1) / 2))::timestamp + (((i % 18) + 1) || ' hours')::interval,
       round((18 + (i % 45) * 1.37)::numeric, 4), 'COMPLETED'
FROM generate_series(1, 730) AS s(i);

INSERT INTO charging_orders
SELECT s.session_id, s.session_id, s.station_id, st.region_id, s.ended_at,
       round((s.electricity_kwh * 1.28)::numeric, 2), s.electricity_kwh, 'PAID'
FROM charging_sessions s JOIN stations st ON st.station_id = s.station_id;

INSERT INTO payments
SELECT order_id, order_id, order_date::timestamp + interval '12 hours', revenue,
       (ARRAY['WECHAT','ALIPAY','BANK'])[((order_id - 1) % 3) + 1], 'SUCCESS'
FROM orders WHERE status = 'PAID';

INSERT INTO daily_kpi
SELECT d::date, r.region_id,
       8 + ((extract(doy from d)::integer + r.region_id) % 11),
       round((3200 + r.region_id * 350 + (extract(doy from d)::integer % 17) * 80)::numeric, 2),
       round((2100 + r.region_id * 230 + (extract(doy from d)::integer % 13) * 55)::numeric, 2),
       round((480 + r.region_id * 42 + (extract(doy from d)::integer % 19) * 9.5)::numeric, 4)
FROM generate_series(current_date - 364, current_date, interval '1 day') d
CROSS JOIN regions r;
