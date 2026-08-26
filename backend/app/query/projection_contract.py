from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlglot import exp, parse_one
from sqlglot.errors import ParseError

from app.query.contracts import (
    CanonicalOutputField,
    CanonicalOutputSchema,
    QueryContext,
    SQLPlan,
)


_DIALECT = {"postgresql": "postgres", "mysql": "mysql"}
_TRUSTED_PROVIDER_PREFIXES = ("deterministic-", "wren-", "wrenai-")
_DERIVED_METRICS = {
    "avg_order_value": "DERIVED_AGGREGATE",
    "distinct_order_count": "DERIVED_AGGREGATE",
    "max_quantity": "DERIVED_AGGREGATE",
    "profit": "DERIVED_AGGREGATE",
    "profit_margin": "DERIVED_RATIO",
    "revenue_mom": "DERIVED_GROWTH_RATE",
    "revenue_share": "DERIVED_RATIO",
    "revenue_yoy": "DERIVED_GROWTH_RATE",
}
_DERIVED_DIMENSIONS = {
    "category": "STRING",
    "customer_type": "STRING",
    "month": "DATE",
    "order_id": "IDENTIFIER",
    "year": "INTEGER",
}


class ProjectionContractError(ValueError):
    """A projection cannot be proven to satisfy the canonical output contract."""

    def __init__(self, code: str, *, details: dict[str, Any] | None = None) -> None:
        self.code = code
        self.details = details or {}
        super().__init__(code)


@dataclass(frozen=True)
class ProjectionContractResult:
    plan: SQLPlan
    status: str
    normalization_actions: tuple[dict[str, str], ...]


@dataclass(frozen=True)
class _ExpectedProjection:
    field: CanonicalOutputField
    semantic_expression: str | None


def _trusted_server_plan(plan: SQLPlan) -> bool:
    provider = plan.provider.casefold()
    return provider.startswith(_TRUSTED_PROVIDER_PREFIXES)


def _unique_names(values: list[str], *, code: str) -> list[str]:
    keys = [item.casefold() for item in values]
    if len(keys) != len(set(keys)):
        raise ProjectionContractError(code)
    return keys


def _metric_expression(metric: dict[str, Any]) -> str | None:
    expression = str(metric.get("expression") or "").strip()
    aggregation = str(metric.get("aggregation") or "").strip().upper()
    if not expression or not aggregation:
        return None
    if aggregation in {"COUNT_DISTINCT", "DISTINCT_COUNT"}:
        return f"COUNT(DISTINCT {expression})"
    return f"{aggregation}({expression})"


