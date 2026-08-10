"""
LinkedIn Job Scraper — Apify Actor (Python) — v2 (keyword-based search)

LinkedIn has changed its job search: filter parameters like f_JT, f_E, f_WT
are no longer respected. Instead, everything must be embedded in the keywords
query string. This version builds a rich keyword string from all input fields
and then post-filters results on our side to match the requested jobType.

Flow:
  1. Read input from Apify
  2. Resolve location → LinkedIn geoId
  3. Build a keyword string: {jobTitle} {skills} {jobTypeKW} {workTypeKW} {expLevelKW}
  4. Paginate through LinkedIn jobs/search using ONLY keywords + geoId + f_TPR
  5. For each job card, fetch the detail page
  6. Post-filter: skip jobs whose contractType doesn't match the requested jobType
  7. Push matching results to Apify dataset until maxJobs is met
"""

import asyncio
import logging
import random
import ssl
from urllib.parse import urlencode

import httpx
from apify import Actor

from constants import DATE_POSTED_MAP, JOB_TYPE_MAP, PAGE_SIZE, REQUEST_DELAY, DEFAULT_HEADERS
from geo_resolver import resolve_geo_id
from parser import parse_job_detail, parse_search_results

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

LINKEDIN_SEARCH_URL = "https://www.linkedin.com/jobs/search/"
LINKEDIN_JOB_URL = "https://www.linkedin.com/jobs/view/{job_id}"

# ── Maps for converting enum codes → human-readable keyword strings ──────────

EXPERIENCE_LEVEL_MAP = {
    "1": "Internship",
    "2": "Entry Level",
    "3": "Associate",
    "4": "Mid-Senior Level",
    "5": "Director",
    "6": "Executive",
}

WORK_TYPE_MAP = {
    "1": "On-site",
    "2": "Remote",
    "3": "Hybrid",
}

# jobType code → keyword string to embed in the search query
JOB_TYPE_KEYWORD_MAP = {
    "F": "Full Time",
    "P": "Part Time",
    "C": "Contract OR Temporary",
    "T": "Temporary",
    "I": "Internship",
    "V": "Volunteer",
    "O": "Other",
}


async def main() -> None:
    async with Actor:
        # ── 1. Read & validate input ─────────────────────────────────────────
        actor_input = await Actor.get_input() or {}

        job_title: str = actor_input.get("jobTitle", "").strip()
        skills: list[str] = [s.strip() for s in actor_input.get("skills", []) if s.strip()]
        location: str = actor_input.get("location", "").strip()
        date_posted: str = actor_input.get("datePosted", "anyTime")
        job_type: str = actor_input.get("jobType", "")
        work_type: str = actor_input.get("workType", "").strip()
        experience_level: str = actor_input.get("experienceLevel", "").strip()
        max_jobs: int = int(actor_input.get("maxJobs", 10))

        if not job_title and not skills and not location:
            await Actor.fail(
                status_message="At least one of 'jobTitle', 'skills', or 'location' is required."
            )
            return

        # ── Build the keyword query ──────────────────────────────────────────
        # LinkedIn now requires filters to be part of the keywords string.
        # Format: "{jobTitle} {skills} {jobTypeKW} {workTypeKW} {expLevelKW}"

        keyword_parts: list[str] = []

        # 1) Job title — use as-is from the client
        if job_title:
            keyword_parts.append(job_title)

        # 2) Skills — append directly
        if skills:
            keyword_parts.append(" ".join(skills))

        # 3) Job type → keyword (C→"Contract OR Temporary", F→"Full Time", etc.)
        jt_keyword = JOB_TYPE_KEYWORD_MAP.get(job_type, "")
        if jt_keyword:
            keyword_parts.append(jt_keyword)

        # 4) Work type → keyword string (2→"Remote", 3→"Hybrid", etc.)
        wt_keyword = WORK_TYPE_MAP.get(work_type, "")
        if wt_keyword:
            keyword_parts.append(wt_keyword)

        # 5) Experience level → keyword string (4→"Mid-Senior Level", etc.)
        el_keyword = EXPERIENCE_LEVEL_MAP.get(experience_level, "")
        if el_keyword:
            keyword_parts.append(el_keyword)

        keywords: str = " ".join(keyword_parts)

        # Determine the expected contractType label for post-filtering
        expected_contract_label = JOB_TYPE_MAP.get(job_type, "")

        log.info(
            f"Input → jobTitle='{job_title}' skills={skills} "
            f"location='{location}' datePosted={date_posted} "
            f"jobType={job_type!r} workType={work_type} experienceLevel={experience_level} "
            f"maxJobs={max_jobs}"
        )
        log.info(f"Keywords → {keywords!r}")
        log.info(f"Expected contractType for post-filter → {expected_contract_label!r}")

        # ── 2. Proxy configuration ───────────────────────────────────────────
        try:
            proxy_config = await Actor.create_proxy_configuration(
                groups=["RESIDENTIAL"],
                country_code="US",
            )
        except Exception as proxy_err:
            log.warning(
                f"Could not create proxy configuration: {proxy_err}. "
                f"Running without proxy."
            )
            proxy_config = None

        # ── 3. Resolve location → geoId ───────────────────────────────────────
        geo_id: str | None = None
        if location:
            proxy_url = await proxy_config.new_url() if proxy_config else None
            geo_id = resolve_geo_id(location, proxy_url=proxy_url)
            if not geo_id:
                log.warning(
                    f"Could not resolve geoId for '{location}'. "
                    f"Proceeding without location filter."
                )

        # ── 4. Paginate & scrape with post-filter ─────────────────────────────
        jobs_scraped = 0
        total_skipped = 0
        page = 0

        while jobs_scraped < max_jobs:
            start_index = page * PAGE_SIZE
            search_url = _build_search_url(
                keywords=keywords,
                geo_id=geo_id,
                date_posted=date_posted,
                start=start_index,
            )
            log.info(
                f"Page {page + 1} (start={start_index}, "
                f"scraped={jobs_scraped}/{max_jobs}) → {search_url}"
            )

            proxy_url = await proxy_config.new_url() if proxy_config else None
            html = await _fetch(search_url, proxy_url=proxy_url)
            if not html:
                log.warning(f"Empty response for page {page + 1}, stopping.")
                break

            job_cards = parse_search_results(html)
            if not job_cards:
                log.info("No more job cards found, stopping pagination.")
                break

            log.info(f"  Found {len(job_cards)} cards on this page")

            for card in job_cards:
                if jobs_scraped >= max_jobs:
                    break

                job_id = card["jobId"]
                detail_url = LINKEDIN_JOB_URL.format(job_id=job_id)
                log.info(f"  [{jobs_scraped + 1}/{max_jobs}] Detail: {detail_url}")

                await _random_delay()
                proxy_url = await proxy_config.new_url() if proxy_config else None
                detail_html = await _fetch(detail_url, proxy_url=proxy_url)

                if detail_html:
                    full_job = parse_job_detail(detail_html, card)
                else:
                    log.warning(f"  Failed to fetch detail for {job_id}, skipping.")
                    continue

                # ── Post-filter by contractType ──────────────────────────────
                if expected_contract_label:
                    actual_label = full_job.get("contractType", "")
                    if actual_label and actual_label != expected_contract_label:
                        log.info(
                            f"  SKIP (expected={expected_contract_label!r}, "
                            f"actual={actual_label!r}): "
                            f"{full_job.get('title')} @ {full_job.get('companyName')}"
                        )
                        total_skipped += 1
                        continue

                # Remove internal jobId field
                full_job.pop("jobId", None)

                await Actor.push_data(full_job)
                jobs_scraped += 1
                log.info(
                    f"  SAVED [{jobs_scraped}/{max_jobs}]: "
                    f"{full_job.get('title')} @ {full_job.get('companyName')} "
                    f"({full_job.get('contractType')})"
                )

            await _random_delay()
            page += 1

            # Safety net — LinkedIn guest search caps around ~40 pages
            if page > 40:
                log.warning("Hit safety page limit (40). Stopping pagination.")
                break

        log.info(
            f"Done. Saved={jobs_scraped}/{max_jobs}, Skipped={total_skipped}, "
            f"Pages={page}"
        )


