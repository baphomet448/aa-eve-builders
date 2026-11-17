"""Who accepted a contract: the history and the one-time command"""

# Standard Library
from io import StringIO
from unittest.mock import patch

# Third Party
# EVE Universe
from eveuniverse.models import EveEntity

# Django
from django.core.management import call_command

# AA EVE Builders
from evebuilders.models import OrderEvent
from evebuilders.tests.test_names import RESOLVE, keep
from evebuilders.tests.test_sync import SyncTestCase

UNKNOWN_ID = 98698983


class TestTheAcceptorInTheHistory(SyncTestCase):
    """The event of a credit says who accepted the contract"""

    def _finished_by(self, character_id: int) -> dict:
        return self._contract(
            status="finished",
            acceptor_id=character_id,
            date_completed="2026-10-27T11:00:00Z",
        )

    @staticmethod
    def _credited() -> OrderEvent:
        return OrderEvent.objects.get(kind=OrderEvent.Kind.CREDITED)

    def test_an_acceptor_who_is_a_user_of_auth_is_the_actor(self):
        self._process([self._finished()])

        event = self._credited()
        name = self.acceptor.profile.main_character.character_name
        self.assertEqual(event.actor, self.acceptor)
        self.assertEqual(event.actor_label, name)
        self.assertTrue(event.description.endswith(f"accepted by {name}"))

    def test_an_acceptor_that_auth_does_not_know_gets_his_name_from_esi(self):
        keep(UNKNOWN_ID, "Old Officer")

        self._process([self._finished_by(UNKNOWN_ID)])

        event = self._credited()
        self.assertIsNone(event.actor)
        self.assertEqual(event.actor_label, "Old Officer")
        self.assertTrue(event.description.endswith("accepted by Old Officer"))

    def test_when_the_name_cannot_be_found_the_number_is_written(self):
        with patch(RESOLVE, side_effect=RuntimeError("down")):
            self._process([self._finished_by(UNKNOWN_ID)])

        event = self._credited()
        self.assertEqual(event.actor_label, str(UNKNOWN_ID))
        self.assertTrue(event.description.endswith(f"accepted by {UNKNOWN_ID}"))

    def test_without_an_acceptor_nobody_is_named(self):
        self._process([self._finished_by(0)])

        event = self._credited()
        self.assertIsNone(event.actor)
        self.assertEqual(event.actor_label, "")
        self.assertTrue(event.description.endswith("accepted by unknown"))


class TestBackfill(SyncTestCase):
    """The command that fixes the old events"""

    def _old_event(self) -> OrderEvent:
        return OrderEvent.objects.create(
            order=self.order,
            kind=OrderEvent.Kind.CREDITED,
            description=f"Credited 1 x Punisher (contract 5), accepted by {UNKNOWN_ID}",
        )

    @staticmethod
    def _run() -> str:
        out = StringIO()
        call_command("evebuilders_backfill_acceptors", stdout=out)

        return out.getvalue()

    def test_an_old_event_gets_the_name(self):
        event = self._old_event()
        keep(UNKNOWN_ID, "Old Officer")

        output = self._run()

        event.refresh_from_db()
        self.assertEqual(
            event.description,
            "Credited 1 x Punisher (contract 5), accepted by Old Officer",
        )
        self.assertEqual(event.actor_label, "Old Officer")
        self.assertIn("Names written: 1", output)

    def test_it_does_nothing_twice(self):
        event = self._old_event()
        keep(UNKNOWN_ID, "Old Officer")
        self._run()
        event.refresh_from_db()
        text = event.description

        output = self._run()

        event.refresh_from_db()
        self.assertEqual(event.description, text)
        self.assertIn("Names written: 0", output)

    def test_a_name_that_is_not_found_is_left_for_later(self):
        event = self._old_event()

        with patch(RESOLVE, side_effect=RuntimeError("down")):
            output = self._run()

        event.refresh_from_db()
        self.assertTrue(event.description.endswith(str(UNKNOWN_ID)))
        self.assertIn("not found (try again later): 1", output)

    def test_the_user_of_auth_is_found_for_the_old_event(self):
        event = OrderEvent.objects.create(
            order=self.order,
            kind=OrderEvent.Kind.CREDITED,
            description=(
                f"Credited 1 x Punisher (contract 5), accepted by {self.acceptor_id}"
            ),
        )

        self._run()

        event.refresh_from_db()
        self.assertEqual(event.actor, self.acceptor)
        self.assertEqual(
            event.actor_label, self.acceptor.profile.main_character.character_name
        )

    def test_events_with_a_name_are_not_touched(self):
        event = OrderEvent.objects.create(
            order=self.order,
            kind=OrderEvent.Kind.CREDITED,
            description="Credited 1 x Punisher (contract 5), accepted by Someone",
        )

        self._run()

        event.refresh_from_db()
        self.assertEqual(event.actor_label, "")
        self.assertTrue(EveEntity.objects.count() == 0)
