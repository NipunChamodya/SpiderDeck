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
    timeout_seconds: float = 10.0
    max_retries: int = 2
    max_redirects: int = 3
    max_requests: int = 200
    max_frontier: int = 1000
    max_response_bytes: int = 2 * 1024 * 1024
    max_total_bytes: int = 10 * 1024 * 1024
    max_records: int = 10000
    max_duration_seconds: float = 120.0

    def __post_init__(self) -> None:
        for name in ("max_pages", "max_requests", "max_frontier", "max_response_bytes", "max_total_bytes", "max_records"):
            if type(getattr(self, name)) is not int or getattr(self, name) <= 0:
                raise ValueError("Crawl resource limits must be positive integers.")
        for name in ("max_depth", "max_retries", "max_redirects"):
            if type(getattr(self, name)) is not int or not 0 <= getattr(self, name) <= 100:
                raise ValueError("Crawl depth/retry/redirect limits must be integers from 0 to 100.")
        for name in ("delay_seconds", "timeout_seconds", "max_duration_seconds"):
            value = getattr(self, name)
            if type(value) not in (int, float) or not 0 < value <= 3600 or not math.isfinite(value):
                raise ValueError("Crawl timing values must be finite and positive, up to 3600 seconds.")
        if (not isinstance(self.allowed_domains, list)
                or any(not isinstance(domain, str) for domain in self.allowed_domains)):
            raise ValueError("Crawl domains must be a list of exact hostnames.")
        if (not isinstance(self.user_agent, str) or not self.user_agent.startswith("SpiderDeckBot/")
                or len(self.user_agent) > 200 or any(not 32 <= ord(char) < 127 for char in self.user_agent)):
            raise ValueError("Use an accurate printable SpiderDeckBot/ User-Agent.")
        if self.respect_robots_txt is not True or self.allow_localhost is not False:
            raise ValueError("Web collection requires robots handling and prohibits local destinations.")


@dataclass
class OutputConfig:
    dir: str = "output"

    def __post_init__(self) -> None:
        if not isinstance(self.dir, str) or not self.dir.strip() or "\x00" in self.dir:
            raise ValueError("Output directory must be a nonempty path string.")


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

    def __post_init__(self) -> None:
        if type(self.fx_enabled) is not bool or type(self.ranking_offline_only) is not bool:
            raise ValueError("Effects and offline-only flags must be TOML booleans.")


def load_config(path: Path = CONFIG_PATH) -> AppConfig:
    with open(path, "rb") as f:
        raw = tomllib.load(f)
    for name in ("crawl", "output", "import", "ranking", "fx"):
        if not isinstance(raw.get(name, {}), dict):
            raise ValueError("Configuration sections must be TOML tables.")

    return AppConfig(
        crawl=CrawlConfig(**raw.get("crawl", {})),
        output=OutputConfig(**raw.get("output", {})),
        fx_enabled=raw.get("fx", {}).get("enabled", True),
        ranking_offline_only=raw.get("ranking", {}).get("offline_only", True),
        imports=ImportConfig(**raw.get("import", {})),
        ranking=RankingConfig(**{key: value for key, value in raw.get("ranking", {}).items()
                                 if key != "offline_only"}),
    )
