#!/usr/bin/env python3
"""Install/remove only this panel's files and hooks; retain unrelated configuration."""
import argparse
import copy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import tempfile
import time

ROOT = Path(__file__).resolve().parent
PLUGIN_ID = "nino.codex-progress"
SKILL_NAME = "agent-progress"
SKILL_FILES = ("SKILL.md", "scripts/report.py")
EVENTS = ("SessionStart", "UserPromptSubmit", "PreToolUse", "PermissionRequest",
          "PostToolUse", "PreCompact", "PostCompact", "Stop", "Interrupt", "SessionEnd")


def merge_hooks(document, command, remove=False):
    result = copy.deepcopy(document)
    hooks = result.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        raise ValueError("Existing hooks must be an object")
    for event in EVENTS:
        groups = []
        for group in hooks.get(event, []):
            group = copy.deepcopy(group)
            handlers = [h for h in group.get("hooks", []) if h.get("command") != command]
            if handlers:
                group["hooks"] = handlers
                groups.append(group)
        if not remove:
            groups.append({"hooks": [{"type": "command", "command": command,
                                      "timeout": 1, "statusMessage": "Update Codex progress panel"}]})
        if groups:
            hooks[event] = groups
        else:
            hooks.pop(event, None)
    return result


def atomic_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=".progress-")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(value, f, indent=2)
            f.write("\n")
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("install", "remove"))
    parser.add_argument("--with-reporting-skill", action="store_true",
                        help="Install experimental Dot/ChatGPT Work reporting instructions")
    args = parser.parse_args()
    os.umask(0o077)
    home = Path.home()
    data = Path(os.environ.get("XDG_DATA_HOME", str(home / ".local/share"))) / "omarchy-agent-progress"
    config = Path(os.environ.get("XDG_CONFIG_HOME", str(home / ".config"))) / "omarchy"
    plugin = config / "plugins" / PLUGIN_ID
    hooks_path = Path(os.environ.get("CODEX_HOME", str(home / ".codex"))) / "hooks.json"
    skill = hooks_path.parent / "skills" / SKILL_NAME
    state = Path(os.environ.get("XDG_STATE_HOME", str(home / ".local/state"))) / "omarchy-agent-progress"
    receipt = data / "install.json"
    previous_receipt = json.loads(receipt.read_text()) if receipt.exists() else {}
    install_skill = args.with_reporting_skill or bool(previous_receipt.get("reportingSkill"))
    if args.action == "install" and install_skill and skill.exists() and not previous_receipt.get("reportingSkill"):
        raise RuntimeError("Reporting skill already exists without our receipt; inspect before replacing")
    command = "/usr/bin/python3 " + shlex.quote(str(data / "progress.py")) + " hook"
    hooks_existed = hooks_path.exists()
    original = json.loads(hooks_path.read_text()) if hooks_existed else {}
    changed = merge_hooks(original, command, remove=args.action == "remove")
    if args.action == "install":
        subprocess.run(["omarchy", "plugin", "validate", str(ROOT / "plugin")], check=True)
        if (data.exists() or plugin.exists()) and not receipt.exists():
            raise RuntimeError("Destination already exists without our receipt; inspect before replacing")
    elif not receipt.exists():
        raise RuntimeError("No panel installation receipt found")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    backup = state / "backups" / stamp
    backup.mkdir(parents=True, mode=0o700)
    for path in (hooks_path, config / "shell.json"):
        if path.exists():
            shutil.copy2(path, backup / path.name)
    if args.action == "install":
        data.mkdir(parents=True, exist_ok=True)
        plugin.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / "src/progress.py", data / "progress.py")
        for name in ("ProgressPanel.qml", "manifest.json"):
            shutil.copy2(ROOT / "plugin" / name, plugin / name)
        skill_hashes = {}
        if install_skill:
            if skill.exists():
                shutil.copytree(skill, backup / "reporting-skill")
            for name in SKILL_FILES:
                destination = skill / name
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(ROOT / "skills" / SKILL_NAME / name, destination)
                skill_hashes[name] = hashlib.sha256(destination.read_bytes()).hexdigest()
        atomic_json(hooks_path, changed)
        atomic_json(receipt, {"version": "0.2.0", "source": str(ROOT), "command": command,
                             "reportingSkill": skill_hashes,
                             "hooksExisted": previous_receipt.get("hooksExisted", hooks_existed),
                             "backup": str(backup)})
        subprocess.run(["omarchy-shell", "shell", "rescanPlugins"], check=True)
        # Discovery is asynchronous; a successful IPC call only schedules it.
        for _ in range(30):
            discovered = json.loads(subprocess.check_output(["omarchy", "plugin", "list", "--json"]))
            if any(p["id"] == PLUGIN_ID for p in discovered):
                break
            time.sleep(0.1)
        else:
            raise RuntimeError("Plugin discovery timed out; files are staged, rerun install")
        subprocess.run(["omarchy", "plugin", "enable", PLUGIN_ID], check=True)
        print("Installed. Review hooks with /hooks in Codex CLI. Backup: " + str(backup))
    else:
        if changed == {"hooks": {}} and not json.loads(receipt.read_text()).get("hooksExisted", True):
            hooks_path.unlink(missing_ok=True)
        else:
            atomic_json(hooks_path, changed)
        subprocess.run(["omarchy", "plugin", "disable", PLUGIN_ID], check=True)
        if previous_receipt.get("reportingSkill") and skill.exists():
            shutil.copytree(skill, backup / "reporting-skill")
            for name in SKILL_FILES:
                path = skill / name
                expected = previous_receipt["reportingSkill"].get(name)
                if path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest() == expected:
                    path.unlink()
            for directory in (skill / "scripts", skill):
                if directory.is_dir() and not any(directory.iterdir()):
                    directory.rmdir()
        shutil.move(str(plugin), str(backup / "plugin"))
        shutil.move(str(data), str(backup / "application"))
        subprocess.run(["omarchy-shell", "shell", "rescanPlugins"], check=True)
        print("Removed panel and its hook handlers. Data and backup retained at " + str(state))


if __name__ == "__main__":
    main()
