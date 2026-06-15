"""
Synthesis layer — turns the collected intelligence into executive and analyst
briefs via Anthropic.

One API call returns both briefs plus a key finding, confidence, and recommended
action as JSON. The client is constructed explicitly with the base URL and auth
token from config, so it behaves identically inside Claude Code or as a standalone
Flask server. If the call fails for any reason, we fall back to a deterministic,
data-driven brief assembled from the same inputs so the Intelligence Brief card is
never empty.
"""

import json
import logging
import re

import config
from config import ANTHROPIC_MODEL

log = logging.getLogger("services.synthesis")

# Module-level brief cache, keyed by entity_id. Repeated searches for the same
# entity reuse the prior brief instead of re-calling Anthropic. Only successful
# Anthropic briefs are cached, so a transient API failure (which falls back to the
# deterministic brief) can still be retried on a later call.
_brief_cache = {}

SYSTEM_PROMPT = (
    "You are a senior geopolitical risk analyst and sanctions compliance expert "
    "writing intelligence briefs for two audiences simultaneously.\n\n"
    "CRITICAL RULES:\n"
    "1. Both briefs must be specific to THIS entity. Reference its name, its "
    "specific connections, its exact designation program, its specific "
    "jurisdiction. Never write generic compliance language.\n"
    "2. If the entity is SDGT-designated (terrorism financing), this is MORE "
    "serious than a standard SDN designation and must be stated explicitly.\n"
    "3. If named government officials, military figures, or persons of geopolitical "
    "significance appear in the network connections, identify them by name and role.\n"
    "4. If vessel connections exist with multi-jurisdiction flags, note this as a "
    "potential sanctions evasion pattern.\n"
    "5. The executive brief must answer three questions in order: (1) What is this "
    "entity and what is the single most alarming specific fact about it? (2) What "
    "is the legal/business risk in concrete terms? (3) What specific action must be "
    "taken today?\n"
    "6. The analyst brief must reference: specific OFAC designation programs, "
    "relevant regulatory obligations (SAR filing under 31 C.F.R. § 501.604 where "
    "applicable, OFAC 50% Rule where UBO is unclear), confidence assessment based "
    "on data quality, and specific named connections.\n"
    "7. Never start either brief with \"This entity\" — lead with the entity name.\n"
    "8. Executive brief: maximum 4 sentences. Plain English. No acronyms without "
    "explanation.\n"
    "9. Analyst brief: maximum 6 sentences. Technical compliance language. Cite "
    "specific regulations where applicable.\n"
    "10. key_finding: exactly one sentence. The single most surprising or alarming "
    "specific fact. Must name a specific entity, date, person, vessel, or program "
    "— never a generic statement.\n"
    "11. recommended_action: one specific action sentence. Must be actionable "
    "today, not aspirational.\n"
    "12. confidence: HIGH if Sayari, FATF, trade data all present; MEDIUM if some "
    "sources missing; LOW if only partial data.\n"
    "13. CRITICAL: Never fabricate or misstate dates. The designation date is "
    "explicitly provided in the ENTITY INTELLIGENCE PACKAGE as 'Designation date:'. "
    "Use that exact date. Never infer or calculate dates from other information. If "
    "the designation date field shows 2026-05-11, the entity was designated in "
    "2026, not any other year."
)

_MARKDOWN_RE = re.compile(r"(\*\*|\*|__|_|`|#+\s*)")

# Anthropic client — constructed once and reused, pointed at the LiteLLM proxy from
# config. Lazily built so the app still imports if the SDK is absent.
_anthropic_client = None


def _get_client():
    global _anthropic_client
    if _anthropic_client is None:
        import anthropic
        _anthropic_client = anthropic.Anthropic(
            api_key=config.ANTHROPIC_AUTH_TOKEN,
            base_url=config.ANTHROPIC_BASE_URL,
        )
    return _anthropic_client


def _strip_markdown(text):
    if not text:
        return ""
    return _MARKDOWN_RE.sub("", str(text)).strip()


def _plural(n, noun):
    """'1 trade shipment' / '4 trade shipments' — clean plural, no parentheticals."""
    try:
        n = int(n or 0)
    except (TypeError, ValueError):
        n = 0
    return f"{n} {noun}" if n == 1 else f"{n} {noun}s"


