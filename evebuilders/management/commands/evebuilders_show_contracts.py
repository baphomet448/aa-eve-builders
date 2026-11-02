"""Show the newest corporation contracts as ESI returns them (read only)"""

# Django
from django.core.management.base import BaseCommand, CommandError

# AA EVE Builders
from evebuilders.contracts import (
    EsiError,
    fetch_contract_items,
    fetch_corporation_contracts,
)
from evebuilders.models import ContractSource


class Command(BaseCommand):
    """Management command: evebuilders_show_contracts"""

    help = (
        "Shows the newest contracts of the connected corporation as ESI returns "
        "them. Changes nothing."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--limit", type=int, default=10, help="How many contracts to show"
        )
        parser.add_argument(
            "--items",
            action="store_true",
            help="Also show the items of the contracts that are shown",
        )

    def handle(self, *args, **options):
        source = ContractSource.get_solo()
        if source is None or source.token is None:
            raise CommandError(
                "No ESI source is connected. Connect it on the Settings page first."
            )

        try:
            result = fetch_corporation_contracts(source)
        except EsiError as ex:
            raise CommandError(str(ex)) from ex

        contracts = sorted(
            result.contracts, key=lambda c: c.get("date_issued", ""), reverse=True
        )
        self.stdout.write(
            f"{len(contracts)} contracts, ESI keeps this answer until {result.expires}"
        )

        for contract in contracts[: options["limit"]]:
            self.stdout.write(
                f"{contract.get('contract_id')} {contract.get('status')} "
                f"{contract.get('type')} issuer={contract.get('issuer_id')} "
                f"assignee={contract.get('assignee_id')} "
                f"acceptor={contract.get('acceptor_id')} "
                f"price={contract.get('price')} title={contract.get('title', '')!r}"
            )

            if not options["items"]:
                continue

            try:
                items = fetch_contract_items(source, contract["contract_id"])
            except EsiError as ex:
                self.stdout.write(f"    items: {ex}")
                continue

            for item in items:
                self.stdout.write(
                    f"    type_id={item.get('type_id')} "
                    f"quantity={item.get('quantity')} "
                    f"included={item.get('is_included')}"
                )
