import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


def uuid_str() -> str:
    return str(uuid.uuid4())


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class Workspace(Base, TimestampMixin):
    __tablename__ = "workspace"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)


class AppUser(Base, TimestampMixin):
    __tablename__ = "app_user"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspace.id", ondelete="CASCADE"), index=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    display_name: Mapped[str] = mapped_column(String(128), nullable=False)
    role: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), default="ACTIVE", index=True)
    last_active_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    password_hash: Mapped[str | None] = mapped_column(String(512))
    password_changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ResourceGrant(Base, TimestampMixin):
    __tablename__ = "resource_grant"
    __table_args__ = (UniqueConstraint("user_id", "resource_type", "resource_id"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    user_id: Mapped[str] = mapped_column(ForeignKey("app_user.id", ondelete="CASCADE"), index=True)
    resource_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    resource_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    can_read: Mapped[bool] = mapped_column(Boolean, default=True)
    can_query: Mapped[bool] = mapped_column(Boolean, default=False)


class AuditEvent(Base):
    __tablename__ = "audit_event"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    workspace_id: Mapped[str | None] = mapped_column(ForeignKey("workspace.id", ondelete="SET NULL"), index=True)
    actor_user_id: Mapped[str | None] = mapped_column(ForeignKey("app_user.id", ondelete="SET NULL"), index=True)
    actor_email: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    action: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    resource_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    resource_id: Mapped[str | None] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    details: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class VerifiedAnswer(Base, TimestampMixin):
    __tablename__ = "verified_answer"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspace.id", ondelete="CASCADE"), index=True)
    question: Mapped[str] = mapped_column(String(512), nullable=False)
    module: Mapped[str] = mapped_column(String(64), nullable=False)
    sql_synced: Mapped[bool] = mapped_column(Boolean, default=True)
    model_name: Mapped[str] = mapped_column(String(255), nullable=False)
    owner_name: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="DRAFT", index=True)
    accuracy_percent: Mapped[float] = mapped_column(Float, default=0)
    adoption_count: Mapped[int] = mapped_column(Integer, default=0)
    monthly_adoption_count: Mapped[int] = mapped_column(Integer, default=0)
    is_favorite: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, index=True)
    query_run_id: Mapped[str | None] = mapped_column(String(36), index=True)
    sql_text: Mapped[str | None] = mapped_column(Text)
    result_signature: Mapped[str | None] = mapped_column(String(64))
    semantic_model_version: Mapped[int | None] = mapped_column(Integer)
    semantic_intent: Mapped[dict] = mapped_column(JSON, default=dict)
    sql_plan: Mapped[dict] = mapped_column(JSON, default=dict)
    result_snapshot: Mapped[dict] = mapped_column(JSON, default=dict)
    chart_spec: Mapped[dict] = mapped_column(JSON, default=dict)
    narrative: Mapped[dict] = mapped_column(JSON, default=dict)
    semantic_model_id: Mapped[str | None] = mapped_column(ForeignKey("semantic_model.id", ondelete="RESTRICT"), index=True)
    datasource_id: Mapped[str | None] = mapped_column(ForeignKey("datasource.id", ondelete="RESTRICT"), index=True)
    oracle_status: Mapped[str | None] = mapped_column(String(32), index=True)
    feedback: Mapped[dict] = mapped_column(JSON, default=dict)
    versions: Mapped[list["AnswerVersion"]] = relationship(cascade="all, delete-orphan", passive_deletes=True)


