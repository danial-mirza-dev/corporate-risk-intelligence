"""
Central configuration for the Corporate Risk Intelligence Platform.

Everything needed to run is inlined here — no .env, no environment variables, no
setup steps. `python app.py` and nothing else.

Anthropic synthesis uses the hardcoded LiteLLM-proxy token and base URL below.
If a synthesis call fails for any reason the layer degrades to a deterministic,
data-driven brief so the Intelligence Brief card is never empty.
"""

# --- Sayari (provided for the exercise) ------------------------------------------
SAYARI_CLIENT_ID = "cayi459m0mKytTV4cM816T96JMUU67VP"
SAYARI_CLIENT_SECRET = "rj_jNvmR3Rb075f25XyvKOJK0xI0qj-3Vvc_E345UFyufeWQ1KQNCVD1oNljp35Q"
SAYARI_AUTH_URL = "https://api.sayari.com/oauth/token"
SAYARI_BASE_URL = "https://api.sayari.com"

# Sayari meters search/profile/traversal calls; a polite delay keeps us under any
# limit while the multi-call pipeline runs.
SAYARI_CALL_DELAY_SECONDS = 1.0

# --- Anthropic -------------------------------------------------------------------
ANTHROPIC_MODEL = "claude-opus-4-8"
# Explicit, inlined credentials so the app behaves identically whether run inside
# Claude Code or as a standalone Flask server on any machine. The client is always
# constructed with these values (see services/synthesis.py).
ANTHROPIC_BASE_URL = "https://api.tools.bloomreach.ai"
ANTHROPIC_AUTH_TOKEN = "sk-Z1k8WVBK9Z4ER5dUtHAVCw"

# --- World Bank Worldwide Governance Indicators (no key required) ----------------
# Validated working codes: the classic CC.EST/CC.PER.RNK are archived under source
# 57; the LIVE codes live under source 3 with the GOV_WGI_ prefix and the *.SC
# variant is already a 0-100 governance percentile score.
WORLD_BANK_BASE_URL = "https://api.worldbank.org/v2"
WORLD_BANK_SOURCE = 3
WORLD_BANK_INDICATORS = {
    "corruption_control": "GOV_WGI_CC.SC",
    "rule_of_law": "GOV_WGI_RL.SC",
    "political_stability": "GOV_WGI_PV.SC",
}

# --- UN Comtrade (no key required for the public preview endpoint) ---------------
# Validated format: everything in query params, NUMERIC reporter code, path C/A/HS.
COMTRADE_PREVIEW_URL = "https://comtradeapi.un.org/public/v1/preview/C/A/HS"
COMTRADE_PERIOD = "2022"

# --- Shared ----------------------------------------------------------------------
HTTP_USER_AGENT = "CorporateRiskIntelligence/2.0 (sayari-technical-exercise)"
ANALYSIS_TRADE_BASELINE_HS = "27"   # mineral fuels / oils — the demo trade corridor
