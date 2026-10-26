"""Published cloud ranges as corroborating network evidence (policy 14)."""

import pytest

from core_ml.features import network
from core_ml.features.network import cloud_provider


@pytest.mark.parametrize("address, provider", [
    ("34.90.165.170", "gcp"),          # zero-mouse crawler seen on 2026-10-26
    ("152.42.205.62", "digitalocean"),  # this deployment's own droplet
    ("2600:1f18::1", "aws"),
])
def test_published_cloud_addresses_are_recognised(address, provider):
    assert cloud_provider(address) == provider


@pytest.mark.parametrize("address", [
    "1.53.91.243", "222.252.97.118", "42.113.160.186", "183.81.123.185",  # real visitors (VN ISPs)
    "127.0.0.1", "10.0.0.1", "192.168.1.5", "::1", "not-an-ip", "", None,
])
def test_residential_private_and_invalid_addresses_are_not(address):
    assert cloud_provider(address) is None


def test_missing_data_file_disables_the_signal(monkeypatch, tmp_path):
    monkeypatch.setattr(network, "RANGES_PATH", str(tmp_path / "missing.json"))
    network._index.cache_clear()
    try:
        assert cloud_provider("34.90.165.170") is None
    finally:
        network._index.cache_clear()
