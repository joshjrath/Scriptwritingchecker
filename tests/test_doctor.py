import unittest

from scriptcheck.config import Config
from scriptcheck.doctor import (
    FAIL,
    PASS,
    READ_ONLY_PERMISSIONS,
    WARN,
    Facts,
    diagnose,
    invite_url,
    render,
)

CONFIG = Config(
    my_user_ids=["111111111111111111"],
    my_roles=["SCRIPT"],
    channel_name_patterns=["assignments", "workflow"],
)


def healthy(**overrides) -> Facts:
    facts = Facts(
        logged_in=True,
        bot_name="scriptcheck#1234",
        bot_id="999",
        guilds=[{"id": "900", "name": "Specular Industries"}],
        channels=[
            {
                "id": "901",
                "name": "secondary-assignments-workflow",
                "can_view": True,
                "can_read_history": True,
            }
        ],
        threads_seen=14,
        messages_sampled=12,
        messages_with_content=12,
        my_ids_seen={"111111111111111111"},
    )
    for key, value in overrides.items():
        setattr(facts, key, value)
    return facts


def by_name(checks):
    return {c.name: c for c in checks}


class TestInvite(unittest.TestCase):
    def test_permissions_are_read_only(self):
        # View Channels (1<<10) + Read Message History (1<<16), nothing else.
        self.assertEqual(READ_ONLY_PERMISSIONS, (1 << 10) | (1 << 16))

    def test_url_shape(self):
        url = invite_url("123")
        self.assertIn("client_id=123", url)
        self.assertIn(f"permissions={READ_ONLY_PERMISSIONS}", url)
        self.assertIn("scope=bot", url)


class TestDiagnosis(unittest.TestCase):
    def test_a_healthy_setup_passes_everything(self):
        checks = diagnose(healthy(), CONFIG)
        self.assertTrue(all(c.status == PASS for c in checks), [c.name for c in checks if c.status != PASS])
        self.assertIn("unattended", render(checks))

    def test_bad_token_stops_at_login_with_a_fix(self):
        checks = diagnose(Facts(error="LoginFailure: improper token"), CONFIG)
        self.assertEqual(len(checks), 1)
        self.assertEqual(checks[0].status, FAIL)
        self.assertIn("DISCORD_BOT_TOKEN", checks[0].fix)

    def test_not_invited_says_so(self):
        checks = by_name(diagnose(healthy(guilds=[]), CONFIG))
        self.assertEqual(checks["Server membership"].status, FAIL)
        self.assertIn("invite URL", checks["Server membership"].fix)

    def test_wrong_guild_id_is_caught(self):
        config = Config(guild_ids=["555"], channel_name_patterns=["workflow"])
        checks = by_name(diagnose(healthy(), config))
        self.assertEqual(checks["Server membership"].status, FAIL)
        self.assertIn("555", checks["Server membership"].detail)

    def test_no_channel_matched(self):
        checks = by_name(diagnose(healthy(channels=[]), CONFIG))
        self.assertEqual(checks["Assignment channels"].status, FAIL)
        self.assertIn("channel_name_patterns", checks["Assignment channels"].fix)

    def test_channel_visible_but_not_readable(self):
        facts = healthy(
            channels=[
                {"id": "901", "name": "x", "can_view": True, "can_read_history": False}
            ]
        )
        checks = by_name(diagnose(facts, CONFIG))
        self.assertEqual(checks["Channel access"].status, FAIL)
        self.assertIn("Read Message History", checks["Channel access"].fix)

    def test_channel_matched_but_invisible(self):
        facts = healthy(
            channels=[
                {"id": "901", "name": "x", "can_view": False, "can_read_history": False}
            ]
        )
        checks = by_name(diagnose(facts, CONFIG))
        self.assertEqual(checks["Channel access"].status, FAIL)
        self.assertIn("View Channel", checks["Channel access"].fix)

    def test_no_threads_mentions_archived_setting(self):
        config = Config(channel_name_patterns=["workflow"], include_archived=False)
        checks = by_name(diagnose(healthy(threads_seen=0), config))
        self.assertEqual(checks["Threads"].status, FAIL)
        self.assertIn("OFF", checks["Threads"].fix)

    def test_archived_denial_is_a_warning_not_a_blocker(self):
        checks = by_name(diagnose(healthy(archived_denied=["old-channel"]), CONFIG))
        self.assertEqual(checks["Archived threads"].status, WARN)

    def test_message_content_intent_off_is_the_headline_failure(self):
        facts = healthy(messages_sampled=12, messages_with_content=0)
        checks = by_name(diagnose(facts, CONFIG))
        check = checks["Message Content intent"]
        self.assertEqual(check.status, FAIL)
        self.assertIn("MESSAGE CONTENT INTENT", check.fix)
        self.assertIn("blank", check.fix)

    def test_unsampled_messages_cannot_confirm_the_intent(self):
        facts = healthy(messages_sampled=0, messages_with_content=0)
        self.assertEqual(by_name(diagnose(facts, CONFIG))["Message Content intent"].status, WARN)

    def test_missing_user_id_warns_about_name_matching(self):
        config = Config(channel_name_patterns=["workflow"], my_user_ids=[])
        check = by_name(diagnose(healthy(my_ids_seen=set()), config))["Your identity"]
        self.assertEqual(check.status, WARN)
        self.assertIn("Copy User ID", check.fix)

    def test_a_user_id_never_seen_is_suspicious(self):
        check = by_name(diagnose(healthy(my_ids_seen=set()), CONFIG))["Your identity"]
        self.assertEqual(check.status, WARN)
        self.assertIn("someone else's", check.fix)