def _build_expected(plan: SQLPlan, context: QueryContext) -> tuple[list[_ExpectedProjection], CanonicalOutputSchema]:
    metric_names = _unique_names(plan.metrics, code="PROJECTION_DUPLICATE_CANONICAL_ALIAS")
    dimension_names = _unique_names(plan.dimensions, code="PROJECTION_DUPLICATE_CANONICAL_ALIAS")
    if set(metric_names).intersection(dimension_names):
        raise ProjectionContractError("PROJECTION_DUPLICATE_CANONICAL_ALIAS")

    metric_defs = {str(item.get("name", "")).casefold(): item for item in context.metrics}
    dimension_defs = {str(item.get("name", "")).casefold(): item for item in context.dimensions}
    trusted = _trusted_server_plan(plan)
    expected: list[_ExpectedProjection] = []
    metric_fields: list[CanonicalOutputField] = []
    dimension_fields: list[CanonicalOutputField] = []

    for name, key in zip(plan.dimensions, dimension_names, strict=True):
        definition = dimension_defs.get(key)
        if definition is not None:
            field = CanonicalOutputField(
                canonical_name=name,
                semantic_id=str(definition.get("id") or f"dimension:{name}"),
                kind="DIMENSION",
                expected_projection_type=str(definition.get("type") or "UNKNOWN"),
            )
            semantic_expression = str(definition.get("source_column") or "").strip() or None
        elif trusted and key in _DERIVED_DIMENSIONS:
            field = CanonicalOutputField(
                canonical_name=name,
                semantic_id=f"derived_dimension:{name}",
                kind="DIMENSION",
                expected_projection_type=_DERIVED_DIMENSIONS[key],
            )
            semantic_expression = None
        else:
            raise ProjectionContractError(
                "PROJECTION_SEMANTIC_MAPPING_UNKNOWN",
                details={"kind": "DIMENSION", "canonical_name": name},
            )
        dimension_fields.append(field)
        expected.append(_ExpectedProjection(field=field, semantic_expression=semantic_expression))

    for name, key in zip(plan.metrics, metric_names, strict=True):
        definition = metric_defs.get(key)
        if definition is not None:
            aggregation = str(definition.get("aggregation") or "UNKNOWN").upper()
            field = CanonicalOutputField(
                canonical_name=name,
                semantic_id=str(definition.get("id") or f"metric:{name}"),
                kind="METRIC",
                expected_projection_type=f"AGGREGATE_{aggregation}",
            )
            semantic_expression = _metric_expression(definition)
        elif trusted and key in _DERIVED_METRICS:
            field = CanonicalOutputField(
                canonical_name=name,
                semantic_id=f"derived_metric:{name}",
                kind="METRIC",
                expected_projection_type=_DERIVED_METRICS[key],
            )
            semantic_expression = None
        else:
            raise ProjectionContractError(
                "PROJECTION_SEMANTIC_MAPPING_UNKNOWN",
                details={"kind": "METRIC", "canonical_name": name},
            )
        metric_fields.append(field)
        expected.append(_ExpectedProjection(field=field, semantic_expression=semantic_expression))

    return expected, CanonicalOutputSchema(dimensions=dimension_fields, metrics=metric_fields)


def _root_select(statement: exp.Expression) -> exp.Select:
    if isinstance(statement, exp.Select):
        return statement
    raise ProjectionContractError("PROJECTION_ROOT_SELECT_REQUIRED")


def _output_name(projection: exp.Expression) -> str:
    if isinstance(projection, exp.Alias):
        return projection.alias
    if isinstance(projection, exp.Column):
        return projection.name
    return ""


def _projection_body(projection: exp.Expression) -> exp.Expression:
    return projection.this if isinstance(projection, exp.Alias) else projection


def _table_aliases(statement: exp.Expression) -> dict[str, str]:
    aliases: dict[str, str] = {}
    for table in statement.find_all(exp.Table):
        name = table.name
        if not name:
            continue
        aliases[name.casefold()] = name
        aliases[table.alias_or_name.casefold()] = name
    return aliases


def _source_column_owners(context: QueryContext) -> dict[str, set[str]]:
    owners: dict[str, set[str]] = {}
    for table_name, columns in context.security_policy.allowed_columns.items():
        table = table_name.rsplit(".", 1)[-1]
        for column in columns:
            owners.setdefault(str(column).casefold(), set()).add(table)
    for metric in context.metrics:
        expression = str(metric.get("expression") or "")
        try:
            parsed = parse_one(expression, dialect=_DIALECT[context.dialect])
        except ParseError:
            continue
        for column in parsed.find_all(exp.Column):
            if column.table:
                owners.setdefault(column.name.casefold(), set()).add(column.table)
    for dimension in context.dimensions:
        source = str(dimension.get("source_column") or "")
        try:
            parsed = parse_one(source, dialect=_DIALECT[context.dialect])
        except ParseError:
            continue
        for column in parsed.find_all(exp.Column):
            if column.table:
                owners.setdefault(column.name.casefold(), set()).add(column.table)
    return owners


def _fingerprint(
    expression: exp.Expression,
    *,
    dialect: str,
    aliases: dict[str, str],
    owners: dict[str, set[str]],
) -> str:
    normalized = expression.copy()
    for column in normalized.find_all(exp.Column):
        table = column.table
        if table:
            resolved = aliases.get(table.casefold(), table)
            column.set("catalog", None)
            column.set("db", None)
            column.set("table", exp.to_identifier(resolved))
        else:
            candidates = owners.get(column.name.casefold(), set())
            if len(candidates) == 1:
                column.set("table", exp.to_identifier(next(iter(candidates))))
    return normalized.sql(dialect=dialect, pretty=False).casefold()


