"""
Constants and URL mappings for LinkedIn Job Scraper.
"""

LINKEDIN_JOBS_SEARCH_URL = "https://www.linkedin.com/jobs/search/"
LINKEDIN_JOBS_VIEW_URL = "https://www.linkedin.com/jobs/view/{job_id}"
LINKEDIN_GEO_TYPEAHEAD_URL = "https://www.linkedin.com/jobs-guest/api/typeaheadHits"

# f_TPR values — time posted filter
DATE_POSTED_MAP = {
    "anyTime": "",          # no filter
    "pastDay": "r86400",    # past 24 hours
    "pastWeek": "r604800",  # past 7 days
    "pastMonth": "r2592000" # past 30 days
}

# f_JT values — job type filter
JOB_TYPE_MAP = {
    "F": "Full-time",
    "P": "Part-time",
    "C": "Contract",
    "T": "Temporary",
    "I": "Internship",
    "V": "Volunteer",
    "O": "Other",
    "":  "Not Applicable"
}

# LinkedIn returns up to 60 results per page on the guest search endpoint
PAGE_SIZE = 60

# Default search radius — only meaningful for city-level geoIds.
# Country-level geoIds (e.g. "United States") ignore distance entirely.
# Not passed in the URL; LinkedIn uses its own default radius.
DEFAULT_DISTANCE_MILES = 50

# Request headers to mimic a real browser
DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

# Delay between requests in seconds (min, max)
REQUEST_DELAY = (1.5, 3.5)
