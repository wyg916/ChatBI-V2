from __future__ import annotations

import argparse
from pathlib import Path
from time import perf_counter

from _common import connect, load_env, validate_schema


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Idempotently bring an existing isolated benchmark schema to the external-order quality baseline",
    )
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--schema", default="chatbi_benchmark_v21")
    parser.add_argument("--sales-count", type=int, required=True)
    args = parser.parse_args()
    schema = validate_schema(args.schema)
    if args.sales_count < 1:
        raise SystemExit("sales-count must be positive")
    started = perf_counter()
    with connect(load_env(args.env_file)) as conn:
        conn.execute("SET statement_timeout=0")
        exists = conn.execute(
            "SELECT 1 FROM information_schema.columns WHERE table_schema=%s AND table_name='fact_sales' AND column_name='external_order_no'",
            (schema,),
        ).fetchone()
        if not exists:
            conn.execute(f'ALTER TABLE "{schema}".fact_sales ADD COLUMN external_order_no varchar(32)')
        update = conn.execute(
            f'''UPDATE "{schema}".fact_sales
                SET external_order_no = 'EXT-' || lpad((((order_id - 1) %% greatest(1, %s - 500000)) + 1)::text, 12, '0')
                WHERE external_order_no IS NULL''',
            (args.sales_count,),
        )
        updated = update.rowcount
        conn.execute(f'ALTER TABLE "{schema}".fact_sales ALTER COLUMN external_order_no SET NOT NULL')
        conn.execute(f'ANALYZE "{schema}".fact_sales (external_order_no)')
        duplicate_rows = conn.execute(
            f'SELECT count(*) - count(DISTINCT external_order_no) FROM "{schema}".fact_sales'
        ).fetchone()[0]
        null_rows = conn.execute(
            f'SELECT count(*) FROM "{schema}".fact_sales WHERE external_order_no IS NULL'
        ).fetchone()[0]
        conn.commit()
        conn.autocommit = True
        conn.execute(f'VACUUM (ANALYZE) "{schema}".fact_sales')
    print(
        f"external_order_no=PASS updated_rows={updated} "
        f"duplicate_rows={duplicate_rows} null_rows={null_rows} elapsed_s={perf_counter() - started:.3f}",
        flush=True,
    )


if __name__ == "__main__":
    main()
