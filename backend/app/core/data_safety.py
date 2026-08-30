from __future__ import annotations

import re
import unicodedata
from typing import Any

from sqlglot import exp, parse, parse_one


SENSITIVE_COLUMN = re.compile(
    r"password|passwd|pwd|secret|token|apikey|privatekey|idcard|ssn|phone|mobile|email|bankaccount|"
    r"cardnumber|creditcard|密码|密钥|令牌|手机号|手机号码|电话|邮箱|电子邮件|身份证|银行卡|卡号",
    re.IGNORECASE,
)
SENSITIVE_COMMENT_MARKER = "[SENSITIVE_SOURCE]"
PUBLIC_SQL_MASK = "***MASKED***"

_DIALECT = {"postgresql": "postgres", "mysql": "mysql", "excel": "postgres"}
_SENSITIVE_COMPARISONS = tuple(
    getattr(exp, name)
    for name in (
        "EQ", "NEQ", "GT", "GTE", "LT", "LTE", "Like", "ILike",
        "RegexpLike", "SimilarTo", "NullSafeEQ", "NullSafeNEQ",
    )
    if hasattr(exp, name)
)
_PUBLIC_SQL_KEYS = frozenset({
    "sql",
    "sql_text",
    "normalized_sql",
    "generated_sql",
    "corrected_sql",
    "candidate_sql",
    "expected_sql",
    "semantic_sql",
    "final_sql",
    "verification_sql",
    "replay_sql",
    "source_sql",
    "previous_sql",
    "predicted_sql",
    "gt_sql",
    "verified_sql",
})
_PUBLIC_ERROR_TEXT_KEYS = frozenset({
    "error",
    "error_text",
    "error_message",
    "exception",
    "exception_text",
    "exception_message",
    "stack_trace",
    "traceback",
})
_PUBLIC_EXPLAIN_EXPRESSION_KEYS = frozenset({
    # PostgreSQL JSON EXPLAIN expression-bearing fields.  These values are
    # rendered SQL fragments and can echo predicate/projection literals even
    # when the surrounding public SQL has already been redacted.
    "filter",
    "function_call",
    "group_key",
    "hash_cond",
    "hash_key",
    "index_cond",
    "join_filter",
    "merge_cond",
    "one_time_filter",
    "output",
    "presorted_key",
    "recheck_cond",
    "remote_sql",
    "run_condition",
    "sort_key",
    "tid_cond",
    # MySQL JSON EXPLAIN condition fields.
    "attached_condition",
    "having_condition",
    "index_condition",
    "pushed_index_condition",
    "table_condition",
})


def is_sensitive_column(value: str) -> bool:
    normalized = unicodedata.normalize("NFKC", str(value))
    normalized = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", normalized).lower()
    compact = re.sub(r"[^a-z0-9\u4e00-\u9fff]", "", normalized)
    return bool(SENSITIVE_COLUMN.search(compact))