class AnswerVersion(Base):
    __tablename__ = "answer_version"
    __table_args__ = (UniqueConstraint("answer_id", "version"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    answer_id: Mapped[str] = mapped_column(ForeignKey("verified_answer.id", ondelete="CASCADE"), index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Dashboard(Base, TimestampMixin):
    __tablename__ = "dashboard"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspace.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    card_count: Mapped[int] = mapped_column(Integer, default=0)
    is_shared: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    refresh_count_today: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(32), default="REALTIME")
    trend_variant: Mapped[int] = mapped_column(Integer, default=0)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, index=True)
    cards: Mapped[list["DashboardCard"]] = relationship(cascade="all, delete-orphan", passive_deletes=True)


class DashboardCard(Base, TimestampMixin):
    __tablename__ = "dashboard_card"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    dashboard_id: Mapped[str] = mapped_column(ForeignKey("dashboard.id", ondelete="CASCADE"), index=True)
    answer_id: Mapped[str] = mapped_column(ForeignKey("verified_answer.id", ondelete="RESTRICT"), index=True)
    query_run_id: Mapped[str] = mapped_column(ForeignKey("query_run.id", ondelete="RESTRICT"), index=True)
    chart_spec: Mapped[dict] = mapped_column(JSON, nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    position: Mapped[dict] = mapped_column(JSON, default=dict)
    size: Mapped[dict] = mapped_column(JSON, default=dict)
    filter_context: Mapped[dict] = mapped_column(JSON, default=dict)
    semantic_model_version: Mapped[int] = mapped_column(Integer, nullable=False)
    result_signature: Mapped[str | None] = mapped_column(String(64), index=True)
    refresh_policy: Mapped[str] = mapped_column(String(32), default="MANUAL")


class EvaluationRun(Base, TimestampMixin):
    __tablename__ = "evaluation_run"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspace.id", ondelete="CASCADE"), index=True)
    release_name: Mapped[str] = mapped_column(String(255), nullable=False)
    model_name: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="COMPLETED", index=True)
    is_current: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    golden_set_count: Mapped[int] = mapped_column(Integer, default=0)
    sql_generation_rate: Mapped[float] = mapped_column(Float, default=0)
    result_accuracy: Mapped[float] = mapped_column(Float, default=0)
    semantic_accuracy: Mapped[float] = mapped_column(Float, default=0)
    relevance_accuracy: Mapped[float] = mapped_column(Float, default=0)
    average_response_seconds: Mapped[float] = mapped_column(Float, default=0)
    error_distribution: Mapped[list] = mapped_column(JSON, default=list)
    trend_points: Mapped[list] = mapped_column(JSON, default=list)
    completed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    duration_seconds: Mapped[int] = mapped_column(Integer, default=0)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, index=True)
    manifest_sha256: Mapped[str | None] = mapped_column(String(64), index=True)
    sql_execution_pass_count: Mapped[int] = mapped_column(Integer, default=0)
    result_value_pass_count: Mapped[int] = mapped_column(Integer, default=0)
    semantic_pass_count: Mapped[int] = mapped_column(Integer, default=0)
    dangerous_sql_total: Mapped[int] = mapped_column(Integer, default=0)
    dangerous_sql_block_count: Mapped[int] = mapped_column(Integer, default=0)
    cases: Mapped[list["EvaluationCaseResult"]] = relationship(cascade="all, delete-orphan", passive_deletes=True)


