CREATE TABLE regions (
  region_id INT PRIMARY KEY, region_code VARCHAR(16) NOT NULL UNIQUE,
  region_name VARCHAR(64) NOT NULL, province VARCHAR(64) NOT NULL
) COMMENT='区域维度';
CREATE TABLE customers (
  customer_id INT PRIMARY KEY, customer_name VARCHAR(96) NOT NULL,
  region_id INT NOT NULL, customer_type VARCHAR(24) NOT NULL, joined_at DATE NOT NULL,
  CONSTRAINT fk_customer_region FOREIGN KEY (region_id) REFERENCES regions(region_id)
);
CREATE TABLE products (
  product_id INT PRIMARY KEY, product_name VARCHAR(96) NOT NULL, category VARCHAR(48) NOT NULL,
  unit_price DECIMAL(12,2) NOT NULL, unit_cost DECIMAL(12,2) NOT NULL
);
CREATE TABLE stations (
  station_id INT PRIMARY KEY, station_code VARCHAR(24) NOT NULL UNIQUE, station_name VARCHAR(96) NOT NULL,
  region_id INT NOT NULL, capacity_kw DECIMAL(12,2) NOT NULL, status VARCHAR(20) NOT NULL,
  CONSTRAINT fk_station_region FOREIGN KEY (region_id) REFERENCES regions(region_id)
);
CREATE TABLE orders (
  order_id BIGINT PRIMARY KEY, customer_id INT NOT NULL, product_id INT NOT NULL, region_id INT NOT NULL,
  order_date DATE NOT NULL, quantity INT NOT NULL, revenue DECIMAL(14,2) NOT NULL,
  cost DECIMAL(14,2) NOT NULL, status VARCHAR(20) NOT NULL,
  CONSTRAINT fk_order_customer FOREIGN KEY (customer_id) REFERENCES customers(customer_id),
  CONSTRAINT fk_order_product FOREIGN KEY (product_id) REFERENCES products(product_id),
  CONSTRAINT fk_order_region FOREIGN KEY (region_id) REFERENCES regions(region_id)
);
CREATE TABLE charging_sessions (
  session_id BIGINT PRIMARY KEY, station_id INT NOT NULL, customer_id INT NOT NULL,
  started_at DATETIME NOT NULL, ended_at DATETIME NOT NULL, electricity_kwh DECIMAL(14,4) NOT NULL,
  status VARCHAR(20) NOT NULL,
  CONSTRAINT fk_session_station FOREIGN KEY (station_id) REFERENCES stations(station_id),
  CONSTRAINT fk_session_customer FOREIGN KEY (customer_id) REFERENCES customers(customer_id)
);
CREATE TABLE charging_orders (
  charging_order_id BIGINT PRIMARY KEY, session_id BIGINT NOT NULL, station_id INT NOT NULL,
  region_id INT NOT NULL, finish_time DATETIME NOT NULL, order_amount DECIMAL(14,2) NOT NULL COMMENT '订单金额',
  electricity_kwh DECIMAL(14,4) NOT NULL COMMENT '充电电量', order_status VARCHAR(20) NOT NULL,
  CONSTRAINT fk_charging_session FOREIGN KEY (session_id) REFERENCES charging_sessions(session_id),
  CONSTRAINT fk_charging_station FOREIGN KEY (station_id) REFERENCES stations(station_id),
  CONSTRAINT fk_charging_region FOREIGN KEY (region_id) REFERENCES regions(region_id)
) COMMENT='充电订单明细';
CREATE TABLE payments (
  payment_id BIGINT PRIMARY KEY, order_id BIGINT NOT NULL, paid_at DATETIME NOT NULL,
  amount DECIMAL(14,2) NOT NULL, payment_method VARCHAR(24) NOT NULL, status VARCHAR(20) NOT NULL,
  CONSTRAINT fk_payment_order FOREIGN KEY (order_id) REFERENCES orders(order_id)
);
CREATE TABLE daily_kpi (
  kpi_date DATE NOT NULL, region_id INT NOT NULL, order_count INT NOT NULL,
  revenue DECIMAL(14,2) NOT NULL, cost DECIMAL(14,2) NOT NULL, charging_kwh DECIMAL(14,4) NOT NULL,
  PRIMARY KEY (kpi_date, region_id),
  CONSTRAINT fk_kpi_region FOREIGN KEY (region_id) REFERENCES regions(region_id)
);

