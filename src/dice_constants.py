"""
Constants and URL mappings for Dice.com Job Scraper.

Dice uses server-rendered HTML (Next.js SSR) — all job data is in the initial
HTML response. No headless browser needed.

Dice does NOT require geoId resolution — location strings are passed directly
in the URL. Filters are native URL params, not embedded in keywords.
"""

# ── Base URLs ─────────────────────────────────────────────────────────────────
DICE_SEARCH_URL = "https://www.dice.com/jobs"
DICE_JOB_URL = "https://www.dice.com/job-detail/{job_id}"

# ── Date posted filter (Dice uses simple enums) ───────────────────────────────
POSTED_DATE_MAP = {
    "anyTime": "",
    "pastDay": "ONE",
    "pastWeek": "SEVEN",
    "pastMonth": "THIRTY",
}

# ── Employment type filter (Dice uses native URL params) ──────────────────────
EMPLOYMENT_TYPE_MAP = {
    "F": "FULL_TIME",
    "P": "PART_TIME",
    "C": "CONTRACTS",
    "T": "TEMPORARY",
    "I": "INTERNSHIP",
    "V": "VOLUNTEER",
    "":  "",
}

# Human-readable label for post-filtering (matches LinkedIn output schema)
CONTRACT_TYPE_LABEL_MAP = {
    "FULL_TIME": "Full-time",
    "PART_TIME": "Part-time",
    "CONTRACTS": "Contract",
    "TEMPORARY": "Temporary",
    "INTERNSHIP": "Internship",
    "VOLUNTEER": "Volunteer",
    "CONTRACTOR": "Contract",  # Dice JSON-LD uses "CONTRACTOR"
    "FULLTIME": "Full-time",
    "PARTTIME": "Part-time",
}

# ── Work type filter ──────────────────────────────────────────────────────────
WORK_TYPE_MAP = {
    "1": "On-Site",
    "2": "Remote",
    "3": "Hybrid",
}

# ── Experience level → keyword embedding (Dice has no native exp filter) ──────
EXPERIENCE_LEVEL_KEYWORD_MAP = {
    "1": "Internship",
    "2": "Entry Level",
    "3": "Associate",
    "4": "Mid-Senior Level",
    "5": "Director",
    "6": "Executive",
}

# ── Dice returns ~25 results per page ─────────────────────────────────────────
PAGE_SIZE = 25

# ── Request headers ───────────────────────────────────────────────────────────
DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

# ── Delay between requests in seconds (min, max) ──────────────────────────────
REQUEST_DELAY = (1.5, 3.5)