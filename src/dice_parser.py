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

log = logging.getLogger(__name__)


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

    # ── Company name — from the company link ─────────────────────────────
    company_link = card.select_one('a[href*="/company-profile/"]')
    company_name = ""
    company_url = ""
    if company_link:
        company_name = company_link.get_text(strip=True)
        raw_company_href = company_link.get("href", "")
        company_url = f"https://www.dice.com{raw_company_href.split('?')[0].strip()}" if raw_company_href else ""

    # ── Location — first instance of text-zinc-600 paragraph ──────────────
    zinc_paras = card.select("p.text-zinc-600")
    location = ""
    posted_time = ""
    for p in zinc_paras:
        text = p.get_text(strip=True)
        if text in ("Remote", "On-Site", "Hybrid", "Remote / Hybrid"):
            # Work type is captured separately
            pass
        else:
            location = text

    # ── Posted time — look for patterns like "2h ago", "Today", "3d ago", "Just now" ─
    time_pattern = re.compile(
        r"\b(\d+[dhm] ago|Today|Yesterday|Just now)\b", re.IGNORECASE
    )
    for p in zinc_paras:
        text = p.get_text(strip=True)
        m = time_pattern.search(text)
        if m:
            posted_time = m.group(1)
            break

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

    # ── Work type detection ─────────────────────────────────────────────
    work_type_text = ""
    for p in zinc_paras:
        text = p.get_text(strip=True)
        if text in ("Remote", "On-Site", "Hybrid"):
            work_type_text = text
            break

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

    # Normalize contractType to LinkedIn-style labels
    raw_type = result.get("contractType", "")
    normalized = raw_type
    # Schema.org employment types → human labels
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
    }
    normalized = ld_normalize.get(raw_type.upper(), raw_type) if raw_type else ""
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