class TestRendering(unittest.TestCase):
    def test_failures_print_their_fix(self):
        text = render(diagnose(healthy(messages_with_content=0), CONFIG))
        self.assertIn("FAIL", text)
        self.assertIn("MESSAGE CONTENT INTENT", text)
        self.assertIn("blocking problem", text)

    def test_warnings_do_not_block(self):
        text = render(diagnose(healthy(archived_denied=["c"]), CONFIG))
        self.assertIn("Ready to run", text)


if __name__ == "__main__":
    unittest.main()


class TestConfigFromEnvironment(unittest.TestCase):
    """A browser-only deploy configures everything through variables."""

    def setUp(self):
        import os

        self.saved = {
            k: os.environ.pop(k, None)
            for k in (
                "SCRIPTCHECK_CONFIG",
                "SCRIPTCHECK_CONFIG_FILE",
                "SCRIPTCHECK_MY_USER_ID",
                "SCRIPTCHECK_WEBHOOK_URL",
                "SCRIPTCHECK_ACCESS_TOKEN",
            )
        }

    def tearDown(self):
        import os

        for key, value in self.saved.items():
            os.environ.pop(key, None)
            if value is not None:
                os.environ[key] = value

    def test_inline_json_becomes_the_config(self):
        import json
        import os

        os.environ["SCRIPTCHECK_CONFIG"] = json.dumps(
            {"channel_name_patterns": ["workflow"], "my_roles": ["SCRIPT"]}
        )
        config = Config.load()
        self.assertEqual(config.channel_name_patterns, ["workflow"])
        self.assertEqual(config.my_roles, ["SCRIPT"])

    def test_separate_variables_still_layer_on_top(self):
        import json
        import os

        os.environ["SCRIPTCHECK_CONFIG"] = json.dumps({"my_roles": ["SCRIPT"]})
        os.environ["SCRIPTCHECK_MY_USER_ID"] = "424242424242424242"
        os.environ["SCRIPTCHECK_ACCESS_TOKEN"] = "shh"
        config = Config.load()
        self.assertIn("424242424242424242", config.my_user_ids)
        self.assertEqual(config.access_token, "shh")

    def test_a_typo_in_the_variable_is_rejected_with_help(self):
        import os

        os.environ["SCRIPTCHECK_CONFIG"] = "{not json}"
        with self.assertRaises(ValueError) as ctx:
            Config.load()
        self.assertIn("not valid JSON", str(ctx.exception))

    def test_an_unknown_key_is_named(self):
        import json
        import os

        os.environ["SCRIPTCHECK_CONFIG"] = json.dumps({"my_rolls": ["SCRIPT"]})
        with self.assertRaises(ValueError) as ctx:
            Config.load()
        self.assertIn("my_rolls", str(ctx.exception))


