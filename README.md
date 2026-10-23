# SpiderDeck

An authorized-access data collection and ranking tool. SpiderDeck only
collects from sources you're permitted to access — it will not bypass
view-only restrictions, paywalls, logins, or download/copy/print blocks.
If a source is restricted, it stops and tells you to request an export.

This is **Phase 1** of the build: installer, menu, config, logging, and the
security module. Crawling, file reading, and ranking are stubbed in the menu
and get filled in during later phases.

## Setup (macOS, zsh)

```zsh
cd ~/supervisor-finder
mkdir -p spiderdeck
# copy all SpiderDeck files into ~/supervisor-finder/spiderdeck
cd spiderdeck

python3 spiderdeck.py --setup
```

This creates a `.venv`, asks before installing packages, and tells you the
exact command to re-run afterward. Then:

```zsh
source .venv/bin/activate
python spiderdeck.py
```

On first real run it will ask whether to install Playwright's browsers
(Chromium, Firefox) — say yes if you plan to use the browser-based options.

## Run the security self-check any time

```zsh
python spiderdeck.py --security-check
```

This tests SpiderDeck's own input validators (path traversal, SSRF,
shell-injection guards) against a battery of malicious-looking inputs.
It does not touch any external target.

## Disable the visual effects

```zsh
python spiderdeck.py --no-fx
```

## Project layout

```
spiderdeck.py       entry point: bootstrap, self-check, menu loop
core/                config loading, logging
security/            validators + self-check suite (read this first)
handlers/            web / file input handlers (Phase 2–3)
rank/                TF-IDF / embedding ranking (Phase 5)
fx/                  cosmetic terminal effects only — never slows logic
ui/                  CLI menu (questionary)
tests/               pytest unit tests
config.toml          domain allowlist, crawl limits, feature toggles
logs/                audit log of what was accessed and when
output/              all collected data is written here, nowhere else
```

## Before you crawl anything

Open `config.toml` and add the domains you're authorized to collect from to
`allowed_domains`. Requests to domains not on this list, or to private/
internal IP ranges, are rejected by `security/validators.py` regardless of
what a page tries to redirect you to.

## On the Google Sheets restriction

If a sheet shows "Security limitations" / view-only with downloads
disabled, SpiderDeck's Google Sheets handler (Phase 3) will detect this and
stop rather than attempting screen-reader scraping or OCR of the grid — ask
the sheet owner for an export instead.

## Run tests

```zsh
pip install pytest
pytest
```
