"""
HTML parser for Dice.com job search results and job detail pages.

Dice search pages are server-rendered. Job cards contain title, company,
location, date, employment type, salary — all in the initial HTML.
Job detail pages include a <script type="application/ld+json"> block
with structured JobPosting data — far more reliable than CSS selectors.

Output schema matches the LinkedIn scraper for dataset consistency:
    title, companyName, companyUrl, location, postedTime, publishedAt,
    description, contractType, experienceLevel, workType, sector,
    salary, applicationsCount, jobUrl, source
"""

import json
import logging
import re
from bs4 import BeautifulSoup
from markdownify import markdownify as md
from dice_constants import CONTRACT_TYPE_LABEL_MAP, EMPLOYMENT_TYPE_MAP

log = logging.getLogger(__name__)

CORP_TO_CORP_BADGE = re.compile(r"\bcorp[\s-]+to[\s-]+corp\b", re.IGNORECASE)
C2C_MENTION = re.compile(
    r"\b(?:C2C|corp(?:oration)?[\s-]+to[\s-]+corp(?:oration)?)\b",
    re.IGNORECASE,
)
NEGATED_C2C_PREFIX = re.compile(
    r"\b(?:no|not|without|excluding|except|not accepting|"
    r"not considering|not available for|do not accept|don't accept|"
    r"can't do|cannot do|can not do)\s+"
    r"(?:(?:[\w-]+(?:\s+[\w-]+){0,2})\s+(?:or|and|/)\s+)?$",
    re.IGNORECASE,
)
NEGATED_C2C_SUFFIX = re.compile(
    r"^\s+(?:(?:is|are|will be)\s+)?not\s+"
    r"(?:accepted|allowed|considered|eligible)\b",
    re.IGNORECASE,
)


def _has_positive_c2c_mention(value: str) -> bool:
    """Recognize C2C text while ignoring phrases such as 'No C2C'."""
    clean = re.sub(r"[*_~]", "", value)
    for mention in C2C_MENTION.finditer(clean):
        preceding = clean[max(0, mention.start() - 50):mention.start()]
        following = clean[mention.end():mention.end() + 35]
        if NEGATED_C2C_PREFIX.search(preceding) or NEGATED_C2C_SUFFIX.search(following):
            continue
        return True
    return False


def expected_contract_label(job_type: str) -> str:
    """Resolve an input code such as C through Dice's native filter value."""
    return CONTRACT_TYPE_LABEL_MAP.get(EMPLOYMENT_TYPE_MAP.get(job_type, ""), "")


def matches_selected_job_type(expected_label: str, job: dict) -> bool:
    """For Contract, accept a Corp To Corp badge or positive C2C text."""
    if not expected_label:
        return True

    if expected_label == "Contract":
        badge_match = any(
            CORP_TO_CORP_BADGE.search(label)
            for label in job.get("_diceDetailBadges", [])
        )
        return badge_match or any(
            _has_positive_c2c_mention(job.get(field, ""))
            for field in ("title", "description")
        )

    return job.get("contractType", "").strip() == expected_label


# ── Search Results Parsing ────────────────────────────────────────────────────

def parse_search_results(html: str) -> list[dict]:
    """
    Parse the Dice.com jobs search results page (server-rendered HTML).
    Returns a list of dicts with basic job info + job_id for detail fetching.
    """
    soup = BeautifulSoup(html, "lxml")
    jobs = []

    # Each card is a <div data-testid="job-card" role="article">
    cards = soup.select('[data-testid="job-card"]')

    for card in cards:
        try:
            job = _parse_card(card)
            if job:
                jobs.append(job)
        except Exception as e:
            log.warning(f"Failed to parse Dice job card: {e}")

    log.info(f"Parsed {len(jobs)} Dice job cards from search page")
    return jobs


