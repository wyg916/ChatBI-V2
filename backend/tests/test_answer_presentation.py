from __future__ import annotations

import json

from chatbi_agent_contracts import QuestionRoute

import app.services.answer_presentation as answer_presentation_module
from app.core.access import Principal
from app.core.config import get_settings
from app.integration.question_router import QuestionRouter
from app.model_gateway import ModelReply, RequestContext
from app.models import AppUser, DataSource, DataSourceSchema, DataSourceTable, Workspace
from app.services.answer_presentation import AnswerPresenter
from app.services.chat import _data_catalog_answer


class _Gateway:
    def __init__(self, answer: str, *, trace: dict | None = None) -> None:
        self.answer = answer
        self.trace = trace or {"resolved_provider": "mimo", "resolved_model": "mimo-v2.5"}
        self.providers = {"mimo": object()}
        self.calls: list[dict] = []

    def complete(self, **kwargs):
        self.calls.append(kwargs)
        return ModelReply(
            content=json.dumps({"answer": self.answer}, ensure_ascii=False),
            provider="mimo",
            model="mimo-v2.5",
            trace=self.trace,
        )


def _context() -> RequestContext:
    return RequestContext(
        request_id="answer-presentation-001",
        trace_id="TRACE-answer-presentation-001",
        workspace_id="workspace-a",
        user_id="user-a",
        question="not forwarded by the presentation stage",
    )


def _verified_payload() -> dict:
    return {
        "analysis": {
            "primary": {
                "status": "SUCCEEDED",
                "execution": {
                    "status": "SUCCEEDED",
                    "rows": [{"revenue": 730000}],
                    "row_count": 1,
                    "result_signature": "result-signature-1",
                },
                "guard": {"allowed": True},
                "oracle": {"status": "PASSED"},
            },
        },
    }


def test_verified_answer_is_presented_only_with_exact_source_anchor() -> None:
    source = "当前总收入为 73 万元。"
    gateway = _Gateway(f"我来把结论说得直观一些：{source} 你还可以继续按区域查看。")

    result = AnswerPresenter(gateway).present(
        route=QuestionRoute.DATA_QUERY,
        status="SUCCEEDED",
        answer=source,
        response_payload=_verified_payload(),
        request_context=_context(),
    )

    assert result.applied is True
    assert result.source_verified is True
    assert result.provider == "mimo"
    assert source in result.content
    assert gateway.calls[0]["requested_alias"] == "auto"
    assert gateway.calls[0]["json_mode"] is True
    assert gateway.calls[0]["budget_mode"].value == get_settings().model_budget_mode


def test_unrestricted_complex_answer_uses_kimi_for_guarded_final_presentation(monkeypatch) -> None:
    source = "已验证的复杂分析结论保持原样。"
    gateway = _Gateway(f"下面是核验后的结果：{source}")
    settings = get_settings().model_copy(update={"provider_usage_unrestricted": True})
    monkeypatch.setattr(answer_presentation_module, "get_settings", lambda: settings)

    result = AnswerPresenter(gateway).present(
        route=QuestionRoute.COMPLEX_ANALYSIS,
        status="SUCCEEDED",
        answer=source,
        response_payload=_verified_payload(),
        request_context=_context(),
    )

    assert result.applied is True
    assert source in result.content
    assert gateway.calls[0]["requested_alias"] == "auto"
    assert gateway.calls[0]["complexity_score"] == 90


def test_presentation_rejects_changed_or_new_facts_and_keeps_verified_source() -> None:
    source = "当前总收入为 73 万元。"
    gateway = _Gateway("当前总收入为 80 万元，而且同比增长 10%。")

    result = AnswerPresenter(gateway).present(
        route=QuestionRoute.DATA_QUERY,
        status="SUCCEEDED",
        answer=source,
        response_payload=_verified_payload(),
        request_context=_context(),
    )

    assert result.applied is False
    assert result.status == "FALLBACK_PRESENTATION_GUARD_REJECTED"
    assert result.content == source


def test_presentation_rejects_unapproved_qualitative_wrapper() -> None:
    source = "当前总收入为 73 万元。"
    gateway = _Gateway(f"先看结论：{source} 但这个结论其实不可信。")

    result = AnswerPresenter(gateway).present(
        route=QuestionRoute.DATA_QUERY,
        status="SUCCEEDED",
        answer=source,
        response_payload=_verified_payload(),
        request_context=_context(),
    )

    assert result.applied is False
    assert result.status == "FALLBACK_PRESENTATION_GUARD_REJECTED"
    assert result.content == source


