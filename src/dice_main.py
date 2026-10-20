"""
Dice.com Job Scraper — Apify Actor (Python)

Dice.com uses server-rendered HTML (Next.js SSR). All job data is in the
initial HTML response — no headless browser, no keyword-embedding hacks.
Filters are native URL params that Dice respects.

Flow:
  1. Read input from Apify
  2. Build search URL with native filter params (employmentType, workplaceTypes, postedDate)
  3. Paginate through Dice /jobs search
  4. For each job card, fetch the detail page (JSON-LD structured data)
  5. Normalize output to match LinkedIn scraper schema
  6. Push matching results to Apify dataset until maxJobs is met

Output fields match the LinkedIn scraper exactly for dataset compatibility:
    title, companyName, companyUrl, location, postedTime, publishedAt,
    description, contractType, experienceLevel, workType, sector,
    salary, applicationsCount, jobUrl, source
"""

import asyncio
import logging
import random
import ssl
from urllib.parse import urlencode, quote_plus

import httpx
from apify import Actor

from dice_constants import (
    DICE_SEARCH_URL,
    DICE_JOB_URL,
    EMPLOYMENT_TYPE_MAP,
    WORK_TYPE_MAP,
    EXPERIENCE_LEVEL_KEYWORD_MAP,
    POSTED_DATE_MAP,
    PAGE_SIZE,
    DEFAULT_HEADERS,
    REQUEST_DELAY,
)
from dice_parser import (
    expected_contract_label,
    matches_selected_job_type,
    parse_job_detail,
    parse_search_results,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)


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

        # Build the keyword query: jobTitle + skills + experienceLevel keyword
        keyword_parts: list[str] = []

        if job_title:
            keyword_parts.append(job_title)

        if skills:
            keyword_parts.append(" ".join(skills))

        # Dice has no native experience level filter — embed in search keywords
        exp_keyword = EXPERIENCE_LEVEL_KEYWORD_MAP.get(experience_level, "")
        if exp_keyword:
            keyword_parts.append(exp_keyword)

        keywords: str = " ".join(keyword_parts)

        # Determine the expected contractType label for post-filtering
        contract_label = expected_contract_label(job_type)

        log.info(
            f"Dice Input → jobTitle='{job_title}' skills={skills} "
            f"location='{location}' datePosted={date_posted} "
            f"jobType={job_type!r} workType={work_type} experienceLevel={experience_level} "
            f"maxJobs={max_jobs}"
        )
        log.info(f"Dice Keywords → {keywords!r}")
        if contract_label:
            log.info(f"Dice expected contractType → {contract_label!r}")

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

        # ── 3. No geoId resolution needed — Dice accepts plain location strings ─

        # ── 4. Paginate & scrape ─────────────────────────────────────────────
        jobs_scraped = 0
        total_skipped = 0
        page = 1  # Dice pages start at 1

        while jobs_scraped < max_jobs:
            search_url = _build_search_url(
                keywords=keywords,
                location=location,
                date_posted=date_posted,
                job_type=job_type,
                work_type=work_type,
                page=page,
            )
            log.info(
                f"Dice Page {page} (scraped={jobs_scraped}/{max_jobs}) → {search_url}"
            )

            proxy_url = await proxy_config.new_url() if proxy_config else None
            html = await _fetch(search_url, proxy_url=proxy_url)
            if not html:
                log.warning(f"Empty response for page {page}, stopping.")
                break

            job_cards = parse_search_results(html)
            if not job_cards:
                log.info("No more Dice job cards found, stopping pagination.")
                break

            log.info(f"  Found {len(job_cards)} cards on this page")

            for card in job_cards:
                if jobs_scraped >= max_jobs:
                    break

                job_id = card["jobId"]
                detail_url = DICE_JOB_URL.format(job_id=job_id)
                log.info(f"  [{jobs_scraped + 1}/{max_jobs}] Dice Detail: {detail_url}")

                await _random_delay()
                proxy_url = await proxy_config.new_url() if proxy_config else None
                detail_html = await _fetch(detail_url, proxy_url=proxy_url)

                if detail_html:
                    full_job = parse_job_detail(detail_html, card)
                else:
                    log.warning(f"  Failed to fetch detail for {job_id}, skipping.")
                    continue

                # ── Post-filter by contractType ──────────────────────────────
                if not matches_selected_job_type(contract_label, full_job):
                    log.info(
                        f"  DICE SKIP (expected={contract_label!r}, "
                        f"badges={full_job.get('_diceDetailBadges')!r}): "
                        f"{full_job.get('title')} @ {full_job.get('companyName')}"
                    )
                    total_skipped += 1
                    continue

                if contract_label == "Contract":
                    full_job["contractType"] = "Contract"

                # Remove internal fields
                full_job.pop("jobId", None)
                full_job.pop("_diceDetailBadges", None)

                await Actor.push_data(full_job)
                jobs_scraped += 1
                log.info(
                    f"  DICE SAVED [{jobs_scraped}/{max_jobs}]: "
                    f"{full_job.get('title')} @ {full_job.get('companyName')} "
                    f"({full_job.get('contractType')}) | {full_job.get('salary')}"
                )

            await _random_delay()
            page += 1

            # Safety net — Dice pagination is generous but not infinite
            if page > 50:
                log.warning("Hit safety page limit (50). Stopping pagination.")
                break

        log.info(
            f"Dice Done. Saved={jobs_scraped}/{max_jobs}, Skipped={total_skipped}, "
            f"Pages={page - 1}"
        )


