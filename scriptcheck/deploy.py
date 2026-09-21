"""Turn a working local setup into something you can paste into a host.

Railway, Render and Fly all accept a block of KEY=VALUE lines in their bulk
variable editor, so the whole handoff can be one copy instead of eight fields
typed by hand from a file you are not supposed to open in public.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

BOLD = "\033[1m"
DIM = "\033[2m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
OFF = "\033[0m"

#: Where a mounted volume lives, so hand corrections survive a redeploy.
VOLUME_PATH = "/data"

#: Variables that belong in the host, in the order they read best.
KEYS = [
    "DISCORD_BOT_TOKEN",
    "SCRIPTCHECK_MY_USER_ID",
    "SCRIPTCHECK_WEBHOOK_URL",
    "SCRIPTCHECK_ACCESS_TOKEN",
    "SCRIPTCHECK_VIEW_TOKEN",
]


def read_env(path: str | Path = ".env") -> dict[str, str]:
    values: dict[str, str] = {}
    path = Path(path)
    if not path.is_file():
        return values
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip()
    return values


def hosted_config(config: dict) -> dict:
    """The local config, adjusted for a container with a mounted volume."""

    hosted = dict(config)
    hosted["overrides_file"] = f"{VOLUME_PATH}/overrides.json"
    hosted.pop("data_file", None)
    return hosted


def railway_env(env: dict, config: dict) -> str:
    """The block to paste into a bulk variable editor."""

    lines = [f"{key}={env.get(key, '')}" for key in KEYS if env.get(key)]
    lines.append(
        "SCRIPTCHECK_CONFIG=" + json.dumps(hosted_config(config), separators=(",", ":"))
    )
    return "\n".join(lines)


def missing(env: dict) -> list[str]:
    required = ["DISCORD_BOT_TOKEN", "SCRIPTCHECK_MY_USER_ID", "SCRIPTCHECK_ACCESS_TOKEN"]
    return [key for key in required if not env.get(key)]


def _c(text: str, code: str) -> str:
    import os
    import sys

    if not sys.stdout.isatty() or os.environ.get("NO_COLOR"):
        return text
    return f"{code}{text}{OFF}"


def run(
    env_path: str | Path = ".env",
    config_path: str | Path = "scriptcheck.config.json",
    branch: str = "",
) -> int:
    env = read_env(env_path)
    if not env:
        print(f"No {env_path} found. Run `bash start.command` first.")
        return 1

    gaps = missing(env)
    if gaps:
        print(_c(f"Missing from {env_path}: {', '.join(gaps)}", YELLOW))
        print("Run `bash start.command` again to fill them in.")
        return 1

    config_path = Path(config_path)
    config = json.loads(config_path.read_text()) if config_path.is_file() else {}

    print()
    print(_c("Putting your board online", BOLD))
    print()
    print("1. Go to railway.com and sign in with GitHub")
    print("2. New Project -> Deploy from GitHub repo -> Scriptwritingchecker")
    if branch:
        print(f"3. Settings -> Source -> set the branch to {_c(branch, BOLD)}")
    else:
        print("3. Settings -> Source -> pick the branch your code is on")
    print(f"4. Settings -> Volumes -> Add Volume, mount path {_c(VOLUME_PATH, BOLD)}")
    print(_c("   (without this, anything you mark delivered is lost on redeploy)", DIM))
    print("5. Variables -> Raw Editor -> paste everything between the lines:")
    print()
    print(_c("-" * 68, DIM))
    print(railway_env(env, config))
    print(_c("-" * 68, DIM))
    print()
    print("6. Settings -> Networking -> Generate Domain")
    print()
    print(_c("Then your two links are:", BOLD))
    print(f"  yours      https://YOUR-DOMAIN/?k={env['SCRIPTCHECK_ACCESS_TOKEN']}")
    view = env.get("SCRIPTCHECK_VIEW_TOKEN", "")
    if view:
        print(f"  {_c('the team', GREEN)}   https://YOUR-DOMAIN/?k={view}   {_c('(read-only)', DIM)}")
    else:
        print(_c("  No view token set, so there is no read-only link yet.", YELLOW))
    print()
    print(_c("That block contains your bot token. Paste it into Railway, nowhere else.", YELLOW))
    print()
    return 0
