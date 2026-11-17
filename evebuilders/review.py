"""The contracts that wait for a manager to accept them: filtered, sorted, in pages"""

# Standard Library
from dataclasses import dataclass, field
from decimal import Decimal
from urllib.parse import urlencode

# Django
from django.core.paginator import Page, Paginator
from django.db.models import Q, Sum
from django.db.models.functions import Coalesce

# AA EVE Builders
from evebuilders.messages import display_name
from evebuilders.models import ContractRecord

PAGE_SIZE = 50
DEFAULT_SORT = "issued"
DEFAULT_DIRECTION = "asc"

# What each sorting is by. "issued" is the order by default (the oldest contract
# first, so the managers accept them in the order they came); it has no column.
SORT_FIELDS = {
    "issued": "issued_at",
    "order": "order__number",
    "item": "order__eve_type__name",
    "price": "order__unit_price",
    "quantity": "quantity",
    "place": "order__destination",
    "builder": "builder_name",
}

# The columns whose title sorts the table
COLUMNS = ("order", "item", "price", "quantity", "place", "builder")

# The name of the builder: the main character, or the login
BUILDER_NAME = Coalesce(
    "assignment__builder__profile__main_character__character_name",
    "assignment__builder__username",
)


@dataclass(frozen=True)
class ReviewQuery:
    """What the address of the page asks for"""

    text: str = ""
    sort: str = DEFAULT_SORT
    direction: str = DEFAULT_DIRECTION
    page: str = "1"

    @classmethod
    def from_params(cls, params) -> "ReviewQuery":
        """Read the parameters of the address; what is not valid is ignored"""

        sort = params.get("sort", DEFAULT_SORT)
        if sort not in SORT_FIELDS:
            sort = DEFAULT_SORT

        direction = params.get("dir", DEFAULT_DIRECTION)
        if direction not in ("asc", "desc"):
            direction = DEFAULT_DIRECTION

        return cls(
            text=params.get("q", "").strip(),
            sort=sort,
            direction=direction,
            page=params.get("page", "1"),
        )

    @property
    def is_filtered(self) -> bool:
        """Whether a filter is set"""

        return bool(self.text)

    def params(self, **overrides) -> dict:
        """
        The parameters of an address that keeps this query, with some changed.
        What has its default value is left out.
        """

        values = {
            "q": self.text,
            "sort": self.sort,
            "dir": self.direction,
            "page": self.page,
        }
        values.update(overrides)

        if values["sort"] == DEFAULT_SORT:
            values["sort"] = ""
        if values["dir"] == DEFAULT_DIRECTION:
            values["dir"] = ""
        if str(values["page"]) == "1":
            values["page"] = ""

        return {key: value for key, value in values.items() if value not in ("", None)}

    def url(self, **overrides) -> str:
        """The query string of an address, with some parameters changed"""

        return "?" + urlencode(self.params(**overrides))


@dataclass
class ReviewResult:
    """One page of the contracts and the links around it"""

    query: ReviewQuery
    page: Page
    rows: list[dict]
    total: Decimal
    sort_links: dict[str, dict]
    pages: list[dict] = field(default_factory=list)
    previous_url: str = ""
    next_url: str = ""

    @property
    def count(self) -> int:
        """How many contracts match the filter"""

        return self.page.paginator.count


def _filtered(query: ReviewQuery):
    """The contracts that wait for acceptance and match the filter, in order"""

    contracts = (
        ContractRecord.objects.filter(
            state=ContractRecord.State.OUTSTANDING, order__isnull=False
        )
        .select_related(
            "order__eve_type", "assignment__builder__profile__main_character"
        )
        .annotate(builder_name=BUILDER_NAME)
    )

    if query.text:
        contracts = contracts.filter(
            Q(order__number__icontains=query.text)
            | Q(order__eve_type__name__icontains=query.text)
            | Q(order__destination__icontains=query.text)
            | Q(builder_name__icontains=query.text)
        )

    prefix = "" if query.direction == "asc" else "-"
    column = SORT_FIELDS[query.sort]
    if column == "issued_at":
        ordering = [f"{prefix}issued_at", f"{prefix}pk"]
    else:
        ordering = [f"{prefix}{column}", "issued_at", "pk"]

    return contracts.order_by(*ordering)


def _sort_link(query: ReviewQuery, column: str) -> dict:
    """The link of a title of a column: sorts by it, or turns the sorting around"""

    if query.sort == column:
        direction = "asc" if query.direction == "desc" else "desc"
        arrow = " ▲" if query.direction == "asc" else " ▼"
    else:
        direction = "asc"
        arrow = ""

    return {"url": query.url(sort=column, dir=direction, page=1), "arrow": arrow}


def review_result(params) -> ReviewResult:
    """
    The page of the contracts that the address asks for.

    The total is the cost of all the contracts that match the filter, on every
    page, not only on the one that is shown.

    :param params: The query parameters of the request (request.GET)
    """

    query = ReviewQuery.from_params(params)
    contracts = _filtered(query)
    total = contracts.aggregate(total=Sum("price"))["total"] or Decimal("0")

    paginator = Paginator(contracts, PAGE_SIZE)
    page = paginator.get_page(query.page)

    rows = [
        {
            "record": record,
            "builder": (
                display_name(record.assignment.builder) if record.assignment else ""
            ),
        }
        for record in page
    ]

    pages = []
    for number in paginator.get_elided_page_range(
        page.number, on_each_side=2, on_ends=1
    ):
        if number == paginator.ELLIPSIS:
            pages.append({"gap": True})
        else:
            pages.append(
                {
                    "gap": False,
                    "number": number,
                    "current": number == page.number,
                    "url": query.url(page=number),
                }
            )

    return ReviewResult(
        query=query,
        page=page,
        rows=rows,
        total=total,
        sort_links={column: _sort_link(query, column) for column in COLUMNS},
        pages=pages,
        previous_url=(
            query.url(page=page.previous_page_number()) if page.has_previous() else ""
        ),
        next_url=query.url(page=page.next_page_number()) if page.has_next() else "",
    )