class TestDotenv(unittest.TestCase):
    def setUp(self):
        import os
        import tempfile

        self.dir = tempfile.mkdtemp()
        self.saved = dict(os.environ)

    def tearDown(self):
        import os

        os.environ.clear()
        os.environ.update(self.saved)

    def write(self, text):
        from pathlib import Path

        path = Path(self.dir) / ".env"
        path.write_text(text)
        return path

    def test_values_are_loaded(self):
        import os

        from scriptcheck.config import load_dotenv

        path = self.write("DISCORD_BOT_TOKEN=abc123\nSCRIPTCHECK_MY_USER_ID=999\n")
        applied = load_dotenv(path)
        self.assertEqual(sorted(applied), ["DISCORD_BOT_TOKEN", "SCRIPTCHECK_MY_USER_ID"])
        self.assertEqual(os.environ["DISCORD_BOT_TOKEN"], "abc123")

    def test_comments_blanks_and_export_prefixes(self):
        import os

        from scriptcheck.config import load_dotenv

        path = self.write(
            "# a comment\n\n  \nexport SCRIPTCHECK_ACCESS_TOKEN=shh\nnot_a_pair\n"
        )
        load_dotenv(path)
        self.assertEqual(os.environ["SCRIPTCHECK_ACCESS_TOKEN"], "shh")

    def test_quotes_are_stripped_once(self):
        import os

        from scriptcheck.config import load_dotenv

        self.write('A="quoted"\nB=\'single\'\nC="keeps "inner" quotes"\n')
        load_dotenv(self.write('A="quoted"\nB=\'single\'\nC=say "hi"\n'))
        self.assertEqual(os.environ["A"], "quoted")
        self.assertEqual(os.environ["B"], "single")
        self.assertEqual(os.environ["C"], 'say "hi"')

    def test_a_real_environment_variable_wins(self):
        import os

        from scriptcheck.config import load_dotenv

        os.environ["DISCORD_BOT_TOKEN"] = "from-the-host"
        load_dotenv(self.write("DISCORD_BOT_TOKEN=from-the-file\n"))
        self.assertEqual(os.environ["DISCORD_BOT_TOKEN"], "from-the-host")

    def test_a_missing_file_is_fine(self):
        from scriptcheck.config import load_dotenv

        self.assertEqual(load_dotenv("/nonexistent/.env"), [])

    def test_a_webhook_url_with_an_equals_sign_survives(self):
        import os

        from scriptcheck.config import load_dotenv

        load_dotenv(self.write("SCRIPTCHECK_WEBHOOK_URL=https://x.com/a?b=c&d=e\n"))
        self.assertEqual(os.environ["SCRIPTCHECK_WEBHOOK_URL"], "https://x.com/a?b=c&d=e")