def redact_public_sql(
    sql: str | None,
    sensitive_columns: list[str] | set[str] = (),
    *,
    dialect: str,
) -> str | None:
    """Render SQL for an API response without exposing sensitive predicates.

    Execution and signature calculation continue to use the original SQL.  This
    renderer operates on a copied SQLGlot AST and replaces only literal values
    compared with a recognized sensitive column (including ``IN``, ``BETWEEN``
    and pattern predicates).  Parse failures fail closed because returning the
    original text would turn an unusual dialect construct into a disclosure.
    """

    if sql is None or not str(sql).strip():
        return sql
    sqlglot_dialect = _DIALECT.get(dialect, dialect)
    try:
        statements = parse(str(sql), read=sqlglot_dialect)
    except Exception:
        return "/* SQL hidden: public redaction failed */"
    if len(statements) != 1:
        return "/* SQL hidden: public redaction failed */"
    statement = statements[0].copy()
    recognized = {
        str(value).rsplit(".", 1)[-1].casefold()
        for value in sensitive_columns
        if str(value).strip()
    }

    def mask_literals(expression: exp.Expression | None) -> None:
        if expression is None:
            return
        for literal in list(expression.find_all(exp.Literal)):
            literal.replace(exp.Literal.string(PUBLIC_SQL_MASK))

    def contains_sensitive_column(expression: exp.Expression | None) -> bool:
        if expression is None:
            return False
        return any(
            column.name.casefold() in recognized or is_sensitive_column(column.name)
            for column in expression.find_all(exp.Column)
        )

    # Follow projection aliases and explicit CTE/derived-table/LATERAL column
    # alias lists. SQL column alias lists can rename ``email`` to a harmless
    # word such as ``contact``; when child lineage is tainted, public rendering
    # deliberately taints all explicit names rather than guessing an unsafe
    # partial ordinal mapping.
    changed = True
    while changed:
        changed = False
        for alias in statement.find_all(exp.Alias):
            alias_name = str(alias.alias or "").casefold()
            alias_is_sensitive = bool(
                alias_name
                and (alias_name in recognized or is_sensitive_column(alias_name))
            )
            if alias_is_sensitive:
                mask_literals(alias.this)
            if alias_name and alias_name not in recognized and contains_sensitive_column(alias.this):
                recognized.add(alias_name)
                changed = True

        for owner in statement.walk():
            alias_expression = owner.args.get("alias")
            columns = (
                alias_expression.args.get("columns")
                if alias_expression is not None
                else None
            )
            if not columns:
                continue
            names = [str(column.name).casefold() for column in columns if column.name]
            if not names:
                continue
            child = owner.args.get("this")
            if contains_sensitive_column(child):
                for name in names:
                    if name not in recognized:
                        recognized.add(name)
                        changed = True
            if any(name in recognized or is_sensitive_column(name) for name in names):
                # Table-valued functions can materialize a literal document as
                # explicitly named columns without any child Column node. Once
                # one output alias is sensitive, the opaque source arguments
                # must be treated as tainted as well.
                mask_literals(child)
            child_select = (
                child
                if isinstance(child, exp.Select)
                else child.find(exp.Select)
                if isinstance(child, exp.Expression)
                else None
            )
            if child_select is not None:
                for name, projection in zip(names, child_select.expressions, strict=False):
                    if name in recognized or is_sensitive_column(name):
                        mask_literals(projection)

    def is_sensitive_expression(expression: exp.Expression | None) -> bool:
        if expression is None:
            return False
        return any(
            column.name.casefold() in recognized or is_sensitive_column(column.name)
            for column in expression.find_all(exp.Column)
        )

    # Public SQL may disclose a sensitive literal outside predicates as part of
    # a computed output or ordering key.  Treat each expression independently
    # so unrelated SELECT/GROUP/ORDER expressions keep their useful literals.
    for select_expression in statement.find_all(exp.Select):
        for projection in select_expression.expressions:
            if is_sensitive_expression(projection):
                mask_literals(projection)

    for group in statement.find_all(exp.Group):
        for group_expression in group.expressions:
            if is_sensitive_expression(group_expression):
                mask_literals(group_expression)

    for order in statement.find_all(exp.Order):
        for ordered_expression in order.expressions:
            if is_sensitive_expression(ordered_expression):
                mask_literals(ordered_expression)

    for distinct in statement.find_all(exp.Distinct):
        distinct_on = distinct.args.get("on")
        if is_sensitive_expression(distinct_on):
            mask_literals(distinct_on)

    for window in statement.find_all(exp.Window):
        for partition_expression in window.args.get("partition_by") or []:
            if is_sensitive_expression(partition_expression):
                mask_literals(partition_expression)
        window_order = window.args.get("order")
        if isinstance(window_order, exp.Expression):
            for ordered_expression in window_order.expressions:
                if is_sensitive_expression(ordered_expression):
                    mask_literals(ordered_expression)

    def mask_sensitive_predicate(expression: exp.Expression | None) -> None:
        """Mask literals in the smallest boolean branch that reads PII.

        Dialects can represent boolean functions, regex operators and generic
        ``OPERATOR(...)`` syntax with AST classes that are not ordinary binary
        comparisons. Splitting AND/OR/NOT/PAREN branches first preserves useful
        non-sensitive predicates while making every remaining sensitive branch
        fail closed regardless of its operator class.
        """

        if expression is None:
            return
        if isinstance(expression, (exp.And, exp.Or)):
            mask_sensitive_predicate(expression.args.get("this"))
            mask_sensitive_predicate(expression.args.get("expression"))
            return
        if isinstance(expression, (exp.Not, exp.Paren)):
            mask_sensitive_predicate(expression.args.get("this"))
            return
        if is_sensitive_expression(expression):
            mask_literals(expression)

    predicate_owners = tuple(
        getattr(exp, name)
        for name in ("Where", "Having", "Qualify")
        if hasattr(exp, name)
    )
    for owner in statement.find_all(*predicate_owners):
        mask_sensitive_predicate(owner.args.get("this"))
    for join in statement.find_all(exp.Join):
        mask_sensitive_predicate(join.args.get("on"))

    for node in list(statement.walk()):
        if isinstance(node, _SENSITIVE_COMPARISONS):
            left = node.args.get("this")
            right = node.args.get("expression")
            if is_sensitive_expression(left):
                mask_literals(right)
            if is_sensitive_expression(right):
                mask_literals(left)
        elif isinstance(node, exp.In) and is_sensitive_expression(node.args.get("this")):
            for candidate in node.expressions:
                mask_literals(candidate)
            mask_literals(node.args.get("query"))
        elif isinstance(node, exp.Between) and is_sensitive_expression(node.args.get("this")):
            mask_literals(node.args.get("low"))
            mask_literals(node.args.get("high"))

    return statement.sql(dialect=sqlglot_dialect, pretty=False, comments=False)


