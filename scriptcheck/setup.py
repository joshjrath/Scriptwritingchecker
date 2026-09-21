"""Interactive first-run setup: ask a few questions, write the files.

Everything here exists so that getting started is one command and a handful
of answers, rather than a checklist of files and environment variables.
"""

from __future__ import annotations

import json
import os
import secrets
import sys
from pathlib import Path
from typing import Optional

from .doctor import DROPBOX_PERMISSIONS, invite_url

BOLD = "\033[1m"
DIM = "\033[2m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
RED = "\033[31m"
OFF = "\033[0m"


def _colour(text: str, code: str) -> str:
    if not sys.stdout.isatty() or os.environ.get("NO_COLOR"):
        return text
    return f"{code}{text}{OFF}"


def heading(text: str) -> None:
    print()
    print(_colour(text, BOLD))
    print(_colour("-" * len(text), DIM))


def build_env(
    token: str,
    user_id: str,
    webhook: str = "",
    access_token: str = "",
    view_token: str = "",
) -> str:
    """The .env file contents. Pure, so the format is testable."""

    access_token = access_token or secrets.token_urlsafe(24)
    view_token = view_token or secrets.token_urlsafe(24)
    return "\n".join(
        [
            "# Written by `scriptcheck setup`. Keep this file private.",
            f"DISCORD_BOT_TOKEN={token}",
            f"SCRIPTCHECK_MY_USER_ID={user_id}",
            f"SCRIPTCHECK_WEBHOOK_URL={webhook}",
            "",
            "# Your own link. Full control.",
            f"SCRIPTCHECK_ACCESS_TOKEN={access_token}",
            "# The link you hand the team. They can look, not touch.",
            f"SCRIPTCHECK_VIEW_TOKEN={view_token}",
            "",
        ]
    )


def build_config(
    channel: str = "my-assignments",
    timezone: str = "America/New_York",
    roles: Optional[list] = None,
) -> dict:
    """The config file contents, for drop-box mode."""

    return {
        "my_roles": roles or ["SCRIPT"],
        "dropbox_channel_patterns": [channel],
        "auto_thread": True,
        "display_timezone": timezone,
        "default_timezone": timezone,
        "preferred_timezones": [timezone],
        "reminder_lead_hours": [24, 2],
        "overrides_file": "data/overrides.json",
    }


def read_env_value(path: Path, key: str) -> str:
    """Pull one value back out of a .env file."""

    if not path.is_file():
        return ""
    for line in path.read_text().splitlines():
        name, _, value = line.partition("=")
        if name.strip() == key:
            return value.strip()
    return ""


def ask(prompt: str, default: str = "", secret: bool = False) -> str:
    suffix = f" [{default}]" if default else ""
    while True:
        if secret:
            import getpass

            value = getpass.getpass(f"{prompt}{suffix}: ").strip()
        else:
            value = input(f"{prompt}{suffix}: ").strip()
        if value:
            return value
        if default:
            return default
        print(_colour("  That one is required.", YELLOW))


def ask_optional(prompt: str) -> str:
    return input(f"{prompt} {_colour('(press Enter to skip)', DIM)}: ").strip()


def confirm(prompt: str) -> bool:
    return input(f"{prompt} [Y/n]: ").strip().lower() in ("", "y", "yes")


def run(env_path: Path = Path(".env"), config_path: Path = Path("scriptcheck.config.json")) -> int:
    print()
    print(_colour("Script Board setup", BOLD))
    print("Four questions, then it runs. Nothing here touches anyone else's server.")

    existing_token = read_env_value(env_path, "DISCORD_BOT_TOKEN")
    existing_access = read_env_value(env_path, "SCRIPTCHECK_ACCESS_TOKEN")

    # --- 1. the invite ------------------------------------------------------
    heading("1 of 4  Invite the bot to YOUR server")
    print("From https://discord.com/developers/applications")
    print("open your app, then General Information -> copy the Application ID.")
    print()
    app_id = ask("Application ID")
    print()
    print("Open this link and pick a server you own:")
    print()
    print("  " + _colour(invite_url(app_id, DROPBOX_PERMISSIONS), GREEN))
    print()
    print(_colour("Make sure that server has a channel for forwarded briefs.", DIM))
    input("Press Enter once the bot has joined... ")

    # --- 2. the token -------------------------------------------------------
    heading("2 of 4  Bot token")
    if existing_token:
        print(_colour("A token is already saved in .env.", DIM))
        token = existing_token if confirm("Keep the saved token?") else ""
    else:
        token = ""
    if not token:
        print("Developer Portal -> your app -> Bot -> Reset Token -> Copy.")
        print(_colour("It will not echo as you paste. That is normal.", DIM))
        token = ask("Bot token", secret=True)

    # --- 3. you -------------------------------------------------------------
    heading("3 of 4  Your Discord user ID")
    print("Discord -> Settings -> Advanced -> Developer Mode ON,")
    print("then right-click your own name -> Copy User ID.")
    print()
    user_id = ask("Your user ID")
    if not user_id.isdigit():
        print(_colour("  Hmm, that is usually 17-20 digits. Continuing anyway.", YELLOW))

    # --- 4. the rest --------------------------------------------------------
    heading("4 of 4  Where things go")
    channel = ask("Channel you will forward briefs into", default="my-assignments")
    timezone = ask("Your timezone", default="America/New_York")
    print()
    print("Alerts (24h / 2h / overdue) get posted to a Discord webhook.")
    print(_colour("Your server -> Edit Channel -> Integrations -> Webhooks -> New Webhook.", DIM))
    webhook = ask_optional("Webhook URL")

    # --- write --------------------------------------------------------------
    env_path.write_text(
        build_env(
            token, user_id, webhook, existing_access, read_env_value(env_path, "SCRIPTCHECK_VIEW_TOKEN")
        )
    )
    try:
        env_path.chmod(0o600)
    except OSError:
        pass
    config_path.write_text(json.dumps(build_config(channel, timezone), indent=2) + "\n")
    Path("data").mkdir(exist_ok=True)

    access = read_env_value(env_path, "SCRIPTCHECK_ACCESS_TOKEN")
    view = read_env_value(env_path, "SCRIPTCHECK_VIEW_TOKEN")

    heading("Done")
    print(f"  {_colour('wrote', GREEN)} {env_path}   {_colour('(your token - never commit this)', DIM)}")
    print(f"  {_colour('wrote', GREEN)} {config_path}")
    print()
    print("Your board (full control):")
    print("  " + _colour(f"http://localhost:8080/?k={access}", GREEN))
    print()
    print("Read-only link for teammates:")
    print("  " + _colour(f"http://localhost:8080/?k={view}", GREEN))
    print(_colour("  (works once it is hosted - localhost only reaches this Mac)", DIM))
    print()

    # --- check --------------------------------------------------------------
    if not confirm("Check that the bot can see everything now?"):
        print("\nWhen you are ready:  python -m scriptcheck doctor")
        return 0

    from .config import Config, load_dotenv
    from .doctor import collect, diagnose, render

    load_dotenv(env_path, override=True)
    config = Config.load(config_path)
    print()
    print("Connecting to Discord...")
    checks = diagnose(collect(config), config)
    print()
    print(render(checks))

    if all(c.ok for c in checks):
        print(_colour("You are ready.", GREEN))
        print()
        print("  1. Start it:   " + _colour("python -m scriptcheck serve", BOLD))
        print(f"  2. Forward a brief into #{channel}")
        print("  3. Open the board link above")
        return 0

    print(_colour("Fix the items marked FAIL above, then run this again.", YELLOW))
    return 2