def _semantic_fingerprint(
    expected: _ExpectedProjection,
    *,
    dialect: str,
    aliases: dict[str, str],
    owners: dict[str, set[str]],
) -> str | None:
    if expected.semantic_expression is None:
        return None
    try:
        expression = parse_one(expected.semantic_expression, dialect=dialect)
    except ParseError as exc:
        raise ProjectionContractError("PROJECTION_SEMANTIC_EXPRESSION_INVALID") from exc
    return _fingerprint(expression, dialect=dialect, aliases=aliases, owners=owners)


def _is_bound_year_grain_projection(
    projection: exp.Expression,
    expected: _ExpectedProjection,
    *,
    plan: SQLPlan,
    root: exp.Select,
    dialect: str,
    aliases: dict[str, str],
    owners: dict[str, set[str]],
) -> bool:
    """Prove a YEAR(date_dimension) projection from SQL AST, plan, and semantics."""

    if (
        expected.field.kind != "DIMENSION"
        or expected.field.expected_projection_type.upper() not in {"DATE", "DATETIME", "TIMESTAMP"}
        or expected.semantic_expression is None
    ):
        return False
    body = _projection_body(projection)
    if not isinstance(body, exp.Year):
        return False
    columns = list(body.find_all(exp.Column))
    if len(columns) != 1:
        return False
    try:
        semantic = parse_one(expected.semantic_expression, dialect=dialect)
    except ParseError as exc:
        raise ProjectionContractError("PROJECTION_SEMANTIC_EXPRESSION_INVALID") from exc
    if not isinstance(semantic, exp.Column):
        return False
    if _fingerprint(columns[0], dialect=dialect, aliases=aliases, owners=owners) != _fingerprint(
        semantic,
        dialect=dialect,
        aliases=aliases,
        owners=owners,
    ):
        return False

    body_fingerprint = _fingerprint(body, dialect=dialect, aliases=aliases, owners=owners)
    group = root.args.get("group")
    sql_group_expressions = list(group.expressions) if isinstance(group, exp.Group) else []
    if body_fingerprint not in {
        _fingerprint(item, dialect=dialect, aliases=aliases, owners=owners)
        for item in sql_group_expressions
    }:
        return False

    plan_group_fingerprints: set[str] = set()
    for item in plan.group_by:
        try:
            parsed = parse_one(item, dialect=dialect)
        except ParseError:
            continue
        plan_group_fingerprints.add(
            _fingerprint(parsed, dialect=dialect, aliases=aliases, owners=owners)
        )
    return body_fingerprint in plan_group_fingerprints


def _nearest_select(node: exp.Expression) -> exp.Select | None:
    parent = node.parent
    while parent is not None and not isinstance(parent, exp.Select):
        parent = parent.parent
    return parent if isinstance(parent, exp.Select) else None


def _root_argument(root: exp.Select, node: exp.Expression) -> str | None:
    current = node
    while current.parent is not None and current.parent is not root:
        current = current.parent
    if current.parent is not root:
        return None
    for key, value in root.args.items():
        if value is current:
            return key
        if isinstance(value, list) and current in value:
            return key
    return None


def _visible_source_names(context: QueryContext) -> set[str]:
    return set(_source_column_owners(context))


def _rewrite_dependent_alias(
    *,
    root: exp.Select,
    projection: exp.Expression,
    old_alias: str,
    canonical_name: str,
    context: QueryContext,
) -> None:
    if not old_alias:
        return
    old_key = old_alias.casefold()
    if old_key in _visible_source_names(context):
        raise ProjectionContractError(
            "PROJECTION_ALIAS_DEPENDENCY_UNSAFE",
            details={"from": old_alias, "to": canonical_name},
        )

    allowed_arguments = {"group", "order", "having", "qualify"}
    for column in list(root.find_all(exp.Column)):
        if _nearest_select(column) is not root or column.table or column.name.casefold() != old_key:
            continue
        argument = _root_argument(root, column)
        if argument == "expressions" and column.find_ancestor(exp.Alias) is projection:
            continue
        if argument not in allowed_arguments:
            raise ProjectionContractError(
                "PROJECTION_ALIAS_DEPENDENCY_UNSAFE",
                details={"from": old_alias, "to": canonical_name, "clause": argument or "UNKNOWN"},
            )
        column.set("this", exp.to_identifier(canonical_name))