def redact_public_explain_plan_payload(
    value: Any,
    sensitive_columns: list[str] | set[str] = (),
) -> Any:
    """Copy an EXPLAIN payload while hiding SQL-expression fragments.

    PostgreSQL and MySQL JSON plans expose predicates and projection
    expressions as ordinary strings (for example ``Filter`` or
    ``attached_condition``).  They are not standalone SQL fields, so the SQL
    renderer cannot safely parse every dialect-specific fragment.  When the
    datasource policy contains sensitive columns, fail closed for those
    expression-bearing fields while retaining structural/cost evidence.
    """

    recognized = {
        str(column).rsplit(".", 1)[-1].casefold()
        for column in sensitive_columns
        if str(column).strip()
    }
    if isinstance(value, list):
        return [
            redact_public_explain_plan_payload(item, sensitive_columns)
            for item in value
        ]
    if not isinstance(value, dict):
        return value

    result: dict[str, Any] = {}
    for key, item in value.items():
        normalized_key = re.sub(
            r"[^a-z0-9]+", "_", str(key).casefold(),
        ).strip("_")
        if recognized and normalized_key in _PUBLIC_EXPLAIN_EXPRESSION_KEYS:
            if isinstance(item, list):
                result[key] = [
                    None if candidate is None else PUBLIC_SQL_MASK
                    for candidate in item
                ]
            elif item is None:
                result[key] = None
            else:
                result[key] = PUBLIC_SQL_MASK
        else:
            result[key] = redact_public_explain_plan_payload(
                item, sensitive_columns,
            )
    return result


def redact_public_sql_payload(
    value: Any,
    sensitive_columns: list[str] | set[str] = (),
    *,
    dialect: str,
) -> Any:
    """Copy a public payload while redacting every known SQL-bearing field."""

    if isinstance(value, list):
        return [
            redact_public_sql_payload(item, sensitive_columns, dialect=dialect)
            for item in value
        ]
    if not isinstance(value, dict):
        return value

    recognized = {
        str(column).rsplit(".", 1)[-1].casefold()
        for column in sensitive_columns
        if str(column).strip()
    }
    filter_field = str(value.get("field") or "").rsplit(".", 1)[-1]
    sensitive_filter = bool(
        filter_field
        and (filter_field.casefold() in recognized or is_sensitive_column(filter_field))
    )
    result: dict[str, Any] = {}
    coded_message = "code" in value and "message" in value
    for key, item in value.items():
        if key in _PUBLIC_SQL_KEYS and isinstance(item, str):
            result[key] = redact_public_sql(
                item, sensitive_columns, dialect=dialect,
            )
        elif str(key).casefold() == "plan" and recognized:
            # ``plan`` is also used by NL2SQL/evaluation payloads and may
            # contain ordinary SQL-bearing keys such as ``generated_sql``.
            # Apply the normal recursive SQL redactor first, then scrub any
            # EXPLAIN expression fields without treating every plan as an
            # opaque planner tree.
            result[key] = redact_public_explain_plan_payload(
                redact_public_sql_payload(
                    item,
                    sensitive_columns,
                    dialect=dialect,
                ),
                sensitive_columns,
            )
        elif (
            key == "question"
            and isinstance(item, str)
            and re.match(r"^\s*(?:SELECT|WITH)\b", item, re.IGNORECASE)
        ):
            result[key] = redact_public_sql(
                item, sensitive_columns, dialect=dialect,
            )
        elif sensitive_filter and key == "value":
            if isinstance(item, list):
                result[key] = [PUBLIC_SQL_MASK for _ in item]
            elif item is not None:
                result[key] = PUBLIC_SQL_MASK
            else:
                result[key] = None
        elif str(key).casefold() in _PUBLIC_ERROR_TEXT_KEYS and item is not None:
            result[key] = "The operation could not be completed; use the error code for diagnosis."
        elif coded_message and key == "message" and item is not None:
            result[key] = "SQL did not pass the public safety boundary."
        else:
            result[key] = redact_public_sql_payload(
                item, sensitive_columns, dialect=dialect,
            )
    return result


