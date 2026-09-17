SET search_path TO {{schema}};

INSERT INTO dim_date
SELECT d::date,
       extract(year from d)::smallint,
       extract(quarter from d)::smallint,
       extract(month from d)::smallint,
       to_char(d, 'YYYY-MM'),
       extract(week from d)::smallint,
       extract(day from d)::smallint,
       (extract(year from d) + CASE WHEN extract(month from d) >= 4 THEN 1 ELSE 0 END)::smallint,
       (((extract(month from d)::integer + 8) % 12) + 1)::smallint,
       extract(isodow from d) IN (6, 7)
FROM generate_series(date '{{date_start}}', date '{{date_end}}', interval '1 day') AS t(d)
ON CONFLICT DO NOTHING;

INSERT INTO dim_region
SELECT i,
       'R-' || lpad(i::text, 3, '0'),
       (ARRAY['华北','华东','华南','西部','华中'])[((i - 1) % 5) + 1] || '-' || lpad(i::text, 2, '0'),
       '省份-' || lpad((((i - 1) % 31) + 1)::text, 2, '0'),
       '城市-' || lpad(i::text, 2, '0'),
       (ARRAY['NORTH','EAST','SOUTH','WEST','CENTRAL'])[((i - 1) % 5) + 1]
FROM generate_series(1, 50) AS s(i)
ON CONFLICT DO NOTHING;

INSERT INTO dim_product
SELECT i,
       'P-' || lpad(i::text, 8, '0'),
       '产品-' || lpad(i::text, 8, '0'),
       (ARRAY['充电设备','储能设备','能源软件','运维服务','配套器件'])[((i - 1) % 5) + 1],
       '品牌-' || lpad((((i * 17 + {{seed}}) % 200) + 1)::text, 3, '0'),
       round((80 + ((i * 37 + {{seed}}) % 90000) / 10.0)::numeric, 2),
       round((120 + ((i * 53 + {{seed}}) % 150000) / 10.0)::numeric, 2),
       CASE WHEN i % 97 = 0 THEN 'DISCONTINUED' WHEN i % 17 = 0 THEN 'MATURE' ELSE 'ACTIVE' END
FROM generate_series(1, {{product_count}}) AS s(i)
ON CONFLICT DO NOTHING;

INSERT INTO dim_customer
SELECT i,
       'C-' || lpad(i::text, 9, '0'),
       '客户-' || lpad(i::text, 9, '0'),
       (ARRAY['STRATEGIC','KEY','GROWTH','STANDARD'])[((i * 13 + {{seed}}) % 4) + 1],
       (ARRAY['制造','零售','交通','能源','地产','公共事业'])[((i * 7 + {{seed}}) % 6) + 1],
       ((i * 19 + {{seed}}) % 50) + 1,
       date '{{date_start}}' + ((i * 23 + {{seed}}) % (date '{{date_end}}' - date '{{date_start}}' + 1)),
       CASE WHEN i % 101 = 0 THEN NULL ELSE 'customer' || i || '@example.invalid' END,
       CASE WHEN i % 89 = 0 THEN NULL ELSE '138' || lpad((i % 100000000)::text, 8, '0') END
FROM generate_series(1, {{customer_count}}) AS s(i)
ON CONFLICT DO NOTHING;
