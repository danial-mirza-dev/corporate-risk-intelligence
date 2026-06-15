"""
Shared reference data and translation helpers.

The platform's core principle is that nothing raw reaches the screen: every code,
key, and abbreviation is translated to plain English here, in one place, so the
services and the analyzer all speak the same vocabulary.
"""

# ---------------------------------------------------------------------------
# Country codes -> full names (covers every code seen in Sayari/Comtrade output)
# ---------------------------------------------------------------------------
COUNTRY_NAMES = {
    "AE": "United Arab Emirates", "ARE": "United Arab Emirates",
    "RU": "Russia", "RUS": "Russia",
    "IR": "Iran", "IRN": "Iran",
    "CN": "China", "CHN": "China",
    "US": "United States", "USA": "United States",
    "GB": "United Kingdom", "GBR": "United Kingdom",
    "DE": "Germany", "DEU": "Germany",
    "FR": "France", "FRA": "France",
    "NG": "Nigeria", "NGA": "Nigeria",
    "PA": "Panama", "PAN": "Panama",
    "MZ": "Mozambique", "MOZ": "Mozambique",
    "SM": "San Marino", "SMR": "San Marino",
    "GA": "Gabon", "GAB": "Gabon",
    "GY": "Guyana", "GUY": "Guyana",
    "CW": "Curaçao", "CUW": "Curaçao",
    "KM": "Comoros", "COM": "Comoros",
    "CM": "Cameroon", "CMR": "Cameroon",
    "LR": "Liberia", "LBR": "Liberia",
    "GN": "Guinea", "GIN": "Guinea",
    "ZW": "Zimbabwe", "ZWE": "Zimbabwe",
    "SY": "Syria", "SYR": "Syria",
    "IN": "India", "IND": "India",
    "TR": "Turkey", "TUR": "Turkey",
    "KZ": "Kazakhstan", "KAZ": "Kazakhstan",
    "BE": "Belgium", "BEL": "Belgium",
    "CH": "Switzerland", "CHE": "Switzerland",
    "JP": "Japan", "JPN": "Japan",
    "KR": "South Korea", "KOR": "South Korea",
    "SA": "Saudi Arabia", "SAU": "Saudi Arabia",
    "QA": "Qatar", "QAT": "Qatar",
    "CY": "Cyprus", "CYP": "Cyprus",
    "BG": "Bulgaria", "BGR": "Bulgaria",
    "KG": "Kyrgyzstan", "KGZ": "Kyrgyzstan",
    "NL": "Netherlands", "NLD": "Netherlands",
    "HK": "Hong Kong", "HKG": "Hong Kong",
    "LU": "Luxembourg", "LUX": "Luxembourg",
    "CA": "Canada", "CAN": "Canada",
    "SG": "Singapore", "SGP": "Singapore",
    "AU": "Australia", "AUS": "Australia",
    "MT": "Malta", "MLT": "Malta",
    "SC": "Seychelles", "SYC": "Seychelles",
    "VG": "British Virgin Islands", "VGB": "British Virgin Islands",
    "MH": "Marshall Islands", "MHL": "Marshall Islands",
    # --- Broad ISO-3 coverage for every code seen across Sayari responses ---
    "COG": "Republic of Congo", "SLE": "Sierra Leone", "GNQ": "Equatorial Guinea",
    "TCD": "Chad", "MLI": "Mali", "BFA": "Burkina Faso", "NER": "Niger",
    "SDN": "Sudan", "SSD": "South Sudan", "ERI": "Eritrea", "DJI": "Djibouti",
    "SOM": "Somalia", "ETH": "Ethiopia", "UGA": "Uganda", "RWA": "Rwanda",
    "BDI": "Burundi", "TZA": "Tanzania", "KEN": "Kenya", "MDG": "Madagascar",
    "ZMB": "Zambia", "MWI": "Malawi", "BWA": "Botswana", "NAM": "Namibia",
    "AGO": "Angola", "COD": "Democratic Republic of Congo",
    "CAF": "Central African Republic", "GHA": "Ghana", "CIV": "Ivory Coast",
    "SEN": "Senegal", "GNB": "Guinea-Bissau", "CPV": "Cape Verde",
    "STP": "São Tomé and Príncipe", "MUS": "Mauritius",
    "CYP": "Cyprus", "LIE": "Liechtenstein", "MCO": "Monaco", "AND": "Andorra",
    "ISL": "Iceland", "MKD": "North Macedonia", "ALB": "Albania",
    "MNE": "Montenegro", "SRB": "Serbia", "BIH": "Bosnia and Herzegovina",
    "HRV": "Croatia", "SVN": "Slovenia", "SVK": "Slovakia", "CZE": "Czech Republic",
    "HUN": "Hungary", "ROU": "Romania", "MDA": "Moldova", "BLR": "Belarus",
    "UKR": "Ukraine", "GEO": "Georgia", "ARM": "Armenia", "AZE": "Azerbaijan",
    "UZB": "Uzbekistan", "TKM": "Turkmenistan", "TJK": "Tajikistan",
    "MNG": "Mongolia", "PRK": "North Korea", "MMR": "Myanmar", "KHM": "Cambodia",
    "LAO": "Laos", "VNM": "Vietnam", "THA": "Thailand", "MYS": "Malaysia",
    "IDN": "Indonesia", "PHL": "Philippines", "BGD": "Bangladesh",
    "LKA": "Sri Lanka", "NPL": "Nepal", "PAK": "Pakistan", "AFG": "Afghanistan",
    "IRQ": "Iraq", "YEM": "Yemen", "OMN": "Oman", "BHR": "Bahrain",
    "KWT": "Kuwait", "JOR": "Jordan", "LBN": "Lebanon", "ISR": "Israel",
    "PSE": "Palestine", "EGY": "Egypt", "LBY": "Libya", "TUN": "Tunisia",
    "DZA": "Algeria", "MAR": "Morocco", "MRT": "Mauritania",
    "VEN": "Venezuela", "COL": "Colombia", "ECU": "Ecuador", "PER": "Peru",
    "BOL": "Bolivia", "PRY": "Paraguay", "URY": "Uruguay", "ARG": "Argentina",
    "CHL": "Chile", "BRA": "Brazil", "SUR": "Suriname",
    "TTO": "Trinidad and Tobago", "CUB": "Cuba", "HTI": "Haiti",
    "DOM": "Dominican Republic", "JAM": "Jamaica", "CRI": "Costa Rica",
    "NIC": "Nicaragua", "HND": "Honduras", "SLV": "El Salvador",
    "GTM": "Guatemala", "MEX": "Mexico", "BLZ": "Belize",
    "VCT": "Saint Vincent and the Grenadines", "KNA": "Saint Kitts and Nevis",
    "ATG": "Antigua and Barbuda", "DMA": "Dominica", "GRD": "Grenada",
    "LCA": "Saint Lucia", "MSR": "Montserrat", "CYM": "Cayman Islands",
    "BMU": "Bermuda", "TCA": "Turks and Caicos Islands", "ABW": "Aruba",
    "PLW": "Palau", "FSM": "Micronesia", "MNP": "Northern Mariana Islands",
    "GUM": "Guam", "WSM": "Samoa", "TON": "Tonga", "FJI": "Fiji",
    "VUT": "Vanuatu", "SLB": "Solomon Islands", "PNG": "Papua New Guinea",
    "NZL": "New Zealand", "ITA": "Italy", "ESP": "Spain", "SWE": "Sweden",
    "NOR": "Norway", "DNK": "Denmark", "POL": "Poland", "TWN": "Taiwan",
    "AT": "Austria", "AUT": "Austria", "IE": "Ireland", "IRL": "Ireland",
    "PT": "Portugal", "PRT": "Portugal", "FI": "Finland", "FIN": "Finland",
    "GR": "Greece", "GRC": "Greece",
}