def sensitive_output_columns(
    sql: str,
    output_columns: list[str],
    source_sensitive_columns: list[str] | set[str],
    *,
    dialect: str,
) -> list[str]:
    """Resolve sensitive source columns through SELECT aliases at the API boundary."""

    sensitive_sources = {
        str(value).rsplit(".", 1)[-1].lower() for value in source_sensitive_columns
    }
    resolved = {
        column for column in output_columns
        if is_sensitive_column(column) or column.lower() in sensitive_sources
    }
    try:
        parsed = parse_one(sql, read={"postgresql": "postgres", "mysql": "mysql"}.get(dialect, dialect))
    except Exception:
        # The query already executed, so an AST incompatibility must not turn
        # into a PII bypass.  If lineage cannot be proven, mask every returned
        # field rather than exposing an aliased sensitive value.
        return sorted(output_columns if sensitive_sources else resolved)

    def projection_taint(
        node: exp.Expression,
        inherited_ctes: dict[str, set[str]] | None = None,
    ) -> set[str]:
        """Return output names derived from sensitive columns.

        This deliberately implements a small, fail-closed lineage resolver
        instead of relying on output aliases alone.  It follows CTEs and
        derived tables recursively, including ``SELECT *`` propagation.  A
        ``*`` marker means the exact output name cannot be proven and causes
        every public result column to be masked.
        """

        inherited = dict(inherited_ctes or {})

        def remap_explicit_alias_columns(owner: exp.Expression, tainted: set[str]) -> set[str]:
            alias_expression = owner.args.get("alias")
            columns = alias_expression.args.get("columns") if alias_expression is not None else None
            if not columns or not tainted:
                return tainted
            # SQL column alias lists are ordinal and can rename a sensitive
            # output to any otherwise harmless catalog name.  Stars, set
            # operations and dialect-specific projections make a partial name
            # mapping unsafe, so mask every explicitly renamed output whenever
            # the child contains any taint.
            return {str(column.name).lower() for column in columns if column.name}

        if isinstance(node, exp.Subquery):
            return projection_taint(node.this, inherited)
        if isinstance(node, (exp.Union, exp.Except, exp.Intersect)):
            left = projection_taint(node.this, inherited)
            right = projection_taint(node.expression, inherited)
            return {"*"} if left or right else set()
        if not isinstance(node, exp.Select):
            nested = node.find(exp.Select)
            if nested is not None:
                return projection_taint(nested, inherited)
            return {
                "*"
                for column in node.find_all(exp.Column)
                if column.name.lower() in sensitive_sources
            }

        cte_outputs = dict(inherited)
        with_clause = node.args.get("with_")
        if with_clause is not None:
            for cte in with_clause.expressions:
                alias = str(cte.alias_or_name or "").lower()
                if alias:
                    cte_outputs[alias] = remap_explicit_alias_columns(
                        cte, projection_taint(cte.this, cte_outputs),
                    )

        source_outputs: dict[str, set[str]] = {}

        def expression_reads_tainted_source(
            expression: exp.Expression,
            known_sources: dict[str, set[str]],
        ) -> bool:
            """Detect opaque table functions fed by sensitive/whole-row input.

            PostgreSQL table functions such as ``jsonb_each_text(to_jsonb(u))``
            can rename a whole row into generic ``key``/``value`` outputs.  If
            the function's output schema is not independently provable, any
            tainted input makes every function output tainted.
            """

            visible = set().union(*known_sources.values()) if known_sources else set()
            for column in expression.find_all(exp.Column):
                name = column.name.lower()
                qualifier = column.table.lower() if column.table else ""
                candidates = known_sources.get(qualifier, set()) if qualifier else visible
                if (
                    name in sensitive_sources
                    or name in candidates
                    or "*" in candidates
                    or (not qualifier and name in known_sources and bool(known_sources[name]))
                    or (name == "*" and bool(candidates or visible))
                ):
                    return True
            return False

        sources: list[exp.Expression] = []
        from_clause = node.args.get("from_")
        if from_clause is not None:
            if from_clause.this is not None:
                sources.append(from_clause.this)
            sources.extend(from_clause.expressions)
        sources.extend(
            join.this for join in node.args.get("joins") or [] if join.this is not None
        )
        for source in sources:
            alias = str(source.alias_or_name or "").lower()
            if isinstance(source, exp.Subquery):
                tainted = remap_explicit_alias_columns(
                    source, projection_taint(source.this, cte_outputs),
                )
            elif isinstance(source, exp.Table):
                if isinstance(source.this, exp.Identifier):
                    tainted = set(cte_outputs.get(source.name.lower(), sensitive_sources))
                else:
                    # PostgreSQL permits implicit-LATERAL table functions in
                    # ordinary JOIN/comma syntax. SQLGlot represents these as
                    # ``Table(Anonymous(...))`` rather than ``Lateral``, so
                    # inspect the function input before trusting its generic
                    # key/value output names.
                    child_taint = (
                        {"*"}
                        if expression_reads_tainted_source(source, source_outputs)
                        else set()
                    )
                    tainted = remap_explicit_alias_columns(source, child_taint)
            else:
                nested = source.find(exp.Select)
                if nested is not None:
                    child_taint = projection_taint(nested, cte_outputs)
                elif expression_reads_tainted_source(source, source_outputs):
                    # A table-valued function can turn one sensitive input into
                    # arbitrary generic output names.  Preserve no partial name
                    # mapping here: explicit alias columns are remapped below;
                    # otherwise the star marker masks every selected output.
                    child_taint = {"*"}
                else:
                    child_taint = set()
                tainted = remap_explicit_alias_columns(source, child_taint)
            source_outputs[alias or f"__source_{len(source_outputs)}"] = tainted

        visible_taint = set().union(*source_outputs.values()) if source_outputs else set(sensitive_sources)
        outputs: set[str] = set()
        for projection in node.expressions:
            if projection.is_star:
                qualifier = str(getattr(projection, "table", "") or "").lower()
                outputs.update(source_outputs.get(qualifier, visible_taint))
                continue
            tainted = False
            for column in projection.find_all(exp.Column):
                name = column.name.lower()
                qualifier = column.table.lower() if column.table else ""
                candidates = source_outputs.get(qualifier, set()) if qualifier else visible_taint
                whole_row_taint = source_outputs.get(name, set()) if not qualifier else set()
                if (
                    name in sensitive_sources
                    or name in candidates
                    or "*" in candidates
                    or (name == "*" and bool(candidates or visible_taint))
                    or bool(whole_row_taint)
                ):
                    tainted = True
                    break
            if tainted:
                output_name = str(projection.alias_or_name or "").lower()
                outputs.add(output_name or "*")
        return outputs

    tainted_outputs = projection_taint(parsed)
    if "*" in tainted_outputs:
        return sorted(output_columns)
    output_lookup = {column.lower(): column for column in output_columns}
    matched_lineage = False
    for name in tainted_outputs:
        if name in output_lookup:
            resolved.add(output_lookup[name])
            matched_lineage = True
    explicit_sensitive_reference = any(
        column.name.lower() in sensitive_sources
        for column in parsed.find_all(exp.Column)
    )
    if (tainted_outputs and not matched_lineage) or (
        explicit_sensitive_reference and not tainted_outputs
    ):
        return sorted(output_columns)
    return sorted(resolved)


def mask_result_rows(
    sql: str,
    rows: list[dict[str, Any]],
    source_sensitive_columns: list[str] | set[str],
    *,
    dialect: str,
) -> tuple[list[dict[str, Any]], list[str]]:
    output_columns = list(rows[0]) if rows else []
    masked_columns = sensitive_output_columns(
        sql, output_columns, source_sensitive_columns, dialect=dialect,
    )
    masked_set = set(masked_columns)
    return [
        {
            column: (PUBLIC_SQL_MASK if column in masked_set and value is not None else value)
            for column, value in row.items()
        }
        for row in rows
    ], masked_columns


__all__ = [
    "SENSITIVE_COLUMN",
    "SENSITIVE_COMMENT_MARKER",
    "PUBLIC_SQL_MASK",
    "is_sensitive_column",
    "mask_result_rows",
    "redact_public_sql",
    "redact_public_sql_payload",
    "sensitive_output_columns",
]
