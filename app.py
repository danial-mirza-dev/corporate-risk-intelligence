"""
Corporate Risk Intelligence Platform — Flask application.

Runs with `python app.py` and nothing else. Three endpoints back a single-page
app: /search (disambiguation), /analyze (full dossier), /demo-entities. The
analysis pipeline runs Sayari sequentially (it is rate-limited), then World Bank
and UN Comtrade in parallel, then Anthropic synthesis last. Demo entities are
pre-warmed in a background thread on startup so the first demo lookup is instant.
"""

import json
import logging
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from flask import Flask, jsonify, render_template, request

from config import ANALYSIS_TRADE_BASELINE_HS
from intelligence.analyzer import (
    build_network_timeline,
    build_undated_nodes,
    compute_risk_rating,
    detect_trade_pattern,
    get_ubo_message,
    network_risk_band,
)
from services import comtrade, worldbank
from services.sayari import sayari_service
from services.synthesis import generate_brief

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-5s %(name)s :: %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("app")

app = Flask(__name__)

_HERE = os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(_HERE, "data", "demo_entities.json"), encoding="utf-8") as fh:
    DEMO_ENTITIES = json.load(fh)

# Country code -> primary country (for Comtrade reporter + WB). Falls back to the
# entity's own country codes from its Sayari profile.
_DEMO_COUNTRY_BY_NAME = {e["name"].lower(): e["country"] for e in DEMO_ENTITIES}

# Known sanctioned anchor for shortest-path checks (Atic Energy FZE, OFAC SDN).
# When a different entity has sanctioned-network exposure, we test whether a short
# corporate path links it to this anchor and surface it as a direct connection.
_ANCHOR_ID = "s-gHsFl-X8vaQS8Bvy8Vqg"
_ANCHOR_NAME = "Atic Energy FZE"
_SHORTEST_PATH_MAX = 4   # only surface paths this short (longer = not "direct")

# Pre-warm caches (populated by the background warmer; read by /search & /analyze).
_SEARCH_CACHE = {}     # (name_lower, country) -> candidates list
_PROFILE_CACHE = {}    # entity_id -> profile dict
_CACHE_LOCK = threading.Lock()


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@app.route("/")
def index():
    return render_template("index.html", demo_entities=DEMO_ENTITIES)


@app.route("/demo-entities")
def demo_entities():
    return jsonify(DEMO_ENTITIES)


@app.route("/reference/jurisdiction/<country>")
def jurisdiction_reference(country):
    """FATF status + sanctions-programs reference for a country (ISO-2 or ISO-3)."""
    from services.reference import (
        FATF_STATUS, FATF_DEFAULT, SANCTIONS_PROGRAMS, SANCTIONS_DEFAULT,
    )
    code = _to_iso3((country or "").upper())
    fatf = FATF_STATUS.get(code, FATF_DEFAULT)
    sanctions = SANCTIONS_PROGRAMS.get(code, SANCTIONS_DEFAULT)
    return jsonify({"fatf": fatf, "sanctions": sanctions, "country": code})


@app.route("/search", methods=["POST"])
def search():
    body = request.get_json(silent=True) or {}
    name = (body.get("name") or "").strip()
    country = (body.get("country") or "").strip()
    if country.lower() in ("", "all", "all countries"):
        country = None
    if not name:
        return jsonify({"candidates": [], "error": "Please enter an entity name."}), 400

    cache_key = (name.lower(), country or "")
    with _CACHE_LOCK:
        cached = _SEARCH_CACHE.get(cache_key)
    if cached is not None:
        log.info("search cache hit for %r (%s)", name, country)
        return jsonify({"candidates": cached})

    t0 = time.time()
    candidates = sayari_service.search_entity(name, country=country, limit=5)
    log.info("search %r country=%s -> %d candidates (%.0fms)",
             name, country, len(candidates), (time.time() - t0) * 1000)
    with _CACHE_LOCK:
        _SEARCH_CACHE[cache_key] = candidates
    return jsonify({"candidates": candidates})


