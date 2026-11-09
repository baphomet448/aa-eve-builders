"""Forms"""

# Django
from django import forms
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

# AA EVE Builders
from evebuilders.catalog import catalog_types
from evebuilders.models import Destination, Order


class OrderForm(forms.Form):
    """Create a corporate order"""

    # Shown to the manager; the order form's JS fills it from the search results
    item_text = forms.CharField(
        label=_("Item"),
        required=False,
        widget=forms.TextInput(
            attrs={
                "autocomplete": "off",
                "placeholder": _("Start typing the item name"),
            }
        ),
    )
    # What is actually saved: the id of the picked item
    eve_type_id = forms.IntegerField(
        widget=forms.HiddenInput,
        error_messages={"required": _("Please pick an item from the list.")},
    )
    quantity = forms.IntegerField(label=_("Quantity"), min_value=1)
    unit_price = forms.DecimalField(
        label=_("Price per unit (ISK)"),
        min_value=0,
        max_digits=20,
        decimal_places=2,
        widget=forms.NumberInput(attrs={"step": "1"}),
    )
    priority = forms.ChoiceField(
        label=_("Priority"),
        choices=Order.Priority.choices,
        initial=Order.Priority.MEDIUM,
    )
    due_date = forms.DateField(
        label=_("Due date"),
        widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
    )
    access_level = forms.TypedChoiceField(
        label=_("Access level"),
        choices=Order.AccessLevel.choices,
        coerce=int,
        initial=Order.AccessLevel.BASE,
        help_text=_("Builders below this level will not see the order."),
    )
    destination = forms.CharField(
        label=_("Destination"), max_length=255, required=False
    )
    note = forms.CharField(
        label=_("Note"), required=False, widget=forms.Textarea(attrs={"rows": 3})
    )

    def __init__(self, *args, current_destination: str = "", **kwargs):
        super().__init__(*args, **kwargs)
        self._use_the_list_of_places(current_destination)

        for field in self.fields.values():
            if isinstance(field.widget, forms.HiddenInput):
                continue
            css_class = (
                "form-select"
                if isinstance(field.widget, forms.Select)
                else "form-control"
            )
            field.widget.attrs["class"] = css_class

    def _use_the_list_of_places(self, current_destination: str) -> None:
        """
        The destination is picked from the places a manager added in the
        settings. While there are none, it stays a free text.

        :param current_destination: The destination an order has already, it
            stays a choice even when it is not in the list
        """

        labels = list(Destination.objects.values_list("label", flat=True))
        if not labels:
            return

        if current_destination and current_destination not in labels:
            labels.append(current_destination)

        self.fields["destination"] = forms.ChoiceField(
            label=_("Destination"),
            required=False,
            choices=[("", "---------")] + [(label, label) for label in labels],
        )

    def clean_unit_price(self):
        unit_price = self.cleaned_data["unit_price"]
        if unit_price != unit_price.to_integral_value():
            raise forms.ValidationError(_("The price must be a whole number of ISK."))

        return unit_price

    def clean_due_date(self):
        due_date = self.cleaned_data["due_date"]
        if due_date < timezone.localdate():
            raise forms.ValidationError(_("The due date cannot be in the past."))

        return due_date

    def clean(self):
        cleaned_data = super().clean()

        type_id = cleaned_data.get("eve_type_id")
        if type_id is not None:
            eve_type = catalog_types().filter(id=type_id).first()
            if eve_type is None:
                self.add_error("eve_type_id", _("This item is not in the catalog."))
            else:
                cleaned_data["eve_type"] = eve_type

        return cleaned_data


class OrderEditForm(OrderForm):
    """
    Change an order. The same fields as when creating one, with two
    differences: the item is fixed once builders took the order, and the due
    date may stay as it is even when it has passed.
    """

    def __init__(self, *args, order, item_locked: bool, **kwargs):
        super().__init__(*args, current_destination=order.destination, **kwargs)
        self.order = order
        self.item_locked = item_locked

        if item_locked:
            # A disabled field always has its initial value, whatever is posted
            self.fields["item_text"].disabled = True
            self.fields["eve_type_id"].disabled = True

    def clean_due_date(self):
        due_date = self.cleaned_data["due_date"]
        if due_date != self.order.due_date and due_date < timezone.localdate():
            raise forms.ValidationError(_("The due date cannot be in the past."))

        return due_date

    def clean(self):
        if self.item_locked:
            # The item is the order's own, it need not be in the catalog (anymore)
            cleaned_data = forms.Form.clean(self)
            cleaned_data["eve_type"] = self.order.eve_type

            return cleaned_data

        return super().clean()
