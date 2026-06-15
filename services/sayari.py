"""
Sayari knowledge-graph client.

Stateful wrapper around the Sayari REST API: OAuth token caching with expiry,
1-second call spacing to stay under rate limits, and structured timing logs on
every call. Each public method returns data already translated into the plain
vocabulary the rest of the app speaks — human-readable risk-factor labels,
relationship labels, and full country names — so nothing raw reaches the UI.

Endpoints exercised (all validated against the live API):
  /oauth/token                          auth (client_credentials)
  /v1/search/entity                     search + client-side country re-ranking
  /v1/entity/{id}                       full profile
  /v1/ubo/{id}                          beneficial ownership (traversal-shaped)
  /v1/watchlist/{id}                    sanctioned-network paths
  /v1/traversal/{id}?sanctioned=true    sanctioned entities within reach
  /v1/shortest_path?entities=&entities= path between two entities (underscore!)
  /v1/trade/search/shipments            trade shipment records
"""

import logging
import re
import threading
import time

import requests

from config import (
    HTTP_USER_AGENT,
    SAYARI_AUTH_URL,
    SAYARI_BASE_URL,
    SAYARI_CALL_DELAY_SECONDS,
    SAYARI_CLIENT_ID,
    SAYARI_CLIENT_SECRET,
)
from services.reference import country_name, country_names, hs_description

log = logging.getLogger("services.sayari")


# ---------------------------------------------------------------------------
# Translation tables (raw API key -> plain English)
# ---------------------------------------------------------------------------
RISK_FACTOR_LABELS = {
    "sanctioned": "Sanctioned Entity",
    "sanctioned_usa_ofac_sdn": "OFAC SDN Sanctioned",
    "ofac_sdgt_sanctioned": "OFAC Global Terrorist Designated",
    "export_controls": "Export Controls Violation",
    "state_owned": "State-Owned Entity",
    "pep_adjacent": "Politically Exposed Person Adjacent",
    "cpi_score": "High Corruption Jurisdiction",
    "basel_aml": "High AML Risk Jurisdiction",
    "owner_of_sanctioned_usa_ofac_sdn_entity": "Owns OFAC-Sanctioned Entity",
    "ofac_50_percent_rule": "OFAC 50% Rule Exposure",
    "eu_50_percent_rule": "EU 50% Rule Exposure",
    "law_enforcement_action": "Law Enforcement Action",
    "soe_adjacent": "State Enterprise Adjacent",
    "formerly_sanctioned": "Formerly Sanctioned",
    "reputational_risk_financial_crime": "Financial Crime Risk",
    "reputational_risk_organized_crime": "Organized Crime Risk",
    "reputational_risk_terrorism": "Terrorism Risk",
    "reputational_risk_bribery_and_corruption": "Bribery and Corruption Risk",
    "reputational_risk_modern_slavery": "Modern Slavery Risk",
    "reputational_risk_cybercrime": "Cybercrime Risk",
    "reputational_risk_other": "Reputational Risk",
    "regulatory_action": "Regulatory Action",
    "xinjiang_geospatial": "Xinjiang Region Exposure",
    "forced_labor_xinjiang_origin_subtier": "Xinjiang Forced Labor Supply Chain",
    "forced_labor_aspi_origin_subtier": "ASPI Forced Labor Risk",
    "forced_labor_sheffield_hallam_university_reports_origin_subtier":
        "Sheffield Hallam Forced Labor Risk",
    "eu_high_risk_third": "EU High Risk Third Country",
    "sanctioned_adjacent": "Sanctioned Entity Adjacent",
    "chinese_soe_adjacent": "Chinese State Enterprise Adjacent",
    "esg_score_very_high": "Very High ESG Risk Score",
    "esg_score_high": "High ESG Risk Score",
    "esg_score_medium": "Medium ESG Risk Score",
    "esg_score_low": "Low ESG Risk Score",
    "esg_score": "ESG Risk Indicator",
}

# PSA (Possible Same As) categories — many individual psa_* flags collapse into a
# single tag per category so the risk section isn't cluttered with 8+ near-dupes.
_PSA_CATEGORIES = [
    ("sanction", "Possible Connection to Sanctioned Entity", "amber"),
    ("ofac", "Possible Connection to Sanctioned Entity", "amber"),
    ("forced_labor", "Possible Forced Labor Exposure", "amber"),
    ("export", "Possible Export Controls Exposure", "amber"),
    ("state", "Possible State Entity Connection", "grey"),
    ("soe", "Possible State Entity Connection", "grey"),
]
_PSA_DEFAULT = ("Indirect Risk Network Exposure", "grey")

