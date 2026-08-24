from __future__ import annotations

import importlib.util
import json
import re
import shutil
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PIPELINE_PATH = ROOT / "skills" / "paper-lens" / "scripts" / "paper_pipeline.py"
SPEC = importlib.util.spec_from_file_location("project_pipeline", PIPELINE_PATH)
pipeline = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(pipeline)


class ProjectMetadataTests(unittest.TestCase):
    def test_manifest_has_public_oss_identity(self) -> None:
        manifest = json.loads(
            (ROOT / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8")
        )
        self.assertEqual(manifest["license"], "Apache-2.0")
        self.assertEqual(
            manifest["repository"], "https://github.com/YSQ-boop/paper-lens"
        )
        self.assertEqual(manifest["author"]["name"], "YSQ-boop")
        self.assertTrue((ROOT / "LICENSE").is_file())
        self.assertEqual(manifest["version"].split("+", 1)[0], pipeline.PLUGIN_VERSION)

    def test_application_answers_stay_within_form_budget(self) -> None:
        worksheet = (ROOT / "docs" / "codex-for-oss-application.md").read_text(
            encoding="utf-8"
        )
        headings = (
            "Project description",
            "Why Codex credits help",
            "Public impact and maintenance",
        )
        for heading in headings:
            match = re.search(
                rf"^## {re.escape(heading)}\n\n(.*?)(?=\n\n## )", worksheet, re.M | re.S
            )
            self.assertIsNotNone(match, heading)
            answer = match.group(1).strip()
            self.assertLessEqual(
                len(answer), 500, f"{heading} has {len(answer)} characters"
            )
            self.assertNotIn("TODO", answer)

    def test_public_example_satisfies_quick_contract(self) -> None:
        example = ROOT / "examples" / "1706.03762v7"
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory) / "example"
            shutil.copytree(example, workspace)
            result = pipeline.validate_workspace(workspace, "quick")
        self.assertTrue(result["ok"], result)


if __name__ == "__main__":
    unittest.main()
