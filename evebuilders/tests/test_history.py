"""The tab History of the management: the filter, the sorting and the pages"""

# Standard Library
from datetime import date, datetime
from datetime import timezone as dt_timezone
from urllib.parse import urlencode

# Django
from django.http import QueryDict
from django.test import SimpleTestCase, override_settings
from django.urls import reverse

# AA EVE Builders
from evebuilders.history import PAGE_SIZE, HistoryQuery, history_result
from evebuilders.messages import display_name
from evebuilders.models import OrderEvent
from evebuilders.tests.test_take_discard_views import ViewsTestCase
from evebuilders.tests.test_views import TEST_STORAGES


def params(**values) -> QueryDict:
    """The parameters of an address"""

    return QueryDict(urlencode(values))


class TestHistoryQuery(SimpleTestCase):
    """Reading the address"""

    def test_nothing_gives_the_defaults(self):
        query = HistoryQuery.from_params(params())

        self.assertEqual(query.kind, "")
        self.assertEqual(query.text, "")
        self.assertEqual((query.sort, query.direction), ("when", "desc"))
        self.assertFalse(query.is_filtered)

    def test_what_is_not_valid_is_ignored(self):
        query = HistoryQuery.from_params(
            params(
                kind="NOPE",
                sort="nope",
                dir="up",
                date_from="2026-13-45",
                date_to="abc",
            )
        )

        self.assertEqual(query.kind, "")
        self.assertEqual((query.sort, query.direction), ("when", "desc"))
        self.assertIsNone(query.date_from)
        self.assertIsNone(query.date_to)

    def test_a_filter_is_read(self):
        query = HistoryQuery.from_params(
            params(
                kind="TAKEN", q="  abc ", date_from="2026-11-05", date_to="2026-11-06"
            )
        )

        self.assertEqual(query.kind, "TAKEN")
        self.assertEqual(query.text, "abc")
        self.assertEqual(query.date_from, date(2026, 11, 5))
        self.assertEqual(query.date_to, date(2026, 11, 6))
        self.assertTrue(query.is_filtered)

    def test_the_links_keep_the_filter_and_leave_out_the_defaults(self):
        query = HistoryQuery.from_params(params(kind="TAKEN", q="abc"))

        self.assertEqual(query.params(), {"kind": "TAKEN", "q": "abc"})
        self.assertEqual(
            query.params(sort="kind", dir="asc", page=2),
            {"kind": "TAKEN", "q": "abc", "sort": "kind", "dir": "asc", "page": 2},
        )
        self.assertEqual(query.params(sort="when", dir="desc", page=1), query.params())


class HistoryTestCase(ViewsTestCase):
    """Helpers: events at known moments"""

    def setUp(self):
        OrderEvent.objects.all().delete()

    def _event(self, kind=OrderEvent.Kind.TAKEN, *, order=True, actor=None, **extra):
        when = extra.pop("when", None)
        event = OrderEvent.objects.create(
            order=self.order if order is True else order,
            kind=kind,
            actor=actor,
            description=extra.pop("description", ""),
        )
        if when is not None:
            OrderEvent.objects.filter(pk=event.pk).update(created_at=when)

        return event

    @staticmethod
    def _result(**values):
        return history_result(params(**values))

    def _descriptions(self, **values):
        return [row["event"].description for row in self._result(**values).rows]


class TestFiltering(HistoryTestCase):
    """What matches"""

    def test_by_the_kind_of_the_event(self):
        self._event(OrderEvent.Kind.TAKEN, description="a")
        self._event(OrderEvent.Kind.CANCELLED, description="b")

        self.assertEqual(self._descriptions(kind="CANCELLED"), ["b"])

    def test_by_the_number_of_the_order(self):
        self._event(description="here")
        self._event(order=self.middle, description="there")

        self.assertEqual(self._descriptions(q=self.order.number), ["here"])

    def test_by_the_details(self):
        self._event(description="alpha beta")
        self._event(description="gamma")

        self.assertEqual(self._descriptions(q="BETA"), ["alpha beta"])

    def test_by_who_did_it(self):
        self._event(actor=self.builder, description="by the builder")
        self._event(actor=self.manager, description="by the manager")

        name = display_name(self.builder).split()[0]

        self.assertEqual(self._descriptions(q=name), ["by the builder"])

    def test_by_the_dates_both_days_included(self):
        for day in (4, 5, 6, 7):
            self._event(
                description=f"day {day}",
                when=datetime(2026, 11, day, 12, 0, tzinfo=dt_timezone.utc),
            )

        found = self._descriptions(date_from="2026-11-05", date_to="2026-11-06")

        self.assertEqual(sorted(found), ["day 5", "day 6"])

    def test_the_filters_work_together(self):
        self._event(OrderEvent.Kind.TAKEN, description="wanted")
        self._event(OrderEvent.Kind.CANCELLED, description="wanted too")
        self._event(OrderEvent.Kind.TAKEN, description="other")

        self.assertEqual(self._descriptions(kind="TAKEN", q="wanted"), ["wanted"])


