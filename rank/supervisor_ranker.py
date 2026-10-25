"""Bounded, deterministic TF-IDF ranking. No network or model downloads."""
from __future__ import annotations

import heapq
import unicodedata
from dataclasses import dataclass, field, replace
from typing import Iterable

from core.config import RankingConfig
from core.text import tokenize
from core.models import ExtractedRecord
from core.storage import canonical_json, content_hash
from rank.models import IdeaRanking, RankedMatch, ResearchIdea


class RankingError(ValueError):
    pass


def _column(value: str) -> str:
    return "".join(tokenize(value))


def _strings(value: object) -> list[str]:
    result: list[str] = []
    stack = [value]
    while stack:
        item = stack.pop()
        if isinstance(item, str) and item.strip():
            result.append(item.strip())
        elif isinstance(item, list):
            stack.extend(reversed(item))
    return result


def _values(columns: dict[str, object], aliases: tuple[str, ...]) -> list[str]:
    return [text for alias in aliases for text in _strings(columns.get(alias))]


def _first(columns: dict[str, object], aliases: tuple[str, ...]) -> str | None:
    return next((value for value in _values(columns, aliases)
                 if value.casefold() not in {"n/a", "na", "unknown", "-", "none"}), None)


@dataclass(eq=False)
class _Candidate:
    name: str | None
    chunks: dict[str, str] = field(default_factory=dict)
    domains: set[str] = field(default_factory=set)
    sources: set[str] = field(default_factory=set)
    identifiers: set[str] = field(default_factory=set)
    warnings: set[str] = field(default_factory=set)
    parent: _Candidate | None = field(default=None, repr=False)

    @property
    def text(self) -> str:
        return "\n".join(self.chunks[key] for key in sorted(self.chunks))


def _root(candidate: _Candidate) -> _Candidate:
    root = candidate
    while root.parent is not None:
        root = root.parent
    while candidate.parent is not None:
        parent = candidate.parent
        candidate.parent = root
        candidate = parent
    return root


def _merge(first: _Candidate, second: _Candidate) -> _Candidate:
    if first is second:
        return first
    if first.name and second.name and first.name.casefold() != second.name.casefold():
        first.warnings.add("Grouped records contain different names; inspect their source records.")
    first.chunks.update({key: value for key, value in second.chunks.items() if key not in first.chunks})
    first.domains.update(second.domains)
    first.sources.update(second.sources)
    first.identifiers.update(second.identifiers)
    first.warnings.update(second.warnings)
    second.parent = first
    return first


