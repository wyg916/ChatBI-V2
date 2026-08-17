from __future__ import annotations

from collections.abc import Iterable

from pydantic import BaseModel, ConfigDict, Field


class PromptVersion(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    version: int = Field(ge=1)
    content: str = Field(min_length=1, max_length=100_000)
    status: str = Field(pattern=r"^(DRAFT|ACTIVE|RETIRED)$")
    source_commit: str | None = None


class PromptTemplate(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    code: str = Field(pattern=r"^[a-z][a-z0-9_.-]{2,95}$")
    purpose: str = Field(min_length=1, max_length=256)
    versions: tuple[PromptVersion, ...]


class PromptRegistry:
    def __init__(self, templates: Iterable[PromptTemplate] = ()) -> None:
        self._templates = {item.code: item for item in templates}

    def resolve(self, code: str, version: int | None = None) -> PromptVersion:
        template = self._templates.get(code)
        if template is None:
            raise LookupError(f"prompt not found: {code}")
        candidates = [item for item in template.versions if item.status == "ACTIVE"]
        if version is not None:
            candidates = [item for item in template.versions if item.version == version]
        if not candidates:
            raise LookupError(f"prompt version not found: {code}@{version or 'active'}")
        return max(candidates, key=lambda item: item.version)
