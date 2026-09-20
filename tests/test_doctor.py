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
