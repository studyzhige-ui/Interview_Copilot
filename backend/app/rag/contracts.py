"""Stable data contracts shared by the RAG pipeline."""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator


class SearchIntent(BaseModel):
    """One self-contained information need.

    ``query`` stays in the user's language. ``alternate_query`` is an optional
    cross-language search variant, never a replacement. ``keywords`` drives
    lexical retrieval, while ``required_terms`` contains exact product, API,
    version, symbol, or configuration qualifiers that evidence must preserve.
    """

    query: str
    alternate_query: str = ""
    keywords: list[str] = Field(default_factory=list)
    required_terms: list[str] = Field(default_factory=list)

    @field_validator("query", "alternate_query", mode="before")
    @classmethod
    def _clean_query(cls, value: object) -> str:
        return " ".join(str(value or "").split())

    @field_validator("keywords", "required_terms", mode="before")
    @classmethod
    def _clean_terms(cls, value: object) -> list[str]:
        if not isinstance(value, list):
            return []
        return list(
            dict.fromkeys(
                " ".join(str(term).split()) for term in value if str(term or "").strip()
            )
        )

    @property
    def dense_queries(self) -> tuple[str, ...]:
        values = [self.query, self.alternate_query]
        return tuple(dict.fromkeys(value for value in values if value))

    @property
    def sparse_query(self) -> str:
        return " ".join(self.keywords) or self.query

    @classmethod
    def from_query(cls, query: str) -> "SearchIntent":
        return cls(query=query, keywords=[query])


__all__ = ["SearchIntent"]
