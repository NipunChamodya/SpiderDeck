from __future__ import annotations

import tomllib
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
class AppConfig:
    crawl: CrawlConfig
    output: OutputConfig
    fx_enabled: bool = True
    ranking_offline_only: bool = True
    imports: ImportConfig = field(default_factory=ImportConfig)


def load_config(path: Path = CONFIG_PATH) -> AppConfig:
    with open(path, "rb") as f:
        raw = tomllib.load(f)

    return AppConfig(
        crawl=CrawlConfig(**raw.get("crawl", {})),
        output=OutputConfig(**raw.get("output", {})),
        fx_enabled=raw.get("fx", {}).get("enabled", True),
        ranking_offline_only=raw.get("ranking", {}).get("offline_only", True),
        imports=ImportConfig(**raw.get("import", {})),
    )
