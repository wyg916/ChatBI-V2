from __future__ import annotations

from dataclasses import dataclass

import sqlglot

from app.query.contracts import QueryContext
from app.semantic_runtime._upstream.openchatbi.catalog_store import split_db_table_name
from app.semantic_runtime._upstream.wren.type_mapping import parse_types
from app.semantic_runtime._upstream.wren.wren_dialect import Wren


OPENCHATBI_COMMIT = "c8786cb180081dbdd18d841efa33b70d77b633e9"
OPENCHATBI_SOURCE_SHA256 = "24686e93fb8fc9c21931b13f2e4076a19a033299939185744ac78d4eb5b4d494"
WRENAI_COMMIT = "7830cc746c11602d5899d8fdec1e28de4ce11a87"
WREN_TYPE_MAPPING_SHA256 = "fadc3a136f79c3721e46727c9d633d3976475b9290786c34c3684b14669dae53"
WREN_DIALECT_SHA256 = "96e0834c1d6a5ecdcc66580abe8d710f4431f835ba0e5f1d42534ca77f9b6f27"


@dataclass(frozen=True)
class OpenChatBICatalogProjection:
    table_names: frozenset[str]
    qualified_names: tuple[str, ...]
    source_calls: int


def project_openchatbi_catalog(context: QueryContext) -> OpenChatBICatalogProjection:
    """Project authorized tables through OpenChatBI's pinned catalog-name helper.

    The upstream function participates in the selection input; database access,
    vector stores and LLM calls remain outside this selected-source closure.
    """

    allowed_tables = set(context.security_policy.allowed_tables)
    table_names: set[str] = set()
    qualified_names: list[str] = []
    calls = 0
    raw_names = [item.qualified_name or item.name for item in context.candidate_tables]
    raw_names.extend(str(item.get("source_table") or item.get("name") or "") for item in context.entities)
    for raw_name in dict.fromkeys(item for item in raw_names if item):
        full_name, _, table_name = split_db_table_name(raw_name)
        calls += 1
        if table_name in allowed_tables:
            table_names.add(table_name)
            qualified_names.append(full_name)
    return OpenChatBICatalogProjection(
        table_names=frozenset(table_names),
        qualified_names=tuple(qualified_names),
        source_calls=calls,
    )


_DIALECTS = {"postgresql": "postgres", "mysql": "mysql"}
_SEMANTIC_TYPES = {
    "STRING": "VARCHAR",
    "TIME": "TIMESTAMP",
    "NUMBER": "DECIMAL",
    "BOOLEAN": "BOOLEAN",
}


def normalize_wren_dimension_types(dimensions: list[dict], dialect: str) -> dict[str, str]:
    """Invoke WrenAI's pinned type mapper for MDL dimension types."""

    rows = [
        {
            "column": str(item["name"]),
            "raw_type": _SEMANTIC_TYPES.get(str(item.get("type", "")).upper(), str(item.get("type", ""))),
        }
        for item in dimensions
    ]
    normalized = parse_types(rows, _DIALECTS.get(dialect, dialect))
    return {str(item["column"]): str(item["type"]) for item in normalized}


def validate_wren_semantic_sql(sql: str) -> str:
    """Parse a dry semantic query with WrenAI's pinned SQLGlot dialect."""

    return sqlglot.parse_one(sql, read=Wren).sql()