# ── URL Builder ───────────────────────────────────────────────────────────────

def _build_search_url(
    keywords: str,
    location: str,
    date_posted: str,
    job_type: str,
    work_type: str,
    page: int,
) -> str:
    """
    Construct the Dice.com job search URL with native filter params.

    Dice uses clean, RESTful params — no keyword-embedding hacks needed.
    Filters: employmentType, workplaceTypes, postedDate are all first-class params.

    Example:
        /jobs?q=data+engineer&countryCode=US&location=United+States
        &filters.employmentType=CONTRACTS&filters.postedDate=SEVEN
        &filters.workplaceTypes=Remote&page=1&pageSize=25
    """
    params: dict[str, str] = {
        "q": keywords if keywords else "",
        "page": str(page),
        "pageSize": str(PAGE_SIZE),
    }

    # Location — Dice accepts plain text
    if location:
        params["location"] = location
        params["countryCode"] = "US"

    # Date posted filter
    if date_posted and date_posted in POSTED_DATE_MAP:
        pd_val = POSTED_DATE_MAP[date_posted]
        if pd_val:
            params["filters.postedDate"] = pd_val

    # Employment type filter (Dice native — very reliable)
    if job_type and job_type in EMPLOYMENT_TYPE_MAP:
        emp_val = EMPLOYMENT_TYPE_MAP[job_type]
        if emp_val:
            params["filters.employmentType"] = emp_val

    # Work type filter (Dice native)
    if work_type and work_type in WORK_TYPE_MAP:
        wt_val = WORK_TYPE_MAP[work_type]
        if wt_val:
            params["filters.workplaceTypes"] = wt_val

    # Build query string with proper encoding
    param_parts = []
    for key, value in params.items():
        param_parts.append(f"{key}={quote_plus(value)}")

    return f"{DICE_SEARCH_URL}?{'&'.join(param_parts)}"


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
                    f"Dice rate limited (429). Waiting {wait}s before "
                    f"retry {attempt}/{retries}…"
                )
                await asyncio.sleep(wait)
            elif response.status_code in (403, 401):
                log.warning(
                    f"Dice access denied ({response.status_code}) for {url}. "
                    f"Attempt {attempt}/{retries}."
                )
                await asyncio.sleep(5 * attempt)
            else:
                log.warning(
                    f"Dice HTTP {response.status_code} for {url}. "
                    f"Attempt {attempt}/{retries}."
                )
                await asyncio.sleep(3)

        except httpx.RequestError as e:
            log.warning(
                f"Dice request error for {url}: {e}. Attempt {attempt}/{retries}."
            )
            await asyncio.sleep(3 * attempt)
        except ssl.SSLError as e:
            log.warning(
                f"Dice SSL error for {url}: {e}. Attempt {attempt}/{retries}."
            )
            await asyncio.sleep(5 * attempt)
        except Exception as e:
            log.warning(
                f"Dice unexpected error for {url}: {e}. Attempt {attempt}/{retries}."
            )
            await asyncio.sleep(3 * attempt)

    log.error(f"Dice all {retries} attempts failed for {url}")
    return None


# ── Utilities ─────────────────────────────────────────────────────────────────

async def _random_delay() -> None:
    """Sleep a random amount of time between requests to avoid rate limiting."""
    delay = random.uniform(*REQUEST_DELAY)
    log.debug(f"Dice sleeping {delay:.1f}s…")
    await asyncio.sleep(delay)


if __name__ == "__main__":
    asyncio.run(main())