def test_presentation_never_calls_model_before_data_publication_guards_pass() -> None:
    source = "当前总收入为 73 万元。"
    gateway = _Gateway(f"结论如下：{source}")
    payload = _verified_payload()
    payload["analysis"]["primary"]["oracle"]["status"] = "FAILED"

    result = AnswerPresenter(gateway).present(
        route=QuestionRoute.DATA_QUERY,
        status="SUCCEEDED",
        answer=source,
        response_payload=payload,
        request_context=_context(),
    )

    assert result.status == "SKIPPED_PUBLICATION_GUARD"
    assert result.content == source
    assert gateway.calls == []


def test_safe_limitation_can_be_softened_without_changing_refusal() -> None:
    source = "这个请求超出了当前 ChatBI 的只读分析范围，我没有执行它。"
    gateway = _Gateway(f"我理解你想尽快完成这件事。{source} 可以换成一个只读数据问题。")

    result = AnswerPresenter(gateway).present(
        route=QuestionRoute.UNSUPPORTED,
        status="REFUSED",
        answer=source,
        response_payload={"answer": source},
        request_context=_context(),
        error_code="UNSUPPORTED",
    )

    assert result.applied is True
    assert result.source_verified is False
    assert source in result.content


def test_primary_model_general_file_and_multimodal_answers_are_not_called_twice() -> None:
    source = "  这是模型已经生成并适合直接展示的回答。\n"
    for route in (
        QuestionRoute.GENERAL_CHAT,
        QuestionRoute.FILE_QUERY,
        QuestionRoute.MULTIMODAL_QUERY,
    ):
        gateway = _Gateway("must not be used")
        result = AnswerPresenter(gateway).present(
            route=route,
            status="SUCCEEDED",
            answer=source,
            response_payload={"answer": source},
            request_context=_context(),
            already_model_presented=True,
            primary_provider="deepseek",
            primary_model="deepseek-v4-flash",
            primary_trace={
                "resolved_provider": "deepseek",
                "resolved_model": "deepseek-v4-flash",
                "system_prompt": "must-not-leak",
            },
        )

        assert result.content == source
        assert result.status == "PRIMARY_MODEL_PRESENTED"
        assert result.public_trace()["mode"] == "PRIMARY_MODEL"
        assert result.public_trace()["guard"] == "PRIMARY_MODEL_OUTPUT"
        assert result.public_trace()["provider"] == "deepseek"
        assert "system_prompt" not in json.dumps(result.public_trace())
        assert gateway.calls == []


def test_server_authored_status_and_date_answers_use_exact_anchor_presenter() -> None:
    cases = (
        (QuestionRoute.MODEL_STATUS, "当前模型状态：MiMo 已配置。"),
        (QuestionRoute.SYSTEM_CAPABILITY, "ChatBI V2 支持只读数据分析。"),
        (QuestionRoute.GENERAL_CHAT, "当前日期是 2026-08-29，星期六（Saturday）。"),
    )
    for route, source in cases:
        gateway = _Gateway(f"下面是核验后的结果：{source}")
        result = AnswerPresenter(gateway).present(
            route=route,
            status="SUCCEEDED",
            answer=source,
            response_payload={"answer": source},
            request_context=_context(),
            server_authored=True,
        )

        assert result.applied is True
        assert result.source_verified is True
        assert result.content.endswith(source)
        assert result.public_trace()["mode"] == "POST_VALIDATION_MODEL"
        assert len(gateway.calls) == 1


def test_admin_query_keeps_local_identity_answer_without_provider_pii_egress() -> None:
    source = (
        "当前用户是 隐私测试用户（privacy-person@example.invalid），角色为 ANALYST，"
        "工作空间 ID 为 workspace-private-001。权限摘要：query.ask。"
    )
    gateway = _Gateway("must not be used")

    result = AnswerPresenter(gateway).present(
        route=QuestionRoute.ADMIN_QUERY,
        status="SUCCEEDED",
        answer=source,
        response_payload={
            "answer": source,
            "admin_context": {"role": "ANALYST", "permissions": ["query.ask"]},
        },
        request_context=_context(),
        server_authored=True,
    )

    assert result.content == source
    assert result.status == "LOCAL_PRIVACY_PASSTHROUGH"
    assert result.source_verified is True
    assert result.applied is False
    assert result.public_trace()["mode"] == "LOCAL_SERVER"
    assert result.public_trace()["guard"] == "PRIVACY_NO_EXTERNAL_EGRESS"
    assert gateway.calls == []
    provider_egress = json.dumps(gateway.calls, ensure_ascii=False)
    assert "privacy-person@example.invalid" not in provider_egress
    assert "workspace-private-001" not in provider_egress