def _candidates(records: Iterable[ExtractedRecord], config: RankingConfig) -> list[_Candidate]:
    bounded: list[ExtractedRecord] = []
    total = 0
    for record in records:
        if len(bounded) >= config.max_records:
            raise RankingError("Too many records for one comparison. Narrow the source/type filters.")
        chars = len(record.text) + len(canonical_json(record.fields))
        if chars > config.max_chars_per_record:
            raise RankingError("A record exceeds ranking.max_chars_per_record; split or filter the document.")
        total += chars
        if total > config.max_total_chars:
            raise RankingError("Comparison exceeds ranking.max_total_chars. Narrow the source/type filters.")
        bounded.append(record)

    by_identity: dict[tuple[str, ...], _Candidate] = {}
    by_content: dict[str, _Candidate] = {}
    name_fields, email_fields, affiliation_fields, expertise_fields, domain_fields = (
        tuple(_column(alias) for alias in getattr(config, field_name)) for field_name in (
            "name_fields", "email_fields", "affiliation_fields", "expertise_fields", "domain_fields"))
    for record in sorted(bounded, key=lambda row: (row.source, row.source_type, row.record_id)):
        columns = {_column(key): value for key, value in record.fields.items()}
        name = _first(columns, name_fields)
        email = _first(columns, email_fields)
        affiliation = _first(columns, affiliation_fields)
        exact = content_hash(record)
        if name and email:
            identity = ("email", email.casefold())
        elif name and affiliation:
            identity = ("name-affiliation", " ".join(tokenize(name)), " ".join(tokenize(affiliation)))
        elif name:
            identity = ("name-source", " ".join(tokenize(name)), record.source)
        else:
            identity = ("content", exact)
        identity_match = by_identity.get(identity)
        content_match = by_content.get(exact)
        candidate = _root(identity_match) if identity_match is not None else None
        if content_match is not None:
            content_match = _root(content_match)
            candidate = _merge(candidate, content_match) if candidate is not None else content_match
        if candidate is None:
            candidate = _Candidate(name)
        by_identity[identity] = candidate
        by_content[exact] = candidate
        expertise = _values(columns, expertise_fields)
        text = "\n".join(expertise) if expertise else record.text
        normalized = unicodedata.normalize("NFC", text).strip()
        candidate.chunks.setdefault(normalized.casefold(), normalized)
        candidate.domains.update(_values(columns, domain_fields))
        candidate.sources.add(record.source)
        candidate.identifiers.add(record.record_id)
        if not name:
            candidate.warnings.add("Supervisor name is missing; this result represents a document record.")
        if not expertise:
            candidate.warnings.add("No recognized expertise field; full record text was used.")
        if name and not email:
            candidate.warnings.add("Identity grouping uses name and affiliation/source; identities are unverified.")
        if name and candidate.name and name.casefold() != candidate.name.casefold():
            candidate.warnings.add("Grouped records contain different names; inspect their source records.")
    # Multiple identity keys may refer to one candidate after exact-copy grouping.
    unique = {id(_root(candidate)): _root(candidate) for candidate in by_identity.values()}
    return sorted(unique.values(), key=lambda candidate: (
        (candidate.name or "").casefold(), tuple(sorted(candidate.sources)), tuple(sorted(candidate.identifiers))))


def _token_text(text: str) -> str:
    # Tokenizer output contains no NULs; sentinels preserve exact token/phrase
    # boundaries while allowing compact cached strings and C-level substring search.
    tokens = tokenize(text)
    return "\x00" + "\x00".join(tokens) + "\x00" if tokens else ""


def _contains(tokens: str, phrase: str) -> bool:
    return bool(phrase) and phrase in tokens


def _keyword_score(patterns: list[tuple[str, float, str]], total: float, tokens: str) -> tuple[float, list[str]]:
    matched = 0.0
    terms: list[str] = []
    for term, weight, pattern in patterns:
        if weight > 0 and _contains(tokens, pattern):
            matched += weight
            terms.append(term)
    return (matched / total if total else 0.0), terms