RELATIONSHIP_LABELS = {
    "linked_to": "Corporate Link",
    "has_director": "Director",
    "has_manager": "Manager",
    "has_officer": "Officer",
    "has_subsidiary": "Subsidiary",
    "shareholder_of": "Shareholder",
    "beneficial_owner_of": "Beneficial Owner",
    "owner_of": "Owner",
    "has_member_of_the_board": "Board Member",
    "has_auditor": "Auditor",
    "has_shareholder": "Has Shareholder",
    # Common ownership/control inverses & variants we also want to keep + label.
    "subsidiary_of": "Parent Company",
    "owned_by": "Owned By",
    "controlled_by": "Controlled By",
    "director_of": "Director Of",
    "officer_of": "Officer Of",
    "manager_of": "Manager Of",
    "member_of_the_board_of": "Board Member Of",
    "has_beneficial_owner": "Beneficial Owner (Inbound)",
    "has_legal_representative": "Legal Representative",
    "branch_of": "Branch Of",
    "has_branch": "Has Branch",
    "partner_of": "Partner",
    "has_partner": "Has Partner",
    "has_founder": "Founder",
    "founder_of": "Founder Of",
    # Financial-entity relationships (banks surface these instead of ownership).
    "has_correspondent_bank": "Correspondent Bank",
    "correspondent_bank_of": "Correspondent Bank Of",
    "has_registered_agent": "Registered Agent",
    "registered_agent_of": "Registered Agent Of",
    "has_legal_successor": "Legal Successor",
    "legal_successor_of": "Legal Successor Of",
    "has_supervisor": "Supervisor",
    "supervisor_of": "Supervisor Of",
}

# Trade / shipment edges — never surfaced in the relationships list.
EXCLUDED_RELATIONSHIPS = {
    "notify_party_of", "ships_to", "carrier_of", "procures_from",
    "recipient_of", "awarder_of", "contracted_by", "consignee_of",
    "shipper_of", "buyer_of", "supplier_of",
    # Additional trade edges observed in the wild.
    "shipped_by", "received_by", "receiver_of", "receives_from", "shipper_of",
    # Employee + securities edges — not ownership/control, clutter the table.
    "has_employee", "issuer_of", "issued_by", "employee_of",
    "has_security", "registered_security",
}

# One-sentence tooltips so an executive understands each flag without a glossary.
RISK_FACTOR_TOOLTIPS = {
    "sanctioned": "This entity appears on one or more government sanctions lists.",
    "sanctioned_usa_ofac_sdn": "Listed on the US Treasury OFAC Specially Designated Nationals list — US persons are broadly prohibited from dealing with it.",
    "ofac_sdgt_sanctioned": "Designated by OFAC as a Specially Designated Global Terrorist.",
    "export_controls": "Subject to export-control restrictions limiting the goods and technology it can receive.",
    "state_owned": "Owned or controlled by a national government.",
    "pep_adjacent": "Connected to a politically exposed person, raising bribery and corruption risk.",
    "cpi_score": "Registered in a country that scores poorly on Transparency International's Corruption Perceptions Index.",
    "basel_aml": "Registered in a country that scores poorly on the Basel Anti-Money-Laundering Index.",
    "owner_of_sanctioned_usa_ofac_sdn_entity": "Owns an entity that is itself OFAC-sanctioned — potential 50% Rule exposure.",
    "ofac_50_percent_rule": "May be blocked under OFAC's rule that property of entities 50%+ owned by sanctioned parties is itself blocked.",
    "eu_50_percent_rule": "May be blocked under the EU equivalent of the OFAC 50% ownership rule.",
    "law_enforcement_action": "Has been the subject of a documented law-enforcement action.",
    "soe_adjacent": "Connected to a state-owned enterprise.",
}


# Acronyms / country codes to keep upper-cased in the title-case fallback so an
# unmapped key never renders an unexplained-looking half-word (e.g. "Ofac", "Eu").
_ACRONYMS = {
    "OFAC": "OFAC", "EU": "EU", "UN": "UN", "UK": "UK", "US": "US", "USA": "USA",
    "AML": "AML", "SDN": "SDN", "SDGT": "SDGT", "PSA": "Possible Match To", "PEP": "PEP",
    "SOE": "State-Owned", "BIS": "BIS", "MEU": "Military End-User", "CPI": "Corruption-Index",
    "DFAT": "Australian (DFAT)", "SECO": "Swiss (SECO)", "FCDO": "UK (FCDO)",
    "HMT": "UK Treasury", "OFSI": "UK (OFSI)", "GAC": "Canadian (GAC)",
    "MFAT": "New Zealand (MFAT)", "DGT": "French (DGT)", "MOF": "Japanese (MOF)",
    "NSDC": "Ukrainian (NSDC)", "EC": "EC", "FIS": "Latvian (FIS)",
}


def risk_factor_label(key):
    """Human label for a risk-factor key.

    Mapped keys use the curated label. Unmapped keys follow the spec's fallback —
    underscores to spaces, title-cased — but with known acronyms/country-source
    codes preserved or expanded so nothing renders as an unexplained half-word.
    """
    if key in RISK_FACTOR_LABELS:
        return RISK_FACTOR_LABELS[key]
    words = []
    for token in key.split("_"):
        upper = token.upper()
        if upper in _ACRONYMS:
            words.append(_ACRONYMS[upper])
        else:
            words.append(token.title())
    return " ".join(words)


def risk_factor_severity(key):
    """Colour band for a risk factor: 'red' (sanctions), 'amber' (controls/links),
    'grey' (jurisdictional/contextual)."""
    k = key.lower()
    if "sanctioned" in k or "ofac" in k or k.endswith("_sdn") or "sdgt" in k:
        # A degree removed (ownership-of / possible-match / adjacency) -> amber.
        if k.startswith("owner_of") or k.startswith("psa_owner") or k.startswith("owned_by") \
                or k.startswith("controlled_by") or k.startswith("psa_owned") \
                or k.startswith("psa_") or "adjacent" in k or "formerly" in k:
            return "amber"
        return "red"
    if "terrorism" in k or "organized_crime" in k:
        return "red"
    if key in ("export_controls", "law_enforcement_action") or "export_controls" in k \
            or "regulatory_action" in k or "bis" in k or "meu_list" in k \
            or "reputational_risk" in k or "forced_labor" in k or "xinjiang" in k \
            or "eu_high_risk" in k or k.endswith("_adjacent"):
        return "amber"
    return "grey"


