from __future__ import annotations

import argparse
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--schema", required=True)
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--tenant-count", type=int, required=True)
    parser.add_argument("--date-start", required=True)
    parser.add_argument("--date-end", required=True)
    args = parser.parse_args()
    content = f"""# 经营分析基准业务规则

此文档由固定参数生成，仅描述 `{args.schema}` 演示基准数据，不代表用户企业事实。

- Seed：`{args.seed}`
- 租户：1–{args.tenant_count}；所有查询必须显式绑定 `tenant_id`，不得跨租户聚合。
- 时间：{args.date_start} 至 {args.date_end}，自然月和自然年使用左闭右开边界。
- 有效订单：`VALID`、`PARTIAL_REFUND`、`REFUNDED`；`TEST` 与 `CANCELLED` 不计入净销售。
- 净销售额：`SUM(net_amount - refund_amount)`。
- 净利润：`SUM(profit_amount - refund_amount)`。
- 完全退款：`refund_amount = net_amount`；部分退款：`refund_amount = net_amount * 30%`。
- 应收余额：`receivable_amount - received_amount` 的已生成一致值；账龄桶为 `PAID`、`0_30`、`31_60`、`61_90`、`90_PLUS`。
- 季节性：11–12 月数量提升；2025-07 的指定区域存在可解释销量下调事件。
- 长尾：产品、客户由互质步长映射，形成稳定长尾覆盖。
- 边界：测试/取消订单产生零净额，折扣包含 95% 与 100% 极值，`payment_date` 包含 NULL，贡献率必须使用 `NULLIF` 防止除零。
- 外部订单号：`external_order_no` 有意包含可复现重复值，用于重复编号质量检查；内部 `order_id` 仍作为事实键。
- 数据来源：固定 Seed 模拟数据。RAG 引用本文件时必须附带“演示基准规则”说明和数据签名。
"""
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(content, encoding="utf-8")


if __name__ == "__main__":
    main()