# Non-Latin script blocks (Greek, Cyrillic, Hebrew, Arabic, CJK, Kana, Hangul).
_NONLATIN_RE = re.compile(
    "[Ͱ-ϿЀ-ӿ֐-׿؀-ۿ܀-ݏ"
    "぀-ヿ㐀-䶿一-鿿가-힯]+")


def _is_latin(s):
    return bool(s) and all(ord(c) <= 127 for c in s)


def _latinize(label, row=None):
    """Latin form of a label: the original if Latin, else a Latin translated_label,
    else the original stripped of non-ASCII. Returns None if nothing usable remains
    — so non-Latin script never enters the synthesis payload (and thus the briefs)."""
    if _is_latin(label):
        return label
    tl = (row or {}).get("translated_label")
    if _is_latin(tl):
        return tl
    stripped = " ".join("".join(c for c in (label or "") if ord(c) <= 127).split())
    return stripped or None


def _strip_nonlatin(text):
    """Remove any residual non-Latin script runs and tidy the leftover spacing —
    a defense-in-depth guard so no Arabic/Cyrillic/CJK reaches the UI."""
    if not text:
        return text
    cleaned = _NONLATIN_RE.sub("", text)
    cleaned = re.sub(r"\(\s*\)", "", cleaned)          # empty parens left behind
    cleaned = re.sub(r"\s+([,.;)])", r"\1", cleaned)   # space before punctuation
    return re.sub(r"\s{2,}", " ", cleaned).strip()


def generate_brief(entity_name, profile_data, ubo_data, watchlist_data,
                   worldbank_data, comtrade_data, trade_data, risk_rating,
                   trade_pattern=None, designation_date=None, designation_url=None,
                   connection_breakdown=None, fatf_status=None,
                   sanctions_programs=None, fdi_data=None, ubo_message=None):
    """Return {executive, analyst, key_finding, confidence, recommended_action,
    source}. `source` records provenance internally; it is never surfaced in the
    UI."""
    cache_key = (profile_data or {}).get("id") or entity_name
    if cache_key in _brief_cache:
        log.info("synthesis cache hit (%s)", cache_key)
        return dict(_brief_cache[cache_key])
    log.info("synthesis cache miss (%s)", cache_key)

    payload = _build_payload(entity_name, profile_data, ubo_data, watchlist_data,
                             worldbank_data, comtrade_data, trade_data, risk_rating,
                             trade_pattern, designation_date, designation_url,
                             connection_breakdown, fatf_status, sanctions_programs,
                             fdi_data, ubo_message)
    try:
        brief = _call_anthropic(payload)
        if brief:
            brief["source"] = "anthropic"
            _log_briefs(entity_name, brief)
            _brief_cache[cache_key] = dict(brief)
            return brief
    except Exception as e:  # noqa: BLE001 — any SDK/network/parse failure -> fallback
        log.warning("Anthropic synthesis failed (%s) — using deterministic fallback", e)

    fallback = _fallback_brief(entity_name, profile_data, ubo_data, watchlist_data,
                               worldbank_data, comtrade_data, trade_data, risk_rating)
    fallback["source"] = "fallback"
    _log_briefs(entity_name, fallback)
    return fallback


def _log_briefs(entity_name, brief):
    """Log the head of both briefs so we can confirm they are genuinely different."""
    ex = (brief.get("executive") or "")[:150]
    an = (brief.get("analyst") or "")[:150]
    log.info("SYNTHESIS [%s] (%s): executive=%r analyst=%r",
             entity_name, brief.get("source"), ex, an)


# Trade-pattern classification -> plain-English label for the model prompt.
_TRADE_PATTERN_LABELS = {
    "documented_trade": "documented trade activity present",
    "anomaly": "trade volume materially exceeds the national baseline",
    "opacity": "no documented trade despite presenting as a trading company",
    "insufficient_data": "no documented trade (not expected for this entity type)",
}


# ---------------------------------------------------------------------------
def _designation_program(risk_labels):
    if any("SDGT" in r or "Global Terrorist" in r for r in risk_labels):
        return ("OFAC SDGT (Specially Designated Global Terrorist — terrorism "
                "financing authority, E.O. 13224)")
    if any("OFAC SDN" in r for r in risk_labels):
        return "OFAC SDN (Specially Designated National)"
    if any("Export Control" in r for r in risk_labels):
        return "Export Controls"
    return "N/A"


