"""App Tasks"""

# Standard Library
import logging

# Third Party
from celery import shared_task  # noqa: F401

logger = logging.getLogger(__name__)

# Tasks are added here as the plugin grows