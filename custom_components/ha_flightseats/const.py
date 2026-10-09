"""Constants for the FlightSeats.io integration."""

DOMAIN = "ha_flightseats"

API_BASE = "https://flightseats.io"
API_SEARCH_PATH = "/api/v1/search"
REQUEST_TIMEOUT = 30

SUBENTRY_TYPE_WATCH = "watch"

# Watch (subentry) configuration keys
CONF_API_KEY = "api_key"
CONF_NAME = "name"
CONF_PROGRAMS = "programs"
CONF_ORIGINS = "origins"
CONF_DESTINATIONS = "destinations"
CONF_CABINS = "cabins"
CONF_MIN_SEATS = "min_seats"
CONF_MAX_POINTS = "max_points"
CONF_DAYS_AHEAD = "days_ahead"
CONF_DATE_FROM = "date_from"
CONF_DATE_TO = "date_to"
CONF_REWARD_ONLY = "reward_only"
CONF_INTERVAL_HOURS = "interval_hours"
CONF_COOLDOWN_HOURS = "cooldown_hours"

PROGRAMS = ["QF", "VA"]
CABINS = ["ECO", "PRM", "BUS", "FIR"]
PROGRAM_MAX_SEATS = {"QF": 6, "VA": 9}

DEFAULT_PROGRAMS = ["QF"]
DEFAULT_MIN_SEATS = 1
DEFAULT_REWARD_ONLY = True
DEFAULT_INTERVAL_HOURS = 6
DEFAULT_COOLDOWN_HOURS = 12
MIN_INTERVAL_HOURS = 1
MAX_INTERVAL_HOURS = 24
MAX_DAYS_AHEAD = 365
MAX_CODES = 30

# The API rejects searches where origins x destinations x days exceeds this.
MAX_PERMUTATIONS = 10_000
# Used only to estimate permutations when a watch leaves the date window open
# (the API then uses its own per-program search horizon).
ASSUMED_HORIZON_DAYS = 365

# Quota protection. The account allowance is shared with the website and any
# other keys, so these are deliberately conservative.
DEFAULT_DAILY_LIMIT = 200
MIN_REQUEST_SPACING = 7.0  # seconds; the API allows 10 requests per minute
SCHEDULED_RESERVE = 10  # scheduled polls stop at this many requests remaining
MANUAL_FLOOR = 3  # button and search action stop at this many remaining
RESULT_LIMIT = 500

# A match must be missing from this many consecutive complete polls before an
# availability_gone event is raised.
ABSENT_POLLS_BEFORE_GONE = 2
TRANSIENT_FAILURES_BEFORE_UNAVAILABLE = 3

STORAGE_VERSION = 1
MAX_RESULTS_ATTRIBUTE = 10
MAX_EVENT_MATCHES = 5

EVENT_NEW_AVAILABILITY = "new_availability"
EVENT_AVAILABILITY_GONE = "availability_gone"
EVENT_PRICE_DROP = "price_drop"
EVENT_TYPES = [EVENT_NEW_AVAILABILITY, EVENT_AVAILABILITY_GONE, EVENT_PRICE_DROP]

ISSUE_NOT_GOLD = "not_gold"
