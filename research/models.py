from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from uuid import uuid4

from rank.models import clean_text

MODES = ('strict', 'balanced', 'discovery')
DEFAULT_SETTINGS = {'strict_threshold': 60.0, 'balanced_threshold': 35.0,
                    'discovery_threshold': 20.0, 'max_scoring_chars': 200000,
                    'search_mode': 'literal'}


def now() -> str:
    return datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')


@dataclass(frozen=True)
class ResearchProject:
    title: str
    description: str = ''
    keywords: tuple[str, ...] = ()
    excluded: tuple[str, ...] = ()
    mode: str = 'balanced'
    settings: dict = field(default_factory=lambda: dict(DEFAULT_SETTINGS))
    project_id: str = field(default_factory=lambda: uuid4().hex)
    created_at: str = field(default_factory=now)
    updated_at: str = field(default_factory=now)
    archived: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, 'title', clean_text(self.title, 300))
        object.__setattr__(self, 'description', clean_text(self.description, 20000))
        if not self.title or self.mode not in MODES:
            raise ValueError('Use a title and Strict, Balanced or Discovery mode.')
        if len(self.project_id) != 32 or any(c not in '0123456789abcdef' for c in self.project_id):
            raise ValueError('Invalid project identifier.')
        for name in ('keywords', 'excluded'):
            terms = getattr(self, name)
            if not isinstance(terms, (tuple, list)) or len(terms) > 100:
                raise ValueError('Use at most 100 research terms.')
            unique = {}
            for term in terms:
                term = clean_text(term, 200)
                if term:
                    unique.setdefault(term.casefold(), term)
            object.__setattr__(self, name, tuple(unique.values()))
        settings = {**DEFAULT_SETTINGS, **self.settings}
        if set(settings) != set(DEFAULT_SETTINGS):
            raise ValueError('Unknown project setting.')
        for key in ('strict_threshold', 'balanced_threshold', 'discovery_threshold'):
            value = settings[key]
            if type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= 100:
                raise ValueError('Thresholds must be finite numbers from 0 to 100.')
        if not settings['discovery_threshold'] <= settings['balanced_threshold'] <= settings['strict_threshold']:
            raise ValueError('Discovery threshold must not exceed Balanced or Strict.')
        if type(settings['max_scoring_chars']) is not int or not 1000 <= settings['max_scoring_chars'] <= 2000000:
            raise ValueError('Scoring limit must be between 1000 and 2000000 characters.')
        if settings['search_mode'] not in {'literal', 'fts'}:
            raise ValueError('Search mode must be literal or fts.')
        object.__setattr__(self, 'settings', settings)
        for timestamp in (self.created_at, self.updated_at):
            if datetime.fromisoformat(timestamp).tzinfo is None:
                raise ValueError('Project timestamps must have a timezone.')
        if type(self.archived) is not bool:
            raise ValueError('Archive state must be a boolean.')

    def to_dict(self) -> dict:
        return asdict(self)


def profile_settings(project: ResearchProject) -> dict:
    """Only fields that affect topic meaning/scoring, not collection timestamps."""
    return {key:value for key,value in project.to_dict().items()
            if key in {'title','description','keywords','excluded','mode','settings'}}


def profile_fingerprint(project: ResearchProject) -> str:
    import hashlib,json
    return hashlib.sha256(json.dumps(profile_settings(project),ensure_ascii=False,sort_keys=True,
        separators=(',',':'),allow_nan=False).encode('utf-8')).hexdigest()
