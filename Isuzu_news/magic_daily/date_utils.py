"""Compatibility wrapper for date utils."""

from .api.date_utils import WEEKDAYS_CN, get_current_date_info, get_lunar_date, set_alapi_token

__all__ = [
    "WEEKDAYS_CN",
    "get_current_date_info",
    "get_lunar_date",
    "set_alapi_token",
]
