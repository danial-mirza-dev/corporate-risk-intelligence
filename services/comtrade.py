"""
UN Comtrade client — legitimate-trade baseline.

Pulls a country's declared trade for a commodity chapter (default HS 27, mineral
fuels & oils) to establish a "legitimate baseline" we can compare an entity's
documented trade against. Used to flag two patterns: documented activity that
exceeds the national baseline (anomaly), and the absence of any documented trade
for an entity that presents as a trading/shipping company (opacity).

Validated endpoint: everything in query params, NUMERIC reporter code, path
.../preview/C/A/HS. No API key required for the public preview tier.
"""

import logging
import time

import requests

from config import COMTRADE_PERIOD, COMTRADE_PREVIEW_URL, HTTP_USER_AGENT
from services.reference import comtrade_code, country_name, hs_description

log = logging.getLogger("services.comtrade")

_HEADERS = {"User-Agent": HTTP_USER_AGENT}


def _get_json(url, params, retries=4):
    last = None
    for attempt in range(1, retries + 1):
        try:
            resp = requests.get(url, params=params, headers=_HEADERS, timeout=45)
            if resp.status_code in (429, 500, 502, 503, 504):
                last = f"HTTP {resp.status_code}"
                time.sleep(1.2 * attempt)
                continue
            if not resp.ok:
                log.warning("Comtrade HTTP %s for %s", resp.status_code, params)
                return None
            return resp.json()
        except (requests.RequestException, ValueError) as e:
            last = repr(e)
            time.sleep(1.2 * attempt)
    log.warning("Comtrade GET failed after %d attempts (%s)", retries, last)
    return None


def get_trade_baseline(reporter_country, hs_code="27", partner_country=None):
    """Declared trade baseline for a country/commodity, or None if unavailable."""
    numeric = comtrade_code(reporter_country)
    if not numeric:
        log.info("Comtrade: no numeric code for %s — skipping baseline", reporter_country)
        return None

    params = {
        "reporterCode": numeric,
        "cmdCode": hs_code,
        "period": COMTRADE_PERIOD,
        "flowCode": "X",          # exports
        "limit": 10,
    }
    if partner_country and comtrade_code(partner_country):
        params["partnerCode"] = comtrade_code(partner_country)

    payload = _get_json(COMTRADE_PREVIEW_URL, params)
    rows = (payload or {}).get("data") if isinstance(payload, dict) else None
    if not rows:
        return None

    total_value = 0.0
    partners = {}
    for row in rows:
        val = row.get("primaryValue") or 0
        try:
            total_value += float(val)
        except (TypeError, ValueError):
            pass
        pc = row.get("partnerCode")
        # Comtrade code 0 = "World" aggregate; skip it as a "partner".
        if pc and int(pc) != 0:
            partners[pc] = partners.get(pc, 0) + (float(val) if val else 0)

    top_partners = sorted(partners.items(), key=lambda kv: kv[1], reverse=True)[:3]
    top_partner_names = [country_name(_iso_from_numeric(c)) or f"Partner {c}"
                         for c, _ in top_partners]

    return {
        "reporter": country_name(reporter_country),
        "year": COMTRADE_PERIOD,
        "hs_code": hs_code,
        "commodity": hs_description(hs_code),
        "total_value": total_value,
        "total_value_display": _format_money(total_value),
        "top_partners": top_partner_names,
    }


def calculate_anomaly(entity_trade_value, baseline_value, is_trading_company=True):
    """Classify entity trade against the national baseline.

    Returns a finding dict, or None when there is simply no basis to render the
    comparison (no baseline available)."""
    # No documented entity trade at all.
    if not entity_trade_value:
        if is_trading_company:
            return {
                "type": "opacity",
                "headline": "No Documented Trade Activity",
                "explanation": (
                    "No documented trade activity found. This is atypical for a "
                    "registered trading or shipping company and may indicate "
                    "operations outside formal trade documentation systems."),
            }
        # Non-trading entity with no shipments: absence is expected, so report it
        # neutrally rather than flagging it as suspicious.
        return {
            "type": "neutral",
            "headline": "No Trade Records",
            "explanation": "No trade records found in Sayari's global trade database.",
        }

    if not baseline_value:
        return None

    gap = ((entity_trade_value - baseline_value) / baseline_value) * 100
    if gap > 20:
        return {
            "type": "anomaly",
            "gap_percent": round(gap, 1),
            "headline": "Trade Anomaly Detected",
            "explanation": (
                f"Documented trade activity exceeds the established legitimate "
                f"baseline for this commodity corridor by {round(gap)}%. This "
                f"discrepancy warrants enhanced due diligence."),
        }
    return {
        "type": "consistent",
        "headline": "Consistent With Baseline",
        "explanation": (
            "Trade activity is consistent with established baselines for this "
            "commodity and country corridor."),
    }


# ---------------------------------------------------------------------------
_NUMERIC_TO_ISO = {
    364: "IRN", 643: "RUS", 784: "ARE", 156: "CHN",
    792: "TUR", 699: "IND", 398: "KAZ",
}


def _iso_from_numeric(code):
    try:
        return _NUMERIC_TO_ISO.get(int(code))
    except (TypeError, ValueError):
        return None


def _format_money(value):
    if not value:
        return None
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    if v >= 1e9:
        return f"${v / 1e9:,.1f} billion"
    if v >= 1e6:
        return f"${v / 1e6:,.1f} million"
    return f"${v:,.0f}"
