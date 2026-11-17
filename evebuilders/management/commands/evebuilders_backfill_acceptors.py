"""Write the names of the people who accepted contracts into the history"""

# Standard Library
import re

# Django
from django.core.management.base import BaseCommand

# AA EVE Builders
from evebuilders.matching import user_of_character
from evebuilders.models import OrderEvent
from evebuilders.names import character_names

# The text of an event written when the name of the acceptor was not known
WITH_ID = re.compile(
    r"^(?P<head>Credited .+ \(contract \d+\), accepted by )(?P<id>\d+)$"
)


class Command(BaseCommand):
    """Replace the numbers of the acceptors in the history with their names"""

    help = (
        "Looks up the names of the characters that accepted contracts and are "
        "written down as a number, and writes the names into the history. Safe "
        "to run again."
    )

    def handle(self, *args, **options):
        events = list(
            OrderEvent.objects.filter(
                kind=OrderEvent.Kind.CREDITED, description__regex=r"accepted by [0-9]+$"
            )
        )
        matches = {event: WITH_ID.match(event.description) for event in events}
        ids = {int(match["id"]) for match in matches.values() if match}
        names = character_names(ids, resolve=True)

        fixed = 0
        unknown = 0
        for event, match in matches.items():
            if match is None:
                continue

            character_id = int(match["id"])
            name = names.get(character_id)
            if not name:
                unknown += 1
                continue

            event.description = f"{match['head']}{name}"
            event.actor_label = name
            event.actor = event.actor or user_of_character(character_id)
            event.save(update_fields=["description", "actor", "actor_label"])
            fixed += 1

        self.stdout.write(
            f"Names written: {fixed}. Names not found (try again later): {unknown}."
        )
