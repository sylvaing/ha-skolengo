"""Constants for the Skolengo integration."""

from typing import Final

DOMAIN: Final = "skolengo"

# Config entry data
CONF_SCHOOL: Final = "school"
CONF_PROVIDER: Final = "provider_id"
CONF_TOKENS: Final = "tokens"
CONF_CALLBACK_URL: Final = "callback_url"

# Options
CONF_SCAN_INTERVAL: Final = "scan_interval"
CONF_HOMEWORK_DAYS: Final = "homework_days"
CONF_TIMETABLE_DAYS: Final = "timetable_days"

DEFAULT_SCAN_INTERVAL: Final = 30  # minutes
MIN_SCAN_INTERVAL: Final = 15
MAX_SCAN_INTERVAL: Final = 240
DEFAULT_HOMEWORK_DAYS: Final = 15
DEFAULT_TIMETABLE_DAYS: Final = 7
MAX_DAYS: Final = 60
