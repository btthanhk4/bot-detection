import hashlib
import json
import zipfile

import pytest

from pilot.build_release import build_release


def fixture(tmp_path):
    root = tmp_path / "source"
    for name, text in {
        "collector/dist/bot-collector.js": "verified-sdk", "pilot/embed.html": "snippet",
        "pilot/README.md": "guide", "api_service/main.py": "source",
        "api_service/.env": "never-ship", ".env.pilot": "never-ship",
        "var/raw.json": "never-ship", "pilot/node_modules/package/data": "never-ship",
        "core_ml/__pycache__/compiled.pyc": "never-ship", ".env.pilot.example": "sample",
    }.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    evidence = tmp_path / "evidence.json"
    evidence.write_text(json.dumps({"verified": True, "collector_sha256": hashlib.sha256(b"verified-sdk").hexdigest()}))
    return root, evidence


def test_source_release_excludes_credentials_raw_data_and_dependencies(tmp_path):
    root, evidence = fixture(tmp_path)
    output = tmp_path / "source.zip"
    result = build_release(root, output, evidence, source=True)
    with zipfile.ZipFile(output) as archive:
        assert "never-ship" not in "".join(archive.read(name).decode() for name in archive.namelist())
        assert ".env.pilot.example" in archive.namelist()
        manifest = json.loads(archive.read("release-manifest.json"))
        assert all(hashlib.sha256(archive.read(name)).hexdigest() == digest
                   for name, digest in manifest["files"].items())
    assert result["sha256"] == hashlib.sha256(output.read_bytes()).hexdigest()


def test_embed_release_is_small_and_requires_matching_browser_evidence(tmp_path):
    root, evidence = fixture(tmp_path)
    output = tmp_path / "embed.zip"
    build_release(root, output, evidence)
    with zipfile.ZipFile(output) as archive:
        assert set(archive.namelist()) == {"bot-collector.js", "embed.html", "README.md",
                                           "verification.json", "release-manifest.json"}
    with pytest.raises(FileExistsError):
        build_release(root, output, evidence)
    (root / "collector/dist/bot-collector.js").write_text("modified-sdk")
    with pytest.raises(ValueError, match="does not match"):
        build_release(root, tmp_path / "wrong.zip", evidence)


def test_release_output_inside_source_is_rejected(tmp_path):
    root, evidence = fixture(tmp_path)
    with pytest.raises(ValueError, match="outside"):
        build_release(root, root / "release.zip", evidence)