class TestSetupWizard(unittest.TestCase):
    """The wizard writes the two files a first run needs."""

    def test_env_has_every_variable_the_daemon_reads(self):
        from scriptcheck.setup import build_env

        text = build_env("tok", "123", "https://hook", "acc")
        for key in (
            "DISCORD_BOT_TOKEN",
            "SCRIPTCHECK_MY_USER_ID",
            "SCRIPTCHECK_WEBHOOK_URL",
            "SCRIPTCHECK_ACCESS_TOKEN",
        ):
            self.assertIn(f"{key}=", text)
        self.assertIn("DISCORD_BOT_TOKEN=tok", text)

    def test_an_access_token_is_generated_when_absent(self):
        from scriptcheck.setup import build_env, read_env_value

        import tempfile
        from pathlib import Path

        path = Path(tempfile.mkdtemp()) / ".env"
        path.write_text(build_env("tok", "123"))
        generated = read_env_value(path, "SCRIPTCHECK_ACCESS_TOKEN")
        self.assertGreaterEqual(len(generated), 20)

    def test_the_env_file_round_trips_through_the_loader(self):
        import os
        import tempfile
        from pathlib import Path

        from scriptcheck.config import load_dotenv
        from scriptcheck.setup import build_env

        path = Path(tempfile.mkdtemp()) / ".env"
        path.write_text(build_env("tok", "123", "https://hook?a=b&c=d", "acc"))
        saved = dict(os.environ)
        try:
            os.environ.pop("SCRIPTCHECK_WEBHOOK_URL", None)
            load_dotenv(path, override=True)
            self.assertEqual(os.environ["SCRIPTCHECK_WEBHOOK_URL"], "https://hook?a=b&c=d")
            self.assertEqual(os.environ["DISCORD_BOT_TOKEN"], "tok")
        finally:
            os.environ.clear()
            os.environ.update(saved)

    def test_the_config_it_writes_is_valid_and_in_dropbox_mode(self):
        from scriptcheck.config import Config
        from scriptcheck.setup import build_config

        config = Config.from_dict(build_config("my-assignments", "America/New_York"))
        self.assertEqual(config.dropbox_channel_patterns, ["my-assignments"])
        self.assertTrue(config.dropbox_matches("my-assignments", "1"))
        # Drop-box mode must not also scan the rest of the personal server.
        self.assertFalse(config.channel_matches("general", "2"))
        self.assertEqual(config.display_timezone, "America/New_York")

    def test_a_custom_channel_and_timezone_are_carried_through(self):
        from scriptcheck.config import Config
        from scriptcheck.setup import build_config

        config = Config.from_dict(build_config("briefs", "Europe/London"))
        self.assertTrue(config.dropbox_matches("briefs", "1"))
        self.assertEqual(config.default_timezone, "Europe/London")
        self.assertEqual(config.assume_time_obj.hour, 23)


class TestDropboxPreflight(unittest.TestCase):
    """The preflight has to see the drop-box channel it is checking."""

    CONFIG = Config(
        my_user_ids=["111111111111111111"],
        my_roles=["SCRIPT"],
        dropbox_channel_patterns=["my-assignments"],
    )

    def facts(self, **overrides):
        base = Facts(
            logged_in=True,
            bot_name="ScriptTracker#9101",
            bot_id="999",
            guilds=[{"id": "900", "name": "Script Tracker"}],
            channels=[
                {
                    "id": "901",
                    "name": "my-assignments",
                    "can_view": True,
                    "can_read_history": True,
                    "can_create_threads": True,
                    "dropbox": True,
                }
            ],
            threads_seen=0,
            messages_sampled=0,
            my_ids_seen={"111111111111111111"},
        )
        for key, value in overrides.items():
            setattr(base, key, value)
        return base

    def test_an_empty_dropbox_channel_is_not_a_failure(self):
        checks = diagnose(self.facts(), self.CONFIG)
        by_name = {c.name: c for c in checks}
        self.assertNotIn("Assignment channels", by_name)
        self.assertEqual(by_name["Channel access"].status, PASS)
        # No briefs forwarded yet is expected, not broken.
        self.assertEqual(by_name["Forwarded briefs"].status, WARN)
        self.assertFalse([c for c in checks if c.status == FAIL])

    def test_missing_thread_permission_is_caught(self):
        facts = self.facts()
        facts.channels[0]["can_create_threads"] = False
        by_name = {c.name: c for c in diagnose(facts, self.CONFIG)}
        self.assertEqual(by_name["Thread creation"].status, FAIL)
        self.assertIn("Create Public Threads", by_name["Thread creation"].fix)

    def test_the_advice_is_about_forwarding_not_about_admins(self):
        by_name = {c.name: c for c in diagnose(self.facts(channels=[]), self.CONFIG)}
        self.assertIn("forward a brief", by_name["Assignment channels"].fix)
        self.assertNotIn("admin", by_name["Assignment channels"].fix)

    def test_once_a_brief_is_forwarded_everything_passes(self):
        facts = self.facts(threads_seen=1, messages_sampled=3, messages_with_content=3)
        checks = diagnose(facts, self.CONFIG)
        self.assertTrue(all(c.status == PASS for c in checks), [c.name for c in checks if c.status != PASS])


