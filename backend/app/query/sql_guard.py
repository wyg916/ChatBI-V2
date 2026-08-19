from __future__ import annotations

from sqlglot import exp, parse
from sqlglot.errors import ParseError

from app.query.contracts import GuardIssue, GuardResult, SecurityPolicy


_DIALECT = {"postgresql": "postgres", "mysql": "mysql"}
_FORBIDDEN_NODES = tuple(
    getattr(exp, name)
    for name in (
        "Insert", "Update", "Delete", "Create", "Drop", "Alter", "Command", "Copy", "Merge",
        "Grant", "Revoke", "Use", "Set", "Transaction", "TruncateTable", "Into", "LoadData",
    )
    if hasattr(exp, name)
)
_FORBIDDEN_FUNCTIONS = {
    "pg_read_file", "pg_read_binary_file", "pg_ls_dir", "pg_stat_file", "lo_import", "lo_export",
    "dblink", "dblink_exec", "sys_exec", "sys_eval", "load_file", "sleep", "benchmark",
    "pg_sleep", "current_setting", "set_config", "pg_terminate_backend", "pg_cancel_backend",
    "pg_export_snapshot", "pg_logical_emit_message", "get_lock", "release_lock", "connection_id",
}
_SYSTEM_SCHEMAS = {"information_schema", "pg_catalog", "mysql", "performance_schema", "sys"}


class SqlGuard:
    def validate(self, sql: str, *, dialect: str, policy: SecurityPolicy) -> GuardResult:
        sqlglot_dialect = _DIALECT.get(dialect, dialect)
        issues: list[GuardIssue] = []
        try:
            statements = parse(sql, read=sqlglot_dialect)
        except ParseError as exc:
            return GuardResult(
                allowed=False, dialect=dialect,
                issues=[GuardIssue(code="SQL_PARSE_ERROR", message=str(exc)[:500])],
            )
        if len(statements) != 1:
            return GuardResult(
                allowed=False, dialect=dialect,
                issues=[GuardIssue(code="MULTI_STATEMENT", message="Exactly one SQL statement is allowed")],
            )
        statement = statements[0]
        if not isinstance(statement, exp.Select):
            issues.append(GuardIssue(code="STATEMENT_NOT_ALLOWED", message="Only SELECT or WITH ... SELECT is allowed"))
        forbidden = next(statement.find_all(*_FORBIDDEN_NODES), None) if _FORBIDDEN_NODES else None
        if forbidden is not None:
            issues.append(GuardIssue(
                code="MUTATION_OR_ADMIN_STATEMENT",
                message=f"Forbidden AST node: {forbidden.key}",
                object_name=forbidden.key,
            ))

        cte_nodes = list(statement.find_all(exp.CTE))
        cte_names = {cte.alias_or_name.lower() for cte in cte_nodes}
        cte_output_columns = {
            expression.alias_or_name.lower()
            for cte in cte_nodes
            for expression in getattr(cte.this, "expressions", [])
            if expression.alias_or_name
        }
        tables: list[str] = []
        alias_to_table: dict[str, str] = {}
        allowed_tables = {value.lower() for value in policy.allowed_tables}
        allowed_schemas = {value.lower() for value in policy.allowed_schemas}
        for table in statement.find_all(exp.Table):
            name = table.name.lower()
            schema = (table.db or "").lower()
            if name in cte_names and not schema:
                continue
            tables.append(name)
            alias_to_table[(table.alias_or_name or name).lower()] = name
            alias_to_table[name] = name
            if schema in _SYSTEM_SCHEMAS:
                issues.append(GuardIssue(code="SYSTEM_SCHEMA_DENIED", message="System schemas are not queryable", object_name=schema))
            elif schema and allowed_schemas and schema not in allowed_schemas:
                issues.append(GuardIssue(code="SCHEMA_NOT_AUTHORIZED", message="Schema is outside the datasource allowlist", object_name=schema))
            if name not in allowed_tables:
                issues.append(GuardIssue(code="TABLE_NOT_AUTHORIZED", message="Table is outside the datasource allowlist", object_name=name))

        columns: list[str] = []
        allowed_column_union = {column for values in policy.allowed_columns.values() for column in values}
        for column in statement.find_all(exp.Column):
            name = column.name.lower()
            qualifier = (column.table or "").lower()
            if not name or name == "*":
                continue
            columns.append(f"{qualifier}.{name}" if qualifier else name)
            source_table = alias_to_table.get(qualifier) if qualifier else None
            if source_table:
                allowed = set(policy.allowed_columns.get(source_table, []))
                if name not in allowed:
                    issues.append(GuardIssue(code="COLUMN_NOT_AUTHORIZED", message="Column is outside the table allowlist", object_name=f"{source_table}.{name}"))
            elif name not in allowed_column_union and name not in cte_names and name not in cte_output_columns:
                # SQL aliases are legal in ORDER BY; allow explicit select aliases only.
                select_aliases = {item.alias.lower() for item in statement.expressions if item.alias}
                if name not in select_aliases:
                    issues.append(GuardIssue(code="COLUMN_NOT_AUTHORIZED", message="Column is outside the datasource allowlist", object_name=name))

        for star in statement.find_all(exp.Star):
            if not isinstance(star.parent, exp.Count):
                issues.append(GuardIssue(code="WILDCARD_NOT_ALLOWED", message="SELECT * is not allowed; columns must be explicit"))
        for function in statement.find_all(exp.Func):
            name = (function.name if isinstance(function, exp.Anonymous) else function.sql_name()).lower()
            if name in _FORBIDDEN_FUNCTIONS:
                issues.append(GuardIssue(code="FUNCTION_NOT_ALLOWED", message="Dangerous function is forbidden", object_name=name))

        if issues:
            return GuardResult(
                allowed=False, dialect=dialect, statement_type=statement.key.upper(),
                tables=sorted(set(tables)), columns=sorted(set(columns)), issues=issues,
            )

        requested_limit = policy.row_limit
        limit_node = statement.args.get("limit")
        if limit_node is not None and limit_node.expression is not None:
            try:
                requested_limit = min(policy.row_limit, int(limit_node.expression.name))
            except (TypeError, ValueError):
                requested_limit = policy.row_limit
        statement = statement.limit(requested_limit, copy=True)
        normalized = statement.sql(dialect=sqlglot_dialect, pretty=False, comments=False)
        return GuardResult(
            allowed=True,
            dialect=dialect,
            normalized_sql=normalized,
            statement_type="WITH_SELECT" if statement.args.get("with_") else "SELECT",
            tables=sorted(set(tables)),
            columns=sorted(set(columns)),
            applied_limit=requested_limit,
        )