INSERT INTO regions VALUES
  (1,'NORTH','华北','北京'),(2,'EAST','华东','上海'),(3,'SOUTH','华南','广东'),
  (4,'WEST','西部','四川'),(5,'CENTRAL','华中','湖北');
INSERT INTO products VALUES
  (1,'家用充电桩','充电设备',2899,1900),(2,'商用充电桩','充电设备',12800,8600),
  (3,'储能柜','储能设备',68000,51000),(4,'能源管理终端','软件与终端',5200,2700),
  (5,'运维服务包','服务',3600,1200);

SET SESSION cte_max_recursion_depth = 2000;
CREATE TEMPORARY TABLE sequence_numbers AS
WITH RECURSIVE seq AS (
  SELECT 0 AS n
  UNION ALL
  SELECT n + 1 FROM seq WHERE n < 1094
)
SELECT n FROM seq;
ALTER TABLE sequence_numbers ADD PRIMARY KEY (n);

INSERT INTO customers
SELECT n + 1, CONCAT('客户-', LPAD(n + 1,3,'0')), MOD(n,5)+1,
       ELT(MOD(n,3)+1,'企业','个人','渠道'), DATE_ADD('2025-01-01', INTERVAL MOD((n + 1)*7,365) DAY)
FROM sequence_numbers WHERE n < 60;

INSERT INTO stations
SELECT n + 1, CONCAT('ST-',LPAD(n + 1,3,'0')), CONCAT('示范充电站-',LPAD(n + 1,2,'0')),
       MOD(n,5)+1, 120+(n + 1)*30, 'ACTIVE'
FROM sequence_numbers WHERE n < 10;

INSERT INTO orders
SELECT n + 1, MOD(n,60)+1, MOD(n,5)+1, MOD(n,5)+1,
       DATE_ADD(DATE_SUB(DATE('2026-08-17'), INTERVAL 364 DAY), INTERVAL FLOOR(n/3) DAY), MOD(n + 1,4)+1,
       ROUND(300+MOD(n + 1,70)*37.5,2), ROUND(210+MOD(n + 1,55)*24.5,2),
       IF(MOD(n + 1,19)=0,'REFUNDED','PAID')
FROM sequence_numbers;

INSERT INTO charging_sessions
SELECT n + 1, MOD(n,10)+1, MOD(n,60)+1,
       DATE_ADD(DATE_ADD(DATE_SUB(DATE('2026-08-17'), INTERVAL 364 DAY),INTERVAL FLOOR(n/2) DAY),INTERVAL MOD(n + 1,18) HOUR),
       DATE_ADD(DATE_ADD(DATE_SUB(DATE('2026-08-17'), INTERVAL 364 DAY),INTERVAL FLOOR(n/2) DAY),INTERVAL (MOD(n + 1,18)+1) HOUR),
       ROUND(18+MOD(n + 1,45)*1.37,4), 'COMPLETED'
FROM sequence_numbers WHERE n < 730;

INSERT INTO charging_orders
SELECT s.session_id,s.session_id,s.station_id,st.region_id,s.ended_at,
       ROUND(s.electricity_kwh*1.28,2),s.electricity_kwh,'PAID'
FROM charging_sessions s JOIN stations st ON st.station_id=s.station_id;

INSERT INTO payments
SELECT order_id,order_id,DATE_ADD(order_date,INTERVAL 12 HOUR),revenue,
       ELT(MOD(order_id-1,3)+1,'WECHAT','ALIPAY','BANK'),'SUCCESS'
FROM orders WHERE status='PAID';

INSERT INTO daily_kpi
SELECT DATE_ADD(DATE_SUB(DATE('2026-08-17'),INTERVAL 364 DAY),INTERVAL n DAY),region_id,
       8+MOD(n+region_id,11),3200+region_id*350+MOD(n,17)*80,
       2100+region_id*230+MOD(n,13)*55,480+region_id*42+MOD(n,19)*9.5
FROM sequence_numbers CROSS JOIN regions WHERE n < 365;

DROP TEMPORARY TABLE sequence_numbers;