class TestShareTokens(unittest.TestCase):
    def test_setup_generates_two_distinct_tokens(self):
        from scriptcheck.setup import build_env

        text = build_env("tok", "123")
        lines = dict(
            line.split("=", 1) for line in text.splitlines() if "=" in line and not line.startswith("#")
        )
        self.assertGreaterEqual(len(lines["SCRIPTCHECK_ACCESS_TOKEN"]), 20)
        self.assertGreaterEqual(len(lines["SCRIPTCHECK_VIEW_TOKEN"]), 20)
        self.assertNotEqual(
            lines["SCRIPTCHECK_ACCESS_TOKEN"], lines["SCRIPTCHECK_VIEW_TOKEN"]
        )

    def test_existing_tokens_are_preserved_on_a_re_run(self):
        from scriptcheck.setup import build_env

        text = build_env("tok", "123", "", "keep-owner", "keep-view")
        self.assertIn("SCRIPTCHECK_ACCESS_TOKEN=keep-owner", text)
        self.assertIn("SCRIPTCHECK_VIEW_TOKEN=keep-view", text)

    def test_the_view_token_reaches_the_config(self):
        import os

        from scriptcheck.config import Config

        saved = os.environ.get("SCRIPTCHECK_VIEW_TOKEN")
        os.environ["SCRIPTCHECK_VIEW_TOKEN"] = "team-link"
        try:
            self.assertEqual(Config.load().view_token, "team-link")
        finally:
            os.environ.pop("SCRIPTCHECK_VIEW_TOKEN", None)
            if saved is not None:
                os.environ["SCRIPTCHECK_VIEW_TOKEN"] = saved


class TestDeployHelper(unittest.TestCase):
    def setUp(self):
        import tempfile
        from pathlib import Path

        self.dir = Path(tempfile.mkdtemp())
        (self.dir / ".env").write_text(
            "# comment\n"
            "DISCORD_BOT_TOKEN=tok\n"
            "SCRIPTCHECK_MY_USER_ID=111\n"
            "SCRIPTCHECK_WEBHOOK_URL=https://hook?a=b\n"
            "SCRIPTCHECK_ACCESS_TOKEN=mine\n"
            "SCRIPTCHECK_VIEW_TOKEN=theirs\n"
        )

    def test_every_variable_makes_it_into_the_block(self):
        import json

        from scriptcheck.deploy import railway_env, read_env

        env = read_env(self.dir / ".env")
        block = railway_env(env, {"my_roles": ["SCRIPT"], "dropbox_channel_patterns": ["my-assignments"]})
        for expected in [
            "DISCORD_BOT_TOKEN=tok",
            "SCRIPTCHECK_ACCESS_TOKEN=mine",
            "SCRIPTCHECK_VIEW_TOKEN=theirs",
            "SCRIPTCHECK_WEBHOOK_URL=https://hook?a=b",
        ]:
            self.assertIn(expected, block)

    def test_the_config_is_one_line_and_valid_json(self):
        import json

        from scriptcheck.config import Config
        from scriptcheck.deploy import railway_env, read_env

        block = railway_env(
            read_env(self.dir / ".env"),
            {"my_roles": ["SCRIPT"], "dropbox_channel_patterns": ["my-assignments"]},
        )
        line = [l for l in block.splitlines() if l.startswith("SCRIPTCHECK_CONFIG=")][0]
        self.assertEqual(len(line.splitlines()), 1)
        parsed = json.loads(line.split("=", 1)[1])
        Config.from_dict(parsed)  # must be loadable as-is

    def test_overrides_are_moved_onto_the_volume(self):
        from scriptcheck.deploy import hosted_config

        hosted = hosted_config({"overrides_file": "data/overrides.json"})
        self.assertEqual(hosted["overrides_file"], "/data/overrides.json")

    def test_an_incomplete_env_is_reported(self):
        from scriptcheck.deploy import missing, read_env

        (self.dir / ".env").write_text("SCRIPTCHECK_MY_USER_ID=111\n")
        self.assertIn("DISCORD_BOT_TOKEN", missing(read_env(self.dir / ".env")))

    def test_a_missing_file_is_empty_not_an_error(self):
        from scriptcheck.deploy import read_env

        self.assertEqual(read_env("/nonexistent/.env"), {})