def _breakdown_views(connection_breakdown):
    """Extract direct connections, named individuals, and vessel/flag info."""
    direct, officials, vessels = [], [], []
    for conn in (connection_breakdown or [])[:10]:
        label = _latinize(conn.get("label")) or conn.get("label") or ""
        program = conn.get("designation_program") or ""
        depth = conn.get("path_depth", 99)
        countries = conn.get("countries") or ""
        if conn.get("is_person"):
            officials.append(f"{label} ({countries})")
        if "vessel" in (conn.get("path_description") or "").lower():
            vessels.append(f"{label} (flags: {countries})")
        if depth == 1:
            direct.append(f"{label} — {program}")
    return direct, officials, vessels


def _build_payload(entity_name, profile, ubo, watchlist, worldbank, comtrade,
                   trade, risk_rating, trade_pattern=None, designation_date=None,
                   designation_url=None, connection_breakdown=None, fatf_status=None,
                   sanctions_programs=None, fdi_data=None, ubo_message=None):
    """Compact, model-friendly view of the data (labels, not raw keys)."""
    risk_labels = [r["label"] for r in (profile or {}).get("risk_factors", [])]
    direct, officials, vessels = _breakdown_views(connection_breakdown)
    return {
        "entity_name": entity_name,
        "risk_rating": risk_rating,
        "trade_pattern": _TRADE_PATTERN_LABELS.get(trade_pattern, trade_pattern),
        "designation": {
            "program": _designation_program(risk_labels),
            "Designation date (USE THIS EXACT DATE — DO NOT MODIFY)":
                designation_date or "Not sanctioned",
            "ofac_url": designation_url,
        } if (profile or {}).get("sanctioned") else None,
        "network_named_connections": {
            "direct": direct,
            "named_individuals": officials,
            "vessels_and_flags": vessels,
        } if (direct or officials or vessels) else None,
        "jurisdiction_reference": {
            "fatf_status": (fatf_status or {}).get("label"),
            "fatf_note": (fatf_status or {}).get("note"),
            "sanctions_program_count": (sanctions_programs or {}).get("count"),
            "sanctions_programs": (sanctions_programs or {}).get("programs"),
            "fdi_percent_gdp": (fdi_data or {}).get("value"),
            "fdi_interpretation": (fdi_data or {}).get("interpretation"),
        } if (fatf_status or sanctions_programs or fdi_data) else None,
        "ownership_finding": (ubo_message or {}).get("title"),
        "profile": {
            "country": (profile or {}).get("countries"),
            "company_type": (profile or {}).get("company_type"),
            "status": (profile or {}).get("status"),
            "founded": (profile or {}).get("incorporation_display"),
            "sanctioned": (profile or {}).get("sanctioned"),
            "pep": (profile or {}).get("pep"),
            "network_size": (profile or {}).get("network_size"),
            "risk_factors": [r["label"] for r in (profile or {}).get("risk_factors", [])],
            "key_relationships": [
                {"name": _latinize(r["label"], r),
                 "relationship": r["relationship_type_label"],
                 "sanctioned": r["sanctioned"]}
                for r in (profile or {}).get("relationships", [])[:8]
                if _latinize(r["label"], r)
            ],
        },
        "ownership": ({"undisclosed": True,
                       "entities_explored": ubo.get("explored_count")}
                      if (ubo or {}).get("empty")
                      else {"owners": [_latinize(o["label"], o)
                                       for o in (ubo or {}).get("owners", [])
                                       if _latinize(o["label"], o)]}),
        "sanctioned_network": {
            "connections_found": (watchlist or {}).get("path_count"),
            "entities_explored": (watchlist or {}).get("explored_count"),
            "examples": [_latinize(p["label"], p)
                         for p in (watchlist or {}).get("paths", [])[:8]
                         if _latinize(p["label"], p)],
        },
        "jurisdiction": ({"country": worldbank.get("country_name"),
                          "opacity": worldbank.get("opacity_label"),
                          "corruption_control_percentile": worldbank["corruption_control"]["percentile"],
                          "rule_of_law_percentile": worldbank["rule_of_law"]["percentile"],
                          "political_stability_percentile": worldbank["political_stability"]["percentile"]}
                         if worldbank else None),
        "trade": ({"documented_shipments": trade.get("total"),
                   "sample_commodities": [s["commodity"] for s in trade.get("shipments", [])[:3]]}
                  if not (trade or {}).get("empty")
                  else {"documented_shipments": 0}),
        "trade_baseline": ({"reporter": comtrade.get("reporter"),
                            "commodity": comtrade.get("commodity"),
                            "declared_value": comtrade.get("total_value_display")}
                           if comtrade else None),
    }


