"""Offline IP geolocation: lookups, missing databases, refresh and API fields."""

import gzip
import io

import pytest

from api_service import geoip


class FakeReader:
    def __init__(self, records, database_type="DBIP-City-Lite"):
        self.records = records
        self.database_type = database_type

    def get(self, ip):
        return self.records.get(ip)

    def metadata(self):
        return type("Meta", (), {"database_type": self.database_type})()

    def close(self):
        pass


CITY = {"42.113.160.186": {
    "city": {"names": {"en": "Tây Đằng"}},
    "country": {"iso_code": "VN", "names": {"en": "Vietnam", "fr": "Viêt Nam"}},
    "subdivisions": [{"names": {"en": "Hanoi"}}],
    "location": {"latitude": 21.1981, "longitude": 105.422},
}}
ASN = {"42.113.160.186": {"autonomous_system_number": 18403, "autonomous_system_organization": "FPT Telecom Company"}}


@pytest.fixture
def readers(monkeypatch):
    fakes = {"city": FakeReader(CITY), "asn": FakeReader(ASN, "DBIP-ASN-Lite")}
    monkeypatch.setattr(geoip, "_reader", lambda kind: fakes.get(kind))
    geoip.lookup.cache_clear()
    yield fakes
    geoip.lookup.cache_clear()


def test_lookup_returns_place_and_network(readers):
    assert geoip.lookup("42.113.160.186") == {
        "country_code": "VN", "country": "Vietnam", "region": "Hanoi", "city": "Tây Đằng",
        "latitude": 21.1981, "longitude": 105.422, "asn": 18403, "isp": "FPT Telecom Company",
    }


def test_private_unknown_and_invalid_addresses(readers):
    assert geoip.lookup("192.168.1.5") == {"scope": "private"}
    assert geoip.lookup("127.0.0.1") == {"scope": "private"}
    assert geoip.lookup("8.8.4.4") is None, "not in the database"
    assert geoip.lookup("not-an-ip") is None and geoip.lookup(None) is None


def test_missing_databases_mean_no_location(monkeypatch, tmp_path):
    monkeypatch.setattr(geoip.settings, "GEOIP_DIR", str(tmp_path))
    geoip.lookup.cache_clear()
    assert geoip.lookup("42.113.160.186") is None
    assert geoip.status()["installed"] == {"city": False, "asn": False}
    rows = geoip.attach([{"client_ip": "42.113.160.186"}, {"sessionId": "no-ip"}])
    assert rows[0]["geo"] is None and "geo" not in rows[1]


def test_refresh_falls_back_to_last_month_and_replaces_atomically(monkeypatch, tmp_path):
    monkeypatch.setattr(geoip.settings, "GEOIP_DIR", str(tmp_path))
    monkeypatch.setattr(geoip, "_months", lambda now=None: ["2026-11", "2026-10"])
    requested = []

    def fake_urlopen(request, timeout):
        url = request.full_url
        requested.append(url)
        assert not request.get_header("User-agent", "").startswith("Python-urllib"), "DB-IP refuses it (403)"
        if "2026-11" in url:
            raise OSError("404 not published yet")
        return io.BytesIO(gzip.compress(b"mmdb-bytes"))

    def fake_open(path):
        return FakeReader({}, "DBIP-ASN-Lite" if "asn" in path else "DBIP-City-Lite")

    monkeypatch.setattr(geoip.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(geoip, "_open", fake_open)
    assert geoip.refresh() == ["city:2026-10", "asn:2026-10"]
    assert (tmp_path / "dbip-city-lite.mmdb").read_bytes() == b"mmdb-bytes"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["dbip-asn-lite.mmdb", "dbip-city-lite.mmdb"], "no temp files"
    assert all("download.db-ip.com/free/" in url for url in requested)
    assert geoip.refresh_if_stale() == [], "fresh files are not downloaded again"


def test_refresh_rejects_a_wrong_database(monkeypatch, tmp_path):
    monkeypatch.setattr(geoip.settings, "GEOIP_DIR", str(tmp_path))
    monkeypatch.setattr(geoip, "_months", lambda now=None: ["2026-10"])
    monkeypatch.setattr(geoip.urllib.request, "urlopen", lambda request, timeout: io.BytesIO(gzip.compress(b"x")))
    monkeypatch.setattr(geoip, "_open", lambda path: FakeReader({}, "Something-Else"))
    assert geoip.refresh(("city",)) == []
    assert not list(tmp_path.iterdir())


def test_traffic_and_detail_carry_location(readers, monkeypatch):
    from fastapi.testclient import TestClient

    from api_service import main

    monkeypatch.setattr(main.settings, "READ_TOKEN", "read-secret")
    monkeypatch.setattr(main, "traffic_page", lambda limit, before, site_filter=None: {
        "sessions": [{"sessionId": "s1", "client_ip": "42.113.160.186"}], "returned": 1, "total": 1, "next_before": None})
    response = TestClient(main.app).get("/api/v1/research/traffic", headers={"X-Read-Token": "read-secret"})
    assert response.status_code == 200
    body = response.json()
    assert body["sessions"][0]["geo"]["isp"] == "FPT Telecom Company"
    assert body["sessions"][0]["geo"]["region"] == "Hanoi"
    assert body["geoip_attribution"]["url"] == "https://db-ip.com"
