from __future__ import annotations

import tomllib
import math
from dataclasses import dataclass, field
from pathlib import Path

CONFIG_PATH = Path(__file__).resolve().parent.parent / "config.toml"


@dataclass
class CrawlConfig:
    allowed_domains: list[str] = field(default_factory=list)
    max_pages: int = 50
    max_depth: int = 2
    delay_seconds: float = 1.5
    respect_robots_txt: bool = True
    user_agent: str = "SpiderDeckBot/0.1"
    allow_localhost: bool = False


@dataclass
class OutputConfig:
    dir: str = "output"


@dataclass
class ImportConfig:
    max_file_bytes: int = 20 * 1024 * 1024
    max_expanded_bytes: int = 100 * 1024 * 1024
    max_archive_members: int = 5000
    max_records: int = 20000
    max_text_chars: int = 10_000_000
    max_pdf_pages: int = 500
    min_pdf_text_chars: int = 10

    def __post_init__(self) -> None:
        for value in vars(self).values():
            if type(value) is not int or value <= 0:
                raise ValueError("Import limits must be positive integers.")


@dataclass
class RankingConfig:
    text_weight: float = 1.0
    keyword_weight: float = 0.0
    domain_weight: float = 0.0
    max_records: int = 5000
    max_total_chars: int = 2_000_000
    max_chars_per_record: int = 20000
    max_features: int = 30000
    max_ideas: int = 20
    top_k: int = 10
    name_fields: list[str] = field(default_factory=lambda: [
        "supervisor name", "supervisor", "name", "full name", "academic name"])
    expertise_fields: list[str] = field(default_factory=lambda: [
        "expertise", "research interests", "research areas", "specialization", "research expertise"])
    domain_fields: list[str] = field(default_factory=lambda: ["domain", "category", "research domain"])
    affiliation_fields: list[str] = field(default_factory=lambda: ["affiliation", "university", "institution"])
    email_fields: list[str] = field(default_factory=lambda: ["email", "email address"])

    def __post_init__(self) -> None:
        weights = (self.text_weight, self.keyword_weight, self.domain_weight)
        if (any(type(value) not in (int, float) or not 0 <= value <= 1000
                or not math.isfinite(value) for value in weights) or sum(weights) == 0):
            raise ValueError("Ranking weights must be finite, nonnegative, at most 1000, with a positive sum.")
        for name in ("max_records", "max_total_chars", "max_chars_per_record", "max_features", "max_ideas", "top_k"):
            value = getattr(self, name)
            if type(value) is not int or value <= 0:
                raise ValueError("Ranking limits must be positive integers.")
        for name in ("name_fields", "expertise_fields", "domain_fields", "affiliation_fields", "email_fields"):
            values = getattr(self, name)
            if (not isinstance(values, list) or len(values) > 100
                    or any(not isinstance(value, str) or not value.strip() or len(value) > 200 for value in values)):
                raise ValueError("Ranking field aliases must be lists of nonempty strings (up to 100).")


@dataclass
class AppConfig:
    crawl: CrawlConfig
    output: OutputConfig
    fx_enabled: bool = True
    ranking_offline_only: bool = True
    imports: ImportConfig = field(default_factory=ImportConfig)
    ranking: RankingConfig = field(default_factory=RankingConfig)


def load_config(path: Path = CONFIG_PATH) -> AppConfig:
    with open(path, "rb") as f:
        raw = tomllib.load(f)

    return AppConfig(
        crawl=CrawlConfig(**raw.get("crawl", {})),
        output=OutputConfig(**raw.get("output", {})),
        fx_enabled=raw.get("fx", {}).get("enabled", True),
        ranking_offline_only=raw.get("ranking", {}).get("offline_only", True),
        imports=ImportConfig(**raw.get("import", {})),
        ranking=RankingConfig(**{key: value for key, value in raw.get("ranking", {}).items()
                                 if key != "offline_only"}),
    )
