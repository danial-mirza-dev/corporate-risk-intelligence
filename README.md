# Corporate Risk Intelligence

*Forward Deployed Engineer Technical Exercise — Sayari*
*Submitted by Danial Mirza, June 2026*

---

## What This Is

A Flask web application that produces intelligence dossiers on corporate entities by combining Sayari's knowledge graph with World Bank governance data, UN Comtrade trade baselines, FATF jurisdiction status, and Anthropic synthesis. For any entity it generates a six-section dossier: a risk-rating banner, an entity profile (risk factors, ownership, corporate relationships), a sanctioned-network section (connection breakdown and a D3 timeline), a jurisdiction-risk section (FATF status, active sanctions programs, FDI, governance composite), a trade-intelligence section, and an Anthropic-synthesized intelligence brief with separate executive and analyst views.

---

## Setup — Two Commands

```bash
pip install -r requirements.txt
python app.py
```

Then open `http://localhost:5000` in your browser.

Note: All API credentials are hardcoded in `config.py` — no environment variables or `.env` files required.

---

## How to Use It

Click any demo entity chip on the landing page for an instant analysis. Six entities are preloaded: Petroleos de Venezuela S.A. (Venezuela), Myanma Economic Holdings (Myanmar), Lukoil (Russia), Korea Mining Development Trading Corporation (North Korea), Samsung Electronics (South Korea), National Iranian Oil Company (Iran).

Or type any company name in the search bar, optionally select a country, and click Analyze. A disambiguation list appears — select the correct entity and the full dossier generates.

The Intelligence Brief at the bottom has Executive View and Analyst View tabs. Executive view is plain English for non-technical stakeholders. Analyst view uses precise compliance language with regulatory citations.

---

## Data Sources

| Source | What It Provides |
|--------|-----------------|
| Sayari | Entity graph, sanctions status, ownership structure, watchlist traversal, trade shipments, designation dates |
| World Bank WGI | Corruption control, rule of law, political stability percentiles (2024) |
| FATF Reference | Jurisdiction blacklist/greylist status, maintained as static reference updated quarterly |
| UN Comtrade | Legitimate trade baselines by commodity and country corridor for anomaly detection |
| Anthropic Claude | Executive and analyst intelligence briefs synthesized from all available data |

---

## Project Structure

```
app.py                  # Flask routes and SSE streaming
config.py               # All credentials and constants (hardcoded)
data/
  demo_entities.json    # Six preloaded demo entities with entity_ids
intelligence/
  analyzer.py           # Risk rating, network timeline, trade pattern detection
services/
  sayari.py             # Sayari API client — search, entity, UBO, watchlist, trade
  worldbank.py          # World Bank WGI + FDI data
  comtrade.py           # UN Comtrade trade baselines
  synthesis.py          # Anthropic intelligence brief generation
  reference.py          # Static reference tables — country codes, FATF, sanctions programs
static/
  app.js                # Frontend logic, disambiguation flow, dossier rendering
  timeline.js           # D3.js network timeline visualization
  style.css             # Dark theme styling
templates/
  index.html            # Single page application
```

---

## Key Technical Decisions

- Sayari entity search uses POST with a JSON body filter object — not GET with URL parameters. The POST endpoint supports server-side country filtering; the GET endpoint does not.
- Designation dates are extracted from `attributes.risk_intelligence.data[].from_date` in the Sayari entity profile — more accurate than the boolean `sanctioned` flag which can lag designation events.
- OpenSanctions was evaluated and dropped. Sayari natively returns OFAC designation dates and source URLs, making the external source redundant.
- World Bank governance scores use source=3 (WGI source). Classic indicator codes like GE.EST are archived and return no data — only the GOV_WGI_*.SC codes under source 3 work.
- FATF jurisdiction status is maintained as a static reference table in `services/reference.py`. No API exists for this data.
- The Anthropic client initializes with explicit `api_key` and `base_url` parameters pointing to a LiteLLM proxy. The model is `claude-opus-4-8`.
- All credentials are hardcoded in `config.py` for zero-friction reviewer setup. This is intentional for a demo context.

---

## Scenario Coverage

This submission addresses both scenarios from the exercise brief. Scenario 1 (entity enrichment with external sources) is covered by enriching each Sayari entity with World Bank governance indicators, UN Comtrade trade baselines, FATF jurisdiction status, and Anthropic synthesis. Scenario 2 (analytics report) is covered by the six-section dossier — risk rating, network analysis, jurisdiction scoring, and trade intelligence. The platform treats each analyzed entity as a Proof of Concept engagement with a potential client, producing a deliverable that serves both technical and non-technical stakeholders.
