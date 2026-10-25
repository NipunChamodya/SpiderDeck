"""Read-only configuration inspection; never opens or migrates a database."""
from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from core.config import AppConfig
from ui.display import terminal_text


def as_json(config: AppConfig) -> str:
    # ASCII JSON escapes terminal controls and bidirectional formatting characters.
    return json.dumps(asdict(config), ensure_ascii=True, sort_keys=True, indent=2, allow_nan=False)


def show(config: AppConfig, config_path: Path, root: Path) -> None:
    print("Settings (read-only)")
    print("Config: " + terminal_text(str(config_path), 500))
    output = root / Path(config.output.dir).expanduser()
    print("Output: " + terminal_text(str(output), 500))
    print("Database: opens only when a data workflow needs it.")
    print("\nLocal imports")
    print(f"  File limit: {config.imports.max_file_bytes / 1024**2:g} MiB; records: {config.imports.max_records}")
    print("\nAuthorized web collection")
    print("  Exact hosts: " + terminal_text(", ".join(config.crawl.allowed_domains) or "(none configured)", 1000))
    print(f"  Pages: {config.crawl.max_pages}; depth: {config.crawl.max_depth}; delay: {config.crawl.delay_seconds:g}s")
    print(f"  Timeout: {config.crawl.timeout_seconds:g}s; transport attempts: {config.crawl.max_requests}")
    print("  Robots enforced; every run requires explicit target approval.")
    print("\nOffline ranking")
    print(f"  Weights: text={config.ranking.text_weight:g}, keyword={config.ranking.keyword_weight:g}, domain={config.ranking.domain_weight:g}")
    print(f"  Comparison limit: {config.ranking.max_records} records; top {config.ranking.top_k} per idea")
    print("\nEdit the TOML file and restart to change saved settings. No settings were written.")