def _psa_category(key):
    """(label, severity) for a psa_* key, by the first matching category."""
    k = key.lower()
    for needle, label, severity in _PSA_CATEGORIES:
        if needle in k:
            return label, severity
    return _PSA_DEFAULT


def _cpi_label(value):
    """(label, severity) for cpi_score by its 0-100 value (higher = cleaner)."""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return "Jurisdiction Risk Indicator", "grey"
    if v > 60:
        return "Jurisdiction Risk Indicator", "grey"
    if v >= 40:
        return "Moderate Corruption Risk", "amber"
    return "High Corruption Jurisdiction", "red"


# Designation programs in priority order: (risk-key substring, label).
_DESIGNATION_PRIORITY = [
    ("ofac_sdgt", "OFAC SDGT (Global Terrorist)"),
    ("sanctioned_usa_ofac_sdn", "OFAC SDN"),
    ("eu_sanctions", "EU Sanctions"),
    ("export_controls", "Export Controls"),
    ("sanctioned", "International Sanctions"),
]


def extract_designation_program(risk_dict):
    """Most specific sanctions designation program from a target's risk dict."""
    keys = set((risk_dict or {}).keys())
    for needle, label in _DESIGNATION_PRIORITY:
        if any(needle in k for k in keys):
            return label
    return "International Sanctions"


def build_path_description(path_depth, intermediate_label=None, relationship_type=None):
    """Plain-English description of how a sanctioned entity connects, by hop count."""
    if path_depth <= 1:
        type_map = {
            "linked_to": "Direct corporate link",
            "has_director": "Shared director",
            "has_subsidiary": "Subsidiary relationship",
            "shareholder_of": "Shared shareholder",
            "has_manager": "Shared manager",
            "has_officer": "Shared officer",
        }
        return type_map.get((relationship_type or "").lower(), "Direct corporate link")
    if path_depth == 2 and intermediate_label:
        return f"Connected through {intermediate_label}"
    if path_depth == 3 and intermediate_label:
        return f"Indirect link via {intermediate_label} (3 corporate steps)"
    if path_depth == 4:
        if intermediate_label:
            return f"Indirect link via {intermediate_label} (4 corporate steps from this entity)"
        return "Indirect connection (4 corporate steps from this entity)"
    if path_depth >= 5:
        return f"Distant indirect connection ({path_depth} corporate steps)"
    return "Corporate network connection"


