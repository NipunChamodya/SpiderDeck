"""Bounded lexical scores, not probabilities or source-quality judgments."""
from __future__ import annotations

import math
from collections import Counter
from dataclasses import asdict, dataclass
from urllib.parse import unquote, urlsplit

from core.text import tokenize
from research.models import ResearchProject

_STOP = set('a an the of in on and or to for with using use based study research investigating'.split())
NOTICE = 'Normalized heuristic relevance, not probability, completeness or evidence quality.'


def suggest_keywords(title: str) -> tuple[str, ...]:
    """Literal title tokens only; user reviews these suggestions, not inferred facts."""
    return tuple(dict.fromkeys(token for token in tokenize(title) if token not in _STOP))[:20]


def _key(text: str) -> str:
    return '\x00' + '\x00'.join(tokenize(text)) + '\x00'


@dataclass(frozen=True)
class Relevance:
    score: float
    matched: tuple[str, ...]
    missing: tuple[str, ...]
    excluded_matches: tuple[str, ...]
    components: dict[str, float]
    decision: str
    explanation: str
    truncated: bool = False
    notice: str = NOTICE

    def to_dict(self) -> dict:
        return asdict(self)


class ResearchProfile:
    def __init__(self, project: ResearchProject):
        self.project = project
        terms = project.keywords or suggest_keywords(project.title)
        self.terms = tuple(term for term in terms if tokenize(term))
        self.keys = tuple(_key(term) for term in self.terms)
        self.exclusions = tuple((term, _key(term)) for term in project.excluded if tokenize(term))
        self.query = Counter(tokenize(' '.join((project.title, project.description, *self.terms))))
        self.threshold = project.settings[project.mode + '_threshold']

    def score(self, title: str, text: str, headings: tuple[str, ...] = ()) -> Relevance:
        cap = self.project.settings['max_scoring_chars']
        truncated = len(text) > cap
        body = text[:cap]
        title_key, body_key, heading_key = _key(title[:1000]), _key(body), _key(' '.join(headings)[:10000])
        count = max(1, len(self.terms))
        matches = tuple(term for term, key in zip(self.terms, self.keys)
                        if key in body_key or key in title_key or key in heading_key)
        title_coverage = sum(key in title_key for key in self.keys) / count
        heading_coverage = sum(key in heading_key for key in self.keys) / count
        coverage = sum(key in body_key for key in self.keys) / count
        phrases = [(term, key) for term, key in zip(self.terms, self.keys) if len(tokenize(term)) > 1]
        phrase_coverage = (sum(key in body_key for _, key in phrases) / len(phrases)
                           if phrases else coverage)
        document = Counter(tokenize(body))
        dot = sum(value * document[token] for token, value in self.query.items())
        norm = math.sqrt(sum(v*v for v in self.query.values()) * sum(v*v for v in document.values()))
        cosine = dot / norm if norm else 0.0
        excluded = tuple(term for term, key in self.exclusions if key in body_key or key in title_key)
        penalty = min(50.0, 25.0 * len(excluded))
        # Coverage/phrase signals correlate; their total weight is bounded at .65.
        # Title and headings supply the remaining .25; cosine contributes .10.
        components = {'title': title_coverage, 'headings': heading_coverage, 'coverage': coverage,
                      'phrase': phrase_coverage, 'cosine': cosine, 'exclusion_penalty': penalty}
        score = round(max(0, min(100, 100 * (.15*title_coverage + .10*heading_coverage +
                     .45*coverage + .20*phrase_coverage + .10*cosine) - penalty)), 4)
        decision = 'review' if truncated else 'relevant' if score >= self.threshold else 'low relevance'
        reason = (f'Matched {len(matches)} of {len(self.terms)} reviewed concepts; '
                  f'Body concept coverage {coverage:.0%}, title coverage {title_coverage:.0%}; '
                  f'{len(excluded)} excluded-topic signals. {self.project.mode.title()} threshold {self.threshold:g}.')
        if truncated:
            reason += f' Only the first {cap} characters were scored; retained for manual review.'
        return Relevance(score, matches, tuple(t for t in self.terms if t not in matches),
                         excluded, components, decision, reason, truncated)

    def link_priority(self, url: str, anchor: str = '', context: str = '', parent_score: float = 0) -> float:
        path = unquote(urlsplit(url).path)[:2000]
        return round(.45*self.score('',anchor[:500]).score + .35*self.score('',path).score +
                     .10*self.score('',context[:1000]).score + .10*parent_score,6)

    def explore(self, page_score: float, low_hops: int, link_priority: float) -> bool:
        if self.project.mode == 'strict':
            return page_score >= self.threshold and link_priority >= 10
        return page_score >= self.threshold or link_priority >= 15 or low_hops <= (1 if self.project.mode == 'balanced' else 2)