def _apply_alias(projection: exp.Expression, canonical_name: str) -> exp.Expression:
    if isinstance(projection, exp.Alias):
        projection.set("alias", exp.to_identifier(canonical_name))
        return projection
    replacement = exp.alias_(projection.copy(), canonical_name, quoted=False)
    projection.replace(replacement)
    return replacement


def _trusted_auxiliary_fields(
    plan: SQLPlan,
    projections: list[exp.Expression],
    unmatched_indexes: set[int],
) -> tuple[list[CanonicalOutputField], set[int]]:
    if not _trusted_server_plan(plan) or not plan.provider.casefold().startswith(("wren-", "wrenai-")):
        return [], set()
    names = {_output_name(projections[index]).casefold(): index for index in unmatched_indexes if _output_name(projections[index])}
    accepted: set[int] = set()
    fields: list[CanonicalOutputField] = []
    if len(plan.metrics) == 1:
        metric = plan.metrics[0]
        previous = f"previous_{metric}".casefold()
        if previous in names and "comparison_rate" in names:
            for name, projection_type in ((previous, "COMPARISON_BASE"), ("comparison_rate", "COMPARISON_RATE")):
                accepted.add(names[name])
                fields.append(CanonicalOutputField(
                    canonical_name=_output_name(projections[names[name]]),
                    semantic_id=f"derived_auxiliary:{name}",
                    kind="AUXILIARY",
                    expected_projection_type=projection_type,
                ))
        if "contribution_rate" in names:
            accepted.add(names["contribution_rate"])
            fields.append(CanonicalOutputField(
                canonical_name=_output_name(projections[names["contribution_rate"]]),
                semantic_id=f"derived_auxiliary:{metric}:contribution_rate",
                kind="AUXILIARY",
                expected_projection_type="CONTRIBUTION_RATE",
            ))
    return fields, accepted


