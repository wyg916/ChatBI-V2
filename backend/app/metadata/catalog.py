def qualified_name(*parts: str) -> str:
    """Build a stable catalog key from datasource, schema, table and column parts."""
    return ".".join(parts)