def _parse_card(card) -> dict | None:
    """Extract job metadata from a single Dice search result card."""

    # ── Job GUID (UUID) — from data-job-guid attribute ─────────────────────
    job_guid = card.get("data-job-guid", "")
    if not job_guid:
        return None

    # ── Detail link & title — from the <a> with data-testid="job-search-job-detail-link" ─
    detail_link = card.select_one('[data-testid="job-search-job-detail-link"]')
    if not detail_link:
        return None

    raw_href = detail_link.get("href", "")
    title = detail_link.get_text(strip=True) if detail_link else ""

    # Also check aria-label on the card cover link (more reliable title)
    cover_link = card.select_one('a[aria-label]')
    if cover_link and not title:
        aria = cover_link.get("aria-label", "")
        # Strip "View Details for " prefix
        title = aria.replace("View Details for ", "").strip()

    # ── Company name — from the company profile link ───────────────────
    # The company link contains a <p> with the name inside the <a>
    company_link = card.select_one('a[href*="/company-profile/"] p')
    company_name = ""
    company_url = ""
    if company_link:
        company_name = company_link.get_text(strip=True)
        # Walk up to the parent <a> for the href
        parent_a = company_link.find_parent('a', href=True)
        if parent_a:
            raw_company_href = parent_a.get("href", "")
            company_url = f"https://www.dice.com{raw_company_href.split('?')[0].strip()}" if raw_company_href else ""

    # ── Location & work type — from zinc-600 paragraphs ─────────────
    # Dice has p.text-zinc-600 in TWO areas:
    #   (A) the location/date row — work type, location, separator, date
    #   (B) the badge section — employment type, salary
    # We only want (A). Badges are inside divs with aria-labelledby or bg-zinc-100.
    # Solution: select zinc-600 that is NOT inside a badge container.
    badge_paras = card.select(
        '[aria-labelledby="employmentType-label"] p, '
        '[aria-labelledby="salary-label"] p, '
        '[class*="bg-zinc-100"] p.text-zinc-600'
    )
    badge_texts = {p.get_text(strip=True) for p in badge_paras}

    zinc_paras = card.select("p.text-zinc-600")
    location = ""
    posted_time = ""
    work_type_text = ""

    time_pattern = re.compile(
        r"\b(\d+[dhm] ago|Today|Yesterday|Just now)\b", re.IGNORECASE
    )

    WORK_TYPE_VALUES = {"Remote", "On-Site", "Hybrid", "Remote / Hybrid"}

    for p in zinc_paras:
        text = p.get_text(strip=True)
        # Skip badge paragraphs
        if text in badge_texts:
            continue
        if text in WORK_TYPE_VALUES:
            if not work_type_text:
                work_type_text = text
        elif time_pattern.search(text):
            posted_time = time_pattern.search(text).group(1)
        elif text and text not in ("•", ""):
            # This should be the location — but skip known non-location texts
            if not location:
                location = text

    # ── Employment type badge ──────────────────────────────────────────────
    emp_badge = card.select_one('[aria-labelledby="employmentType-label"] p')
    employment_type = emp_badge.get_text(strip=True) if emp_badge else ""

    # ── Salary badge ─────────────────────────────────────────────────────
    salary_badge = card.select_one('[aria-labelledby="salary-label"] p')
    salary = salary_badge.get_text(strip=True) if salary_badge else ""

    # ── Description snippet — from the line-clamp-2 div ───────────────────
    desc_snippet = ""
    desc_div = card.select_one("p.line-clamp-2")
    if desc_div:
        desc_snippet = desc_div.get_text(strip=True)

    return {
        "jobId": job_guid,
        "title": title,
        "companyName": company_name,
        "companyUrl": company_url,
        "location": location,
        "postedTime": posted_time,
        "publishedAt": "",  # filled from detail page
        "contractType": employment_type,
        "workType": work_type_text,
        "salary": salary,
        "descriptionSnippet": desc_snippet,
    }


# ── Job Detail Parsing (JSON-LD) ──────────────────────────────────────────────

def parse_job_detail(html: str, base_data: dict) -> dict:
    """
    Parse a Dice.com job detail page.

    Primary source: <script type="application/ld+json"> (structured JobPosting data).
    Falls back to HTML selectors if JSON-LD is missing.

    Merges with base_data from the search card and ensures output matches
    the LinkedIn scraper schema.
    """
    soup = BeautifulSoup(html, "lxml")
    result = dict(base_data)
    result["_diceDetailBadges"] = [
        badge.get_text(" ", strip=True)
        for badge in soup.select('[data-testid="job-detail-header-card"] .SeuiInfoBadge')
    ]

    # ── 1. Try JSON-LD structured data (preferred, highly reliable) ─────────
    ld_json_tag = soup.select_one('script[type="application/ld+json"]')
    ld_data = None

    if ld_json_tag:
        try:
            raw_json = ld_json_tag.string
            if raw_json:
                ld_data = json.loads(raw_json)
        except (json.JSONDecodeError, TypeError) as e:
            log.debug(f"Failed to parse JSON-LD: {e}")

    if ld_data:
        _apply_json_ld(result, ld_data)

    # ── 2. Fallback: HTML selectors for any fields still missing ──────────
    _apply_html_fallbacks(soup, result)

    # ── 3. Normalize & format ────────────────────────────────────────────
    _normalize_output(result)

    return result


# ── JSON-LD Extraction ────────────────────────────────────────────────────────

