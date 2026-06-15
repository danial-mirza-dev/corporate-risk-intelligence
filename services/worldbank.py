"""
World Bank Worldwide Governance Indicators client.

Pulls three WGI dimensions (Control of Corruption, Rule of Law, Political
Stability) for a country and converts each to a 0-100 percentile with a plain
English reading, plus a composite "opacity" label. Used to characterize the
jurisdiction an entity is registered in.

Validated against the live API: the classic CC.EST / CC.PER.RNK codes are archived
(source 57) and 404-as-error; the live data lives under source 3 with the
GOV_WGI_ prefix, and the *.SC variant is ALREADY a 0-100 governance score. The
World Bank Azure gateway intermittently 502s, so calls retry with backoff.
"""

import logging
import time

import requests

from config import (
    HTTP_USER_AGENT,
    WORLD_BANK_BASE_URL,
    WORLD_BANK_INDICATORS,
    WORLD_BANK_SOURCE,
)
from services.reference import country_name

log = logging.getLogger("services.worldbank")

_HEADERS = {"User-Agent": HTTP_USER_AGENT}


def _get_json(url, params, retries=5):
    """GET returning parsed JSON, retrying on connection errors and 5xx gateway
    failures (the WB Azure front-end flaps). Returns None if all attempts fail."""
    last = None
    for attempt in range(1, retries + 1):
        try:
            resp = requests.get(url, params=params, headers=_HEADERS, timeout=45)
            if resp.status_code in (429, 500, 502, 503, 504):
                last = f"HTTP {resp.status_code}"
                time.sleep(1.5 * attempt)
                continue
            return resp.json()
        except (requests.RequestException, ValueError) as e:
            last = repr(e)
            time.sleep(1.5 * attempt)
    log.warning("World Bank GET failed after %d attempts (%s): %s", retries, last, url)
    return None


def _latest_value(payload):
    """(value, year) from a WB response, or (None, None) for empty/error bodies."""
    if (isinstance(payload, list) and len(payload) >= 2
            and isinstance(payload[1], list) and payload[1]):
        dp = payload[1][0]
        if isinstance(dp, dict):
            return dp.get("value"), dp.get("date")
    return None, None


def _to_percentile(value):
    """The .SC indicators are already 0-100 governance scores. Guard anyway: if a
    value arrives in the estimate range (-2.5..2.5) convert it; otherwise treat it
    as an already-computed percentile."""
    if value is None:
        return None
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    if -2.5 <= v <= 2.5:
        return round(((v + 2.5) / 5.0) * 100, 1)
    return round(v, 1)


def _reading(metric_name, country, percentile):
    """Plain-English one-liner for a single indicator percentile."""
    if percentile is None:
        return f"No {metric_name} data available for {country}."
    p = percentile
    if p >= 75:
        band = "well above average"
    elif p >= 55:
        band = "above average"
    elif p >= 45:
        band = "around the global average"
    elif p >= 25:
        band = "below average"
    else:
        band = "significantly below average"
    return (f"{country} ranks in the {_ordinal(round(p))} percentile globally "
            f"for {metric_name.lower()} — {band}.")


def _opacity_label(composite):
    if composite is None:
        return None, None
    if composite > 60:
        return "Low Opacity Jurisdiction", "low"
    if composite >= 40:
        return "Moderate Opacity Jurisdiction", "moderate"
    if composite >= 20:
        return "High Opacity Jurisdiction", "high"
    return "Very High Opacity Jurisdiction", "very high"


# Large economies where net FDI % GDP is not a meaningful isolation signal.
LARGE_ECONOMIES = {
    "USA", "CHN", "JPN", "DEU", "GBR", "FRA", "IND", "BRA", "CAN", "KOR",
    "AUS", "ESP", "ITA", "NLD", "CHE",
    # ISO-2 equivalents so the check works whichever form arrives.
    "US", "CN", "JP", "DE", "GB", "FR", "IN", "BR", "CA", "KR",
    "AU", "ES", "IT", "NL", "CH",
}


def _interpret_fdi(value, country_code=None):
    if country_code and country_code.upper() in LARGE_ECONOMIES:
        return ("Net FDI as a percentage of GDP is not a meaningful economic "
                "isolation indicator for major economies. This country remains a "
                "significant participant in global trade and investment.")
    if value < 0:
        return ("Negative FDI indicates capital flight — consistent with economic "
                "isolation under sanctions pressure")
    if value < 0.5:
        return "Near-zero foreign investment indicates significant economic isolation"
    if value < 1.5:
        return ("Below-average foreign investment suggests limited international "
                "economic integration")
    if value < 4:
        return "Moderate foreign investment consistent with a functioning open economy"
    if value < 8:
        return ("Above-average foreign investment indicates strong international "
                "economic integration")
    return ("High foreign investment indicates a well-integrated, internationally "
            "open economy")


def get_fdi_data(country_code):
    """FDI net inflows as % of GDP from the World Bank default source, or None.

    Uses the default WDI source (not WGI source 3). The endpoint accepts both ISO-2
    and ISO-3 codes."""
    if not country_code:
        return None
    url = f"{WORLD_BANK_BASE_URL}/country/{country_code}/indicator/BX.KLT.DINV.WD.GD.ZS"
    payload = _get_json(url, {"format": "json", "mrv": 1})
    raw, year = _latest_value(payload)
    log.info("FDI fetch for %s: value=%s year=%s", country_code, raw, year)
    if raw is None:
        return None
    try:
        value = round(float(raw), 2)
    except (TypeError, ValueError):
        return None
    return {"value": value, "year": year,
            "interpretation": _interpret_fdi(value, country_code)}


def get_governance_scores(country_code):
    """Three WGI percentiles + composite opacity reading for a country, or None."""
    if not country_code:
        return None
    cname = country_name(country_code)

    metric_titles = {
        "corruption_control": "Corruption Control",
        "rule_of_law": "Rule of Law",
        "political_stability": "Political Stability",
    }

    result = {}
    percentiles = []
    year = None
    for field, indicator in WORLD_BANK_INDICATORS.items():
        url = f"{WORLD_BANK_BASE_URL}/country/{country_code}/indicator/{indicator}"
        payload = _get_json(url, {"format": "json", "mrv": 1, "source": WORLD_BANK_SOURCE})
        raw, yr = _latest_value(payload)
        pct = _to_percentile(raw)
        if pct is not None:
            percentiles.append(pct)
            year = year or yr
        title = metric_titles[field]
        result[field] = {
            "title": title,
            "percentile": pct,
            "label": _reading(title, cname, pct),
            "band": _score_band(pct),
        }

    if not percentiles:
        log.warning("World Bank: no governance values returned for %s", country_code)
        return None

    composite = round(sum(percentiles) / len(percentiles), 1)
    opacity_label, opacity_band = _opacity_label(composite)
    result["composite_score"] = composite
    result["opacity_label"] = opacity_label
    result["opacity_band"] = opacity_band
    result["opacity_explanation"] = (
        f"Based on three World Bank governance indicators, {cname} presents "
        f"{(opacity_band or 'unknown')} financial opacity risk.")
    result["country_name"] = cname
    result["year"] = year
    result["fdi"] = get_fdi_data(country_code)
    return result


# ---------------------------------------------------------------------------
def _score_band(percentile):
    """green / amber / red band for a percentile (drives gauge colour)."""
    if percentile is None:
        return "grey"
    if percentile >= 55:
        return "green"
    if percentile >= 30:
        return "amber"
    return "red"


def _ordinal(n):
    if 10 <= (n % 100) <= 20:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"