def country_name(code):
    """Full country name for an ISO-2/ISO-3 code; returns the raw code if unmapped."""
    if not code:
        return None
    return COUNTRY_NAMES.get(str(code).upper(), str(code).upper())


def country_names(codes):
    """Comma-joined full names for a list of codes, de-duplicated, order-preserving."""
    out, seen = [], set()
    for c in codes or []:
        name = country_name(c)
        if name and name not in seen:
            seen.add(name)
            out.append(name)
    return ", ".join(out)


# ---------------------------------------------------------------------------
# UN Comtrade numeric reporter codes
# ---------------------------------------------------------------------------
COMTRADE_NUMERIC = {
    "IR": 364, "IRN": 364,
    "RU": 643, "RUS": 643,
    "AE": 784, "ARE": 784,
    "CN": 156, "CHN": 156,
    "TR": 792, "TUR": 792,
    "IN": 699, "IND": 699,
    "KZ": 398, "KAZ": 398,
}


def comtrade_code(country_code):
    """Numeric Comtrade reporter code for an ISO country code, or None."""
    if not country_code:
        return None
    return COMTRADE_NUMERIC.get(str(country_code).upper())


# ---------------------------------------------------------------------------
# Harmonized System (HS) commodity codes -> plain English
# ---------------------------------------------------------------------------
HS_CODE_DESCRIPTIONS = {
    "27": "Mineral Fuels & Oils",
    "2709": "Crude Petroleum Oils",
    "270900": "Crude Petroleum Oils",
    "2710": "Refined Petroleum Oils",
    "271000": "Refined Petroleum Oils",
    "2711": "Petroleum Gases (LPG/LNG)",
    "2701": "Coal",
    "49": "Printed Materials",
    "4907": "Banknotes & Securities Documents",
    "490700": "Banknotes & Securities Documents",
    "72": "Iron & Steel",
    "84": "Machinery & Mechanical Appliances",
    "85": "Electrical Machinery & Equipment",
    "88": "Aircraft & Spacecraft",
    "89": "Ships & Floating Structures",
    "93": "Arms & Ammunition",
    "71": "Precious Metals & Stones",
}


