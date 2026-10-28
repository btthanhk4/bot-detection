"""Server-side network facts: is the client address inside a public cloud range?

Browsers driven from cloud VMs (headless crawlers, automation farms) connect from the
providers' published ranges; home and mobile users do not. VPN exits can also sit in
these ranges, so this is corroborating evidence only and never decides alone.

Policy 25: the same lookup over the crawler operators' published ranges
(``crawler_ip_ranges.json``) tells a real Googlebot from a script that copied its name.
"""

import bisect
import ipaddress
import json
import os
from functools import lru_cache

RANGES_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "cloud_ip_ranges.json")
CRAWLER_RANGES_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "crawler_ip_ranges.json")


@lru_cache(maxsize=1)
def _index():
    return _table(RANGES_PATH)


@lru_cache(maxsize=1)
def _crawler_index():
    return _table(CRAWLER_RANGES_PATH)


def _table(path):
    try:
        with open(path, encoding="utf-8") as handle:
            providers = json.load(handle).get("providers", {})
    except (OSError, ValueError):
        providers = {}
    tables = {4: [], 6: []}
    for provider, prefixes in providers.items():
        for prefix in prefixes:
            try:
                network = ipaddress.ip_network(prefix, strict=False)
            except ValueError:
                continue
            tables[network.version].append(
                (int(network.network_address), int(network.broadcast_address), provider)
            )
    for version in tables:
        tables[version].sort()
    return {version: ([row[0] for row in rows], rows) for version, rows in tables.items()}


def _lookup(index, address):
    try:
        ip = ipaddress.ip_address(str(address).strip())
    except ValueError:
        return None
    if not ip.is_global:
        return None
    starts, rows = index[ip.version]
    position = bisect.bisect_right(starts, int(ip)) - 1
    if position >= 0 and rows[position][0] <= int(ip) <= rows[position][1]:
        return rows[position][2]
    return None


def cloud_provider(address) -> str | None:
    """Return the provider name when ``address`` is in a published cloud range."""
    return _lookup(_index(), address)


def crawler_operator(address) -> str | None:
    """Return the operator (google, bing, apple, openai, perplexity) whose published
    crawler ranges contain ``address``."""
    return _lookup(_crawler_index(), address)
