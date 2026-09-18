"""clinic/ - shared read-only client for the clinic API.

Owner: whoever takes the clinic lane; every other lane only imports from here.
"""

from __future__ import annotations

from vortex.clinic.client import ClinicApi, ClinicApiError, ClinicClient, FakeClinicClient
from vortex.settings import Settings, get_settings

__all__ = [
    "ClinicApi",
    "ClinicApiError",
    "ClinicClient",
    "FakeClinicClient",
    "make_clinic_client",
]


def make_clinic_client(settings: Settings | None = None) -> ClinicApi:
    """Live client when a platform key exists, fake client otherwise."""
    settings = settings or get_settings()
    if settings.clinic_is_live:
        return ClinicClient(settings.platform_api_base_url, settings.platform_api_key)
    return FakeClinicClient()
