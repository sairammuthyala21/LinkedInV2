"""
HTML parser for LinkedIn job search results and job detail pages.
Extracts all fields visible in the Apify dataset output.
"""

import re
import logging
from datetime import datetime, timezone
from bs4 import BeautifulSoup
from markdownify import markdownify as md

log = logging.getLogger(__name__)


def parse_search_results(html: str) -> list[dict]:
    """
    Parse the LinkedIn jobs search results page.
    Returns a list of dicts with basic job info + job_id for detail fetching.
    """
    soup = BeautifulSoup(html, "lxml")
    jobs = []

    # Each job card — LinkedIn guest page uses div.base-card / div.job-search-card
    cards = soup.select("div.base-card")

    for card in cards:
        try:
            job = _parse_card(card)
            if job:
                jobs.append(job)
        except Exception as e:
            log.warning(f"Failed to parse job card: {e}")

    log.info(f"Parsed {len(jobs)} job cards from search page")
    return jobs


def _parse_card(card) -> dict | None:
    """Extract job metadata from a single search result card."""

    # ── Job ID — from data-entity-urn="urn:li:jobPosting:4365141450" ──────────
    entity_urn = card.get("data-entity-urn", "")
    job_id = entity_urn.split(":")[-1] if entity_urn else ""
    if not job_id or not job_id.isdigit():
        return None

    # ── Job URL — from the <a class="base-card__full-link"> href ──────────────
    link_tag = card.select_one("a.base-card__full-link")
    if not link_tag:
        return None
    raw_href = link_tag.get("href", "")
    # Strip query params — keep only the clean path URL
    job_url = raw_href.split("?")[0].strip()

    # ── Title ─────────────────────────────────────────────────────────────────
    title_tag = card.select_one("h3.base-search-card__title")
    title = title_tag.get_text(strip=True) if title_tag else ""

    # ── Company name ──────────────────────────────────────────────────────────
    company_tag = card.select_one("h4.base-search-card__subtitle a")
    company_name = company_tag.get_text(strip=True) if company_tag else ""

    # ── Company URL ───────────────────────────────────────────────────────────
    company_url = company_tag.get("href", "").split("?")[0].strip() if company_tag else ""

    # ── Location ──────────────────────────────────────────────────────────────
    location_tag = card.select_one("span.job-search-card__location")
    location = location_tag.get_text(strip=True) if location_tag else ""

    # ── Posted time (human) and published date (machine) ──────────────────────
    time_tag = card.select_one("time.job-search-card__listdate, time.job-search-card__listdate--new")
    posted_time = time_tag.get_text(strip=True) if time_tag else ""
    published_at = time_tag.get("datetime", "") if time_tag else ""

    return {
        "jobId": job_id,
        "jobUrl": f"https://www.linkedin.com/jobs/view/{job_id}",
        "title": title,
        "companyName": company_name,
        "companyUrl": company_url,
        "location": location,
        "postedTime": posted_time,
        "publishedAt": published_at,
    }


def parse_job_detail(html: str, base_data: dict) -> dict:
    """
    Parse a LinkedIn job detail page to extract all additional fields.
    Merges with base_data from the search card.

    Fields extracted:
        description, contractType, experienceLevel, workType,
        sector, salary, applicationsCount, companyUrl (fallback)
    """
    soup = BeautifulSoup(html, "lxml")
    result = dict(base_data)

    # ── Description (converted to Markdown to preserve bullets/headers) ─────
    desc_tag = soup.select_one(
        "div.show-more-less-html__markup, "
        "div.description__text, "
        "section.show-more-less-html"
    )
    if desc_tag:
        result["description"] = md(
            str(desc_tag),
            heading_style="ATX",       # use ## style headers
            bullets="-",               # use - for bullet points
            strip=["a"],               # strip hyperlinks (keep text, drop href)
        ).strip()
    else:
        result["description"] = ""

    # ── Job criteria list (Contract Type, Experience Level, Work Type, Sector) ─
    criteria_items = soup.select(
        "ul.description__job-criteria-list li.description__job-criteria-item"
    )
    contract_type = ""
    experience_level = ""
    work_type = ""
    sector = ""

    for item in criteria_items:
        header_tag = item.select_one("h3.description__job-criteria-subheader")
        value_tag = item.select_one("span.description__job-criteria-text")
        if not header_tag or not value_tag:
            continue
        header = header_tag.get_text(strip=True).lower()
        value = value_tag.get_text(strip=True)

        if "employment type" in header or "contract type" in header:
            contract_type = value
        elif "seniority level" in header or "experience level" in header:
            experience_level = value
        elif "job function" in header or "work type" in header:
            work_type = value
        elif "industries" in header or "sector" in header:
            sector = value

    result["contractType"] = contract_type
    result["experienceLevel"] = experience_level
    result["workType"] = work_type
    result["sector"] = sector

    # ── Salary ───────────────────────────────────────────────────────────────
    salary_tag = soup.select_one(
        "div.compensation__salary, "
        "span.compensation__salary-range, "
        "div.salary.compensation__salary"
    )
    result["salary"] = salary_tag.get_text(strip=True) if salary_tag else ""

    # ── Applications count ───────────────────────────────────────────────────
    applicants_tag = soup.select_one(
        "span.num-applicants__caption, "
        "figcaption.num-applicants__caption, "
        "span.applies-number"
    )
    if not applicants_tag:
        # Try broader search
        applicants_tag = soup.find(
            lambda tag: tag.name in ("span", "figcaption")
            and "applicant" in tag.get_text(strip=True).lower()
        )
    result["applicationsCount"] = applicants_tag.get_text(strip=True) if applicants_tag else ""

    # ── Company URL (fill in if missing from card) ───────────────────────────
    if not result.get("companyUrl"):
        company_link = soup.select_one(
            "a[data-tracking-control-name='public_jobs_topcard-org-name'], "
            "a.topcard__org-name-link"
        )
        if company_link:
            result["companyUrl"] = company_link.get("href", "").split("?")[0].strip()

    return result


def _extract_job_id(url: str) -> str | None:
    """Extract the numeric job ID from a LinkedIn job URL.
    Matches IDs that are at least 6 digits (real job IDs are 10 digits).
    """
    match = re.search(r"/jobs/view/(\d{6,})", url)
    return match.group(1) if match else None
