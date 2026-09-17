from __future__ import annotations

import argparse
import json
from datetime import date
from decimal import Decimal
from pathlib import Path

from psycopg.types.json import Jsonb

from _common import atomic_json, canonical_hash, connect, load_env, validate_schema


METRICS = (
    ("net_sales", "round(sum(net_amount - refund_amount)::numeric, 2)"),
    ("net_profit", "round(sum(profit_amount - refund_amount)::numeric, 2)"),
    ("valid_orders", "count(*) FILTER (WHERE order_status IN ('VALID','PARTIAL_REFUND','REFUNDED'))"),
    ("active_customers", "count(DISTINCT customer_id) FILTER (WHERE order_status IN ('VALID','PARTIAL_REFUND','REFUNDED'))"),
    ("refund_amount", "round(sum(refund_amount)::numeric, 2)"),
)


def build_cases(conn, schema: str, data_signature: str, count: int = 100) -> list[dict]:
    cases: list[dict] = []
    month = date(2024, 1, 1)
    months: list[date] = []
    for _ in range(20):
        months.append(month)
        month = date(month.year + (month.month == 12), 1 if month.month == 12 else month.month + 1, 1)
    batch_rows = conn.execute(
        f'''SELECT tenant_id, date_trunc('month', order_date)::date AS month_start,
                   round(sum(net_amount - refund_amount)::numeric, 2) AS net_sales,
                   round(sum(profit_amount - refund_amount)::numeric, 2) AS net_profit,
                   count(*) FILTER (WHERE order_status IN ('VALID','PARTIAL_REFUND','REFUNDED')) AS valid_orders,
                   count(DISTINCT customer_id) FILTER (WHERE order_status IN ('VALID','PARTIAL_REFUND','REFUNDED')) AS active_customers,
                   round(sum(refund_amount)::numeric, 2) AS refund_amount
            FROM "{schema}".fact_sales
            WHERE tenant_id BETWEEN 1 AND 10
              AND order_date >= date '2024-01-01' AND order_date < date '2025-09-01'
              AND order_status <> 'TEST'
            GROUP BY tenant_id, date_trunc('month', order_date)'''
    ).fetchall()
    batch = {
        (row[0], row[1]): {
            "net_sales": row[2], "net_profit": row[3], "valid_orders": row[4],
            "active_customers": row[5], "refund_amount": row[6],
        }
        for row in batch_rows
    }
    for index in range(count):
        tenant = index % 10 + 1
        month_start = months[(index // len(METRICS)) % len(months)]
        month_end = date(month_start.year + (month_start.month == 12), 1 if month_start.month == 12 else month_start.month + 1, 1)
        metric_name, expression = METRICS[index % len(METRICS)]
        sql = (
            f'SELECT {expression} AS value FROM "{schema}".fact_sales '
            f"WHERE tenant_id = {tenant} AND order_date >= date '{month_start.isoformat()}' "
            f"AND order_date < date '{month_end.isoformat()}' AND order_status <> 'TEST'"
        )
        raw_value = batch[(tenant, month_start)][metric_name]
        value = str(raw_value) if isinstance(raw_value, Decimal) else raw_value
        result = [{"value": value}]
        case = {
            "case_id": f"GT-{index + 1:03d}",
            "question": f"租户 {tenant} 在 {month_start:%Y-%m} 的 {metric_name} 是多少？",
            "sql": sql,
            "expected": result,
            "result_signature": canonical_hash(result),
            "data_signature": data_signature,
        }
        conn.execute(
            f'''INSERT INTO "{schema}".golden_expected_result
                (case_id, question, sql_text, expected_json, result_signature, data_signature)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (case_id) DO UPDATE SET
                  question=excluded.question, sql_text=excluded.sql_text,
                  expected_json=excluded.expected_json, result_signature=excluded.result_signature,
                  data_signature=excluded.data_signature, generated_at=now()''',
            (case["case_id"], case["question"], sql, Jsonb(result), case["result_signature"], data_signature),
        )
        cases.append(case)
    return cases


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--env-file", type=Path, default=Path(".env"))
    parser.add_argument("--schema", default="chatbi_benchmark_v21")
    parser.add_argument("--data-signature", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--count", type=int, default=100)
    args = parser.parse_args()
    schema = validate_schema(args.schema)
    env = load_env(args.env_file)
    with connect(env) as conn:
        cases = build_cases(conn, schema, args.data_signature, args.count)
        conn.commit()
    atomic_json(args.output, {"count": len(cases), "data_signature": args.data_signature, "cases": cases})


if __name__ == "__main__":
    main()
