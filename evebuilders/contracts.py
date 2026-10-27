"""Corporation contracts: the ESI source and reading the contracts from ESI"""

# Standard Library
from datetime import datetime
from email.utils import parsedate_to_datetime
from typing import NamedTuple

# Third Party
import requests

# Django
from django.core.exceptions import ValidationError
from django.utils import timezone
from django.utils.translation import gettext as _

# Alliance Auth
from allianceauth.authentication.models import CharacterOwnership

# AA EVE Builders
from evebuilders import __version__
from evebuilders.models import ContractSource

# The ESI scope needed to read the contracts of a corporation
CONTRACTS_SCOPE = "esi-contracts.read_corporation_contracts.v1"

ESI_BASE_URL = "https://esi.evetech.net/latest"
ESI_TIMEOUT = 30  # seconds


class EsiError(Exception):
    """Reading from ESI did not work"""


class EsiTokenError(EsiError):
    """The token cannot be used (revoked, expired for good, refused by ESI)"""


class EsiUnavailable(EsiError):
    """ESI or the network is not available right now (try again later)"""


class FetchResult(NamedTuple):
    """What ESI returned for the corporation contracts"""

    contracts: list
    expires: datetime | None  # until when ESI keeps this answer in its cache


def connect_source(*, user, token) -> ContractSource:
    """
    Make the character of the token the source of the corporation contracts.

    The character must belong to the user, so nobody can plug in a stranger's
    token. The corporation is taken from that character. Connecting again
    replaces the earlier source and clears its error.

    :param user: The manager who connects the token
    :param token: The django-esi token that was just created
    :raises django.core.exceptions.ValidationError: When the character is not
        one of the user's characters
    :return: The (single) contract source
    """

    ownership = (
        CharacterOwnership.objects.filter(
            user=user, character__character_id=token.character_id
        )
        .select_related("character")
        .first()
    )
    if ownership is None:
        raise ValidationError(
            _(
                "The character %(name)s is not on your Auth account. "
                "Add it there first and connect again."
            )
            % {"name": token.character_name}
        )

    character = ownership.character
    source = ContractSource.get_solo() or ContractSource()
    source.corporation_id = character.corporation_id
    source.corporation_name = character.corporation_name
    source.token = token
    source.connected_by = user
    source.connected_at = timezone.now()
    source.token_ok = True
    source.last_error = ""
    source.save()

    return source


def _get(token, path: str, params: dict | None = None):
    """One authenticated GET request to ESI"""

    if token is None:
        raise EsiTokenError("No token is connected")

    try:
        access_token = token.valid_access_token()
    except Exception as ex:  # pylint: disable=broad-exception-caught
        # Whatever the reason (revoked, refresh refused), there is no usable token
        raise EsiTokenError(f"No usable access token: {ex}") from ex

    try:
        response = requests.get(
            f"{ESI_BASE_URL}{path}",
            headers={
                "Authorization": f"Bearer {access_token}",
                "User-Agent": f"aa-eve-builders/{__version__}",
            },
            params=params,
            timeout=ESI_TIMEOUT,
        )
    except requests.RequestException as ex:
        raise EsiUnavailable(f"The ESI request failed: {ex}") from ex

    if response.status_code in (401, 403):
        raise EsiTokenError(f"ESI refused the token (HTTP {response.status_code})")

    if response.status_code != 200:
        raise EsiUnavailable(
            f"ESI answered HTTP {response.status_code}: {response.text[:200]}"
        )

    return response


def _parse_expires(value: str | None) -> datetime | None:
    """The Expires header of an ESI answer as a datetime"""

    if not value:
        return None

    try:
        return parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None


def fetch_corporation_contracts(source: ContractSource) -> FetchResult:
    """
    All contracts ESI lists for the corporation of the source (all pages).

    :raises EsiError: When ESI cannot be read, see EsiTokenError and EsiUnavailable
    """

    path = f"/corporations/{source.corporation_id}/contracts/"
    contracts: list = []
    expires = None
    page = 1
    pages = 1

    while page <= pages:
        response = _get(source.token, path, params={"page": page})
        contracts.extend(response.json())
        expires = _parse_expires(response.headers.get("Expires"))
        pages = int(response.headers.get("X-Pages", 1))
        page += 1

    return FetchResult(contracts=contracts, expires=expires)


def fetch_contract_items(source: ContractSource, contract_id: int) -> list:
    """
    The items of one contract.

    :raises EsiError: When ESI cannot be read, see EsiTokenError and EsiUnavailable
    """

    path = f"/corporations/{source.corporation_id}/contracts/{contract_id}/items/"

    return _get(source.token, path).json()