def _trim_payload(value):
    """Strip the payload down to the essential fields the brief actually needs.

    Recursively drops None and empty containers, and caps the few list fields so
    we send a lean, model-friendly view — never a raw API dump.
    """
    _list_caps = {
        "risk_factors": 5,
        "key_relationships": 5,
        "owners": 5,
        "examples": 5,
        "sample_commodities": 3,
    }

    def _trim(val, key=None):
        if isinstance(val, dict):
            cleaned = {}
            for k, v in val.items():
                tv = _trim(v, k)
                if tv is not None:
                    cleaned[k] = tv
            return cleaned or None
        if isinstance(val, list):
            cap = _list_caps.get(key)
            items = [_trim(v) for v in val]
            items = [v for v in items if v is not None]
            if not items:
                return None
            return items[:cap] if cap else items
        if isinstance(val, str):
            return val if val.strip() else None
        return val

    return _trim(value) or {}


def _call_anthropic(payload):
    """One call, JSON out. Raises on any failure (caught by caller)."""
    payload = _trim_payload(payload)
    client = _get_client()

    user_prompt = (
        "Analyze the following corporate intelligence and return ONLY a JSON object "
        "with exactly these fields: executive_brief, analyst_brief, key_finding, "
        "confidence, recommended_action.\n\n"
        "Ground every field in the DATA below. Reference, by name, this entity's "
        "sanctioned status, its specific risk factor labels, its specific "
        "relationship names (including any IRGC or state-entity connections), its "
        "watchlist sanctioned-connection count, the number of ownership entities "
        "explored, the World Bank governance percentiles and opacity label, the "
        "trade pattern classification, and its incorporation date where present.\n\n"
        "executive_brief: 4 sentences max. Plain English. No jargon or acronyms "
        "without explanation. Lead with the most important finding. If any "
        "relationships exist in the data, name at least one specific connection. "
        "End with a specific recommended action.\n"
        "analyst_brief: 5 sentences max. Technical language for a sanctions "
        "compliance officer. Reference at least one specific regulatory designation "
        "or enforcement program relevant to this entity's actual risk factors "
        "(e.g. OFAC SDN, OFAC 50% Rule, EU sanctions, BIS export controls). "
        "Include a confidence assessment. End with specific compliance actions "
        "required.\n"
        "key_finding: a single sentence specific to this exact entity that mentions "
        "at least one concrete detail — a specific connection, a specific "
        "designation, a specific trade route, or a specific jurisdiction pattern. "
        "It must not be a generic statement that could apply to any sanctioned "
        "company. Bad example: 'This entity is sanctioned and poses high risk.' "
        "Good example: 'A UAE shell company incorporated July 2021 with direct "
        "documented links to Iran's Revolutionary Guard Corps and four sanctioned "
        "vessels operating across six flag states.'\n"
        "confidence: one of high, medium, low.\n"
        "recommended_action: one specific action in plain English.\n\n"
        f"DATA:\n{json.dumps(payload, ensure_ascii=False, indent=2)}"
    )

    message = client.messages.create(
        model=ANTHROPIC_MODEL,
        max_tokens=1600,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_prompt}],
    )
    text = "".join(block.text for block in message.content
                   if getattr(block, "type", None) == "text")
    data = _extract_json(text)
    if not data:
        raise ValueError("model returned no parseable JSON")

    executive = _strip_nonlatin(_strip_markdown(data.get("executive_brief")))
    # Confirm we received real model output (not the deterministic fallback).
    log.info("brief preview (%s): %s", ANTHROPIC_MODEL, (executive or "")[:100])

    return {
        "executive": executive,
        "analyst": _strip_nonlatin(_strip_markdown(data.get("analyst_brief"))),
        "key_finding": _strip_nonlatin(_strip_markdown(data.get("key_finding"))),
        "confidence": (data.get("confidence") or "medium").lower().strip(),
        "recommended_action": _strip_nonlatin(_strip_markdown(data.get("recommended_action"))),
    }


