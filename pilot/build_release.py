"""Build teacher/operator archives without runtime data, credentials or dependencies."""

import argparse
import hashlib
import json
import subprocess
import zipfile
from datetime import datetime, timezone
from pathlib import Path


SOURCE_DIRS = {"api_service", "core_ml", "collector", "pilot", "tests", "docs", "simulator", ".github"}
SOURCE_ROOT_FILES = {"README.md", "EXPERIMENT_REPORT.md", "Dockerfile", ".dockerignore", ".gitignore",
                     ".env.example", ".env.pilot.example", "docker-compose.yml", "docker-compose.pilot.yml",
                     "requirements.txt", "requirements-dev.txt", "requirements-colab.txt", "LICENSE"}
EXCLUDED_PARTS = {"node_modules", "__pycache__", ".git", ".gitnexus", "var", ".pytest_cache", ".ruff_cache"}


def build_release(root, output, evidence_path, *, source=False):
    root, output = Path(root).resolve(), Path(output).resolve()
    if output.is_relative_to(root):
        raise ValueError("Keep release archives outside the source repository")
    evidence = json.loads(Path(evidence_path).read_text(encoding="utf-8"))
    sdk = root / "collector/dist/bot-collector.js"
    sdk_hash = hashlib.sha256(sdk.read_bytes()).hexdigest()
    if evidence.get("verified") is not True or evidence.get("collector_sha256") != sdk_hash:
        raise ValueError("Release SDK does not match successfully verified browser evidence")
    if source:
        files = {}
        for path in root.rglob("*"):
            relative = path.relative_to(root)
            if (not path.is_file() or path.is_symlink() or EXCLUDED_PARTS.intersection(relative.parts)
                    or path.suffix in {".pyc", ".pyo", ".zip", ".sqlite"}
                    or (path.name.startswith(".env") and path.name not in {".env.example", ".env.pilot.example"})):
                continue
            if relative.parts[0] in SOURCE_DIRS or relative.as_posix() in SOURCE_ROOT_FILES:
                files[relative.as_posix()] = path.read_bytes()
    else:
        files = {"bot-collector.js": sdk.read_bytes(),
                 "embed.html": (root / "pilot/embed.html").read_bytes(),
                 "README.md": (root / "pilot/README.md").read_bytes()}
    files["verification.json"] = json.dumps(evidence, indent=2).encode("utf-8")
    hashes = {name: hashlib.sha256(data).hexdigest() for name, data in sorted(files.items())}
    revision = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True, check=False)
    manifest = {
        "release": "datacat-pilot-1.1.0", "created_at": datetime.now(timezone.utc).isoformat(),
        "kind": "operator-source" if source else "teacher-embed",
        "api_configuration_required": True, "website_acceptance_required": True,
        "git_head": revision.stdout.strip() if revision.returncode == 0 else None,
        "source": "current_worktree_not_necessarily_git_head",
        "snapshot_sha256": hashlib.sha256(json.dumps(hashes, sort_keys=True).encode()).hexdigest(),
        "files": hashes,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "x", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, data in sorted(files.items()):
            archive.writestr(name, data)
        archive.writestr("release-manifest.json", json.dumps(manifest, indent=2))
    with zipfile.ZipFile(output) as archive:
        if archive.testzip() is not None:
            raise ValueError("Generated release archive failed its CRC verification")
    return {"path": str(output), "files": len(files), "bytes": output.stat().st_size,
            "sha256": hashlib.sha256(output.read_bytes()).hexdigest()}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--source", action="store_true")
    args = parser.parse_args()
    print(json.dumps(build_release(Path(__file__).resolve().parents[1], args.output,
                                   args.evidence, source=args.source)))
