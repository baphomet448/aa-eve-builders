"""Moments are shown in the time zone of the browser"""

# Standard Library
from datetime import datetime, timedelta
from datetime import timezone as dt_timezone

# Django
from django.test import SimpleTestCase, override_settings
from django.urls import reverse
from django.utils import timezone

# AA EVE Builders
from evebuilders.models import ContractSource
from evebuilders.templatetags.evebuilders_extras import local_time
from evebuilders.tests.test_take_discard_views import ViewsTestCase
from evebuilders.tests.test_views import TEST_STORAGES


class TestLocalTimeFilter(SimpleTestCase):
    """The filter gives a <time> element with the UTC text"""

    def test_a_moment_becomes_a_time_element(self):
        moment = datetime(2026, 11, 9, 10, 0, tzinfo=dt_timezone.utc)

        html = local_time(moment)

        self.assertIn('class="evb-local"', html)
        self.assertIn('data-kind="datetime"', html)
        self.assertIn('datetime="2026-11-09T10:00:00+00:00"', html)
        self.assertIn(">2026-11-09 10:00 UTC</time>", html)

    def test_only_the_time(self):
        moment = datetime(2026, 11, 9, 10, 5, tzinfo=dt_timezone.utc)

        html = local_time(moment, "time")

        self.assertIn('data-kind="time"', html)
        self.assertIn(">10:05 UTC</time>", html)

    def test_another_zone_is_turned_into_utc(self):
        moment = datetime(
            2026, 11, 9, 12, 0, tzinfo=dt_timezone(timedelta(hours=2))
        )

        self.assertIn(">2026-11-09 10:00 UTC</time>", local_time(moment))

    def test_nothing_gives_nothing(self):
        self.assertEqual(local_time(None), "")


@override_settings(STORAGES=TEST_STORAGES)
class TestLocalTimeOnThePages(ViewsTestCase):
    """The pages use it"""

    def _get(self, user, name, *args):
        self.client.force_login(user)

        return self.client.get(reverse(f"evebuilders:{name}", args=args))

    def test_the_order_details_show_moments_as_time_elements(self):
        self._take(self.builder, 5)

        response = self._get(self.manager, "order_detail", self.order.pk)

        self.assertContains(response, 'class="evb-local"')

    def test_the_next_check_is_a_time_element_without_server_time(self):
        now = timezone.now()
        ContractSource.objects.create(
            corporation_id=98000001,
            corporation_name="Test Corp",
            last_success_at=now,
            esi_expires_at=now + timedelta(minutes=3),
        )
        self._take(self.builder, 5)

        response = self._get(self.builder, "my_orders")

        self.assertContains(response, 'data-kind="time"')
        self.assertNotContains(response, "server time")

    def test_the_script_is_on_the_page(self):
        response = self._get(self.manager, "orders")

        self.assertContains(response, "time.evb-local")