def relationship_label(rel_type, target_type=None):
    """Human label for a relationship edge type, disambiguating generic links."""
    if rel_type == "linked_to":
        t = (target_type or "").lower()
        if t == "person":
            return "Associated Person"
        if t in ("vessel", "ship", "aircraft"):
            return "Associated Vessel"
        if t in ("organization", "government", "intergovernmental_organization"):
            return "Operational Link"
        return "Corporate Link"
    if rel_type in RELATIONSHIP_LABELS:
        return RELATIONSHIP_LABELS[rel_type]
    return (rel_type or "").replace("_", " ").title() or "Connection"


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------
class SayariService:
    """Thin, stateful Sayari REST wrapper with token caching and pacing."""

    _EXPIRY_BUFFER_SECONDS = 60

    def __init__(self):
        self._token = None
        self._token_expiry = 0.0
        self._lock = threading.Lock()
        self._session = requests.Session()
        self._session.headers["User-Agent"] = HTTP_USER_AGENT

    # -- Auth -----------------------------------------------------------------
    def _bearer_token(self):
        with self._lock:
            if self._token and time.monotonic() < self._token_expiry:
                return self._token
            log.info("Sayari auth: requesting bearer token (client_credentials)")
            t0 = time.time()
            resp = self._session.post(
                SAYARI_AUTH_URL,
                json={
                    "client_id": SAYARI_CLIENT_ID,
                    "client_secret": SAYARI_CLIENT_SECRET,
                    "audience": "sayari.com",
                    "grant_type": "client_credentials",
                },
                timeout=60,
            )
            resp.raise_for_status()
            payload = resp.json()
            self._token = payload["access_token"]
            ttl = int(payload.get("expires_in", 3600))
            self._token_expiry = time.monotonic() + ttl - self._EXPIRY_BUFFER_SECONDS
            log.info("Sayari auth: token acquired (ttl=%ss) in %.0fms",
                     ttl, (time.time() - t0) * 1000)
            return self._token

    # -- HTTP -----------------------------------------------------------------
    def _get(self, path, params=None):
        time.sleep(SAYARI_CALL_DELAY_SECONDS)   # pace calls under the rate limit
        url = f"{SAYARI_BASE_URL}{path}"
        headers = {"Authorization": f"Bearer {self._bearer_token()}"}
        t0 = time.time()
        resp = self._session.get(url, params=params, headers=headers, timeout=60)
        log.info("Sayari GET %s params=%s -> HTTP %s (%.0fms)",
                 path, params or {}, resp.status_code, (time.time() - t0) * 1000)
        return resp

    def _post(self, path, params=None, json_body=None):
        time.sleep(SAYARI_CALL_DELAY_SECONDS)   # pace calls under the rate limit
        url = f"{SAYARI_BASE_URL}{path}"
        headers = {"Authorization": f"Bearer {self._bearer_token()}",
                   "Content-Type": "application/json"}
        t0 = time.time()
        resp = self._session.post(url, params=params, json=json_body,
                                  headers=headers, timeout=60)
        log.info("Sayari POST %s params=%s body=%s -> HTTP %s (%.0fms)",
                 path, params or {}, json_body or {}, resp.status_code,
                 (time.time() - t0) * 1000)
        return resp

    @staticmethod
    def _json(resp):
        try:
            return resp.json()
        except ValueError:
            return {}

    # -- Search (server-side POST filter) ------------------------------------
    def search_entity(self, name, country=None, limit=10):
        """Resolve a name to candidate matches via POST /v1/search/entity.

        The country filter is applied SERVER-SIDE through the request body's
        `filter` object (confirmed in testing: filter.country narrows results to
        the requested jurisdiction). `limit` must travel as a query param — the
        body's limit field is ignored by the API. Results are sorted Company →
        Organization → Person → Other, and Person rows are suppressed entirely
        when any company/organization result exists, so a stray person match never
        out-ranks the real company.
        """
        body = {"q": name}
        filter_applied = False
        if country:
            iso3 = _ISO2_TO_ISO3.get(country.upper(), country.upper())
            body["filter"] = {"entity_type": ["company"], "country": [iso3]}
            filter_applied = True

        resp = self._post("/v1/search/entity",
                          params={"limit": max(limit, 10)}, json_body=body)
        if not resp.ok:
            log.warning("Sayari search failed for %r (HTTP %s)", name, resp.status_code)
            return []
        data = (self._json(resp).get("data")) or []

        def schema_rank(ent):
            t = (ent.get("type") or "").lower()
            return {"company": 0, "organization": 1, "person": 2}.get(t, 3)

        non_person = [e for e in data if (e.get("type") or "").lower() != "person"]
        ordered = sorted(non_person or data, key=schema_rank)
        log.info("search %r country=%s filter_applied=%s -> %d raw, %d returned",
                 name, country, filter_applied, len(data), min(len(ordered), limit))
        return [self._shape_candidate(e) for e in ordered[:limit]]

    @staticmethod
    def _shape_candidate(ent):
        countries = ent.get("countries") or []
        return {
            "entity_id": ent.get("id"),
            "label": ent.get("label"),
            "country": country_names(countries) or "Unknown",
            "country_codes": countries,
            "company_type": _humanize_company_type(ent.get("type") or ent.get("company_type")),
            "incorporation_date": _format_founded(ent.get("registration_date")),
            "sanctioned": bool(ent.get("sanctioned")),
            "degree": ent.get("degree") or 0,
            "network_size": _network_size(ent.get("degree")),
        }

    # -- Entity profile -------------------------------------------------------
    def get_entity_profile(self, entity_id):
        resp = self._get(f"/v1/entity/{entity_id}")
        if not resp.ok:
            log.warning("Sayari profile failed for %s (HTTP %s)", entity_id, resp.status_code)
            return None
        raw = self._json(resp)
        countries = raw.get("countries") or []
        designation_date, designation_url = self._sanctions_designation(raw)
        if raw.get("sanctioned"):
            log.info("Designation date extracted: %s from %s",
                     designation_date, designation_url)
        return {
            "id": raw.get("id"),
            "label": raw.get("label"),
            "translated_label": raw.get("translated_label"),
            "sanctioned": bool(raw.get("sanctioned")),
            "designation_date": designation_date,
            "designation_url": designation_url,
            "pep": bool(raw.get("pep")),
            "degree": raw.get("degree") or 0,
            "network_size": _network_size(raw.get("degree")),
            "registration_date": raw.get("registration_date"),
            "incorporation_display": _format_founded(raw.get("registration_date")),
            "company_type": _humanize_company_type(raw.get("company_type") or raw.get("type")),
            "status": _humanize_status(raw),
            "country_codes": countries,
            "countries": country_names(countries) or "Unknown",
            "risk_factors": self._risk_factors(raw),
            "relationships": self._enriched_relationships(entity_id, raw),
            "identifiers": self._identifiers(raw),
        }

    @staticmethod
    def _sanctions_designation(raw):
        """Earliest sanctions designation date and an OFAC/sanctions source URL.

        Reads attributes.risk_intelligence: each record's `properties` carries the
        flag `type`, a `from_date`, and (on OFAC records) a `URL`. We take the
        earliest `from_date` across records typed "sanctioned" (falling back to the
        record's `acquisition_date` when `from_date` is absent — a reasonable proxy
        for when the designation entered the data) and the first OFAC/sanctions URL.
        Returns (date_or_None, url_or_None).
        """
        ri = ((raw.get("attributes") or {}).get("risk_intelligence") or {}).get("data") or []
        dates, url = [], None
        for entry in ri:
            props = (entry.get("properties") or {}) if isinstance(entry, dict) else {}
            if props.get("type") != "sanctioned":
                continue
            d = props.get("from_date") or props.get("acquisition_date")
            if d:
                dates.append(str(d))
            if not url:
                candidate = props.get("URL") or props.get("url")
                if candidate:
                    url = candidate
        # ISO-8601 dates sort lexicographically, so min() is the earliest.
        return (min(dates) if dates else None), url

    @staticmethod
    def _risk_factors(raw):
        """Risk dict -> list of {key, label, tooltip, severity}, sanctions first.

        Many `psa_*` (Possible Same As) flags are consolidated into a single tag
        per category so the section isn't cluttered with 8+ near-duplicate tags.
        """
        risk = raw.get("risk") or {}
        out = []
        psa_seen = {}   # consolidated label -> {key, label, tooltip, severity}
        for key in risk.keys():
            entry = risk.get(key)
            value = entry.get("value") if isinstance(entry, dict) else None
            if key.lower().startswith("psa_"):
                label, severity = _psa_category(key)
                if label not in psa_seen:
                    psa_seen[label] = {
                        "key": "psa_group:" + label,
                        "label": label,
                        "tooltip": "One or more possible-match (PSA) signals in the "
                                   "entity's network point to this exposure.",
                        "severity": severity,
                        "value": None,
                    }
                continue
            if key == "cpi_score":
                # CPI is 0-100 (higher = cleaner). Label/colour by the actual score,
                # not merely the flag's presence — a clean jurisdiction must never
                # render as "High Corruption Jurisdiction".
                label, severity = _cpi_label(value)
            else:
                label, severity = risk_factor_label(key), risk_factor_severity(key)
            out.append({
                "key": key,
                "label": label,
                "tooltip": RISK_FACTOR_TOOLTIPS.get(key, label + "."),
                "severity": severity,
                "value": value,
            })
        out.extend(psa_seen.values())
        order = {"red": 0, "amber": 1, "grey": 2}
        out.sort(key=lambda r: order.get(r["severity"], 3))
        return out

    @classmethod
    def _relationships(cls, raw):
        """Ownership/control edges only.

        Trade edges are excluded, rows are truly deduplicated by entity_id (so a
        counterparty that appears under several edge labels — or with differing
        label capitalization like "SEASKY" vs "Seasky" — surfaces once), and raw
        trade-record IDs that leak through as labels are filtered out.
        """
        edges = (raw.get("relationships") or {}).get("data") or []
        raw_count = len(edges)
        type_kept = 0
        by_entity = {}   # entity_id -> shaped row; first occurrence wins
        for edge in edges:
            types = list((edge.get("types") or {}).keys())
            # Drop the edge entirely if every type on it is a trade/shipment edge.
            kept = [t for t in types if t not in EXCLUDED_RELATIONSHIPS]
            if not kept:
                continue
            target = edge.get("target") or {}
            label = target.get("label")
            if _looks_like_record_id(label):
                continue
            type_kept += 1
            tid = target.get("id")
            # Dedup by entity_id; fall back to label when an id is absent.
            dedup_key = tid or ("label:" + (label or ""))
            if dedup_key in by_entity:
                continue
            tcountries = target.get("countries") or []
            ttype = (target.get("type") or "").lower()
            by_entity[dedup_key] = {
                "entity_id": tid,
                "label": _best_label(target),
                "translated_label": target.get("translated_label"),
                "relationship_type_label": relationship_label(kept[0], target.get("type")),
                "sanctioned": bool(target.get("sanctioned")),
                "is_person": ttype == "person",
                "is_pep": bool(target.get("pep")),
                "country_codes": tcountries,
                "countries": country_names(tcountries) or "—",
            }
        log.info("Relationships: %d raw -> %d after type/record filter -> %d after dedup",
                 raw_count, type_kept, len(by_entity))
        return by_entity

    # Ownership/control relationship types, in display priority. Used to enrich
    # entities whose embedded relationship sample is dominated by trade edges
    # (large financial entities and conglomerates like Rosneft / Sberbank).
    _OWNERSHIP_PRIORITY = (
        "has_subsidiary", "subsidiary_of", "has_director", "shareholder_of",
        "has_shareholder", "beneficial_owner_of", "owner_of", "has_officer",
        "has_member_of_the_board", "has_manager", "has_legal_representative",
        "has_correspondent_bank", "has_legal_predecessor", "legal_successor_of",
    )
    _ENRICH_MIN = 8     # embedded ownership rows below this triggers enrichment
    _ENRICH_TARGET = 20  # stop enriching once we have this many rows

    def _enriched_relationships(self, entity_id, raw):
        """Shaped ownership/control relationships. The profile's embedded sample is
        ordered trade-first, so a high-degree entity can have zero ownership edges
        in it despite owning hundreds. When the embedded sample is ownership-poor,
        fetch ownership edges by type (server-side `relationships.type` filter) until
        we have a useful set — so banks/conglomerates never render an empty table."""
        by_entity = self._relationships(raw)   # dict keyed by dedup key
        if len(by_entity) >= self._ENRICH_MIN:
            return list(by_entity.values())

        counts = raw.get("relationship_count") or {}
        before = len(by_entity)
        for rtype in self._OWNERSHIP_PRIORITY:
            if len(by_entity) >= self._ENRICH_TARGET:
                break
            if not counts.get(rtype):
                continue
            resp = self._get(f"/v1/entity/{entity_id}",
                             {"relationships.type": rtype, "relationships.limit": 20})
            if not resp.ok:
                continue
            edges = (self._json(resp).get("relationships") or {}).get("data") or []
            for edge in edges:
                if len(by_entity) >= self._ENRICH_TARGET:
                    break
                target = edge.get("target") or {}
                label = target.get("label")
                if _looks_like_record_id(label):
                    continue
                tid = target.get("id")
                key = tid or ("label:" + (label or ""))
                if key in by_entity:
                    continue
                tcountries = target.get("countries") or []
                ttype = (target.get("type") or "").lower()
                by_entity[key] = {
                    "entity_id": tid,
                    "label": _best_label(target),
                    "translated_label": target.get("translated_label"),
                    "relationship_type_label": relationship_label(rtype, target.get("type")),
                    "sanctioned": bool(target.get("sanctioned")),
                    "is_person": ttype == "person",
                    "is_pep": bool(target.get("pep")),
                    "country_codes": tcountries,
                    "countries": country_names(tcountries) or "—",
                }
        if len(by_entity) != before:
            log.info("relationships enriched: %d -> %d via ownership-type fetch",
                     before, len(by_entity))
        return list(by_entity.values())

    @staticmethod
    def _identifiers(raw):
        out = []
        for ident in raw.get("identifiers") or []:
            out.append({
                "type": (ident.get("type") or "").replace("_", " ").title() or "Identifier",
                "value": ident.get("value"),
            })
        return out

    # -- UBO ------------------------------------------------------------------
    def get_ubo(self, entity_id):
        resp = self._get(f"/v1/ubo/{entity_id}")
        if not resp.ok:
            return {"empty": True, "explored_count": 0, "opacity_finding": True}
        raw = self._json(resp)
        rows = raw.get("data") or []
        explored = raw.get("explored_count") or 0
        depth = _depth_range(raw)
        if not rows:
            return {"empty": True, "explored_count": explored,
                    "depth": depth, "opacity_finding": True}
        owners = []
        for r in rows:
            target = r.get("target") or {}
            tcountries = target.get("countries") or []
            owners.append({
                "entity_id": target.get("id"),
                "label": target.get("label"),
                "sanctioned": bool(target.get("sanctioned")),
                "pep": bool(target.get("pep")),
                "country_codes": tcountries,
                "countries": country_names(tcountries) or "—",
                "degree": target.get("degree"),
            })
        return {"empty": False, "explored_count": explored, "depth": depth, "owners": owners}

    # -- Watchlist ------------------------------------------------------------
    def get_watchlist(self, entity_id):
        # sanctioned=true narrows the returned paths to sanctioned targets only,
        # keeping the network view focused and relevant.
        resp = self._get(f"/v1/watchlist/{entity_id}",
                         {"sanctioned": "true", "limit": 20})
        if not resp.ok:
            return {"explored_count": 0, "path_count": 0, "paths": []}
        raw = self._json(resp)
        rows = raw.get("data") or []
        explored = raw.get("explored_count") or 0
        log.info("Watchlist explored_count: %s", explored)
        if explored > 100000:
            log.warning("Watchlist explored_count unusually large (%s) — likely a "
                        "traversal artifact; UI will summarize rather than show raw",
                        explored)
        depth = _depth_range(raw)
        paths = []
        sanctioned_count = 0
        for r in rows[:20]:
            target = r.get("target") or {}
            is_sanc = bool(target.get("sanctioned"))
            if is_sanc:
                sanctioned_count += 1
            tcountries = target.get("countries") or []
            trisk = target.get("risk") or {}
            ttype = (target.get("type") or "").lower()
            path_items = r.get("path") if isinstance(r.get("path"), list) else []
            depth = len(path_items) or 1
            rel_type = ""
            intermediate = None
            if path_items:
                rel_type = (path_items[0].get("field") or "")
                if depth >= 2:
                    ent = path_items[0].get("entity") or {}
                    intermediate = _best_label(ent)
            if ttype in ("vessel", "ship", "aircraft") and depth <= 1:
                path_desc = "Associated vessel"
            else:
                path_desc = build_path_description(depth, intermediate, rel_type)
            paths.append({
                "entity_id": target.get("id"),
                "label": _best_label(target),
                "translated_label": target.get("translated_label"),
                "sanctioned": is_sanc,
                "pep": bool(target.get("pep")),
                "is_person": ttype == "person",
                "is_pep": bool(target.get("pep")),
                "country_codes": tcountries,
                "countries": country_names(tcountries) or "—",
                "degree": target.get("degree") or 0,
                "incorporation_date": target.get("registration_date"),
                "incorporation_display": _format_founded(target.get("registration_date")),
                # Rich connection-breakdown fields.
                "risk_factors": list(trisk.keys())[:3],
                "path_depth": depth,
                "path_description": path_desc,
                "designation_program": extract_designation_program(trisk),
            })
        # Count sanctioned across the full page, not just the first 20 shown.
        total_sanctioned = sum(1 for r in rows if (r.get("target") or {}).get("sanctioned"))
        return {
            "explored_count": explored,
            "path_count": total_sanctioned,
            "depth": depth,
            "min_depth": raw.get("min_depth"),
            "paths": paths,
        }

    # -- Traversal ------------------------------------------------------------
    def get_traversal(self, entity_id, limit=10):
        resp = self._get(f"/v1/traversal/{entity_id}", {"sanctioned": "true", "limit": limit})
        if not resp.ok:
            return []
        rows = (self._json(resp).get("data")) or []
        out = []
        for r in rows:
            target = r.get("target") or {}
            tcountries = target.get("countries") or []
            # The path/relationship chain shape varies; summarize what's present.
            rel_types = set()
            for seqkey in ("path", "relationships", "edges"):
                seq = r.get(seqkey)
                if isinstance(seq, list):
                    for e in seq:
                        if isinstance(e, dict):
                            t = e.get("types") or e.get("type")
                            if isinstance(t, dict):
                                rel_types.update(t.keys())
                            elif t:
                                rel_types.add(str(t))
            out.append({
                "entity_id": target.get("id"),
                "label": target.get("label"),
                "sanctioned": bool(target.get("sanctioned")),
                "country_codes": tcountries,
                "countries": country_names(tcountries) or "—",
                "degree": target.get("degree"),
                "relationship_summary": ", ".join(relationship_label(t) for t in sorted(rel_types))
                                        or "Connected entity",
            })
        return out

    # -- Shortest path --------------------------------------------------------
    def get_shortest_path(self, entity_id_1, entity_id_2):
        # Correct endpoint is /v1/shortest_path (underscore, not hyphen) with the
        # two entity IDs passed as the `entities` query param REPEATED once each
        # (requests serializes the list as entities=ID1&entities=ID2). Confirmed
        # working in test_api_methods.py.
        try:
            resp = self._get("/v1/shortest_path",
                             {"entities": [entity_id_1, entity_id_2]})
        except requests.RequestException as e:
            log.warning("Shortest path request error: %r", e)
            return None
        if not resp.ok:
            return None
        raw = self._json(resp)
        rows = raw.get("data") or []
        if not rows:
            return None
        first = rows[0]
        intermediates = []
        length = None
        for seqkey in ("path", "relationships", "edges", "entities"):
            seq = first.get(seqkey)
            if isinstance(seq, list):
                length = len(seq)
                for node in seq:
                    if isinstance(node, dict):
                        tgt = node.get("target") or node.get("entity") or node
                        if isinstance(tgt, dict) and tgt.get("label"):
                            intermediates.append(tgt.get("label"))
                break
        return {
            "length": length if length is not None else 1,
            "intermediates": intermediates,
        }

    # -- Trade shipments ------------------------------------------------------
    def get_trade_shipments(self, entity_id, name, limit=10):
        # GET /v1/trade/search/shipments — confirmed returning shipment records
        # for trading entities (e.g. NIOC, Rosneft) in testing.
        log.info("Sayari trade search: GET /v1/trade/search/shipments q=%r limit=%d",
                 name, limit)
        resp = self._get("/v1/trade/search/shipments", {"q": name, "limit": limit})
        if not resp.ok:
            return {"empty": True}
        raw = self._json(resp)
        data = raw.get("data") or []
        size = raw.get("size") or {}
        total = size.get("count", len(data)) if isinstance(size, dict) else len(data)
        if not data:
            return {"empty": True, "total": 0}
        shipments = []
        for ship in data:
            origin = _first(ship.get("departure_country")) or _first(ship.get("product_origin"))
            dest = _first(ship.get("arrival_country"))
            hs = _first(ship.get("hs_codes"))
            commodity = _first(ship.get("product_descriptions"))
            shipments.append({
                "commodity": _clean_text(commodity) or "Not specified",
                "origin": country_name(origin) if origin else "Unknown",
                "destination": country_name(dest) if dest else "Unknown",
                "hs_code": hs,
                "hs_description": hs_description(hs) if hs else "Not specified",
                "monetary_value": _format_money(ship.get("monetary_value")),
                "date": _first(ship.get("arrival_date")) or _first(ship.get("departure_date")),
            })
        return {"empty": False, "total": total, "shipments": shipments}


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------
_ISO2_TO_ISO3 = {
    "AE": "ARE", "RU": "RUS", "IR": "IRN", "CN": "CHN",
    "US": "USA", "GB": "GBR", "DE": "DEU", "FR": "FRA",
    "NG": "NGA", "PA": "PAN", "MZ": "MOZ", "SM": "SMR",
    "GA": "GAB", "GY": "GUY", "CW": "CUW", "KM": "COM",
    "CM": "CMR", "LR": "LBR", "GN": "GIN", "ZW": "ZWE",
    "SY": "SYR", "IN": "IND", "TR": "TUR", "KZ": "KAZ",
    "BE": "BEL", "CH": "CHE", "JP": "JPN", "KR": "KOR",
    "SA": "SAU", "QA": "QAT", "AU": "AUS", "CA": "CAN",
    "IT": "ITA", "ES": "ESP", "NL": "NLD", "SE": "SWE",
    "NO": "NOR", "DK": "DNK", "PL": "POL", "UA": "UKR",
    "VE": "VEN", "MM": "MMR", "KP": "PRK", "BY": "BLR", "CU": "CUB",
    "KR": "KOR", "ZA": "ZAF", "TH": "THA", "VN": "VNM", "SG": "SGP",
}


