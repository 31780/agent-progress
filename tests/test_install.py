import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("installer", Path(__file__).resolve().parents[1] / "install.py")
i = importlib.util.module_from_spec(spec)
spec.loader.exec_module(i)


class InstallTests(unittest.TestCase):
    def test_mcp_bridge_is_optional_preserved_on_update_and_removed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            env = {"XDG_CONFIG_HOME": str(root / "config"), "XDG_DATA_HOME": str(root / "share"),
                   "XDG_STATE_HOME": str(root / "state"), "CODEX_HOME": str(root / "codex")}
            app = root / "share/omarchy-agent-progress"
            with patch.dict(os.environ, env), patch.object(i.subprocess, "run"), \
                 patch.object(i.subprocess, "check_output", return_value=json.dumps([{"id": i.PLUGIN_ID}]).encode()):
                for flags in ([], ["--with-mcp-bridge"], []):
                    with patch.object(sys, "argv", ["install.py", "install", *flags]):
                        i.main()
                    if not flags and not json.loads((app / "install.json").read_text())["mcpBridge"]:
                        self.assertFalse((app / "reporting_mcp.py").exists())
                    else:
                        self.assertEqual((app / "reporting_mcp.py").read_bytes(), (i.ROOT / "src/reporting_mcp.py").read_bytes())
                with patch.object(sys, "argv", ["install.py", "remove"]):
                    i.main()
                self.assertFalse(app.exists())

    def test_optional_skill_updates_and_removes_only_owned_unchanged_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            env = {"XDG_CONFIG_HOME": str(root / "config"), "XDG_DATA_HOME": str(root / "share"),
                   "XDG_STATE_HOME": str(root / "state"), "CODEX_HOME": str(root / "codex")}
            skill = root / "codex/skills/agent-progress"
            with patch.dict(os.environ, env), patch.object(i.subprocess, "run"), \
                 patch.object(i.subprocess, "check_output", return_value=json.dumps([{"id": i.PLUGIN_ID}]).encode()):
                with patch.object(sys, "argv", ["install.py", "install", "--with-reporting-skill"]):
                    i.main()
                self.assertTrue((skill / "scripts/report.py").is_file())
                with patch.object(sys, "argv", ["install.py", "install"]):
                    i.main()
                (skill / "personal.txt").write_text("Keep this")
                (skill / "SKILL.md").write_text("My edited instructions")
                with patch.object(sys, "argv", ["install.py", "remove"]):
                    i.main()
                self.assertEqual((skill / "personal.txt").read_text(), "Keep this")
                self.assertEqual((skill / "SKILL.md").read_text(), "My edited instructions")
                self.assertFalse((skill / "scripts/report.py").exists())

    def test_optional_skill_does_not_overwrite_an_unowned_skill(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            skill = root / "codex/skills/agent-progress"
            skill.mkdir(parents=True)
            (skill / "SKILL.md").write_text("Already here")
            with patch.dict(os.environ, {"CODEX_HOME": str(root / "codex"), "XDG_DATA_HOME": str(root / "share")}), \
                 patch.object(sys, "argv", ["install.py", "install", "--with-reporting-skill"]):
                with self.assertRaises(RuntimeError):
                    i.main()
            self.assertEqual((skill / "SKILL.md").read_text(), "Already here")

    def test_preserves_sibling_hooks_and_roundtrips(self):
        before = {"description": "My hooks", "hooks": {"Stop": [
            {"matcher": "custom", "hooks": [{"type": "command", "command": "existing"}]}],
            "SubagentStop": [{"hooks": [{"type": "command", "command": "other"}]}]}}
        merged = i.merge_hooks(before, "our-command")
        self.assertEqual(merged["hooks"]["Stop"][0], before["hooks"]["Stop"][0])
        self.assertEqual(i.merge_hooks(merged, "our-command", remove=True), before)
        self.assertEqual(i.merge_hooks(merged, "our-command"), merged)

    def test_remove_preserves_handlers_added_later(self):
        doc = i.merge_hooks({}, "our-command")
        doc["hooks"]["Stop"][0]["hooks"].append({"type": "command", "command": "added-later"})
        after = i.merge_hooks(doc, "our-command", remove=True)
        self.assertEqual(after["hooks"]["Stop"][0]["hooks"][0]["command"], "added-later")

    def test_install_update_remove_remembers_initially_absent_hooks(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            env = {"XDG_CONFIG_HOME": str(root / "config"), "XDG_DATA_HOME": str(root / "share"),
                   "XDG_STATE_HOME": str(root / "state"), "CODEX_HOME": str(root / "codex")}
            with patch.dict(os.environ, env), patch.object(i.subprocess, "run"), \
                 patch.object(i.subprocess, "check_output", return_value=json.dumps([{"id": i.PLUGIN_ID}]).encode()):
                for action in ("install", "install", "remove"):
                    with patch.object(sys, "argv", ["install.py", action]):
                        i.main()
                self.assertFalse((root / "codex/hooks.json").exists())
                self.assertFalse((root / "config/omarchy/plugins" / i.PLUGIN_ID).exists())


if __name__ == "__main__":
    unittest.main()
