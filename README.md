# Corporate Risk Intelligence
*Powered by Sayari · World Bank · UN Comtrade · Anthropic*

*Forward Deployed Engineer Technical Exercise — Sayari | Submitted by Danial Mirza, June 2026*

---

## What Does This Do?

Have you ever needed to know whether a company is safe to do business with — but had no idea where to start?

This tool answers that question in under 30 seconds.

Type in any company name anywhere in the world. Within moments, you'll see a complete intelligence report telling you:

- **Who they are** — where they're registered, when they were founded, what type of company they are
- **Who they're connected to** — other companies and individuals in their network, including any with sanctions designations
- **Where they operate** — the risk level of their jurisdiction based on international watchlists and governance data
- **What they actually do** — documented trade shipments and how that compares to legitimate global trade patterns
- **What you should do** — a plain-English summary of the risk and a recommended action, written for both executives and compliance professionals

You don't need to be a sanctions expert or a data analyst to use this. If you can type a company name, you can use this tool.

---

<img width="883" height="452" alt="landing-page" src="https://github.com/user-attachments/assets/96ed9512-fa1c-4659-b4dc-5001b3876fbc" />

---

## Getting Started

You need Python installed on your computer. That's it.

**Step 1 — Download the code**

Click the green **Code** button at the top of this page and select **Download ZIP**. Unzip the folder somewhere on your computer.

Or if you're comfortable with Git:
```bash
git clone https://github.com/danial-mirza-dev/corporate-risk-intelligence.git
cd corporate-risk-intelligence
```

**Step 2 — Install dependencies**

Open a terminal, navigate to the folder you just downloaded, and run:

```bash
pip install -r requirements.txt
```

**Step 3 — Start the app**

```bash
python app.py
```

**Step 4 — Open your browser**

Go to: **http://localhost:5000**

The app will load and you'll see the home screen with six preloaded company examples ready to explore.

No accounts to create. No API keys to configure. Everything is ready to go out of the box.

---

## How to Use It

### Option 1 — Try a preloaded example

When you open the app you'll see six company names on the home screen. These are real companies that have been preloaded for demonstration. Click any one of them and the full report generates automatically.

Each example is chosen to show a different type of risk:

| Company | Country | What It Shows |
|---------|---------|---------------|
| Petroleos de Venezuela S.A. | Venezuela | State-owned oil company under US sanctions with thousands of documented shipments |
| Myanma Economic Holdings | Myanmar | Military-controlled conglomerate sanctioned after the 2021 coup — banking, mining, tourism |
| Lukoil | Russia | Russia's second-largest oil company, sanctioned October 2025 |
| Korea Mining Development Trading Corporation | North Korea | North Korea's primary arms dealer, subject to 6 overlapping UN and US sanctions programs |
| Samsung Electronics | South Korea | A clean, well-known company — shows how the tool surfaces hidden supply chain risk even when there's no direct sanctions exposure |
| National Iranian Oil Company | Iran | Iran's state oil company — the most comprehensive example, with 57 documented petroleum shipments and a $91 billion trade baseline comparison |

### Option 2 — Search any company

Type any company name in the search bar. You can also narrow your search by selecting a country from the dropdown. The tool will show you a list of matching companies — select the right one and the full report generates.

---

<img width="2992" height="10506" alt="Screenshot 2026-06-15 at 10-35-36 Corporate Risk Intelligence" src="https://github.com/user-attachments/assets/c40f84f8-9a30-4209-a766-10bbd7c6a33e" />

---

## What's in the Report?

Every report has six sections:

**Risk Banner** — A headline summary at the top. Tells you the risk level (High, Medium, or Low), when the company was founded, and the single most important finding about this entity.

**Entity Profile** — The company's basic details: where it's registered, what type of company it is, its risk indicators, who owns it, and its corporate relationships. Any connections to sanctioned parties are flagged in red.

**Sanctioned Network** — If the company has connections to sanctioned entities, this section maps those connections. You'll see exactly how they're connected, through how many corporate steps, and what those sanctioned entities are designated for.

