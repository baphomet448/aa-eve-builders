"""Corporation contracts: the ESI source (and later the contract sync)"""

# Django
from django.core.exceptions import ValidationError
from django.utils import timezone
from django.utils.translation import gettext as _

# Alliance Auth
from allianceauth.authentication.models import CharacterOwnership

# AA EVE Builders
from evebuilders.models import ContractSource

# The ESI scope needed to read the contracts of a corporation
CONTRACTS_SCOPE = "esi-contracts.read_corporation_contracts.v1"


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