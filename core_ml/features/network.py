"""Server-side network facts: is the client address inside a public cloud range?

Browsers driven from cloud VMs (headless crawlers, automation farms) connect from the
providers' published ranges; home and mobile users do not. VPN exits can also sit in
these ranges, so this is corroborating evidence only and never decides alone.
"""

import bisect
import ipaddress
import json
import os
from functools import lru_cache

RANGES_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "cloud_ip_ranges.json")


@lru_cache(maxsize=1)
def _index():
    try:
        with open(RANGES_PATH, encoding="utf-8") as handle:
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


def cloud_provider(address) -> str | None:
    """Return the provider name when ``address`` is in a published cloud range."""
    try:
        ip = ipaddress.ip_address(str(address).strip())
    except ValueError:
        return None
    if not ip.is_global:
        return None
    starts, rows = _index()[ip.version]
    position = bisect.bisect_right(starts, int(ip)) - 1
    if position >= 0 and rows[position][0] <= int(ip) <= rows[position][1]:
        return rows[position][2]
    return None
