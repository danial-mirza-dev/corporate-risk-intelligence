"""
Analysis layer — turns raw service output into the derived intelligence the
dossier renders: an overall risk rating, a chronological network timeline, and a
trade-pattern classification.

Pure functions over already-translated service data — no network calls here.
"""

import re


def compute_risk_rating(profile, watchlist, ubo):
    """HIGH / MEDIUM / LOW from sanctions status, severe risk flags, network
    proximity, and elevated contextual flags — tiered so the rating reflects every
    risk factor, not just direct sanctions."""
    profile = profile or {}
    watchlist = watchlist or {}
    risk_keys = [r.get("key") for r in profile.get("risk_factors", [])]

    # Critical flags — always HIGH.
    critical_flags = {
        "sanctioned", "sanctioned_usa_ofac_sdn", "ofac_sdgt_sanctioned",
        "reputational_risk_terrorism", "reputational_risk_organized_crime",
    }
    if profile.get("sanctioned") or any(f in risk_keys for f in critical_flags):
        return "HIGH"

    # Serious flags — HIGH if two or more, MEDIUM if one.
    serious_flags = {
        "export_controls", "law_enforcement_action", "regulatory_action",
        "reputational_risk_financial_crime", "reputational_risk_bribery_and_corruption",
        "forced_labor_xinjiang_origin_subtier", "formerly_sanctioned",
        "owner_of_sanctioned_usa_ofac_sdn_entity", "sanctioned_adjacent",
    }
    serious_count = sum(1 for f in serious_flags if f in risk_keys)
    if serious_count >= 2:
        return "HIGH"
    if serious_count == 1:
        return "MEDIUM"

    # Network proximity to sanctioned parties — MEDIUM.
    if (watchlist.get("path_count", 0) or 0) > 0:
        return "MEDIUM"

    # Elevated contextual flags — MEDIUM.
    elevated_flags = {
        "state_owned", "chinese_soe_adjacent", "soe_adjacent",
        "pep_adjacent", "eu_high_risk_third", "xinjiang_geospatial",
        "reputational_risk_modern_slavery", "reputational_risk_cybercrime",
    }
    if any(f in risk_keys for f in elevated_flags):
        return "MEDIUM"

    return "LOW"


def build_key_finding(entity_name, profile, watchlist):
    """A single, entity-specific finding sentence assembled from real data points:
    a named sanctioned connection (if any), incorporation date, country, and the
    sanctioned-connection count. Used for the deterministic fallback so it never
    reads as a generic line that could apply to any sanctioned company."""
    profile = profile or {}
    watchlist = watchlist or {}
    # Primary (first) jurisdiction only — listing every country reads as a dump.
    country = (profile.get("countries") or "").split(",")[0].strip() \
        or "an undisclosed jurisdiction"
    founded = profile.get("incorporation_display")        # e.g. "Founded October 2018"
    path_count = watchlist.get("path_count") or 0
    sanctioned = profile.get("sanctioned")
    # Never let non-Latin script into the summary sentence.
    entity_name = _latin_name(entity_name, profile, country)
    notable = _notable_sanctioned_name(profile, watchlist)

    # Subject clause (company type is shown elsewhere; kept out here for clean grammar).
    subject = f"{entity_name}, registered in {country}"
    if founded:
        subject += " and " + str(founded).replace("Founded", "incorporated").strip()

    # Risk clause.
    if sanctioned:
        risk = "is a sanctioned entity"
    elif path_count:
        risk = "is not directly sanctioned but sits within a sanctioned network"
    else:
        risk = "shows no direct sanctions exposure in the available data"

    # Concrete detail clause.
    if notable and path_count:
        detail = (f", with documented links to {notable} and "
                  f"{_plural(path_count, 'sanctioned connection')} in its corporate "
                  f"network")
    elif notable:
        detail = f", with documented links to {notable}"
    elif path_count:
        detail = f", with {_plural(path_count, 'sanctioned connection')} in its corporate network"
    else:
        detail = ""

    return f"{subject} {risk}{detail}."


def _notable_sanctioned_name(profile, watchlist):
    """Most notable sanctioned connection name (Latin form), preferring direct
    relationships, then watchlist paths."""
    for r in (profile or {}).get("relationships", []):
        if r.get("sanctioned") and (r.get("label") or r.get("translated_label")):
            return _latin_name(r.get("label"), r, None)
    for p in (watchlist or {}).get("paths", []):
        if p.get("sanctioned") and (p.get("label") or p.get("translated_label")):
            return _latin_name(p.get("label"), p, None)
    return None


