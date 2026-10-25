"""Offline robots parser with longest-match, Allow ties, wildcard and $ rules."""
from __future__ import annotations

from dataclasses import dataclass, field
from urllib.parse import quote, urlsplit, unquote_to_bytes

from security.network_policy import CollectionError, canonical_path


def _robot_path(value: str, *, pattern: bool = False) -> str:
    anchored = pattern and value.endswith("$")
    if anchored:
        value = value[:-1]
    value = quote(canonical_path(value), safe="/%*" if pattern else "/%")
    return value + ("$" if anchored else "")


def _matches(pattern: str, path: str) -> bool:
    anchored = pattern.endswith("$")
    pattern = pattern[:-1] if anchored else pattern
    parts = pattern.split("*")
    if not path.startswith(parts[0]):
        return False
    position = len(parts[0])
    if len(parts) == 1:
        return not anchored or position == len(path)
    for part in parts[1:-1]:
        found = path.find(part, position)
        if found < 0:
            return False
        position = found + len(part)
    if anchored:
        return path.endswith(parts[-1]) and len(path) - len(parts[-1]) >= position
    return path.find(parts[-1], position) >= 0


@dataclass
class _Group:
    agents: list[str] = field(default_factory=list)
    rules: list[tuple[str, bool]] = field(default_factory=list)
    delay: float = 0


class RobotsRules:
    def __init__(self, text: str, user_agent: str):
        groups: list[_Group] = []
        current = _Group()
        directives = False
        for raw in text.splitlines():
            line = raw.split("#", 1)[0].strip()
            if not line or ":" not in line:
                continue
            name, value = (part.strip() for part in line.split(":", 1))
            name = name.lower()
            if name == "user-agent":
                if directives:
                    groups.append(current)
                    current = _Group()
                    directives = False
                current.agents.append(value.lower())
            elif current.agents:
                directives = True
                if name in {"allow", "disallow"} and value:
                    if len(value) > 4096:
                        raise CollectionError("robots_rule_too_large")
                    current.rules.append((_robot_path(value, pattern=True), name == "allow"))
                elif name in {"crawl-delay", "request-rate"}:
                    try:
                        if name == "crawl-delay":
                            delay = float(value)
                        else:
                            count, seconds = value.split("/")
                            delay = float(seconds) / int(count)
                        if not 0 <= delay <= 3600:
                            raise ValueError
                        current.delay = max(current.delay, delay)
                    except (ValueError, ZeroDivisionError, OverflowError):
                        raise CollectionError("invalid_robots_rate") from None
        groups.append(current)
        token = user_agent.split("/", 1)[0].lower()
        def specificity(group: _Group) -> int:
            return max((len(agent) if agent != "*" else 0 for agent in group.agents
                        if agent == "*" or agent == token), default=-1)
        strongest = max((specificity(group) for group in groups), default=-1)
        selected = [group for group in groups if strongest >= 0 and specificity(group) == strongest]
        self.rules = [rule for group in selected for rule in group.rules]
        self.delay = max((group.delay for group in selected), default=0)

    def allows(self, url: str) -> bool:
        path = _robot_path(urlsplit(url).path or "/")
        matches = [(len(unquote_to_bytes(pattern.replace("*", "").removesuffix("$"))), allowed)
                   for pattern, allowed in self.rules if _matches(pattern, path)]
        return max(matches, default=(-1, True))[1]