def _latin_label(label, translated):
    """Prefer a Latin display label: the original if ASCII, else a Latin
    translated_label, else the original (last resort)."""
    if label and all(ord(c) <= 127 for c in label):
        return label
    if translated and all(ord(c) <= 127 for c in translated):
        return translated
    return label or translated


def _best_label(entity_data):
    """Best Latin-script label for a target entity: original if Latin, else a Latin
    translated_label, else a '<Country> <Type>' fallback — so no Arabic/Persian/
    Chinese/Cyrillic script ever reaches a table. Logs every replacement."""
    original = entity_data.get("label") or ""
    translated = entity_data.get("translated_label") or ""
    if original and _NON_ASCII_RE.search(original) is None:
        return original
    if translated and _NON_ASCII_RE.search(translated) is None:
        log.info("Non-Latin label replaced: %s -> %s", original or "—", translated)
        return translated
    countries = entity_data.get("countries") or []
    etype = (entity_data.get("type") or "Entity")
    if countries:
        resolved = f"{country_name(countries[0])} {str(etype).title()}"
    else:
        resolved = "Unknown Entity"
    log.info("Non-Latin label replaced: %s -> %s", original or "—", resolved)
    return resolved


_NON_ASCII_RE = re.compile(r"[^\x00-\x7F]")