# ---------------------------------------------------------------------------
# FATF status (static reference, as of June 2026 — maintained quarterly).
# ---------------------------------------------------------------------------
FATF_STATUS = {
    "IRN": {"status": "Black List", "label": "High-Risk Jurisdiction", "color": "high", "note": "Subject to FATF call for action since 2008"},
    "PRK": {"status": "Black List", "label": "High-Risk Jurisdiction", "color": "high", "note": "Subject to FATF call for action"},
    "RUS": {"status": "Suspended", "label": "FATF Membership Suspended", "color": "high", "note": "Suspended February 2023 following invasion of Ukraine"},
    "SYR": {"status": "Grey List", "label": "Increased Monitoring", "color": "medium", "note": "Subject to FATF increased monitoring"},
    "YEM": {"status": "Grey List", "label": "Increased Monitoring", "color": "medium", "note": "Subject to FATF increased monitoring"},
    "MMR": {"status": "Grey List", "label": "Increased Monitoring", "color": "medium", "note": "Subject to FATF increased monitoring since 2022"},
    "VEN": {"status": "Grey List", "label": "Increased Monitoring", "color": "medium", "note": "Subject to FATF increased monitoring"},
    "LAO": {"status": "Grey List", "label": "Increased Monitoring", "color": "medium", "note": "Subject to FATF increased monitoring"},
    "KHM": {"status": "Grey List", "label": "Increased Monitoring", "color": "medium", "note": "Subject to FATF increased monitoring"},
    "HTI": {"status": "Grey List", "label": "Increased Monitoring", "color": "medium", "note": "Subject to FATF increased monitoring"},
    "MOZ": {"status": "Grey List", "label": "Increased Monitoring", "color": "medium", "note": "Subject to FATF increased monitoring"},
    "TZA": {"status": "Grey List", "label": "Increased Monitoring", "color": "medium", "note": "Subject to FATF increased monitoring"},
    "NGA": {"status": "Grey List", "label": "Increased Monitoring", "color": "medium", "note": "Subject to FATF increased monitoring"},
    "ZAF": {"status": "Grey List", "label": "Increased Monitoring", "color": "medium", "note": "Removed from grey list 2025"},
    "ARE": {"status": "Clean", "label": "Standard Jurisdiction", "color": "low", "note": "Removed from grey list February 2024"},
    "USA": {"status": "Clean", "label": "Standard Jurisdiction", "color": "low", "note": "FATF founding member"},
    "GBR": {"status": "Clean", "label": "Standard Jurisdiction", "color": "low", "note": "FATF member"},
    "DEU": {"status": "Clean", "label": "Standard Jurisdiction", "color": "low", "note": "FATF member"},
    "FRA": {"status": "Clean", "label": "Standard Jurisdiction", "color": "low", "note": "FATF member"},
    "CHN": {"status": "Clean", "label": "Standard Jurisdiction", "color": "low", "note": "FATF member"},
    "JPN": {"status": "Clean", "label": "Standard Jurisdiction", "color": "low", "note": "FATF member"},
    "SGP": {"status": "Clean", "label": "Standard Jurisdiction", "color": "low", "note": "FATF member"},
    "CHE": {"status": "Clean", "label": "Standard Jurisdiction", "color": "low", "note": "FATF member"},
    "NLD": {"status": "Clean", "label": "Standard Jurisdiction", "color": "low", "note": "FATF member"},
    "CYP": {"status": "Clean", "label": "Standard Jurisdiction", "color": "medium", "note": "EU member, elevated financial secrecy risk"},
    "VGB": {"status": "Clean", "label": "Offshore Jurisdiction", "color": "medium", "note": "British Overseas Territory, high financial secrecy"},
    "CYM": {"status": "Clean", "label": "Offshore Jurisdiction", "color": "medium", "note": "British Overseas Territory, high financial secrecy"},
    "PAN": {"status": "Clean", "label": "Standard Jurisdiction", "color": "medium", "note": "Elevated financial opacity risk"},
    "SAU": {"status": "Clean", "label": "Standard Jurisdiction", "color": "low", "note": "FATF member"},
    "TUR": {"status": "Clean", "label": "Standard Jurisdiction", "color": "medium", "note": "FATF member, elevated risk indicators"},
    "IND": {"status": "Clean", "label": "Standard Jurisdiction", "color": "low", "note": "FATF member"},
    "BRA": {"status": "Clean", "label": "Standard Jurisdiction", "color": "low", "note": "FATF member"},
}
FATF_DEFAULT = {"status": "Unknown", "label": "Status Unknown", "color": "medium", "note": "FATF status not available for this jurisdiction"}