def _extract_json(text):
    """Pull the first JSON object out of a model response."""
    if not text:
        return None
    try:
        return json.loads(text)
    except ValueError:
        pass
    start, depth = text.find("{"), 0
    if start == -1:
        return None
    for i in range(start, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(text[start:i + 1])
                except ValueError:
                    return None
    return None


# ---------------------------------------------------------------------------
# Deterministic fallback — data-driven, never empty, no markdown.
# ---------------------------------------------------------------------------
# Risk-tiered fallback templates. Used only when the Anthropic call fails. A LOW
# entity must NEVER receive sanctions-list language — these templates guarantee it.
_FALLBACK_TEMPLATES = {
    "HIGH": {
        "executive": (
            "This entity is subject to active sanctions and carries significant "
            "legal risk. Any business dealings are likely prohibited under "
            "applicable regulations and require immediate legal review before "
            "proceeding."),
        "analyst": (
            "Entity presents critical compliance exposure via active sanctions "
            "designation. Recommend immediate blocking of all transactions, "
            "enhanced due diligence on all counterparties, and mandatory SAR filing "
            "per BSA/AML protocols."),
    },
    "MEDIUM": {
        "executive": (
            "This entity shows indirect connections to sanctioned networks or "
            "operates in a high-risk jurisdiction. Enhanced due diligence is "
            "recommended before establishing any business relationship."),
        "analyst": (
            "Entity presents elevated risk profile through network proximity to "
            "designated parties or high-risk jurisdiction exposure. Recommend "
            "enhanced due diligence, transaction monitoring, and senior compliance "
            "sign-off."),
    },
    "LOW": {
        "executive": (
            "No direct sanctions exposure was identified for this entity. Standard "
            "due diligence procedures apply. Monitor for any changes to the "
            "entity's risk profile."),
        "analyst": (
            "No direct sanctions designations identified. Jurisdiction risk "
            "indicators are within acceptable parameters. Standard KYC procedures "
            "are sufficient. Periodic rescreening recommended."),
    },
    # HIGH rating but NOT on a sanctions list — never claim sanctions membership.
    "HIGH_UNSANCTIONED": {
        "executive": (
            "This entity is not on a sanctions list, but it carries serious risk "
            "indicators such as regulatory or enforcement actions and significant "
            "adverse-media exposure. The risk profile warrants enhanced due "
            "diligence and senior compliance review before proceeding."),
        "analyst": (
            "Entity is not sanctions-designated but presents a high-severity risk "
            "profile driven by regulatory or law-enforcement actions and "
            "reputational risk factors. Recommend enhanced due diligence, "
            "adverse-media and counterparty screening, and senior compliance "
            "sign-off prior to onboarding."),
    },
}


def _fallback_brief(entity_name, profile, ubo, watchlist, worldbank, comtrade,
                    trade, risk_rating):
    """Deterministic, risk-tiered brief used when synthesis fails. The executive
    and analyst text come from the tier templates (so a LOW entity never sees
    sanctions language); the key finding stays entity-specific."""
    profile = profile or {}
    watchlist = watchlist or {}

    from intelligence.analyzer import build_key_finding
    key_finding = build_key_finding(entity_name, profile, watchlist)

    # Only use sanctions language when the entity is actually sanctioned. A HIGH
    # rating driven by regulatory/enforcement/reputational flags must not claim
    # sanctions membership.
    if risk_rating == "HIGH" and not profile.get("sanctioned"):
        template = _FALLBACK_TEMPLATES["HIGH_UNSANCTIONED"]
    else:
        template = _FALLBACK_TEMPLATES.get(risk_rating, _FALLBACK_TEMPLATES["LOW"])
    return {
        "executive": template["executive"],
        "analyst": template["analyst"],
        "key_finding": key_finding,
        "confidence": _confidence(profile, watchlist),
        "recommended_action": _recommended_action(risk_rating),
    }


def _recommended_action(risk_rating):
    if risk_rating == "HIGH":
        return ("Do not proceed without senior compliance sign-off and full "
                "enhanced due diligence.")
    if risk_rating == "MEDIUM":
        return ("Conduct enhanced due diligence before establishing or continuing "
                "any business relationship.")
    return "Proceed with standard due diligence and periodic monitoring."


def _confidence(profile, watchlist):
    if profile.get("sanctioned") or (watchlist.get("path_count") or 0) > 3:
        return "high"
    if profile.get("risk_factors"):
        return "medium"
    return "low"