class TestSorting(HistoryTestCase):
    """The order of the rows"""

    def setUp(self):
        super().setUp()
        self._event(
            OrderEvent.Kind.CANCELLED,
            order=self.middle,
            actor=self.manager,
            description="first",
            when=datetime(2026, 11, 1, 12, 0, tzinfo=dt_timezone.utc),
        )
        self._event(
            OrderEvent.Kind.TAKEN,
            actor=self.builder,
            description="second",
            when=datetime(2026, 11, 2, 12, 0, tzinfo=dt_timezone.utc),
        )
        self._event(
            OrderEvent.Kind.CREDITED,
            actor=None,
            description="third",
            when=datetime(2026, 11, 3, 12, 0, tzinfo=dt_timezone.utc),
        )

    def test_the_newest_come_first_by_default(self):
        self.assertEqual(self._descriptions(), ["third", "second", "first"])

    def test_the_oldest_first(self):
        self.assertEqual(
            self._descriptions(sort="when", dir="asc"), ["first", "second", "third"]
        )

    def test_by_the_kind(self):
        self.assertEqual(
            self._descriptions(sort="kind", dir="asc"), ["first", "third", "second"]
        )

    def test_by_who_did_it(self):
        found = self._descriptions(sort="actor", dir="asc")

        # builder character, manager character, and then the one without a name
        self.assertEqual(found.index("second") < found.index("first"), True)

    def test_by_the_number_of_the_order(self):
        by_order = [
            row["event"].order.number
            for row in self._result(sort="order", dir="asc").rows
            if row["event"].order
        ]

        self.assertEqual(by_order, sorted(by_order))

    def test_an_unknown_sorting_is_ignored(self):
        self.assertEqual(self._descriptions(sort="nope"), ["third", "second", "first"])

    def test_the_title_of_a_column_sorted_upwards_turns_the_sorting_down(self):
        result = self._result(sort="kind", dir="asc")

        link = result.sort_links["kind"]
        turned = HistoryQuery.from_params(QueryDict(link["url"].lstrip("?")))

        self.assertEqual(link["arrow"], " ▲")
        self.assertEqual((turned.sort, turned.direction), ("kind", "desc"))
        self.assertEqual(result.sort_links["when"]["arrow"], "")

    def test_the_title_of_a_column_sorted_downwards_turns_the_sorting_up(self):
        result = self._result(sort="kind", dir="desc")

        link = result.sort_links["kind"]

        self.assertEqual(link["arrow"], " ▼")
        self.assertIn("dir=asc", link["url"])


class TestPages(HistoryTestCase):
    """The pages"""

    def setUp(self):
        super().setUp()
        OrderEvent.objects.bulk_create(
            [
                OrderEvent(
                    order=self.order,
                    kind=OrderEvent.Kind.TAKEN,
                    description=f"event {number}",
                )
                for number in range(PAGE_SIZE * 2 + 20)
            ]
        )

    def test_the_pages_have_the_agreed_size(self):
        self.assertEqual(len(self._result().rows), PAGE_SIZE)
        self.assertEqual(len(self._result(page=2).rows), PAGE_SIZE)
        self.assertEqual(len(self._result(page=3).rows), 20)

    def test_a_page_that_does_not_exist_gives_the_last_one(self):
        self.assertEqual(self._result(page=99).page.number, 3)
        self.assertEqual(self._result(page="abc").page.number, 1)

    def test_the_total_is_the_number_of_the_events_that_match(self):
        self.assertEqual(self._result().total, PAGE_SIZE * 2 + 20)

    def test_the_links_between_the_pages_keep_the_filter(self):
        result = self._result(kind="TAKEN", sort="kind", dir="asc", page=2)

        self.assertTrue(result.previous_url.startswith("?"))
        for url in (result.previous_url, result.next_url):
            with self.subTest(url=url):
                self.assertIn("kind=TAKEN", url)
                self.assertIn("sort=kind", url)
                self.assertIn("dir=asc", url)

    def test_the_first_page_has_no_previous_and_the_last_no_next(self):
        self.assertEqual(self._result().previous_url, "")
        self.assertEqual(self._result(page=3).next_url, "")

    def test_the_current_page_is_marked(self):
        pages = self._result(page=2).pages

        self.assertEqual([item["number"] for item in pages if item.get("current")], [2])


@override_settings(STORAGES=TEST_STORAGES)
class TestTheTab(HistoryTestCase):
    """The page"""

    def _get(self, user=None, **values):
        self.client.force_login(user or self.manager)

        return self.client.get(reverse("evebuilders:management_history"), values)

    def test_only_managers_get_in(self):
        url = reverse("evebuilders:management_history")

        self.assertEqual(self.client.get(url).status_code, 302)
        self.assertEqual(self._get(self.builder).status_code, 302)
        self.assertEqual(self._get().status_code, 200)

    def test_the_events_are_listed(self):
        self._event(description="Took five items")

        response = self._get()

        self.assertContains(response, "Took five items")
        self.assertContains(response, "Events: 1")

    def test_the_filter_keeps_what_was_asked(self):
        self._event(OrderEvent.Kind.CANCELLED, description="gone")

        response = self._get(kind="CANCELLED", q="gone")

        self.assertContains(response, 'value="gone"')
        self.assertContains(response, 'value="CANCELLED" selected')

    def test_nothing_that_matches_is_said_so(self):
        self._event(description="something")

        response = self._get(q="no such thing")

        self.assertContains(response, "Nothing matches the filter.")

    def test_without_events_and_without_a_filter(self):
        response = self._get()

        self.assertContains(response, "Nothing has happened yet.")
