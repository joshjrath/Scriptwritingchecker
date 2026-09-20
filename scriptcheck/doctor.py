"""Preflight: prove the bot can actually see everything it needs.

Separated into fact collection (needs a live connection) and diagnosis (pure),
so the rules that decide pass/fail are testable without Discord.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from typing import Any, Optional

from .config import Config

#: View Channels + Read Message History. The bot never needs to post.
READ_ONLY_PERMISSIONS = 66560

#: Drop-box mode adds Create Public Threads + Send Messages in Threads, since
#: the bot opens a thread on each brief for deliveries to land in. Only ever
#: used in a server you own.
DROPBOX_PERMISSIONS = 66560 | (1 << 35) | (1 << 38)

INVITE_TEMPLATE = (
    "https://discord.com/api/oauth2/authorize"
    "?client_id={client_id}&permissions={permissions}&scope=bot"
)


def invite_url(client_id: str, permissions: int = READ_ONLY_PERMISSIONS) -> str:
    return INVITE_TEMPLATE.format(client_id=client_id, permissions=permissions)


PASS, WARN, FAIL = "PASS", "WARN", "FAIL"


@dataclass
class Check:
    name: str
    status: str
    detail: str = ""
    fix: str = ""

    @property
    def ok(self) -> bool:
        return self.status != FAIL


@dataclass
class Facts:
    """Everything the live probe found. Defaults describe a failed login."""

    logged_in: bool = False
    bot_name: str = ""
    bot_id: str = ""
    error: str = ""
    guilds: list[dict] = field(default_factory=list)
    channels: list[dict] = field(default_factory=list)
    threads_seen: int = 0
    messages_sampled: int = 0
    messages_with_content: int = 0
    my_ids_seen: set = field(default_factory=set)
    archived_denied: list[str] = field(default_factory=list)


def diagnose(facts: Facts, config: Config) -> list[Check]:
    """Turn observations into pass/fail with a fix for each failure."""

    checks: list[Check] = []

    if not facts.logged_in:
        return [
            Check(
                "Bot login",
                FAIL,
                facts.error or "Could not log in.",
                "Check DISCORD_BOT_TOKEN. Reset it in the Developer Portal "
                "(Applications -> your app -> Bot -> Reset Token) if unsure.",
            )
        ]
    checks.append(Check("Bot login", PASS, f"{facts.bot_name} ({facts.bot_id})"))

    # --- is it in the server at all -----------------------------------------
    if not facts.guilds:
        checks.append(
            Check(
                "Server membership",
                FAIL,
                "The bot is not in any server.",
                "An admin of the server has to open the invite URL. Run "
                "`scriptcheck invite --client-id <APPLICATION ID>` to print it. "
                "If the link fails for them, check that Public Bot is ON in the "
                "Developer Portal - with it off, only you can install the app, "
                "and you need Manage Server in the target server to do that.",
            )
        )
        return checks

    names = ", ".join(g["name"] for g in facts.guilds)
    if config.guild_ids:
        wanted = {str(g) for g in config.guild_ids}
        found = {str(g["id"]) for g in facts.guilds}
        missing = wanted - found
        if missing:
            checks.append(
                Check(
                    "Server membership",
                    FAIL,
                    f"Configured guild_ids not visible: {', '.join(sorted(missing))}. In: {names}",
                    "Either the bot was invited to a different server, or guild_ids "
                    "is wrong. The IDs the bot can see are listed above.",
                )
            )
        else:
            checks.append(Check("Server membership", PASS, names))
    else:
        checks.append(Check("Server membership", PASS, names))

    # --- can it see the assignment channels ---------------------------------
    if not facts.channels:
        if config.dropbox_channel_patterns:
            pattern = ", ".join(config.dropbox_channel_patterns)
            fix = (
                "Make a channel in your own server whose name matches, forward a "
                "brief into it, and run this again. The bot needs View Channel, "
                "Read Message History and Create Public Threads there."
            )
        else:
            pattern = ", ".join(config.channel_name_patterns) or "(no filter set)"
            fix = (
                "Either the bot cannot see the channel (ask an admin to grant "
                "View Channel on that category), or channel_name_patterns does "
                "not match its name."
            )
        checks.append(Check("Assignment channels", FAIL, f"No channel matched {pattern}.", fix))
        return checks

    visible = [c for c in facts.channels if c.get("can_view")]
    readable = [c for c in visible if c.get("can_read_history")]
    listing = ", ".join("#" + c["name"] for c in facts.channels[:6])
    if not visible:
        checks.append(
            Check(
                "Channel access",
                FAIL,
                f"Matched {len(facts.channels)} channel(s) but can view none: {listing}",
                "Ask the admin to give the bot role View Channel on that category.",
            )
        )
        return checks
    if not readable:
        checks.append(
            Check(
                "Channel access",
                FAIL,
                f"Can see {len(visible)} channel(s) but cannot read history.",
                "Ask the admin to add Read Message History for the bot role.",
            )
        )
    else:
        checks.append(
            Check(
                "Channel access",
                PASS,
                f"{len(readable)} readable: {listing}",
            )
        )

    # --- threads -------------------------------------------------------------
    if facts.threads_seen == 0 and config.dropbox_channel_patterns:
        checks.append(
            Check(
                "Forwarded briefs",
                WARN,
                "The channel is readable but has no threads yet.",
                "That is expected until you forward your first brief. The bot "
                "opens a thread on each one it recognises.",
            )
        )
    elif facts.threads_seen == 0:
        checks.append(
            Check(
                "Threads",
                FAIL,
                "No threads found in those channels.",
                "If the assignments are forum posts, make sure the bot can see the "
                "forum channel itself. If they are older threads, they may be "
                "archived - include_archived is "
                + ("on" if config.include_archived else "OFF, turn it on"),
            )
        )
    else:
        checks.append(Check("Threads", PASS, f"{facts.threads_seen} thread(s) reachable"))

    if facts.archived_denied:
        checks.append(
            Check(
                "Archived threads",
                WARN,
                "Denied in: " + ", ".join("#" + c for c in facts.archived_denied),
                "Older assignments in those channels will be missed. Read Message "
                "History on the channel usually fixes it.",
            )
        )

    # --- the one everybody forgets ------------------------------------------
    if facts.messages_sampled == 0:
        checks.append(
            Check(
                "Message Content intent",
                WARN,
                "No messages could be sampled, so this could not be verified.",
                "",
            )
        )
    elif facts.messages_with_content == 0:
        checks.append(
            Check(
                "Message Content intent",
                FAIL,
                f"All {facts.messages_sampled} sampled messages came back with empty "
                "text - the privileged intent is off.",
                "Developer Portal -> your app -> Bot -> Privileged Gateway Intents "
                "-> enable MESSAGE CONTENT INTENT, then run this again. Without it "
                "every brief looks blank and nothing can be parsed.",
            )
        )
    else:
        checks.append(
            Check(
                "Message Content intent",
                PASS,
                f"{facts.messages_with_content}/{facts.messages_sampled} sampled "
                "messages carry text",
            )
        )

    # --- is the configured identity real ------------------------------------
    if not config.my_user_ids:
        checks.append(
            Check(
                "Your identity",
                WARN,
                "my_user_ids is empty, so you are matched by display name only.",
                "Turn on Developer Mode in Discord, right-click yourself -> Copy "
                "User ID, and put it in my_user_ids. Name matching breaks the "
                "moment someone changes a nickname.",
            )
        )
    elif facts.my_ids_seen:
        checks.append(
            Check(
                "Your identity",
                PASS,
                f"user ID seen in the fetched threads: {', '.join(sorted(facts.my_ids_seen))}",
            )
        )
    else:
        checks.append(
            Check(
                "Your identity",
                WARN,
                f"my_user_ids {config.my_user_ids} never appears in the threads read.",
                "Check the ID is yours (right-click yourself -> Copy User ID). If it "
                "is wrong, every brief will look like someone else's.",
            )
        )

    return checks


def render(checks: list[Check]) -> str:
    symbols = {PASS: "  ok ", WARN: " warn", FAIL: "FAIL "}
    out = ["=" * 72, "BOT PREFLIGHT", "=" * 72]
    for check in checks:
        out.append(f"[{symbols[check.status]}] {check.name}")
        if check.detail:
            out.append(f"          {check.detail}")
        if check.fix and check.status != PASS:
            for index, line in enumerate(_wrap(check.fix, 60)):
                out.append(f"          {'->' if index == 0 else '  '} {line}")
        out.append("")
    failures = [c for c in checks if c.status == FAIL]
    warnings = [c for c in checks if c.status == WARN]
    if failures:
        out.append(f"{len(failures)} blocking problem(s). Fix those and run again.")
    elif warnings:
        out.append(f"Ready to run, with {len(warnings)} thing(s) worth tightening.")
    else:
        out.append("Everything checks out. `scriptcheck check` will work unattended.")
    out.append("")
    return "\n".join(out)


def _wrap(text: str, width: int) -> list[str]:
    words, lines, current = text.split(), [], ""
    for word in words:
        if current and len(current) + len(word) + 1 > width:
            lines.append(current)
            current = word
        else:
            current = f"{current} {word}".strip()
    if current:
        lines.append(current)
    return lines


# ---------------------------------------------------------------------------
# Live probe
# ---------------------------------------------------------------------------


def collect(config: Config, token: Optional[str] = None) -> Facts:  # pragma: no cover
    """Log in and look around. Network-bound, so kept free of decisions."""

    import asyncio

    from .sources.discord_bot import _require_discord

    dc = _require_discord()
    token = token or os.environ.get("DISCORD_BOT_TOKEN", "")
    facts = Facts()
    if not token:
        facts.error = "No bot token. Set DISCORD_BOT_TOKEN or pass --token."
        return facts

    intents = dc.Intents.default()
    intents.message_content = True
    intents.guilds = True
    client = dc.Client(intents=intents)
    my_ids = {str(u) for u in config.my_user_ids}

    @client.event
    async def on_ready():
        try:
            facts.logged_in = True
            facts.bot_name = str(client.user)
            facts.bot_id = str(client.user.id)

            for guild in client.guilds:
                facts.guilds.append({"id": str(guild.id), "name": guild.name})
                me = guild.me
                for channel in guild.channels:
                    if not isinstance(channel, (dc.TextChannel, dc.ForumChannel)):
                        continue
                    if not config.channel_matches(channel.name, str(channel.id)):
                        continue
                    perms = channel.permissions_for(me)
                    facts.channels.append(
                        {
                            "id": str(channel.id),
                            "name": channel.name,
                            "can_view": bool(perms.view_channel),
                            "can_read_history": bool(perms.read_message_history),
                        }
                    )
                    if not (perms.view_channel and perms.read_message_history):
                        continue

                    threads = list(getattr(channel, "threads", []))
                    try:
                        async for thread in channel.archived_threads(limit=5):
                            threads.append(thread)
                    except dc.Forbidden:
                        facts.archived_denied.append(channel.name)
                    except Exception:
                        pass

                    facts.threads_seen += len(threads)
                    # Sample a few messages to prove the content intent is on.
                    for thread in threads[:3]:
                        try:
                            async for message in thread.history(limit=4, oldest_first=True):
                                facts.messages_sampled += 1
                                if (message.content or "").strip():
                                    facts.messages_with_content += 1
                                if str(message.author.id) in my_ids:
                                    facts.my_ids_seen.add(str(message.author.id))
                                for mention in message.mentions:
                                    if str(mention.id) in my_ids:
                                        facts.my_ids_seen.add(str(mention.id))
                        except Exception:
                            continue
        except Exception as exc:
            facts.error = f"{type(exc).__name__}: {exc}"
        finally:
            await client.close()

    try:
        asyncio.run(client.start(token))
    except Exception as exc:
        if not facts.logged_in:
            facts.error = f"{type(exc).__name__}: {exc}"
    return facts
