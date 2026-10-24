"""Synthetic read-only sources. Live connectors are a documented follow-up."""

from pydantic import BaseModel, ConfigDict, Field


class SourcePage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_id: str
    revision: str
    captured_at: str
    text: str
    offset: int
    next_offset: int | None
    synthetic: bool = True


SOURCES = {
    "github:example/widget/README.md": (
        "fixture-commit-1",
        "Widget example: requests time out after 30 seconds. "
        "The retry policy is documented in docs/retries.md. This is synthetic evidence.",
    ),
    "github:example/widget/docs/retries.md": (
        "fixture-commit-1",
        "Retry only idempotent reads. An ambiguous write must be investigated.",
    ),
    "notion:example/operations": (
        "fixture-revision-1",
        "Synthetic operations note: a timeout is not proof of no effect.",
    ),
}


class SourceRead(BaseModel):
    source_id: str
    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=1500, ge=1, le=4000)


def read_source(query: SourceRead):
    if query.source_id not in SOURCES:
        raise ValueError("Source is not in the Creator allowlist; use list_sources")
    revision, content = SOURCES[query.source_id]
    end = min(len(content), query.offset + query.limit)
    return SourcePage(
        source_id=query.source_id,
        revision=revision,
        captured_at="2026-01-01T00:00:00Z",
        text=content[query.offset : end],
        offset=query.offset,
        next_offset=end if end < len(content) else None,
    )