@app.route("/analyze", methods=["POST"])
def analyze():
    body = request.get_json(silent=True) or {}
    entity_id = (body.get("entity_id") or "").strip()
    entity_name = (body.get("entity_name") or "").strip()
    country = (body.get("country") or "").strip() or None
    if not entity_id:
        return jsonify({"error": "Missing entity_id."}), 400

    pipeline_start = time.time()
    log.info("=== ANALYZE %s (%s) ===", entity_name, entity_id)

    # --- Sayari (sequential — the client is rate-limited) ---
    profile = _cached_profile(entity_id)
    if profile is None:
        return jsonify({"error": "Entity profile could not be retrieved."}), 502

    entity_name = entity_name or profile.get("label") or entity_id

    ubo = _timed("ubo", sayari_service.get_ubo, entity_id)
    watchlist = _timed("watchlist", sayari_service.get_watchlist, entity_id)
    traversal = _timed("traversal", sayari_service.get_traversal, entity_id, 10)
    trade = _timed("trade", sayari_service.get_trade_shipments, entity_id, entity_name, 10)

    # --- Determine the operating country for jurisdiction + trade baseline ---
    country_code = _resolve_country_code(profile, entity_name, country)

    # --- World Bank + UN Comtrade in parallel (different hosts, no Sayari pacing) ---
    wb_data, comtrade_data = _run_external_parallel(country_code)

    # --- Derived intelligence ---
    risk_rating = compute_risk_rating(profile, watchlist, ubo)
    timeline_nodes = build_network_timeline(watchlist)
    trade_pattern = detect_trade_pattern(trade, comtrade_data, profile)
    ubo_message = get_ubo_message(ubo, profile) if ubo else None
    # Primary jurisdiction (ISO-3) for the FATF / sanctions reference lookup. The
    # user-selected search country reflects the jurisdiction being assessed and is
    # preferred (an entity's country_codes[0] is often an incidental foreign
    # registration — e.g. Rosneft lists UAE first). Fall back to the resolved code.
    primary_country = _to_iso3(country) if country else _to_iso3(country_code)
    if not primary_country:
        codes = (profile or {}).get("country_codes") or []
        primary_country = _to_iso3(codes[0]) if codes else None

    # --- Trade anomaly / opacity finding ---
    trade_finding = _trade_finding(trade, comtrade_data, profile)

    # --- Shortest path to a known sanctioned anchor (only if meaningfully short) ---
    shortest_path = None
    if entity_id != _ANCHOR_ID and (watchlist or {}).get("path_count"):
        sp = _timed("shortest_path", sayari_service.get_shortest_path, entity_id, _ANCHOR_ID)
        if sp and sp.get("length") is not None and sp["length"] <= _SHORTEST_PATH_MAX:
            sp["anchor_name"] = _ANCHOR_NAME
            shortest_path = sp

    # --- Jurisdiction reference (FATF + sanctions) for the primary country ---
    from services.reference import (
        FATF_STATUS, FATF_DEFAULT, SANCTIONS_PROGRAMS, SANCTIONS_DEFAULT,
    )
    fatf_status = FATF_STATUS.get(primary_country, FATF_DEFAULT)
    sanctions_programs = SANCTIONS_PROGRAMS.get(primary_country, SANCTIONS_DEFAULT)

    # --- Undated sanctioned connections (rendered below the timeline) ---
    timeline_undated = build_undated_nodes(watchlist)

    # --- Synthesis (last, with everything) ---
    t0 = time.time()
    brief = generate_brief(
        entity_name, profile, ubo, watchlist, wb_data, comtrade_data, trade,
        risk_rating, trade_pattern,
        designation_date=(profile or {}).get("designation_date"),
        designation_url=(profile or {}).get("designation_url"),
        connection_breakdown=(watchlist or {}).get("paths"),
        fatf_status=fatf_status,
        sanctions_programs=sanctions_programs,
        fdi_data=(wb_data or {}).get("fdi"),
        ubo_message=ubo_message,
    )
    log.info("synthesis (%s) done (%.0fms)", brief.get("source"), (time.time() - t0) * 1000)

    # Network context sentence.
    network_context = None
    if watchlist.get("path_count"):
        band = network_risk_band(watchlist["path_count"])
        pc = watchlist["path_count"]
        conn = "connection" if pc == 1 else "connections"
        network_context = (
            f"This entity's corporate network contains {pc} {conn} "
            f"to sanctioned entities across "
            f"{watchlist.get('explored_count', 0):,} explored relationships. "
            f"This indicates {band} network risk.")

    dossier = {
        "entity_id": entity_id,
        "entity_name": entity_name,
        "risk_rating": risk_rating,
        "primary_country": primary_country,
        "key_finding": brief.get("key_finding"),
        "profile": profile,
        "ubo": ubo,
        "ubo_message": ubo_message,
        "watchlist": watchlist,
        "traversal": traversal,
        "trade": trade,
        "trade_finding": trade_finding,
        "trade_pattern": trade_pattern,
        "worldbank": wb_data,
        "comtrade": comtrade_data,
        "timeline_nodes": timeline_nodes,
        "timeline_undated": timeline_undated,
        "network_context": network_context,
        "shortest_path": shortest_path,
        "brief": {
            "executive": brief.get("executive"),
            "analyst": brief.get("analyst"),
            "confidence": brief.get("confidence"),
            "recommended_action": brief.get("recommended_action"),
            "key_finding": brief.get("key_finding"),
            "source": brief.get("source"),
        },
        "analyzed_at": time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime()),
    }
    log.info("=== ANALYZE %s complete: %s (%.1fs total) ===",
             entity_name, risk_rating, time.time() - pipeline_start)
    return jsonify(dossier)


# ---------------------------------------------------------------------------
# Pipeline helpers
# ---------------------------------------------------------------------------
def _timed(label, fn, *args):
    t0 = time.time()
    try:
        result = fn(*args)
    except Exception as e:  # noqa: BLE001 — one source failing must not kill the dossier
        log.warning("step %s failed: %r", label, e)
        result = None
    log.info("step %s done (%.0fms)", label, (time.time() - t0) * 1000)
    return result