**Jurisdiction Risk** — A risk assessment of the country where the company operates. This includes the country's status on the FATF international watchlist (blacklisted, greylisted, or clean), how many active international sanctions programs target that country, and governance scores from the World Bank.

**Trade Intelligence** — Documented shipments of goods associated with this company, compared against legitimate global trade baselines from the United Nations. If a company claims to be a trading firm but has no documented shipments, that gets flagged.

**Intelligence Brief** — A written summary in two formats. The Executive View is a plain-English paragraph written for a CEO or board member who needs to make a fast decision. The Analyst View is a detailed compliance assessment with specific regulatory references, written for a legal or risk professional.

---

## Where Does the Data Come From?

This tool combines five data sources that would normally require separate subscriptions, logins, and expertise to access:

| Source | What It Contributes |
|--------|---------------------|
| **Sayari** | The core intelligence layer. Sayari's knowledge graph contains corporate registries, sanctions designations, ownership structures, and trade records from around the world. This is the primary data source. |
| **World Bank** | Governance scores for every country — measuring corruption control, rule of law, and political stability. Updated annually. |
| **FATF** | The Financial Action Task Force maintains a list of countries with inadequate anti-money-laundering controls. Iran and North Korea are blacklisted. UAE was greylisted until February 2024. This tool reflects current FATF status. |
| **UN Comtrade** | The United Nations' global trade database. Used to establish what legitimate trade volumes look like for a given commodity and country — so we can flag when something looks abnormal. |
| **Anthropic Claude** | The AI layer that reads all the data from the above sources and writes the intelligence briefs in plain English. |

---

## For the Technical Reviewer

### Project Structure

```
app.py                  # Flask application — routes, API orchestration
config.py               # All credentials and constants (hardcoded for reviewer convenience)
data/
  demo_entities.json    # Six preloaded demo entities with resolved Sayari entity_ids
intelligence/
  analyzer.py           # Risk rating logic, network timeline builder, trade pattern detection
services/
  sayari.py             # Sayari API client — search (POST), entity, UBO, watchlist, trade
  worldbank.py          # World Bank WGI governance scores + FDI data
  comtrade.py           # UN Comtrade trade baselines by commodity and country
  synthesis.py          # Anthropic brief generation with structured intelligence payload
  reference.py          # Static reference tables — country codes, FATF status, sanctions programs
static/
  app.js                # Frontend logic — disambiguation flow, dossier rendering, SSE handling
  timeline.js           # D3.js network timeline visualization with collision resolution
  style.css             # Dark theme CSS
templates/
  index.html            # Single-page application shell
```

### Key Technical Decisions

- **Sayari search uses POST, not GET.** The POST endpoint with a JSON body filter supports server-side country filtering. The GET endpoint ignores filter parameters. This was discovered through direct API testing and is documented in the Sayari API reference.

- **Designation dates come from Sayari attributes, not the sanctioned flag.** The boolean `sanctioned` field can lag actual designation events. Dates are extracted from `attributes.risk_intelligence.data[].from_date`, which proved more current in testing.

- **OpenSanctions was evaluated and dropped.** Sayari natively returns OFAC designation dates and source URLs. The external source was redundant and added latency.

- **World Bank scores require source=3.** Classic indicator codes (GE.EST, CC.EST) are archived and return no data. Only GOV_WGI_*.SC codes under source=3 return current 2024 values.

- **FATF status is a static reference table.** FATF has no public API. The reference table in `services/reference.py` reflects FATF's February 2024 update (UAE removal from grey list) and is updated manually on a quarterly basis.

- **All credentials are hardcoded in config.py.** This is intentional for a demo submission — zero setup friction for the reviewer.

### Scenario Coverage

This submission addresses both scenarios from the exercise brief. Scenario 1 (entity enrichment with external sources) is covered through World Bank, UN Comtrade, FATF, and Anthropic enrichment layered on top of Sayari entity data. Scenario 2 (analytics report) is covered through the six-section dossier with risk rating, network analysis, jurisdiction scoring, and trade intelligence. The platform is designed as a Proof of Concept client deliverable — something a Forward Deployed Engineer would demo to a potential Sayari customer.
