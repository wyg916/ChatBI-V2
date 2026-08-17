from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select, text

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db.session import SessionLocal
from app.models import DataSource, SemanticModel
from app.services.datasources import build_connector


DANGEROUS = [
    "INSERT INTO demo_business.orders(order_id) VALUES (999999)",
    "UPDATE demo_business.orders SET revenue = 0",
    "DELETE FROM demo_business.orders",
    "DROP TABLE demo_business.orders",
    "ALTER TABLE demo_business.orders ADD COLUMN hacked int",
    "CREATE TABLE demo_business.hacked(id int)",
    "TRUNCATE TABLE demo_business.orders",
    "GRANT ALL ON demo_business.orders TO public",
    "REVOKE SELECT ON demo_business.orders FROM public",
    "COPY demo_business.orders TO '/tmp/orders.csv'",
    "SET ROLE postgres",
    "SELECT pg_read_file('/etc/passwd')",
    "SELECT pg_read_binary_file('/etc/passwd')",
    "SELECT pg_ls_dir('/')",
    "SELECT lo_import('/tmp/file')",
    "SELECT dblink_exec('x', 'DELETE FROM orders')",
    "SELECT * FROM pg_catalog.pg_user",
    "SELECT * FROM information_schema.tables",
    "SELECT * FROM demo_business.orders",
    "SELECT secret FROM demo_business.orders",
    "SELECT order_id FROM private.orders",
    "SELECT order_id FROM demo_business.unknown_table",
    "SELECT order_id FROM demo_business.orders; DELETE FROM demo_business.orders",
    "INSERT INTO orders(order_id) VALUES (999999)",
    "UPDATE orders SET revenue = 0",
    "DELETE FROM orders",
    "DROP TABLE orders",
    "TRUNCATE TABLE orders",
    "LOAD DATA INFILE '/tmp/x' INTO TABLE orders",
    "SELECT LOAD_FILE('/etc/passwd')",
    "SELECT SLEEP(10)",
    "SELECT BENCHMARK(1000000, SHA2('x', 256))",
    "SELECT * FROM mysql.user",
    "SELECT order_id FROM information_schema.tables",
    "SELECT order_id INTO OUTFILE '/tmp/x' FROM orders",
    "SELECT order_id FROM unknown_table",
    "SELECT password_hash FROM customers",
    "SELECT order_id FROM orders; DROP TABLE orders",
]


def post(base_url: str, body: dict) -> dict:
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}/api/v1/ask",
        data=json.dumps(body).encode("utf-8"), method="POST",
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=15) as response:
        return json.loads(response.read().decode("utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser()
    root = Path(__file__).resolve().parents[2]
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--output", type=Path, default=root / "docs" / "evidence" / "day2" / "security-results.json")
    args = parser.parse_args()
    with SessionLocal() as db:
        sources = list(db.scalars(select(DataSource).order_by(DataSource.type)))
        models = list(db.scalars(select(SemanticModel)))
        runtime = {
            item.type: (item, next(model for model in models if model.datasource_id == item.id))
            for item in sources if item.type in {"postgresql", "mysql"}
        }
        blocked: list[dict] = []
        for index, sql in enumerate(DANGEROUS):
            dialect = "postgresql" if index < 23 else "mysql"
            datasource, model = runtime[dialect]
            result = post(args.base_url, {
                "question": sql, "datasource_id": datasource.id,
                "semantic_model_id": model.id, "row_limit": 100,
            })
            blocked.append({
                "case": index + 1, "dialect": dialect, "status": result["status"],
                "blocked": result["status"] == "SECURITY_REJECTED",
                "error_code": result.get("error_code"),
                "execution_started": bool(result.get("execution")),
            })

        actual_write_attempts: list[dict] = []
        for dialect, (datasource, _) in runtime.items():
            connector = build_connector(datasource)
            engine = connector._engine()
            table = f"{datasource.schema}.orders" if dialect == "postgresql" else "orders"
            try:
                with engine.connect() as connection:
                    before = connection.scalar(text(f"SELECT COUNT(*) FROM {table}"))
                    connection.commit()
                    succeeded = False
                    error_type = None
                    try:
                        with connection.begin():
                            connection.execute(text(f"UPDATE {table} SET revenue = revenue WHERE order_id = -1"))
                        succeeded = True
                    except Exception as exc:
                        connection.rollback()
                        error_type = type(exc).__name__
                    after = connection.scalar(text(f"SELECT COUNT(*) FROM {table}"))
                    actual_write_attempts.append({
                        "dialect": dialect, "write_succeeded": succeeded,
                        "error_type": error_type, "row_count_before": before,
                        "row_count_after": after, "unchanged": before == after,
                    })
            finally:
                engine.dispose()

    block_count = sum(item["blocked"] for item in blocked)
    output = {
        "verified_at": datetime.now(timezone.utc).isoformat(),
        "dangerous_sql_cases": len(blocked),
        "dangerous_sql_block_count": block_count,
        "dangerous_sql_block_rate": block_count / len(blocked),
        "actual_write_attempt_succeeded": sum(item["write_succeeded"] for item in actual_write_attempts),
        "cases": blocked,
        "actual_write_attempts": actual_write_attempts,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: output[key] for key in (
        "dangerous_sql_cases", "dangerous_sql_block_count", "dangerous_sql_block_rate", "actual_write_attempt_succeeded",
    )}, ensure_ascii=False, indent=2))
    return 0 if block_count == len(blocked) and output["actual_write_attempt_succeeded"] == 0 and all(item["unchanged"] for item in actual_write_attempts) else 1


if __name__ == "__main__":
    raise SystemExit(main())
