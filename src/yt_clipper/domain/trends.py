from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class TrendingVideo:
    title: str
    tags: list[str] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class SearchSuggestion:
    text: str
    kind: str