# ── URL Builder ───────────────────────────────────────────────────────────────

def _build_search_url(
    keywords: str,
    geo_id: str | None,
    date_posted: str,
    start: int = 0,
) -> str:
    """Construct the LinkedIn job search URL.

    Uses ONLY keywords + geoId + f_TPR (date posted).
    No f_JT, f_E, f_WT — LinkedIn ignores them on the guest endpoint.
    """
    params: dict[str, str | int] = {
        "keywords": keywords,
        "start": start,
        "position": 1,
        "pageNum": start // PAGE_SIZE,
    }

    if geo_id:
        params["geoId"] = geo_id

    if date_posted:
        tpr = DATE_POSTED_MAP.get(date_posted, "")
        if tpr:
            params["f_TPR"] = tpr

    return f"{LINKEDIN_SEARCH_URL}?{urlencode(params)}"


# ── HTTP Fetch ────────────────────────────────────────────────────────────────

async def _fetch(url: str, proxy_url: str | None = None, retries: int = 3) -> str | None:
    """Fetch a URL with retry logic. Returns HTML string or None on failure."""

    for attempt in range(1, retries + 1):
        try:
            async with httpx.AsyncClient(
                headers=DEFAULT_HEADERS,
                proxy=proxy_url,
                timeout=30,
                follow_redirects=True,
            ) as client:
                response = await client.get(url)

            if response.status_code == 200:
                return response.text

            if response.status_code == 429:
                wait = 10 * attempt
                log.warning(
                    f"Rate limited (429). Waiting {wait}s before "
                    f"retry {attempt}/{retries}…"
                )
                await asyncio.sleep(wait)
            elif response.status_code in (403, 401):
                log.warning(
                    f"Access denied ({response.status_code}) for {url}. "
                    f"Attempt {attempt}/{retries}."
                )
                await asyncio.sleep(5 * attempt)
            else:
                log.warning(
                    f"HTTP {response.status_code} for {url}. "
                    f"Attempt {attempt}/{retries}."
                )
                await asyncio.sleep(3)

        except httpx.RequestError as e:
            log.warning(
                f"Request error for {url}: {e}. Attempt {attempt}/{retries}."
            )
            await asyncio.sleep(3 * attempt)
        except ssl.SSLError as e:
            log.warning(
                f"SSL error for {url}: {e}. Attempt {attempt}/{retries}."
            )
            await asyncio.sleep(5 * attempt)
        except Exception as e:
            log.warning(
                f"Unexpected error for {url}: {e}. Attempt {attempt}/{retries}."
            )
            await asyncio.sleep(3 * attempt)

    log.error(f"All {retries} attempts failed for {url}")
    return None


# ── Utilities ─────────────────────────────────────────────────────────────────

async def _random_delay() -> None:
    """Sleep a random amount of time between requests to avoid rate limiting."""
    delay = random.uniform(*REQUEST_DELAY)
    log.debug(f"Sleeping {delay:.1f}s…")
    await asyncio.sleep(delay)


if __name__ == "__main__":
    asyncio.run(main())