_HEX_ID_RE = re.compile(r"^[a-f0-9]{20,}$")
_UPPER_ID_RE = re.compile(r"^[A-Z0-9]{15,}$")


def _looks_like_record_id(label):
    """True for labels that are actually raw trade-record IDs, not entity names:
    a long unspaced token, a 20+ char hex string, or a 15+ char unspaced
    all-caps/alphanumeric token."""
    if not label:
        return False
    s = str(label).strip()
    if _HEX_ID_RE.match(s):
        return True
    if " " not in s and _UPPER_ID_RE.match(s):
        return True
    if s.isdigit() and len(s) >= 6:        # bare numeric record/security id
        return True
    return len(s) > 40 and " " not in s


def _first(value):
    """First element of a list, or the value itself if scalar."""
    if isinstance(value, list):
        return value[0] if value else None
    return value


def _clean_text(value):
    if value is None:
        return None
    return " ".join(str(value).split())


def _network_size(degree):
    """Raw degree -> 'X corporate connections' (never the bare number)."""
    try:
        n = int(degree or 0)
    except (TypeError, ValueError):
        n = 0
    if n == 0:
        return "No mapped connections"
    if n == 1:
        return "1 corporate connection"
    return f"{n:,} corporate connections"


_MONTHS = ["", "January", "February", "March", "April", "May", "June",
           "July", "August", "September", "October", "November", "December"]


