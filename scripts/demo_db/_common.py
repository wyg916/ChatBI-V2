from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any

import psycopg
from sqlalchemy.engine import make_url


IDENTIFIER = re.compile(r"^[a-z][a-z0-9_]{2,62}$")
SAFE_BENCHMARK_PREFIX = "chatbi_benchmark"


def load_env(path: Path | None) -> dict[str, str]:
    values = dict(os.environ)
    if path and path.exists():
        for raw in path.read_text(encoding="utf-8-sig").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
                value = value[1:-1]
            values.setdefault(key, value)
    return values


def validate_schema(schema: str) -> str:
    if not IDENTIFIER.fullmatch(schema) or not schema.startswith(SAFE_BENCHMARK_PREFIX):
        raise ValueError(f"Benchmark schema must start with {SAFE_BENCHMARK_PREFIX!r} and contain only lowercase identifiers")
    return schema


def connection_kwargs(env: dict[str, str]) -> dict[str, Any]:
    raw_url = env.get("CHATBI_DATABASE_URL", "postgresql+psycopg://chatbi_app@127.0.0.1:5432/chatbi_v2")
    url = make_url(raw_url)
    password = url.password or env.get("CHATBI_META_PASSWORD", "")
    return {
        "host": url.host or "127.0.0.1",
        "port": url.port or 5432,
        "dbname": url.database or "chatbi_v2",
        "user": url.username or "chatbi_app",
        "password": password,
    }


def connect(env: dict[str, str]) -> psycopg.Connection:
    return psycopg.connect(**connection_kwargs(env))


def render_template(path: Path, **values: Any) -> str:
    text = path.read_text(encoding="utf-8")
    for key, value in values.items():
        text = text.replace("{{" + key + "}}", str(value))
    unresolved = sorted(set(re.findall(r"\{\{([a-z_]+)\}\}", text)))
    if unresolved:
        raise ValueError(f"Unresolved SQL template values in {path.name}: {unresolved}")
    return text


def canonical_hash(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    temporary.replace(path)
