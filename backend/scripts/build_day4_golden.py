from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
from typing import Any


ORIGINAL_SHA256 = "741da55b7dd41046a6f8411522a3cf92afb45ca1ac38b90b202b49c87f8eef0e"


def manifest_hash(manifest: dict[str, Any]) -> str:
    value = copy.deepcopy(manifest)
    value["manifest_sha256"] = None
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def case(
    case_id: str,
    category: str,
    question: str,
    entities: list[str],
    metrics: list[str],
    dimensions: list[str],
    sql: str,
    *,
    filters: list[dict[str, Any]] | None = None,
    time_range: dict[str, str] | None = None,
    mysql_sql: str | None = None,
) -> dict[str, Any]:
    value: dict[str, Any] = {
        "id": case_id,
        "category": category,
        "question": question,
        "expected_entities": entities,
        "expected_metrics": metrics,
        "expected_dimensions": dimensions,
        "expected_filters": filters or [],
        "expected_time_range": time_range,
        "expected_sql": sql,
        "expected_result": [],
        "expected_signature": None,
        "expected_outcome": "PASSED",
    }
    if mysql_sql:
        value.update(mysql_expected_sql=mysql_sql, mysql_expected_result=[], mysql_expected_signature=None)
    return value


def new_cases() -> list[dict[str, Any]]:
    return [
        case("G21", "simple_aggregate", "统计全部订单成本", ["orders"], ["cost"], [],
             "SELECT SUM(o.cost) AS cost FROM demo_business.orders o",
             mysql_sql="SELECT SUM(o.cost) AS cost FROM orders o"),
        case("G22", "derived_metric", "统计全部订单利润", ["orders"], ["profit"], [],
             "SELECT SUM(o.revenue - o.cost) AS profit FROM demo_business.orders o",
             mysql_sql="SELECT SUM(o.revenue - o.cost) AS profit FROM orders o"),
        case("G23", "derived_metric", "统计平均订单金额", ["orders"], ["avg_order_value"], [],
             "SELECT AVG(o.revenue) AS avg_order_value FROM demo_business.orders o",
             mysql_sql="SELECT AVG(o.revenue) AS avg_order_value FROM orders o"),
        case("G24", "simple_aggregate", "统计订单量", ["orders"], ["order_count"], [],
             "SELECT COUNT(o.order_id) AS order_count FROM demo_business.orders o",
             mysql_sql="SELECT COUNT(o.order_id) AS order_count FROM orders o"),
        case("G25", "null", "统计状态为空的订单量", ["orders"], ["order_count"], [],
             "SELECT COUNT(o.order_id) AS order_count FROM demo_business.orders o WHERE o.status IS NULL",
             filters=[{"field": "orders.status", "value": None}],
             mysql_sql="SELECT COUNT(o.order_id) AS order_count FROM orders o WHERE o.status IS NULL"),
        case("G26", "group", "按地区统计订单成本", ["orders", "regions"], ["cost"], ["region"],
             "SELECT r.region_name AS region, SUM(o.cost) AS cost FROM demo_business.orders o JOIN demo_business.regions r ON r.region_id = o.region_id GROUP BY r.region_name, r.region_id ORDER BY cost DESC, r.region_id ASC"),
        case("G27", "topn_join", "按产品统计订单利润前3名", ["orders", "products"], ["profit"], ["product"],
             "SELECT p.product_name AS product, SUM(o.revenue - o.cost) AS profit FROM demo_business.orders o JOIN demo_business.products p ON p.product_id = o.product_id GROUP BY p.product_name, p.product_id ORDER BY profit DESC, p.product_id ASC LIMIT 3"),
        case("G28", "group_join", "按品类统计订单收入", ["orders", "products"], ["revenue"], ["category"],
             "SELECT p.category AS category, SUM(o.revenue) AS revenue FROM demo_business.orders o JOIN demo_business.products p ON p.product_id = o.product_id GROUP BY p.category ORDER BY revenue DESC, p.category ASC"),
        case("G29", "topn_join", "按客户统计订单收入前5名", ["orders", "customers"], ["revenue"], ["customer"],
             "SELECT c.customer_name AS customer, SUM(o.revenue) AS revenue FROM demo_business.orders o JOIN demo_business.customers c ON c.customer_id = o.customer_id GROUP BY c.customer_name, c.customer_id ORDER BY revenue DESC, c.customer_id ASC LIMIT 5"),
        case("G30", "group_join", "按客户类型统计订单量", ["orders", "customers"], ["order_count"], ["customer_type"],
             "SELECT c.customer_type AS customer_type, COUNT(o.order_id) AS order_count FROM demo_business.orders o JOIN demo_business.customers c ON c.customer_id = o.customer_id GROUP BY c.customer_type ORDER BY order_count DESC, c.customer_type ASC"),
        case("G31", "time_trend", "2026年按月统计订单成本趋势", ["orders"], ["cost"], ["month"],
             "SELECT DATE_TRUNC('month', o.order_date) AS month, SUM(o.cost) AS cost FROM demo_business.orders o WHERE o.order_date >= DATE '2026-01-01' AND o.order_date < DATE '2027-01-01' GROUP BY DATE_TRUNC('month', o.order_date) ORDER BY month ASC",
             time_range={"start": "2026-01-01", "end_exclusive": "2027-01-01"}),
        case("G32", "multi_dimension_time", "2026年按地区按月统计订单成本", ["orders", "regions"], ["cost"], ["region", "month"],
             "SELECT r.region_name AS region, DATE_TRUNC('month', o.order_date) AS month, SUM(o.cost) AS cost FROM demo_business.orders o JOIN demo_business.regions r ON r.region_id = o.region_id WHERE o.order_date >= DATE '2026-01-01' AND o.order_date < DATE '2027-01-01' GROUP BY r.region_name, r.region_id, DATE_TRUNC('month', o.order_date) ORDER BY month ASC, cost DESC, r.region_id ASC",
             time_range={"start": "2026-01-01", "end_exclusive": "2027-01-01"}),
        case("G33", "filter_join", "按地区统计已支付订单成本", ["orders", "regions"], ["cost"], ["region"],
             "SELECT r.region_name AS region, SUM(o.cost) AS cost FROM demo_business.orders o JOIN demo_business.regions r ON r.region_id = o.region_id WHERE o.status = 'PAID' GROUP BY r.region_name, r.region_id ORDER BY cost DESC, r.region_id ASC",
             filters=[{"field": "orders.status", "value": "PAID"}]),
        case("G34", "filter_join", "按品类统计已退款订单量", ["orders", "products"], ["order_count"], ["category"],
             "SELECT p.category AS category, COUNT(o.order_id) AS order_count FROM demo_business.orders o JOIN demo_business.products p ON p.product_id = o.product_id WHERE o.status = 'REFUNDED' GROUP BY p.category ORDER BY order_count DESC, p.category ASC",
             filters=[{"field": "orders.status", "value": "REFUNDED"}]),
        case("G35", "multi_filter", "统计华东地区订单收入", ["orders", "regions"], ["revenue"], ["region"],
             "SELECT r.region_name AS region, SUM(o.revenue) AS revenue FROM demo_business.orders o JOIN demo_business.regions r ON r.region_id = o.region_id WHERE r.region_name = '华东' GROUP BY r.region_name, r.region_id ORDER BY revenue DESC, r.region_id ASC",
             filters=[{"field": "regions.region_name", "value": "华东"}]),
        case("G36", "multi_filter", "统计华南地区已支付订单利润", ["orders", "regions"], ["profit"], ["region"],
             "SELECT r.region_name AS region, SUM(o.revenue - o.cost) AS profit FROM demo_business.orders o JOIN demo_business.regions r ON r.region_id = o.region_id WHERE o.status = 'PAID' AND r.region_name = '华南' GROUP BY r.region_name, r.region_id ORDER BY profit DESC, r.region_id ASC",
             filters=[{"field": "orders.status", "value": "PAID"}, {"field": "regions.region_name", "value": "华南"}]),
        case("G37", "category_filter", "按品类统计充电设备收入", ["orders", "products"], ["revenue"], ["category"],
             "SELECT p.category AS category, SUM(o.revenue) AS revenue FROM demo_business.orders o JOIN demo_business.products p ON p.product_id = o.product_id WHERE p.category = '充电设备' GROUP BY p.category ORDER BY revenue DESC, p.category ASC",
             filters=[{"field": "products.category", "value": "充电设备"}]),
        case("G38", "category_filter", "按品类统计储能设备已退款订单成本", ["orders", "products"], ["cost"], ["category"],
             "SELECT p.category AS category, SUM(o.cost) AS cost FROM demo_business.orders o JOIN demo_business.products p ON p.product_id = o.product_id WHERE o.status = 'REFUNDED' AND p.category = '储能设备' GROUP BY p.category ORDER BY cost DESC, p.category ASC",
             filters=[{"field": "orders.status", "value": "REFUNDED"}, {"field": "products.category", "value": "储能设备"}]),
        case("G39", "complex_join", "按地区按品类统计订单收入", ["orders", "regions", "products"], ["revenue"], ["region", "category"],
             "SELECT r.region_name AS region, p.category AS category, SUM(o.revenue) AS revenue FROM demo_business.orders o JOIN demo_business.regions r ON r.region_id = o.region_id JOIN demo_business.products p ON p.product_id = o.product_id GROUP BY r.region_name, r.region_id, p.category ORDER BY revenue DESC, r.region_id ASC, p.category ASC"),
        case("G40", "multi_dimension", "按产品按状态统计订单量", ["orders", "products"], ["order_count"], ["product", "status"],
             "SELECT p.product_name AS product, o.status AS status, COUNT(o.order_id) AS order_count FROM demo_business.orders o JOIN demo_business.products p ON p.product_id = o.product_id GROUP BY p.product_name, p.product_id, o.status ORDER BY order_count DESC, p.product_id ASC, o.status ASC"),
        case("G41", "multi_dimension", "按客户类型按状态统计订单收入", ["orders", "customers"], ["revenue"], ["customer_type", "status"],
             "SELECT c.customer_type AS customer_type, o.status AS status, SUM(o.revenue) AS revenue FROM demo_business.orders o JOIN demo_business.customers c ON c.customer_id = o.customer_id GROUP BY c.customer_type, o.status ORDER BY revenue DESC, c.customer_type ASC, o.status ASC"),
        case("G42", "metric_combination", "统计全部订单收入、成本和利润", ["orders"], ["revenue", "cost", "profit"], [],
             "SELECT SUM(o.revenue) AS revenue, SUM(o.cost) AS cost, SUM(o.revenue - o.cost) AS profit FROM demo_business.orders o"),
        case("G43", "contribution", "按地区统计收入贡献度", ["orders", "regions"], ["revenue_share"], ["region"],
             "SELECT r.region_name AS region, ROUND(SUM(o.revenue) * 100.0 / NULLIF(SUM(SUM(o.revenue)) OVER (), 0), 4) AS revenue_share FROM demo_business.orders o JOIN demo_business.regions r ON r.region_id = o.region_id GROUP BY r.region_name, r.region_id ORDER BY revenue_share DESC, r.region_id ASC"),
        case("G44", "ratio_zero_safe", "按品类统计利润率", ["orders", "products"], ["profit_margin"], ["category"],
             "SELECT p.category AS category, ROUND(SUM(o.revenue - o.cost) * 100.0 / NULLIF(SUM(o.revenue), 0), 4) AS profit_margin FROM demo_business.orders o JOIN demo_business.products p ON p.product_id = o.product_id GROUP BY p.category ORDER BY profit_margin DESC, p.category ASC"),
        case("G45", "month_over_month", "按月统计收入环比", ["orders"], ["revenue", "revenue_mom"], ["month"],
             "WITH monthly AS (SELECT DATE_TRUNC('month', o.order_date) AS month, SUM(o.revenue) AS revenue FROM demo_business.orders o GROUP BY DATE_TRUNC('month', o.order_date)) SELECT month, revenue, ROUND((revenue - LAG(revenue, 1) OVER (ORDER BY month)) * 100.0 / NULLIF(LAG(revenue, 1) OVER (ORDER BY month), 0), 4) AS revenue_mom FROM monthly ORDER BY month ASC"),
        case("G46", "year_over_year", "按月统计收入同比", ["orders"], ["revenue", "revenue_yoy"], ["month"],
             "WITH monthly AS (SELECT DATE_TRUNC('month', o.order_date) AS month, SUM(o.revenue) AS revenue FROM demo_business.orders o GROUP BY DATE_TRUNC('month', o.order_date)) SELECT month, revenue, ROUND((revenue - LAG(revenue, 12) OVER (ORDER BY month)) * 100.0 / NULLIF(LAG(revenue, 12) OVER (ORDER BY month), 0), 4) AS revenue_yoy FROM monthly ORDER BY month ASC"),
        case("G47", "duplicate_grain", "按客户统计去重订单量前5名", ["orders", "customers"], ["distinct_order_count"], ["customer"],
             "SELECT c.customer_name AS customer, COUNT(DISTINCT o.order_id) AS distinct_order_count FROM demo_business.orders o JOIN demo_business.customers c ON c.customer_id = o.customer_id GROUP BY c.customer_name, c.customer_id ORDER BY distinct_order_count DESC, c.customer_id ASC LIMIT 5"),
        case("G48", "quarter_boundary", "2026年第一季度按地区统计收入和成本", ["orders", "regions"], ["revenue", "cost"], ["region"],
             "SELECT r.region_name AS region, SUM(o.revenue) AS revenue, SUM(o.cost) AS cost FROM demo_business.orders o JOIN demo_business.regions r ON r.region_id = o.region_id WHERE o.order_date >= DATE '2026-01-01' AND o.order_date < DATE '2026-04-01' GROUP BY r.region_name, r.region_id ORDER BY revenue DESC, r.region_id ASC",
             time_range={"start": "2026-01-01", "end_exclusive": "2026-04-01"}),
        case("G49", "natural_month", "2026年2月按产品统计利润率", ["orders", "products"], ["profit_margin"], ["product"],
             "SELECT p.product_name AS product, ROUND(SUM(o.revenue - o.cost) * 100.0 / NULLIF(SUM(o.revenue), 0), 4) AS profit_margin FROM demo_business.orders o JOIN demo_business.products p ON p.product_id = o.product_id WHERE o.order_date >= DATE '2026-02-01' AND o.order_date < DATE '2026-03-01' GROUP BY p.product_name, p.product_id ORDER BY profit_margin DESC, p.product_id ASC",
             time_range={"start": "2026-02-01", "end_exclusive": "2026-03-01"}),
        case("G50", "empty_result", "2024年按地区统计订单收入", ["orders", "regions"], ["revenue"], ["region"],
             "SELECT r.region_name AS region, SUM(o.revenue) AS revenue FROM demo_business.orders o JOIN demo_business.regions r ON r.region_id = o.region_id WHERE o.order_date >= DATE '2024-01-01' AND o.order_date < DATE '2025-01-01' GROUP BY r.region_name, r.region_id ORDER BY revenue DESC, r.region_id ASC",
             time_range={"start": "2024-01-01", "end_exclusive": "2025-01-01"}),
    ]


def main() -> int:
    parser = argparse.ArgumentParser()
    root = Path(__file__).resolve().parents[2]
    parser.add_argument("--source", type=Path, default=root / "evaluation" / "golden" / "day2-golden-20.json")
    parser.add_argument("--output", type=Path, default=root / "evaluation" / "golden" / "day4-golden-50.json")
    args = parser.parse_args()
    original = json.loads(args.source.read_text(encoding="utf-8"))
    if manifest_hash(original) != ORIGINAL_SHA256 or original.get("manifest_sha256") != ORIGINAL_SHA256:
        raise RuntimeError("Original Golden 20 manifest changed; refusing to build Day 4 manifest")
    manifest = {
        "name": "ChatBI V2 Day 4 Golden 50",
        "version": "4.1.0",
        "source_manifest_sha256": ORIGINAL_SHA256,
        "frozen": False,
        "frozen_at": None,
        "manifest_sha256": None,
        "cases": copy.deepcopy(original["cases"]) + new_cases(),
    }
    if len(manifest["cases"]) != 50 or manifest["cases"][:20] != original["cases"]:
        raise RuntimeError("Golden 20 traceability check failed")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"cases": 50, "source_manifest_sha256": ORIGINAL_SHA256, "output": str(args.output)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
