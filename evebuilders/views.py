"""App Views"""

# Django
from django.contrib.auth.decorators import login_required, user_passes_test
from django.core.handlers.wsgi import WSGIRequest
from django.http import HttpResponse
from django.shortcuts import render

# AA EVE Builders
from evebuilders.permissions import has_any_access


@login_required
@user_passes_test(has_any_access)
def index(request: WSGIRequest) -> HttpResponse:
    """
    Index view
    :param request:
    :return:
    """

    context = {"text": "Hello, World!"}

    return render(request, "evebuilders/index.html", context)