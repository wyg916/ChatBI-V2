from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import EvaluationRun


def evaluation_overview(db: Session) -> dict:
    comparisons = list(db.scalars(select(EvaluationRun).order_by(EvaluationRun.sort_order, EvaluationRun.completed_at.desc())))
    if not comparisons:
        raise LookupError("No evaluation records are available")
    current = next((run for run in comparisons if run.is_current), comparisons[0])
    previous = next((run for run in comparisons if run.id != current.id), current)
    metrics = [
        {"key": "sql_generation_rate", "label": "SQL 生成率", "value": current.sql_generation_rate, "unit": "%", "change": round(current.sql_generation_rate - previous.sql_generation_rate, 1)},
        {"key": "result_accuracy", "label": "结果集准确率", "value": current.result_accuracy, "unit": "%", "change": round(current.result_accuracy - previous.result_accuracy, 1)},
        {"key": "semantic_accuracy", "label": "语义理解准确率", "value": current.semantic_accuracy, "unit": "%", "change": round(current.semantic_accuracy - previous.semantic_accuracy, 1)},
        {"key": "average_response_seconds", "label": "平均响应时间", "value": current.average_response_seconds, "unit": "s", "change": round(current.average_response_seconds - previous.average_response_seconds, 1)},
    ]
    return {"current": current, "metrics": metrics, "comparisons": comparisons}