class EvaluationCaseResult(Base, TimestampMixin):
    __tablename__ = "evaluation_case_result"
    __table_args__ = (UniqueConstraint("evaluation_run_id", "case_id"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    evaluation_run_id: Mapped[str] = mapped_column(ForeignKey("evaluation_run.id", ondelete="CASCADE"), index=True)
    case_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    category: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    execution_ok: Mapped[bool] = mapped_column(Boolean, default=False)
    result_ok: Mapped[bool] = mapped_column(Boolean, default=False)
    semantic_ok: Mapped[bool] = mapped_column(Boolean, default=False)
    expected: Mapped[dict] = mapped_column(JSON, default=dict)
    actual: Mapped[dict] = mapped_column(JSON, default=dict)
    generated_sql: Mapped[str | None] = mapped_column(Text)
    result_diff: Mapped[list] = mapped_column(JSON, default=list)
    error_category: Mapped[str | None] = mapped_column(String(64), index=True)
    query_run_id: Mapped[str | None] = mapped_column(ForeignKey("query_run.id", ondelete="SET NULL"), index=True)


class DataSource(Base, TimestampMixin):
    __tablename__ = "datasource"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspace.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    type: Mapped[str] = mapped_column(String(32), nullable=False)
    host: Mapped[str] = mapped_column(String(255), nullable=False)
    port: Mapped[int] = mapped_column(Integer, nullable=False)
    database: Mapped[str] = mapped_column(String(255), nullable=False)
    username: Mapped[str] = mapped_column(String(255), nullable=False)
    password_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    ssl: Mapped[bool] = mapped_column(Boolean, default=False)
    schema: Mapped[str | None] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(32), default="CREATED")
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    schemas: Mapped[list["DataSourceSchema"]] = relationship(cascade="all, delete-orphan", passive_deletes=True)


class DataSourceSchema(Base):
    __tablename__ = "datasource_schema"
    __table_args__ = (UniqueConstraint("datasource_id", "name"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    datasource_id: Mapped[str] = mapped_column(ForeignKey("datasource.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    qualified_name: Mapped[str] = mapped_column(String(1024), nullable=False)
    tables: Mapped[list["DataSourceTable"]] = relationship(cascade="all, delete-orphan", passive_deletes=True)


class DataSourceTable(Base):
    __tablename__ = "datasource_table"
    __table_args__ = (UniqueConstraint("schema_id", "name"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    schema_id: Mapped[str] = mapped_column(ForeignKey("datasource_schema.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    qualified_name: Mapped[str] = mapped_column(String(1024), nullable=False)
    comment: Mapped[str | None] = mapped_column(Text)
    columns: Mapped[list["DataSourceColumn"]] = relationship(cascade="all, delete-orphan", passive_deletes=True)


class DataSourceColumn(Base):
    __tablename__ = "datasource_column"
    __table_args__ = (UniqueConstraint("table_id", "name"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    table_id: Mapped[str] = mapped_column(ForeignKey("datasource_table.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    qualified_name: Mapped[str] = mapped_column(String(1536), nullable=False)
    data_type: Mapped[str] = mapped_column(String(255), nullable=False)
    nullable: Mapped[bool] = mapped_column(Boolean, default=True)
    primary_key: Mapped[bool] = mapped_column(Boolean, default=False)
    foreign_key: Mapped[bool] = mapped_column(Boolean, default=False)
    default: Mapped[str | None] = mapped_column(Text)
    comment: Mapped[str | None] = mapped_column(Text)
    sample_values: Mapped[list] = mapped_column(JSON, default=list)


class DataSourceRelation(Base):
    __tablename__ = "datasource_relation"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    datasource_id: Mapped[str] = mapped_column(ForeignKey("datasource.id", ondelete="CASCADE"), index=True)
    source_schema: Mapped[str] = mapped_column(String(255))
    source_table: Mapped[str] = mapped_column(String(255))
    source_columns: Mapped[list] = mapped_column(JSON, default=list)
    target_schema: Mapped[str | None] = mapped_column(String(255))
    target_table: Mapped[str] = mapped_column(String(255))
    target_columns: Mapped[list] = mapped_column(JSON, default=list)


class SemanticModel(Base, TimestampMixin):
    __tablename__ = "semantic_model"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspace.id", ondelete="CASCADE"), index=True)
    datasource_id: Mapped[str] = mapped_column(ForeignKey("datasource.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), default="DRAFT")
    version: Mapped[int] = mapped_column(Integer, default=1)
    entities: Mapped[list["SemanticEntity"]] = relationship(cascade="all, delete-orphan", passive_deletes=True)
    metrics: Mapped[list["Metric"]] = relationship(cascade="all, delete-orphan", passive_deletes=True)
    dimensions: Mapped[list["Dimension"]] = relationship(cascade="all, delete-orphan", passive_deletes=True)
    relations: Mapped[list["SemanticRelation"]] = relationship(cascade="all, delete-orphan", passive_deletes=True)
    business_terms: Mapped[list["BusinessTerm"]] = relationship(cascade="all, delete-orphan", passive_deletes=True)
    versions: Mapped[list["SemanticVersion"]] = relationship(cascade="all, delete-orphan", passive_deletes=True)


class SemanticEntity(Base):
    __tablename__ = "semantic_entity"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    semantic_model_id: Mapped[str] = mapped_column(ForeignKey("semantic_model.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    source_table: Mapped[str] = mapped_column(String(255), nullable=False)
    primary_key: Mapped[str] = mapped_column(String(255), nullable=False)
    time_dimension: Mapped[str | None] = mapped_column(String(255))


class Metric(Base):
    __tablename__ = "metric"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    semantic_model_id: Mapped[str] = mapped_column(ForeignKey("semantic_model.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    label: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    expression: Mapped[str] = mapped_column(Text, nullable=False)
    aggregation: Mapped[str] = mapped_column(String(32), nullable=False)
    filters: Mapped[list] = mapped_column(JSON, default=list)


class Dimension(Base):
    __tablename__ = "dimension"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    semantic_model_id: Mapped[str] = mapped_column(ForeignKey("semantic_model.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    label: Mapped[str] = mapped_column(String(255), nullable=False)
    source_column: Mapped[str] = mapped_column(String(255), nullable=False)
    type: Mapped[str] = mapped_column(String(32), nullable=False)


class SemanticRelation(Base):
    __tablename__ = "semantic_relation"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    semantic_model_id: Mapped[str] = mapped_column(ForeignKey("semantic_model.id", ondelete="CASCADE"), index=True)
    left_entity: Mapped[str] = mapped_column(String(255), nullable=False)
    right_entity: Mapped[str] = mapped_column(String(255), nullable=False)
    join_type: Mapped[str] = mapped_column(String(32), nullable=False)
    join_keys: Mapped[list] = mapped_column(JSON, default=list)
    cardinality: Mapped[str] = mapped_column(String(32), nullable=False)


class BusinessTerm(Base):
    __tablename__ = "business_term"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    semantic_model_id: Mapped[str] = mapped_column(ForeignKey("semantic_model.id", ondelete="CASCADE"), index=True)
    term: Mapped[str] = mapped_column(String(255), nullable=False)
    synonyms: Mapped[list] = mapped_column(JSON, default=list)
    definition: Mapped[str] = mapped_column(Text, nullable=False)
    mapped_object: Mapped[str] = mapped_column(String(255), nullable=False)


class SemanticVersion(Base):
    __tablename__ = "semantic_version"
    __table_args__ = (UniqueConstraint("semantic_model_id", "version"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    semantic_model_id: Mapped[str] = mapped_column(ForeignKey("semantic_model.id", ondelete="CASCADE"), index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class QueryRun(Base, TimestampMixin):
    __tablename__ = "query_run"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspace.id", ondelete="CASCADE"), index=True)
    datasource_id: Mapped[str] = mapped_column(ForeignKey("datasource.id", ondelete="RESTRICT"), index=True)
    semantic_model_id: Mapped[str] = mapped_column(ForeignKey("semantic_model.id", ondelete="RESTRICT"), index=True)
    semantic_model_version: Mapped[int] = mapped_column(Integer, nullable=False)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    context_payload: Mapped[dict] = mapped_column(JSON, default=dict)
    plan_payload: Mapped[dict] = mapped_column(JSON, default=dict)
    guard_payload: Mapped[dict] = mapped_column(JSON, default=dict)
    execution_payload: Mapped[dict] = mapped_column(JSON, default=dict)
    oracle_payload: Mapped[dict] = mapped_column(JSON, default=dict)
    chart_spec_payload: Mapped[dict] = mapped_column(JSON, default=dict)
    narrative_payload: Mapped[dict] = mapped_column(JSON, default=dict)
    follow_up_payload: Mapped[list] = mapped_column(JSON, default=list)
    generated_sql: Mapped[str | None] = mapped_column(Text)
    normalized_sql: Mapped[str | None] = mapped_column(Text)
    result_signature: Mapped[str | None] = mapped_column(String(64), index=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    error_code: Mapped[str | None] = mapped_column(String(64))
    error_message: Mapped[str | None] = mapped_column(Text)


class QueryAuditEvent(Base):
    __tablename__ = "query_audit_event"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    query_run_id: Mapped[str] = mapped_column(ForeignKey("query_run.id", ondelete="CASCADE"), index=True)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    details: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class QueryFeedback(Base):
    __tablename__ = "query_feedback"
    __table_args__ = (UniqueConstraint("query_run_id", "feedback_type"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    query_run_id: Mapped[str] = mapped_column(ForeignKey("query_run.id", ondelete="CASCADE"), index=True)
    feedback_type: Mapped[str] = mapped_column(String(32), nullable=False)
    comment: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
