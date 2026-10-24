"""Small, validated research ideas and serializable ranking results."""
from __future__ import annotations

import math
import unicodedata
from dataclasses import asdict, dataclass, field
from typing import Any
from uuid import uuid4

SCORE_NOTICE = (
    "Heuristic relevance estimate, not verified supervisor suitability. "
    "Availability, willingness and qualifications have not been verified."
)


def clean_text(value: str, limit: int) -> str:
    if not isinstance(value, str):
        raise ValueError("Idea text must be a string.")
    value = unicodedata.normalize("NFC", value).strip()
    if len(value) > limit:
        raise ValueError(f"Idea field exceeds its {limit}-character limit.")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise ValueError("Idea text must be valid UTF-8 Unicode.") from exc
    return value


@dataclass(frozen=True)
class ResearchIdea:
    title: str
    description: str = ""
    keywords: tuple[str, ...] = ()
    domain: str | None = None
    keyword_weights: dict[str, float] = field(default_factory=dict)
    idea_id: str = field(default_factory=lambda: uuid4().hex)

    def __post_init__(self) -> None:
        title = clean_text(self.title, 300)
        if not title:
            raise ValueError("An idea needs a title.")
        if (not isinstance(self.idea_id, str) or len(self.idea_id) != 32
                or any(char not in "0123456789abcdef" for char in self.idea_id)):
            raise ValueError("Idea identifier must be 32 lowercase hexadecimal characters.")
        if not isinstance(self.keywords, (tuple, list)) or len(self.keywords) > 100:
            raise ValueError("Use at most 100 keywords.")
        unique: dict[str, str] = {}
        for term in self.keywords:
            term = clean_text(term, 200)
            if term:
                unique.setdefault(term.casefold(), term)
        if not isinstance(self.keyword_weights, dict):
            raise ValueError("Keyword weights must be a JSON object.")
        weights: dict[str, float] = {}
        for key, weight in self.keyword_weights.items():
            normalized = clean_text(key, 200).casefold()
            if normalized not in unique:
                raise ValueError("Each weighted term must also be listed as a keyword.")
            if (type(weight) not in (int, float) or not 0 <= weight <= 1000
                    or not math.isfinite(weight)):
                raise ValueError("Keyword weights must be finite numbers between 0 and 1000.")
            if unique[normalized] in weights:
                raise ValueError("Do not repeat a keyword weight with different casing.")
            weights[unique[normalized]] = float(weight)
        object.__setattr__(self, "title", title)
        object.__setattr__(self, "description", clean_text(self.description, 20000))
        object.__setattr__(self, "keywords", tuple(unique.values()))
        domain = clean_text(self.domain, 300) if self.domain is not None else ""
        object.__setattr__(self, "domain", domain or None)
        object.__setattr__(self, "keyword_weights", weights)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class RankedMatch:
    supervisor_name: str | None
    score: float
    components: dict[str, float]
    matched_terms: tuple[str, ...]
    sources: tuple[str, ...]
    record_ids: tuple[str, ...]
    reason: str
    uncertainties: tuple[str, ...]


@dataclass(frozen=True)
class IdeaRanking:
    idea_id: str
    idea_title: str
    candidate_count: int
    matches: list[RankedMatch]
    warnings: tuple[str, ...]
    score_notice: str = SCORE_NOTICE

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