def _apply_json_ld(result: dict, ld: dict) -> None:
    """Populate result dict from JSON-LD JobPosting schema."""

    # Title
    result["title"] = ld.get("title", "") or result.get("title", "")

    # Description (JSON-LD description is HTML, convert to Markdown)
    raw_desc = ld.get("description", "")
    if raw_desc:
        # Sometimes description is plain text, sometimes HTML
        if "<" in raw_desc and ">" in raw_desc:
            result["description"] = md(
                raw_desc,
                heading_style="ATX",
                bullets="-",
                strip=["a"],
            ).strip()
        else:
            result["description"] = raw_desc.strip()

    # Published date
    result["publishedAt"] = ld.get("datePosted", "") or result.get("publishedAt", "")

    # Employment type (JSON-LD uses schema.org values like "CONTRACTOR", "FULL_TIME")
    emp_type = ld.get("employmentType", "")
    if emp_type:
        result["contractType"] = emp_type

    # Hiring organization
    org = ld.get("hiringOrganization", {})
    if isinstance(org, dict):
        result["companyName"] = org.get("name", "") or result.get("companyName", "")
        if not result.get("companyUrl"):
            same_as = org.get("sameAs", "")
            if same_as:
                result["companyUrl"] = same_as

    # Job location
    job_loc = ld.get("jobLocation", {})
    if isinstance(job_loc, dict):
        address = job_loc.get("address", {})
        if isinstance(address, dict):
            parts = []
            for key in ("addressLocality", "addressRegion", "postalCode"):
                val = address.get(key, "")
                if val:
                    parts.append(val)
            if parts:
                result["location"] = ", ".join(parts) or result.get("location", "")

    # Base salary
    salary_obj = ld.get("baseSalary", {})
    if isinstance(salary_obj, dict) and salary_obj:
        min_val = salary_obj.get("minValue", "")
        max_val = salary_obj.get("maxValue", "")
        currency = salary_obj.get("currency", "USD")
        if min_val and max_val:
            result["salary"] = f"{min_val} - {max_val} {currency}"
        elif min_val:
            result["salary"] = f"{min_val}+ {currency}"
        elif max_val:
            result["salary"] = f"{max_val} {currency}"


# ── HTML Fallback Selectors ───────────────────────────────────────────────────

def _apply_html_fallbacks(soup, result: dict) -> None:
    """Fill any still-missing fields from HTML selectors on the detail page."""

    if not result.get("description"):
        desc_el = soup.select_one('[class*="job-description"]') or \
                  soup.select_one('[data-testid="job-description"]')
        if desc_el:
            result["description"] = md(
                str(desc_el), heading_style="ATX", bullets="-", strip=["a"]
            ).strip()

    if not result.get("companyName"):
        company_el = soup.select_one('[data-testid="company-name"]') or \
                     soup.select_one('a[href*="/company-profile/"]')
        if company_el:
            result["companyName"] = company_el.get_text(strip=True)

    if not result.get("location"):
        loc_el = soup.select_one('[data-testid="job-location"]') or \
                 soup.select_one('[class*="location"]')
        if loc_el:
            result["location"] = loc_el.get_text(strip=True)

    if not result.get("postedTime"):
        posted_el = soup.select_one('[class*="posted"] time') or \
                     soup.select_one('[data-testid="posted-date"]')
        if posted_el:
            result["postedTime"] = posted_el.get_text(strip=True)


# ── Output Normalization ──────────────────────────────────────────────────────

def _normalize_output(result: dict) -> None:
    """
    Normalize all fields to match the LinkedIn scraper output schema exactly.
    This ensures datasets from both sources are mergeable.
    """

    # Normalize contractType to LinkedIn-style labels.
    # Dice JSON-LD can return comma-separated values like
    # "CONTRACTOR, FULL_TIME, PART_TIME" — we take the first one.
    raw_type = result.get("contractType", "")
    normalized = ""
    if raw_type:
        # Split on comma, normalize first meaningful value
        parts = [p.strip() for p in raw_type.split(",") if p.strip()]
        ld_normalize = {
            "FULL_TIME": "Full-time",
            "PART_TIME": "Part-time",
            "CONTRACTOR": "Contract",
            "CONTRACTS": "Contract",
            "TEMPORARY": "Temporary",
            "INTERNSHIP": "Internship",
            "VOLUNTEER": "Volunteer",
            "FULLTIME": "Full-time",
            "PARTTIME": "Part-time",
            "PER_DIEM": "Contract",
            "THIRD PARTY": "Contract",
        }
        for part in parts:
            label = ld_normalize.get(part.upper(), "")
            if label:
                normalized = label
                break
        # Fallback: use first part as-is if no mapping found
        if not normalized and parts:
            normalized = parts[0]

    result["contractType"] = normalized

    # Job URL — reconstruct from jobId if not already set
    if not result.get("jobUrl"):
        job_guid = result.get("jobId", "")
        if job_guid:
            result["jobUrl"] = f"https://www.dice.com/job-detail/{job_guid}"

    # Strip internal fields
    result.pop("descriptionSnippet", None)

    # Set source identifier
    result["source"] = "dice"

    # Ensure all LinkedIn schema fields are present
    for field in (
        "title", "companyName", "companyUrl", "location",
        "postedTime", "publishedAt", "description",
        "contractType", "experienceLevel", "workType",
        "sector", "salary", "applicationsCount", "jobUrl", "source",
    ):
        if field not in result:
            result[field] = ""

    # Clean up whitespace in all string fields
    for key in result:
        if isinstance(result[key], str):
            result[key] = " ".join(result[key].split())
