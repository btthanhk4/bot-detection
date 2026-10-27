"""Offline IP geolocation: country, region, city and network operator of a visitor IP.

Uses the DB-IP Lite databases (https://db-ip.com, CC BY 4.0, monthly) stored on
the server, so no visitor address is sent to a third-party lookup service and
there is no per-request quota. City-level results are approximate: mobile
carriers often place every subscriber at a regional gateway.

    python -m api_service.geoip --refresh     # download the current month
"""

import argparse
import gzip
import ipaddress
import logging
import os
import shutil
import threading
import time
import urllib.request
from datetime import datetime, timezone
from functools import lru_cache

from api_service.config import settings

logger = logging.getLogger("bot_detection.geoip")

DATABASES = {"city": "dbip-city-lite.mmdb", "asn": "dbip-asn-lite.mmdb"}
_URL = "https://download.db-ip.com/free/dbip-{kind}-lite-{month}.mmdb.gz"
ATTRIBUTION = {"text": "IP Geolocation by DB-IP", "url": "https://db-ip.com"}
MAX_AGE_DAYS = 35

_lock = threading.Lock()
_readers = {}
_mtimes = {}


def _path(kind):
    return os.path.join(settings.GEOIP_DIR, DATABASES[kind])


def _open(path):
    """The C reader cannot open non-ASCII Windows paths; the pure-Python mmap reader can."""
    import maxminddb

    try:
        return maxminddb.open_database(path)
    except OSError:
        return maxminddb.open_database(path, mode=maxminddb.MODE_MMAP)


def _reader(kind):
    """Open (or reopen after a refresh) one database; None when it is not installed."""
    path = _path(kind)
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        return None
    with _lock:
        if _mtimes.get(kind) != mtime:
            old = _readers.pop(kind, None)
            _readers[kind] = _open(path)
            _mtimes[kind] = mtime
            lookup.cache_clear()
            if old is not None:
                try:
                    old.close()
                except Exception:
                    pass
        return _readers.get(kind)


def _name(record):
    names = (record or {}).get("names") or {}
    return names.get("en") or next(iter(names.values()), None)


@lru_cache(maxsize=8192)
def lookup(ip):
    """{"country_code", "country", "region", "city", "latitude", "longitude", "asn", "isp"} or None."""
    try:
        address = ipaddress.ip_address(str(ip or "").strip())
    except ValueError:
        return None
    if not address.is_global:
        return {"scope": "private"}
    result = {}
    try:
        city = _reader("city")
        record = city.get(str(address)) if city else None
        if record:
            country = record.get("country") or {}
            location = record.get("location") or {}
            result.update({
                "country_code": country.get("iso_code"),
                "country": _name(country),
                "region": _name((record.get("subdivisions") or [None])[0]),
                "city": _name(record.get("city")),
                "latitude": location.get("latitude"),
                "longitude": location.get("longitude"),
            })
        asn = _reader("asn")
        network = asn.get(str(address)) if asn else None
        if network:
            result.update({"asn": network.get("autonomous_system_number"),
                           "isp": network.get("autonomous_system_organization")})
    except Exception:
        logger.warning("GeoIP lookup failed", exc_info=True)
        return None
    return result or None


def attach(rows):
    """Add a "geo" field to session documents that carry a client_ip."""
    for row in rows or []:
        if isinstance(row, dict) and row.get("client_ip"):
            row["geo"] = lookup(row["client_ip"])
    return rows


def status():
    installed = {kind: os.path.exists(_path(kind)) for kind in DATABASES}
    ages = {kind: round((time.time() - os.path.getmtime(_path(kind))) / 86400, 1)
            for kind, present in installed.items() if present}
    return {"installed": installed, "age_days": ages, "attribution": ATTRIBUTION}


def _months(now=None):
    now = now or datetime.now(timezone.utc)
    previous = (now.replace(day=1).toordinal() - 1)
    last = datetime.fromordinal(previous)
    return [now.strftime("%Y-%m"), last.strftime("%Y-%m")]


def refresh(kinds=tuple(DATABASES), timeout=300):
    """Download this month's databases (last month's if not yet published); atomic replace."""
    os.makedirs(settings.GEOIP_DIR, exist_ok=True)
    updated = []
    for kind in kinds:
        target = _path(kind)
        for month in _months():
            tmp = f"{target}.{os.getpid()}.download"
            try:
                with urllib.request.urlopen(_URL.format(kind=kind, month=month), timeout=timeout) as response, \
                        gzip.GzipFile(fileobj=response) as unpacked, open(tmp, "wb") as out:
                    shutil.copyfileobj(unpacked, out, length=1 << 20)
                check = _open(tmp)
                kind_ok = "City" in check.metadata().database_type if kind == "city" else "ASN" in check.metadata().database_type
                check.close()
                if not kind_ok:
                    raise ValueError(f"unexpected database type for {kind}")
                os.replace(tmp, target)
                updated.append(f"{kind}:{month}")
                break
            except Exception as exc:
                logger.warning("GeoIP %s %s download failed: %s", kind, month, exc)
            finally:
                if os.path.exists(tmp):
                    os.remove(tmp)
    return updated


def refresh_if_stale(max_age_days=MAX_AGE_DAYS):
    """Called from the maintenance loop when auto-update is enabled."""
    stale = [kind for kind in DATABASES
             if not os.path.exists(_path(kind))
             or time.time() - os.path.getmtime(_path(kind)) > max_age_days * 86400]
    return refresh(stale) if stale else []


def main(argv=None):
    parser = argparse.ArgumentParser(description="Manage the offline GeoIP databases")
    parser.add_argument("--refresh", action="store_true", help="download the current DB-IP Lite databases")
    parser.add_argument("ip", nargs="*", help="addresses to look up")
    args = parser.parse_args(argv)
    if args.refresh:
        print("updated:", refresh() or "nothing")
    for ip in args.ip:
        print(ip, lookup(ip))
    print(status())


if __name__ == "__main__":
    main()
