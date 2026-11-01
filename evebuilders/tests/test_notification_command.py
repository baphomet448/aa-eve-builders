"""The test notification command (Discord is mocked out)"""

# Standard Library
from io import StringIO
from unittest.mock import patch

# Django
from django.core.management import call_command
from django.test import SimpleTestCase

# AA EVE Builders
from evebuilders.notifications import DiscordRetry

DELIVER = "evebuilders.management.commands.evebuilders_test_notification.deliver"


class TestTestNotificationCommand(SimpleTestCase):
    """evebuilders_test_notification"""

    def test_reports_the_result_for_every_channel(self):
        out = StringIO()

        with patch(DELIVER, side_effect=["sent", "skipped"]) as mock_deliver:
            call_command("evebuilders_test_notification", stdout=out)

        lines = out.getvalue().splitlines()
        self.assertEqual(mock_deliver.call_count, 2)
        self.assertIn("industry-new-order-ping): sent", lines[0])
        self.assertIn("no webhook is configured", lines[1])

    def test_a_busy_discord_is_reported_not_raised(self):
        out = StringIO()

        with patch(DELIVER, side_effect=DiscordRetry("busy")):
            call_command("evebuilders_test_notification", stdout=out)

        self.assertIn("try again later (busy)", out.getvalue())

    def test_a_refusal_is_explained(self):
        out = StringIO()

        with patch(DELIVER, return_value="rejected"):
            call_command("evebuilders_test_notification", stdout=out)

        self.assertIn("check the webhook URL", out.getvalue())