def _cached_profile(entity_id):
    with _CACHE_LOCK:
        cached = _PROFILE_CACHE.get(entity_id)
    if cached is not None:
        log.info("profile cache hit for %s", entity_id)
        return cached
    profile = _timed("profile", sayari_service.get_entity_profile, entity_id)
    if profile is not None:
        with _CACHE_LOCK:
            _PROFILE_CACHE[entity_id] = profile
    return profile


def _to_iso3(code):
    """Normalize an ISO-2 (or already ISO-3) country code to ISO-3."""
    from services.sayari import _ISO2_TO_ISO3
    c = (code or "").upper()
    return _ISO2_TO_ISO3.get(c, c)


def _resolve_country_code(profile, entity_name, requested_country):
    """Best operating-country code for jurisdiction + trade baseline lookups."""
    # Prefer the demo mapping (curated), then the entity's own first country, then
    # the requested country from the search form.
    demo = _DEMO_COUNTRY_BY_NAME.get((entity_name or "").lower())
    if demo:
        return demo
    codes = (profile or {}).get("country_codes") or []
    if codes:
        return codes[0]
    return requested_country


def _run_external_parallel(country_code):
    """World Bank + UN Comtrade concurrently. Either may be None."""
    if not country_code:
        return None, None
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=2) as pool:
        wb_future = pool.submit(_safe, worldbank.get_governance_scores, country_code)
        ct_future = pool.submit(_safe, comtrade.get_trade_baseline,
                                country_code, ANALYSIS_TRADE_BASELINE_HS)
        wb_data = wb_future.result()
        comtrade_data = ct_future.result()
    log.info("external (WB + Comtrade) done (%.0fms)", (time.time() - t0) * 1000)
    return wb_data, comtrade_data


def _safe(fn, *args):
    try:
        return fn(*args)
    except Exception as e:  # noqa: BLE001
        log.warning("external source %s failed: %r", getattr(fn, "__name__", fn), e)
        return None


def _trade_finding(trade, comtrade_data, profile):
    """Anomaly / opacity / services / consistency finding for the Trade card."""
    from intelligence.analyzer import (
        _is_trading_company, _is_services_company, _entity_trade_value,
    )

    if trade and not trade.get("empty") and trade.get("total"):
        entity_value = _entity_trade_value(trade)
        baseline = (comtrade_data or {}).get("total_value")
        # Records exist: only a computable value supports a baseline comparison.
        # Without one we render the shipment table alone — no misleading "no trade"
        # callout (the entity clearly has documented trade).
        if not entity_value or not baseline:
            return None
        return comtrade.calculate_anomaly(entity_value, baseline, is_trading_company=True)
    # Zero documented records — software/services firms don't ship goods.
    if _is_services_company(profile):
        return {
            "type": "services_no_trade",
            "headline": "No Trade Records",
            "explanation": ("No trade records found. This is expected for software, "
                            "technology, and services companies that do not ship "
                            "physical goods."),
        }
    return comtrade.calculate_anomaly(None, None,
                                      is_trading_company=_is_trading_company(profile))


# ---------------------------------------------------------------------------
# Startup pre-warming
# ---------------------------------------------------------------------------
def _prewarm():
    """Search + profile the demo entities so the first demo lookup is instant.
    Spaced 2s apart to respect Sayari pacing; runs once in a background thread."""
    log.info("pre-warm: starting for %d demo entities", len(DEMO_ENTITIES))
    for i, ent in enumerate(DEMO_ENTITIES, 1):
        name, country = ent["name"], ent.get("country")
        try:
            candidates = sayari_service.search_entity(name, country=country, limit=5)
            with _CACHE_LOCK:
                _SEARCH_CACHE[(name.lower(), country or "")] = candidates
                _SEARCH_CACHE[(name.lower(), "")] = candidates
            if candidates:
                top = candidates[0]
                profile = sayari_service.get_entity_profile(top["entity_id"])
                if profile:
                    with _CACHE_LOCK:
                        _PROFILE_CACHE[top["entity_id"]] = profile
                log.info("pre-warm %d/%d: %s -> %s", i, len(DEMO_ENTITIES),
                         name, top.get("entity_id"))
            else:
                log.info("pre-warm %d/%d: %s -> no candidates", i, len(DEMO_ENTITIES), name)
        except Exception as e:  # noqa: BLE001
            log.warning("pre-warm failed for %s: %r", name, e)
        time.sleep(2)
    log.info("pre-warm: complete")


def _start_prewarm_once():
    # Avoid double-warming under the Flask reloader (it spawns two processes).
    if os.environ.get("WERKZEUG_RUN_MAIN") == "true" or not app.debug:
        threading.Thread(target=_prewarm, name="prewarm", daemon=True).start()


if __name__ == "__main__":
    _start_prewarm_once()
    log.info("Corporate Risk Intelligence Platform — starting on http://127.0.0.1:5000")
    app.run(host="127.0.0.1", port=5000, debug=False)