# ---------------------------------------------------------------------------
# Major active sanctions programs by country (static reference).
# ---------------------------------------------------------------------------
SANCTIONS_PROGRAMS = {
    "IRN": {"programs": ["OFAC Iran (Comprehensive)", "EU Iran Sanctions", "UN Resolution 1737", "UN Resolution 1747", "UN Resolution 1803", "UN Resolution 2231"], "count": 6, "summary": "Subject to the most extensive multilateral sanctions regime globally"},
    "PRK": {"programs": ["OFAC DPRK (Comprehensive)", "UN Resolution 1718", "UN Resolution 1874", "UN Resolution 2087", "UN Resolution 2094", "EU DPRK Sanctions"], "count": 6, "summary": "Comprehensive multilateral sanctions including weapons proliferation restrictions"},
    "RUS": {"programs": ["OFAC Russia (Executive Orders)", "EU Russia Sanctions (14 packages)", "UK Russia Sanctions"], "count": 3, "summary": "Extensive sanctions following February 2022 invasion of Ukraine"},
    "SYR": {"programs": ["OFAC Syria (Comprehensive)", "EU Syria Sanctions"], "count": 2, "summary": "Comprehensive sanctions on government and associated entities"},
    "BLR": {"programs": ["OFAC Belarus", "EU Belarus Sanctions"], "count": 2, "summary": "Sanctions following disputed 2020 election and human rights violations"},
    "CUB": {"programs": ["OFAC Cuba (Comprehensive)"], "count": 1, "summary": "US comprehensive embargo"},
    "VEN": {"programs": ["OFAC Venezuela (Sectoral)"], "count": 1, "summary": "Sectoral sanctions targeting government and key industries"},
    "MMR": {"programs": ["OFAC Myanmar", "EU Myanmar Sanctions"], "count": 2, "summary": "Sanctions following February 2021 military coup"},
    "ZWE": {"programs": ["OFAC Zimbabwe (Targeted)"], "count": 1, "summary": "Targeted sanctions on specific individuals and entities"},
    "LBY": {"programs": ["OFAC Libya", "UN Libya Sanctions"], "count": 2, "summary": "Arms embargo and targeted sanctions"},
    "SDN": {"programs": ["OFAC Sudan (Targeted)"], "count": 1, "summary": "Targeted sanctions on specific actors"},
    "MLI": {"programs": ["EU Mali Sanctions"], "count": 1, "summary": "EU targeted sanctions following coup"},
    "ARE": {"programs": [], "count": 0, "summary": "No country-level sanctions programs"},
    "USA": {"programs": [], "count": 0, "summary": "No country-level sanctions programs"},
    "GBR": {"programs": [], "count": 0, "summary": "No country-level sanctions programs"},
    "CHN": {"programs": [], "count": 0, "summary": "No comprehensive country-level programs. Entity-specific export controls apply"},
}
SANCTIONS_DEFAULT = {"programs": [], "count": 0, "summary": "No major international sanctions programs identified"}


def hs_description(code):
    """Plain-English commodity name for an HS code, matching the longest known
    prefix (full code, then 4-digit, then 2-digit chapter)."""
    if code is None:
        return None
    s = str(code).strip()
    if not s:
        return None
    for candidate in (s, s[:6], s[:4], s[:2]):
        if candidate in HS_CODE_DESCRIPTIONS:
            label = HS_CODE_DESCRIPTIONS[candidate]
            return f"{label} (HS {s})"
    return f"HS {s}"
