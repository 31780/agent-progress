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
