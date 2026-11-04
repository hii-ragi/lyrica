import json
from pathlib import Path
import tomllib
import unittest


class ReleaseMetadataTests(unittest.TestCase):
    def test_all_product_versions_and_root_lock_entries_match(self):
        root = Path(__file__).resolve().parents[2]
        package = json.loads((root / "package.json").read_text(encoding="utf-8"))
        version = package["version"]
        lock = json.loads((root / "package-lock.json").read_text(encoding="utf-8"))
        tauri = json.loads((root / "src-tauri/tauri.conf.json").read_text(encoding="utf-8"))
        cargo = tomllib.loads((root / "src-tauri/Cargo.toml").read_text(encoding="utf-8"))
        cargo_lock = tomllib.loads((root / "src-tauri/Cargo.lock").read_text(encoding="utf-8"))
        backend = tomllib.loads((root / "backend/pyproject.toml").read_text(encoding="utf-8"))
        versions = [lock["version"], lock["packages"][""]["version"], tauri["version"],
                    cargo["package"]["version"], backend["project"]["version"],
                    next(p["version"] for p in cargo_lock["package"] if p["name"] == "lyrica")]
        self.assertTrue(all(v == version for v in versions), versions)
