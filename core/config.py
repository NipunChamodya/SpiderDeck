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
class AppConfig:
    crawl: CrawlConfig
    output: OutputConfig
    fx_enabled: bool = True
    ranking_offline_only: bool = True


def load_config(path: Path = CONFIG_PATH) -> AppConfig:
    with open(path, "rb") as f:
        raw = tomllib.load(f)

    return AppConfig(
        crawl=CrawlConfig(**raw.get("crawl", {})),
        output=OutputConfig(**raw.get("output", {})),
        fx_enabled=raw.get("fx", {}).get("enabled", True),
        ranking_offline_only=raw.get("ranking", {}).get("offline_only", True),
    )
