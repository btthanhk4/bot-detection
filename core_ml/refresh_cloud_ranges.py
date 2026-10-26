"""Regenerate core_ml/data/cloud_ip_ranges.json from the providers' published lists.

    python -m core_ml.refresh_cloud_ranges

Only official, machine-readable publications are used; a provider whose list cannot
be fetched keeps its previous ranges so a transient outage never empties the file.
"""

import csv
import io
import ipaddress
import json
import os
import urllib.request
from datetime import datetime, timezone

OUTPUT = os.path.join(os.path.dirname(__file__), "data", "cloud_ip_ranges.json")
SOURCES = {
    "gcp": "https://www.gstatic.com/ipranges/cloud.json",
    "aws": "https://ip-ranges.amazonaws.com/ip-ranges.json",
    "oracle": "https://docs.oracle.com/en-us/iaas/tools/public_ip_ranges.json",
    "digitalocean": "https://digitalocean.com/geo/google.csv",
    "linode": "https://geoip.linode.com/",
    "vultr": "https://geofeed.constant.com/?text",
}


def _fetch(url):
    request = urllib.request.Request(url, headers={"User-Agent": "datacat-cloud-ranges/1"})
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read().decode("utf-8", "replace")


def _parse(provider, text):
    if provider == "gcp":
        data = json.loads(text)
        return [p.get("ipv4Prefix") or p.get("ipv6Prefix") for p in data["prefixes"]]
    if provider == "aws":
        data = json.loads(text)
        return [p["ip_prefix"] for p in data["prefixes"]] + [p["ipv6_prefix"] for p in data["ipv6_prefixes"]]
    if provider == "oracle":
        data = json.loads(text)
        return [entry["cidr"] for region in data["regions"] for entry in region["cidrs"]]
    # RFC 8805 geofeeds: first column is the prefix, '#' lines are comments.
    rows = csv.reader(io.StringIO(text))
    return [row[0].strip() for row in rows if row and row[0].strip() and not row[0].startswith("#")]


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
    for provider, url in SOURCES.items():
        try:
            providers[provider] = _collapse(_parse(provider, _fetch(url)))
            status[provider] = "fetched"
        except Exception as exc:  # keep the last good list for this provider
            providers[provider] = previous.get(provider, [])
            status[provider] = f"kept previous ({type(exc).__name__})"
        print(f"{provider:13s} {len(providers[provider]):6d} prefixes  {status[provider]}")
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