def rank_records(records: Iterable[ExtractedRecord], ideas: Iterable[ResearchIdea],
                 config: RankingConfig | None = None) -> list[IdeaRanking]:
    config = config or RankingConfig()
    selected: list[ResearchIdea] = []
    seen: set[str] = set()
    for idea in ideas:
        if len(selected) >= config.max_ideas:
            raise RankingError("Too many ideas for one comparison; select fewer ideas.")
        idea = ResearchIdea(**idea.to_dict())  # Validate mutable nested weights again.
        if idea.idea_id in seen:
            raise RankingError("Select each idea only once.")
        selected.append(idea)
        seen.add(idea.idea_id)
    if not selected:
        raise RankingError("Create or select at least one research idea.")
    candidates = _candidates(records, config)
    if not candidates:
        return [IdeaRanking(idea.idea_id, idea.title, 0, [], ("No records match the selected filters.",))
                for idea in selected]
    try:
        import numpy as np
        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.metrics.pairwise import cosine_similarity
    except ImportError as exc:
        raise RankingError("Offline ranking dependencies are missing; install requirements.txt.") from exc

    texts = [candidate.text for candidate in candidates]
    # Bounded, per-comparison normalization; nothing is cached across user sessions.
    token_texts = [_token_text(text) for text in texts]
    domain_texts = [[_token_text(value) for value in candidate.domains] for candidate in candidates]
    vectorizer = TfidfVectorizer(tokenizer=tokenize, token_pattern=None, lowercase=False,
                                 ngram_range=(1, 2), sublinear_tf=True, max_features=config.max_features,
                                 dtype=np.float32)
    matrix = vectorizer.fit_transform(texts) if any(token_texts) else None
    features = vectorizer.get_feature_names_out() if matrix is not None else None
    weights = (config.text_weight, config.keyword_weight, config.domain_weight)
    results: list[IdeaRanking] = []
    for idea in selected:
        patterns = [(term, idea.keyword_weights.get(term, 1.0), _token_text(term)) for term in idea.keywords]
        keyword_total = sum(weight for _, weight, _ in patterns)
        domain_pattern = _token_text(idea.domain) if idea.domain else ""
        query = vectorizer.transform([idea.title + "\n" + idea.description]) if matrix is not None else None
        similarities = (cosine_similarity(matrix, query).ravel() if matrix is not None
                        else np.zeros(len(candidates)))
        warnings: list[str] = []
        if not idea.description:
            warnings.append("Description is empty; text similarity uses the title only.")
        if config.keyword_weight and not idea.keywords:
            warnings.append("Keyword scoring is enabled but no keywords were provided; that component is zero.")
        if config.domain_weight and not idea.domain:
            warnings.append("Domain scoring is enabled but no idea domain was provided; that component is zero.")
        if matrix is None or query.nnz == 0:
            warnings.append("No idea text terms occur in the candidate vocabulary; text similarity is zero.")

        def matches() -> Iterable[tuple[int, RankedMatch]]:
            for index, candidate in enumerate(candidates):
                keyword, terms = _keyword_score(patterns, keyword_total, token_texts[index])
                domain = float(any(_contains(value, domain_pattern) for value in domain_texts[index]))
                components = dict(text_similarity=round(float(similarities[index]), 6),
                                  keyword_relevance=round(keyword, 6), domain_relevance=domain)
                score = sum(weight * value for weight, value in zip(weights, (
                    float(similarities[index]), keyword, domain))) / sum(weights)
                uncertainties = set(candidate.warnings)
                if config.domain_weight and not candidate.domains:
                    uncertainties.add("No recognized supervisor domain field; domain relevance is zero.")
                if not keyword_total and config.keyword_weight:
                    uncertainties.add("No positively weighted keywords; keyword relevance is zero.")
                reason = (f"TF-IDF cosine={components['text_similarity']:.3f}; "
                          f"keyword coverage={keyword:.3f}; domain match={domain:.0f}. "
                          f"Weighted mean uses text/keyword/domain weights {weights}.")
                if score <= 0:
                    reason += " No relevance was found under the configured scoring weights."
                if config.keyword_weight:
                    uncertainties.add("Keyword and TF-IDF features can overlap; weights blend correlated signals.")
                if config.domain_weight:
                    uncertainties.add("Domain and text features can overlap; weights blend correlated signals.")
                yield index, RankedMatch(candidate.name, round(min(1.0, max(0.0, score)), 6), components,
                                         tuple(dict.fromkeys(terms)), tuple(sorted(candidate.sources)),
                                         tuple(sorted(candidate.identifiers)), reason, tuple(sorted(uncertainties)))

        best = heapq.nsmallest(config.top_k, matches(), key=lambda item: (
            -item[1].score, (item[1].supervisor_name or "").casefold(), item[1].sources, item[1].record_ids))
        explained: list[RankedMatch] = []
        for index, match in best:
            terms = list(match.matched_terms)
            # Sparse evidence is needed only for returned results, not all N candidates.
            if matrix is not None:
                contributions = matrix[index].multiply(query).tocsr()
                shared = sorted(zip(contributions.indices, contributions.data),
                                key=lambda item: (-float(item[1]), str(features[item[0]])))[:10]
                terms.extend(str(features[column]) for column, value in shared if value > 0)
            explained.append(replace(match, matched_terms=tuple(dict.fromkeys(terms))))
        results.append(IdeaRanking(idea.idea_id, idea.title, len(candidates), explained, tuple(warnings)))
    return results