def _format_founded(date_str):
    """registration_date -> 'Founded October 2018' / 'Founded 2021' / None."""
    if not date_str:
        return None
    s = str(date_str).split("T")[0]
    parts = s.split("-")
    try:
        year = int(parts[0])
    except (ValueError, IndexError):
        return None
    if len(parts) >= 2 and parts[1].isdigit():
        m = int(parts[1])
        if 1 <= m <= 12:
            return f"Founded {_MONTHS[m]} {year}"
    return f"Founded {year}"


# Raw company-type codes -> human-readable labels (matched case-insensitively).
_COMPANY_TYPE_LABELS = {
    "llc": "Limited Liability Company",
    "fze": "Free Zone Establishment",
    "fz": "Free Zone Company",
    "fzco": "Free Zone Company",
    "fze/llc": "Free Zone Establishment",
    "ltd": "Limited Company",
    "co": "Company",
    "corp": "Corporation",
    "inc": "Incorporated",
    "rao": "Russian Joint Stock Company",
    "pao": "Russian Public Joint Stock Company",
    "oao": "Russian Open Joint Stock Company",
    "zao": "Russian Closed Joint Stock Company",
    "ooo": "Russian Limited Liability Company",
    "gmbh": "German Limited Company",
    "ag": "German Stock Corporation",
    "sa": "Société Anonyme",
    "bv": "Dutch Private Limited",
    "nv": "Dutch Public Limited",
    "plc": "Public Limited Company",
    "jsc": "Joint Stock Company",
    "ojsc": "Open Joint Stock Company",
    "cjsc": "Closed Joint Stock Company",
    "company": "Company",
    "person": "Person",
    "organization": "Organization",
    "vessel": "Vessel",
}


