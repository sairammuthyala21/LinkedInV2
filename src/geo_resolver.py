"""
Geo ID resolver: converts a human-readable location string
into a LinkedIn geoId using LinkedIn's public typeahead API.
"""

import httpx
import logging

log = logging.getLogger(__name__)

TYPEAHEAD_URL = "https://www.linkedin.com/jobs-guest/api/typeaheadHits"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.linkedin.com/jobs/search/",
    "X-Requested-With": "XMLHttpRequest",
}


def resolve_company_id(company: str, proxy_url: str | None = None) -> str | None:
    """
    Query LinkedIn's public typeahead API to convert a company name
    to a LinkedIn company ID. Returns the ID string, or None if not found.

    Args:
        company:   Company name, e.g. "Microsoft" or "Google"
        proxy_url: Optional proxy URL string

    Returns:
        company ID string (e.g. "1035") or None
    """
    if not company or not company.strip():
        return None

    params = {
        "query": company.strip(),
        "typeaheadType": "COMPANY",
    }

    try:
        with httpx.Client(headers=HEADERS, proxy=proxy_url, timeout=15) as client:
            response = client.get(TYPEAHEAD_URL, params=params)
            response.raise_for_status()
            data = response.json()

        hits = data if isinstance(data, list) else data.get("hits", [])

        if not hits:
            log.warning(f"No company results found for: '{company}'")
            return None

        first = hits[0]
        company_id = str(first.get("id", ""))
        display_name = first.get("displayName", "")
        log.info(f"Resolved company '{company}' → id={company_id} ({display_name})")
        return company_id if company_id else None

    except Exception as e:
        log.error(f"Failed to resolve company ID for '{company}': {e}")
        return None


def resolve_geo_id(location: str, proxy_url: str | None = None) -> str | None:
    """
    Query LinkedIn's public typeahead API to convert a location string
    to a geoId. Returns the geoId string, or None if not found.

    Args:
        location:  Human-readable location, e.g. "Seattle, Washington"
        proxy_url: Optional proxy URL string, e.g. "http://user:pass@host:port"

    Returns:
        geoId string (e.g. "104116203") or None
    """
    if not location or not location.strip():
        return None

    params = {
        "query": location.strip(),
        "typeaheadType": "GEO",
        "geoTypes": "POPULATED_PLACE,ADMIN_DIVISION_2,MARKET_AREA,COUNTRY_REGION",
    }

    try:
        with httpx.Client(headers=HEADERS, proxy=proxy_url, timeout=15) as client:
            response = client.get(TYPEAHEAD_URL, params=params)
            response.raise_for_status()
            data = response.json()

        # The API returns a list of hit objects
        hits = data if isinstance(data, list) else data.get("hits", [])

        if not hits:
            log.warning(f"No geo results found for location: '{location}'")
            return None

        # Take the first result (best match)
        first = hits[0]
        geo_id = str(first.get("id", ""))
        display_name = first.get("displayName", "")
        log.info(f"Resolved '{location}' → geoId={geo_id} ({display_name})")
        return geo_id if geo_id else None

    except Exception as e:
        log.error(f"Failed to resolve geoId for '{location}': {e}")
        return None