def _is_latin(s):
    """True only if every character is ASCII (code point <= 127)."""
    return bool(s) and all(ord(ch) <= 127 for ch in s)


def _latin_name(name, source, country):
    """A Latin-script display name. Prefers the original if Latin, then a Latin
    `translated_label`, then the original stripped of non-ASCII characters, and
    finally a country-based fallback so non-Latin script never reaches the UI."""
    if _is_latin(name):
        return name
    translated = (source or {}).get("translated_label")
    if _is_latin(translated):
        return translated
    stripped = "".join(ch for ch in (name or "") if ord(ch) <= 127).strip()
    # Collapse whitespace left behind by stripped characters.
    stripped = " ".join(stripped.split())
    if len(stripped) >= 3:
        return stripped
    if country and country != "an undisclosed jurisdiction":
        return f"{country} entity"
    return "Undisclosed entity"


def _plural(n, noun):
    """'1 sanctioned connection' / '4 sanctioned connections' — no parentheticals."""
    try:
        n = int(n or 0)
    except (TypeError, ValueError):
        n = 0
    return f"{n} {noun}" if n == 1 else f"{n} {noun}s"


def network_risk_band(path_count):
    """Plain-English band for the sanctioned-network context line."""
    if path_count >= 10:
        return "high"
    if path_count >= 3:
        return "moderate"
    return "low"


def build_network_timeline(watchlist_data):
    """Connected sanctioned entities that have an incorporation date, sorted oldest
    first, shaped for the D3 timeline."""
    paths = (watchlist_data or {}).get("paths", [])
    nodes = []
    for p in paths:
        raw_date = p.get("incorporation_date")
        year = _year_of(raw_date)
        if year is None:
            continue
        nodes.append({
            "entity_id": p.get("entity_id"),
            "label": p.get("label"),
            "translated_label": p.get("translated_label"),
            "incorporation_date": raw_date,
            "incorporation_display": p.get("incorporation_display"),
            "incorporation_year": year,
            "designation_date": p.get("designation_date"),
            "degree": p.get("degree") or 0,
            "primary_risk_type": _primary_risk_type(p),
            "country_codes": p.get("country_codes", []),
            "countries": p.get("countries"),
            "sanctioned": p.get("sanctioned", False),
        })
    nodes.sort(key=lambda n: (n["incorporation_year"], n["label"] or ""))
    return nodes


def build_undated_nodes(watchlist_data):
    """Sanctioned connections that have no incorporation date — rendered as a list
    below the timeline rather than silently dropped."""
    out = []
    for p in (watchlist_data or {}).get("paths", []):
        if not p.get("sanctioned"):
            continue
        if _year_of(p.get("incorporation_date")) is not None:
            continue
        out.append({
            "entity_id": p.get("entity_id"),
            "label": p.get("label"),
            "designation_program": p.get("designation_program"),
            "countries": p.get("countries"),
            "primary_country": (p.get("country_codes") or [None])[0],
        })
    return out


def detect_trade_pattern(trade_data, comtrade_data, entity_profile):
    """Classify the entity's trade footprint.

    Returns one of: documented_trade, anomaly, opacity, insufficient_data.
    'opacity' is reserved for entities that *present* as trading/shipping firms
    but have zero documented shipments; a non-trading company with zero shipments
    is merely insufficient_data (absence is expected, not suspicious)."""
    has_records = bool(trade_data) and not trade_data.get("empty") and trade_data.get("total")

    if has_records:
        # Anomaly if documented value materially exceeds the national baseline.
        if comtrade_data and comtrade_data.get("total_value"):
            entity_value = _entity_trade_value(trade_data)
            if entity_value and entity_value > comtrade_data["total_value"] * 1.2:
                return "anomaly"
        return "documented_trade"

    # Zero records: software/tech/services firms don't ship goods — expected.
    if _is_services_company(entity_profile):
        return "services_no_trade"
    if _is_trading_company(entity_profile):
        return "opacity"
    return "insufficient_data"


# Company types / names that indicate a software, technology, or services firm
# — entities that legitimately have no physical-goods trade footprint.
SOFTWARE_TYPES = {
    "incorporated", "inc", "software", "technology", "tech",
    "services", "consulting", "saas", "platform", "digital",
    "media", "entertainment", "financial services",
}