def test_primary_model_marker_cannot_bypass_data_publication_guard() -> None:
    source = "当前总收入为 73 万元。"
    gateway = _Gateway(f"先看结论：{source}")
    payload = _verified_payload()
    payload["analysis"]["primary"]["oracle"]["status"] = "FAILED"

    result = AnswerPresenter(gateway).present(
        route=QuestionRoute.DATA_QUERY,
        status="SUCCEEDED",
        answer=source,
        response_payload=payload,
        request_context=_context(),
        already_model_presented=True,
        primary_provider="deepseek",
        primary_model="deepseek-v4-flash",
    )

    assert result.status == "SKIPPED_PUBLICATION_GUARD"
    assert result.content == source
    assert gateway.calls == []


def test_presentation_trace_drops_prompts_credentials_and_unknown_fields() -> None:
    source = "当前总收入为 73 万元。"
    gateway = _Gateway(
        f"先看结论：{source}",
        trace={
            "resolved_provider": "mimo",
            "resolved_model": "mimo-v2.5",
            "usage": {"input_tokens": 12, "secret": "must-not-leak"},
            "system_prompt": "must-not-leak",
            "api_key": "must-not-leak",
        },
    )

    result = AnswerPresenter(gateway).present(
        route=QuestionRoute.DATA_QUERY,
        status="SUCCEEDED",
        answer=source,
        response_payload=_verified_payload(),
        request_context=_context(),
    )

    public = json.dumps(result.public_trace(), ensure_ascii=False)
    assert result.applied is True
    assert "system_prompt" not in public
    assert "api_key" not in public
    assert "must-not-leak" not in public
    assert result.trace["usage"] == {"input_tokens": 12}


def test_unexpected_presentation_gateway_failure_keeps_verified_answer() -> None:
    class _FailingGateway(_Gateway):
        def complete(self, **kwargs):
            self.calls.append(kwargs)
            raise RuntimeError("private gateway detail")

    source = "当前总收入为 73 万元。"
    result = AnswerPresenter(_FailingGateway("unused")).present(
        route=QuestionRoute.DATA_QUERY,
        status="SUCCEEDED",
        answer=source,
        response_payload=_verified_payload(),
        request_context=_context(),
    )

    assert result.content == source
    assert result.status == "FALLBACK_PRESENTATION_ERROR"
    assert "private gateway detail" not in json.dumps(result.public_trace())


def test_database_inventory_question_uses_safe_metadata_route() -> None:
    decision = QuestionRouter(gateway=_Gateway("unused")).decide("数据库有哪些数据？")
    assert decision.route == QuestionRoute.SYSTEM_CAPABILITY
    assert decision.reason == "DATA_CATALOG_OVERVIEW"


def test_database_table_mentions_in_quantitative_questions_stay_on_data_route() -> None:
    router = QuestionRouter(gateway=_Gateway("unused"))
    for question in (
        "数据库订单表今年收入是多少",
        "数据源 orders 表销售额趋势",
    ):
        decision = router.decide(question)
        assert decision.route == QuestionRoute.DATA_QUERY
        assert decision.reason == "DATA_L0"
    assert decision.model_required is False


def test_database_inventory_answer_lists_only_accessible_synced_metadata(db_session) -> None:
    workspace = Workspace(name="Presentation Test Workspace")
    db_session.add(workspace)
    db_session.flush()
    user = AppUser(
        workspace_id=workspace.id,
        email="admin@chatbi.local",
        display_name="Admin",
        role="ADMIN",
        status="ACTIVE",
    )
    db_session.add(user)
    db_session.flush()
    source = DataSource(
        workspace_id=workspace.id,
        name="经营分析库",
        type="postgresql",
        host="secret-host.invalid",
        port=5432,
        database="secret_database",
        username="secret_user",
        password_encrypted="secret_ciphertext",
        status="READY",
    )
    db_session.add(source)
    db_session.flush()
    schema = DataSourceSchema(
        datasource_id=source.id,
        name="demo_business",
        qualified_name="demo_business",
    )
    db_session.add(schema)
    db_session.flush()
    db_session.add(DataSourceTable(
        schema_id=schema.id,
        name="orders",
        qualified_name="demo_business.orders",
    ))
    db_session.commit()

    answer, payload = _data_catalog_answer(
        db_session,
        Principal(user.id, workspace.id, user.email, user.display_name, user.role),
    )

    assert payload["datasource_count"] >= 1
    assert payload["table_count"] >= 1
    assert "经营分析库" in answer
    assert "demo_business.orders" in answer
    assert "secret-host" not in answer
    assert "secret_database" not in json.dumps(payload, ensure_ascii=False)
    assert "secret_user" not in json.dumps(payload, ensure_ascii=False)
    assert "secret_ciphertext" not in json.dumps(payload, ensure_ascii=False)
