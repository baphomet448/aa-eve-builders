"""Load the names of all solar systems from ESI into the local index"""

# Django
from django.core.management.base import BaseCommand, CommandError

# AA EVE Builders
from evebuilders.contracts import EsiError
from evebuilders.places import load_system_index


class Command(BaseCommand):
    """Management command: evebuilders_load_systems"""

    help = (
        "Reads the names of all solar systems from ESI into the plugin, so that "
        "systems can be searched by a part of the name when places are added. "
        "This also happens by itself at the first search; run it to refresh the "
        "names or to have them ready."
    )

    def handle(self, *args, **options):
        try:
            count = load_system_index()
        except EsiError as ex:
            raise CommandError(str(ex)) from ex

        self.stdout.write(f"{count} solar systems are in the index.")