def _is_services_company(profile):
    """True for software/technology/services firms (no physical-goods trade)."""
    if not profile:
        return False
    ct = (profile.get("company_type") or "").lower()
    name = (profile.get("label") or "").lower()
    name_words = set(re.findall(r"[a-z]+", name))
    for t in SOFTWARE_TYPES:
        if t in ct:
            return True
        if " " in t and t in name:   # multi-word phrase
            return True
        if t in name_words:          # whole-word match (avoids 'inc' in 'prince')
            return True
    return False


# Jurisdictions where undisclosed ownership signals deliberate opacity.
HIGH_OPACITY_COUNTRIES = {
    "ARE", "PAN", "CYM", "VGB", "BMU", "LIE", "SMR", "MCO",
    "AND", "MHL", "VCT", "BLZ", "ANT", "ABW",
}
FREE_ZONE_TYPES = {"fze", "fzco", "fz", "free zone", "freezone"}


def get_ubo_message(ubo_data, profile):
    """Context-aware beneficial-ownership message. Opacity-jurisdiction / free-zone
    entities get a 'designed to obscure' warning; ordinary private/nonprofit
    structures get a neutral informational note."""
    ubo_data = ubo_data or {}
    profile = profile or {}
    explored = ubo_data.get("explored_count", 0) or 0
    codes = profile.get("country_codes") or []
    company_type = (profile.get("company_type") or "").lower()

    is_opacity_jurisdiction = any(c in HIGH_OPACITY_COUNTRIES for c in codes)
    is_free_zone = any(t in company_type for t in FREE_ZONE_TYPES)

    if is_opacity_jurisdiction or is_free_zone:
        return {
            "title": "Beneficial Ownership Undisclosed",
            "message": (f"Sayari explored {explored:,} connected entities and found no "
                        f"registered beneficial owners. This opacity pattern is "
                        f"consistent with structures designed to obscure ultimate "
                        f"control."),
            "severity": "warning",
        }
    return {
        "title": "Beneficial Ownership Not Available",
        "message": (f"Sayari explored {explored:,} connected entities and found no "
                    f"registered beneficial ownership records in available public "
                    f"registry data. This is common for privately held companies and "
                    f"nonprofit-adjacent structures."),
        "severity": "info",
    }


# ---------------------------------------------------------------------------
# Company types / purposes that would normally generate trade records. Generic
# vehicles (LLC, FZE, holding, consultancy, bank) are deliberately excluded so the
# absence of trade records for them is treated as expected, not suspicious.
_TRADE_TYPE_KEYWORDS = (
    "trading", "shipping", "logistics", "transport", "import", "export",
    "commodit", "petroleum", "oil", "gas", "energy", "freight", "maritime",
    "navigation", "fuel", "minerals", "metals",
)


def _is_trading_company(profile):
    """Should this entity reasonably be expected to have trade records?

    True only when the entity's company type / business purpose points to trade,
    or it carries trade- or export-control-related risk factors. A general LLC,
    holding company, consultancy, or bank — and any entity whose type is unknown —
    returns False, so an absence of trade records is reported neutrally rather than
    flagged as suspicious.
    """
    if not profile:
        return False
    ctype = (profile.get("company_type") or "").strip().lower()
    if ctype and ctype != "not specified":
        if any(k in ctype for k in _TRADE_TYPE_KEYWORDS):
            return True
    # Trade- or export-control-related risk factors also imply expected trade.
    for rf in profile.get("risk_factors", []):
        k = (rf.get("key") or "").lower()
        if "export_control" in k or "trade" in k:
            return True
    return False


def _entity_trade_value(trade_data):
    """Best-effort numeric sum of documented shipment values (often unavailable)."""
    total = 0.0
    found = False
    for s in (trade_data or {}).get("shipments", []):
        disp = s.get("monetary_value")
        if not disp:
            continue
        num = _money_to_float(disp)
        if num is not None:
            total += num
            found = True
    return total if found else None


def _money_to_float(display):
    if not display:
        return None
    s = str(display).replace("$", "").replace(",", "").strip().lower()
    mult = 1.0
    if s.endswith("billion"):
        mult, s = 1e9, s.replace("billion", "").strip()
    elif s.endswith("million"):
        mult, s = 1e6, s.replace("million", "").strip()
    try:
        return float(s) * mult
    except ValueError:
        return None


def _primary_risk_type(path):
    if path.get("sanctioned"):
        return "sanctioned"
    if path.get("pep"):
        return "pep"
    return "export_controls"


def _year_of(date_str):
    if not date_str:
        return None
    head = str(date_str).split("T")[0].split("-")[0]
    if head.isdigit() and len(head) == 4:
        return int(head)
    return None
