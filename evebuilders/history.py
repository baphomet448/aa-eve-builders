"""The tab History of the management: the events of all orders, filtered, sorted, in pages"""

# Standard Library
from dataclasses import dataclass, field
from datetime import date
from urllib.parse import urlencode

# Django
from django.core.paginator import Page, Paginator
from django.db.models import Q
from django.db.models.functions import Coalesce
from django.utils.dateparse import parse_date

# AA EVE Builders
from evebuilders.messages import display_name
from evebuilders.models import OrderEvent

PAGE_SIZE = 50
DEFAULT_SORT = "when"
DEFAULT_DIRECTION = "desc"

# The kinds of events for the filter: (value, name)
EVENT_KINDS = OrderEvent.Kind.choices

# The columns that can be sorted and what they are sorted by
SORT_FIELDS = {
    "when": "created_at",
    "order": "order__number",
    "kind": "kind",
    "actor": "actor_name",
}

# The name of the person who did it: the main character, or the login
ACTOR_NAME = Coalesce(
    "actor__profile__main_character__character_name", "actor__username"
)


def _date(value: str) -> date | None:
    """A date from the address, None if there is none or it is not a date"""

    try:
        return parse_date(value)
    except ValueError:
        return None


@dataclass(frozen=True)
class HistoryQuery:
    """What the address of the page asks for"""

    kind: str = ""
    text: str = ""
    date_from: date | None = None
    date_to: date | None = None
    sort: str = DEFAULT_SORT
    direction: str = DEFAULT_DIRECTION
    page: str = "1"

    @classmethod
    def from_params(cls, params) -> "HistoryQuery":
        """Read the parameters of the address; what is not valid is ignored"""

        kind = params.get("kind", "")
        if kind not in OrderEvent.Kind.values:
            kind = ""

        sort = params.get("sort", DEFAULT_SORT)
        if sort not in SORT_FIELDS:
            sort = DEFAULT_SORT

        direction = params.get("dir", DEFAULT_DIRECTION)
        if direction not in ("asc", "desc"):
            direction = DEFAULT_DIRECTION

        return cls(
            kind=kind,
            text=params.get("q", "").strip(),
            date_from=_date(params.get("date_from", "")),
            date_to=_date(params.get("date_to", "")),
            sort=sort,
            direction=direction,
            page=params.get("page", "1"),
        )

    @property
    def is_filtered(self) -> bool:
        """Whether any filter is set"""

        return bool(self.kind or self.text or self.date_from or self.date_to)

    def params(self, **overrides) -> dict:
        """
        The parameters of an address that keeps this query, with some changed.
        What has its default value is left out.
        """

        values = {
            "kind": self.kind,
            "q": self.text,
            "date_from": self.date_from.isoformat() if self.date_from else "",
            "date_to": self.date_to.isoformat() if self.date_to else "",
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
class HistoryResult:
    """One page of the history and the links around it"""

    query: HistoryQuery
    page: Page
    rows: list[dict]
    sort_links: dict[str, dict]
    pages: list[dict] = field(default_factory=list)
    previous_url: str = ""
    next_url: str = ""

    @property
    def total(self) -> int:
        """How many events match the filter"""

        return self.page.paginator.count


def _filtered(query: HistoryQuery):
    """The events that match the filter, in the order asked for"""

    events = OrderEvent.objects.select_related(
        "order", "actor__profile__main_character"
    ).annotate(actor_name=ACTOR_NAME)

    if query.kind:
        events = events.filter(kind=query.kind)
    if query.text:
        events = events.filter(
            Q(order__number__icontains=query.text)
            | Q(description__icontains=query.text)
            | Q(actor_name__icontains=query.text)
        )
    if query.date_from:
        events = events.filter(created_at__date__gte=query.date_from)
    if query.date_to:
        events = events.filter(created_at__date__lte=query.date_to)

    prefix = "" if query.direction == "asc" else "-"
    column = SORT_FIELDS[query.sort]
    if column == "created_at":
        ordering = [f"{prefix}created_at", f"{prefix}id"]
    else:
        ordering = [f"{prefix}{column}", "-created_at", "-id"]

    return events.order_by(*ordering)


def _sort_link(query: HistoryQuery, column: str) -> dict:
    """The link of a title of a column: sorts by it, or turns the sorting around"""

    if query.sort == column:
        direction = "asc" if query.direction == "desc" else "desc"
        arrow = " ▲" if query.direction == "asc" else " ▼"
    else:
        direction = "desc" if column == "when" else "asc"
        arrow = ""

    return {"url": query.url(sort=column, dir=direction, page=1), "arrow": arrow}


def history_result(params) -> HistoryResult:
    """
    The page of the history that the address asks for.

    :param params: The query parameters of the request (request.GET)
    """

    query = HistoryQuery.from_params(params)
    paginator = Paginator(_filtered(query), PAGE_SIZE)
    page = paginator.get_page(query.page)

    rows = [
        {"event": event, "actor": display_name(event.actor) if event.actor else ""}
        for event in page
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

    return HistoryResult(
        query=query,
        page=page,
        rows=rows,
        sort_links={column: _sort_link(query, column) for column in SORT_FIELDS},
        pages=pages,
        previous_url=(
            query.url(page=page.previous_page_number()) if page.has_previous() else ""
        ),
        next_url=query.url(page=page.next_page_number()) if page.has_next() else "",
    )
