"""Regenerate core_ml/data/crawler_ip_ranges.json from the crawler operators' published lists.

    python -m core_ml.refresh_crawler_ranges

Search and AI crawlers name themselves in the User-Agent, and anyone can copy that string.
Their operators publish the addresses the real crawlers use; a declared crawler from one of
those addresses is verified (policy 25). Only the operators' own machine-readable lists are
used, and an operator whose lists cannot be fetched keeps its previous ranges.
"""

import ipaddress
import json
import os
import urllib.request
from datetime import datetime, timezone

OUTPUT = os.path.join(os.path.dirname(__file__), "data", "crawler_ip_ranges.json")
_GOOGLE = "https://developers.google.com/static/crawling/ipranges/"
SOURCES = {
    "google": [_GOOGLE + "common-crawlers.json", _GOOGLE + "special-crawlers.json",
               _GOOGLE + "user-triggered-fetchers.json", _GOOGLE + "user-triggered-fetchers-google.json"],
    "bing": ["https://www.bing.com/toolbox/bingbot.json"],
    "apple": ["https://search.developer.apple.com/applebot.json"],
    "openai": ["https://openai.com/gptbot.json", "https://openai.com/searchbot.json",
               "https://openai.com/chatgpt-user.json"],
    "perplexity": ["https://www.perplexity.ai/perplexitybot.json", "https://www.perplexity.ai/perplexity-user.json"],
}


def _fetch(url):
    request = urllib.request.Request(url, headers={"User-Agent": "datacat-crawler-ranges/1"})
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.loads(response.read().decode("utf-8", "replace"))


def _prefixes(document):
    return [p.get("ipv4Prefix") or p.get("ipv6Prefix") for p in document.get("prefixes", [])
            if p.get("ipv4Prefix") or p.get("ipv6Prefix")]


def _collapse(prefixes):
    networks = []
    for prefix in prefixes:
        try:
            networks.append(ipaddress.ip_network(prefix, strict=False))
        except ValueError:
            continue
    collapsed = []
    for version in (4, 6):
        collapsed += ipaddress.collapse_addresses(n for n in networks if n.version == version)
    return [str(n) for n in collapsed]


def main():
    previous = {}
    if os.path.exists(OUTPUT):
        with open(OUTPUT, encoding="utf-8") as handle:
            previous = json.load(handle).get("providers", {})
    providers, status = {}, {}
    for operator, urls in SOURCES.items():
        try:
            providers[operator] = _collapse([prefix for url in urls for prefix in _prefixes(_fetch(url))])
            if not providers[operator]:
                raise ValueError("empty list")
            status[operator] = "fetched"
        except Exception as exc:  # keep the last good list for this operator
            providers[operator] = previous.get(operator, [])
            status[operator] = f"kept previous ({type(exc).__name__})"
        print(f"{operator:11s} {len(providers[operator]):5d} prefixes  {status[operator]}")
    os.makedirs(os.path.dirname(OUTPUT), exist_ok=True)
    with open(OUTPUT, "w", encoding="utf-8") as handle:
        json.dump({
            "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            "sources": SOURCES,
            "providers": providers,
        }, handle, separators=(",", ":"))
        handle.write("\n")


if __name__ == "__main__":
    main()