class ProjectionContractValidator:
    """Build and enforce a one-to-one canonical result-column contract before SQL Guard."""

    def validate_and_normalize(self, *, plan: SQLPlan, context: QueryContext) -> ProjectionContractResult:
        if plan.intent == "DIRECT_SQL":
            schema = CanonicalOutputSchema()
            trace = {
                **plan.model_trace,
                "projection_contract": {
                    "status": "PASS_DIRECT_SQL",
                    "canonical_output_schema": schema.model_dump(mode="json"),
                    "normalization_actions": [],
                },
            }
            return ProjectionContractResult(
                plan=plan.model_copy(update={"canonical_output_schema": schema, "model_trace": trace}),
                status="PASS_DIRECT_SQL",
                normalization_actions=(),
            )

        expected, schema = _build_expected(plan, context)
        dialect = _DIALECT[plan.dialect]
        try:
            statement = parse_one(plan.generated_sql, dialect=dialect)
        except ParseError as exc:
            raise ProjectionContractError("PROJECTION_SQL_PARSE_ERROR") from exc
        root = _root_select(statement)
        projections = list(root.expressions)
        if not projections:
            raise ProjectionContractError("PROJECTION_MISSING_EXPECTED_OUTPUT")

        output_names = [_output_name(item) for item in projections]
        named_keys = [item.casefold() for item in output_names if item]
        if len(named_keys) != len(set(named_keys)):
            raise ProjectionContractError("PROJECTION_DUPLICATE_OUTPUT_ALIAS")

        aliases = _table_aliases(statement)
        owners = _source_column_owners(context)
        expected_by_name = {item.field.canonical_name.casefold(): item for item in expected}
        assigned_expected: dict[str, int] = {}
        assigned_projection: set[int] = set()

        for index, output_name in enumerate(output_names):
            key = output_name.casefold()
            if key and key in expected_by_name:
                assigned_expected[key] = index
                assigned_projection.add(index)

        remaining_expected = [item for item in expected if item.field.canonical_name.casefold() not in assigned_expected]
        remaining_indexes = set(range(len(projections))).difference(assigned_projection)
        auxiliary, auxiliary_indexes = _trusted_auxiliary_fields(plan, projections, remaining_indexes)
        remaining_indexes.difference_update(auxiliary_indexes)
        schema = schema.model_copy(update={"auxiliary": auxiliary})

        semantic_fingerprints: dict[str, str] = {}
        for item in remaining_expected:
            fingerprint = _semantic_fingerprint(item, dialect=dialect, aliases=aliases, owners=owners)
            if fingerprint is not None:
                semantic_fingerprints[item.field.canonical_name.casefold()] = fingerprint

        projection_candidates: dict[int, list[_ExpectedProjection]] = {}
        for index in remaining_indexes:
            projection_fingerprint = _fingerprint(
                _projection_body(projections[index]),
                dialect=dialect,
                aliases=aliases,
                owners=owners,
            )
            projection_candidates[index] = [
                item for item in remaining_expected
                if semantic_fingerprints.get(item.field.canonical_name.casefold()) == projection_fingerprint
                or _is_bound_year_grain_projection(
                    projections[index],
                    item,
                    plan=plan,
                    root=root,
                    dialect=dialect,
                    aliases=aliases,
                    owners=owners,
                )
            ]

        if any(len(candidates) > 1 for candidates in projection_candidates.values()):
            raise ProjectionContractError("PROJECTION_AMBIGUOUS_SEMANTIC_MAPPING")
        matched_by_expected: dict[str, list[int]] = {}
        for index, candidates in projection_candidates.items():
            if len(candidates) == 1:
                matched_by_expected.setdefault(candidates[0].field.canonical_name.casefold(), []).append(index)
        if any(len(indexes) > 1 for indexes in matched_by_expected.values()):
            raise ProjectionContractError("PROJECTION_AMBIGUOUS_SEMANTIC_MAPPING")

        missing = [
            item.field.canonical_name for item in remaining_expected
            if item.field.canonical_name.casefold() not in matched_by_expected
        ]
        if missing:
            raise ProjectionContractError("PROJECTION_MISSING_EXPECTED_OUTPUT", details={"canonical_names": missing})
        extras = [index for index, candidates in projection_candidates.items() if not candidates]
        if extras:
            raise ProjectionContractError(
                "PROJECTION_UNDECLARED_OUTPUT",
                details={"output_names": [output_names[index] or "<unnamed>" for index in extras]},
            )

        actions: list[dict[str, str]] = []
        original_named = {name.casefold() for name in output_names if name}
        for item in remaining_expected:
            canonical_name = item.field.canonical_name
            index = matched_by_expected[canonical_name.casefold()][0]
            projection = projections[index]
            old_alias = _output_name(projection)
            if canonical_name.casefold() in original_named and old_alias.casefold() != canonical_name.casefold():
                raise ProjectionContractError("PROJECTION_ALIAS_COLLISION")
            _rewrite_dependent_alias(
                root=root,
                projection=projection,
                old_alias=old_alias,
                canonical_name=canonical_name,
                context=context,
            )
            projections[index] = _apply_alias(projection, canonical_name)
            semantic_key = "semantic_metric" if item.field.kind == "METRIC" else "semantic_dimension"
            actions.append({
                "from": old_alias or "<none>",
                "to": canonical_name,
                semantic_key: canonical_name,
                "semantic_id": item.field.semantic_id,
                "reason": "canonical_output_contract",
            })

        normalized_sql = statement.sql(dialect=dialect, pretty=False) if actions else plan.generated_sql
        trace = {
            **plan.model_trace,
            "projection_contract": {
                "status": "PASS",
                "canonical_output_schema": schema.model_dump(mode="json"),
                "normalization_actions": actions,
            },
        }
        normalized_plan = plan.model_copy(update={
            "generated_sql": normalized_sql,
            "canonical_output_schema": schema,
            "model_trace": trace,
        })
        return ProjectionContractResult(
            plan=normalized_plan,
            status="PASS",
            normalization_actions=tuple(actions),
        )