def _humanize_company_type(value):
    """Map a raw company-type code to a human label; title-case anything unmapped."""
    if not value:
        return "Not specified"
    key = str(value).strip().lower()
    if key in _COMPANY_TYPE_LABELS:
        return _COMPANY_TYPE_LABELS[key]
    return str(value).replace("_", " ").title()


def _humanize_status(raw):
    status = raw.get("latest_status")
    if isinstance(status, dict):
        for k in ("value", "status", "label"):
            if status.get(k):
                status = status[k]
                break
        else:
            status = None
    if not status:
        return "Unknown"
    s = str(status).lower()
    if "active" in s and "inactive" not in s:
        return "Active"
    if "inactive" in s or "dissolved" in s or "closed" in s:
        return "Inactive"
    return str(status).replace("_", " ").title()


def _depth_range(raw):
    lo, hi = raw.get("min_depth"), raw.get("max_depth")
    if lo is not None and hi is not None:
        return f"{lo}–{hi}" if lo != hi else str(lo)
    return None


def _format_money(value):
    v = _first(value)
    if v in (None, "", 0, "0"):
        return None
    try:
        return f"${float(v):,.0f}"
    except (TypeError, ValueError):
        return str(v)


# Module-level singleton — token cache shared across requests.
sayari_service = SayariService()
