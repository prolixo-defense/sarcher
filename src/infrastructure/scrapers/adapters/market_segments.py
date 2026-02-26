"""
Market segment definitions for scaled discovery.

Each segment includes NAICS codes, search query templates, job search templates,
target decision-maker titles, and keywords for matching/scoring.

Templates use {geo} placeholder for geographic targeting.
"""
from __future__ import annotations

SEGMENTS: dict[str, dict] = {
    "dib": {
        "label": "Defense Industrial Base",
        "naics_codes": ["541512", "541519", "541690", "336411", "336412", "336413", "334511", "334290"],
        "search_templates": [
            "{geo} defense contractor team page",
            "{geo} CMMC cybersecurity consultants staff",
            "{geo} defense technology company about us",
            "{geo} DoD cleared contractor leadership",
            "{geo} ITAR compliance company team",
            "{geo} military technology firm employees",
            "{geo} defense subcontractor staff directory",
            "{geo} aerospace defense company people",
            "{geo} cleared defense facility CAGE team",
            "{geo} defense industrial base small business leadership",
        ],
        "job_search_templates": [
            "{geo} CMMC assessor hiring",
            "{geo} defense cybersecurity engineer jobs",
            "{geo} ITAR compliance officer position",
            "{geo} cleared software developer defense",
            "{geo} DoD program manager opening",
        ],
        "target_titles": [
            "CISO", "VP Cybersecurity", "Director of Security", "Compliance Officer",
            "CMMC Assessor", "Information Security Manager", "Program Manager",
            "CEO", "President", "COO", "VP Engineering", "CTO",
        ],
        "keywords": ["defense", "CMMC", "ITAR", "DoD", "NIST", "cleared", "DFARS", "CUI"],
    },
    "fedramp": {
        "label": "FedRAMP Cloud Providers",
        "naics_codes": ["541512", "541519", "518210"],
        "search_templates": [
            "{geo} FedRAMP authorized cloud provider team",
            "{geo} FedRAMP cloud security company about us",
            "{geo} government cloud solutions staff",
            "{geo} FedRAMP SaaS company leadership",
            "{geo} cloud security federal team page",
            "{geo} FedRAMP consultant company staff",
            "{geo} government cloud platform people",
            "{geo} StateRAMP authorized provider leadership",
            "{geo} IL4 IL5 cloud service provider team",
            "{geo} FedRAMP marketplace company about",
        ],
        "job_search_templates": [
            "{geo} FedRAMP compliance engineer hiring",
            "{geo} government cloud security architect jobs",
            "{geo} FedRAMP authorized assessor position",
        ],
        "target_titles": [
            "CISO", "VP Cloud Security", "Director of Compliance",
            "FedRAMP Program Manager", "Cloud Security Architect",
            "CEO", "CTO", "VP Engineering", "VP Sales",
        ],
        "keywords": ["FedRAMP", "StateRAMP", "cloud", "ATO", "IL4", "IL5", "3PAO", "government cloud"],
    },
    "ai_compliance": {
        "label": "AI Compliance & Governance",
        "naics_codes": ["541512", "541519", "541690", "541715"],
        "search_templates": [
            "{geo} AI governance compliance company team",
            "{geo} responsible AI consulting firm staff",
            "{geo} AI risk management company about us",
            "{geo} AI ethics compliance leadership",
            "{geo} machine learning governance consultants",
            "{geo} AI regulation advisory firm people",
            "{geo} AI audit assessment company team",
            "{geo} trustworthy AI platform staff",
            "{geo} AI policy compliance consulting leadership",
            "{geo} EU AI Act compliance firm about",
        ],
        "job_search_templates": [
            "{geo} AI governance officer hiring",
            "{geo} responsible AI engineer jobs",
            "{geo} AI compliance consultant position",
        ],
        "target_titles": [
            "Chief AI Officer", "VP AI Governance", "Director of AI Ethics",
            "AI Compliance Manager", "Head of Responsible AI",
            "CEO", "CTO", "VP Engineering", "VP Product",
        ],
        "keywords": ["AI governance", "responsible AI", "AI ethics", "EU AI Act", "AI audit", "ML governance"],
    },
    "mssp": {
        "label": "Managed Security Service Providers",
        "naics_codes": ["541512", "541519", "561621"],
        "search_templates": [
            "{geo} managed security service provider team",
            "{geo} MSSP company leadership about us",
            "{geo} managed SOC provider staff",
            "{geo} MDR cybersecurity firm people",
            "{geo} managed detection response company team",
            "{geo} security operations center provider about",
            "{geo} MSSP small business team page",
            "{geo} cybersecurity managed services staff",
            "{geo} SIEM managed provider leadership",
            "{geo} 24x7 security monitoring company people",
        ],
        "job_search_templates": [
            "{geo} MSSP SOC analyst hiring",
            "{geo} managed security engineer jobs",
            "{geo} MDR threat hunter position",
        ],
        "target_titles": [
            "CEO", "CTO", "CISO", "VP Sales", "Director of Operations",
            "SOC Manager", "VP Managed Services", "Director of MDR",
        ],
        "keywords": ["MSSP", "MDR", "SOC", "managed security", "SIEM", "threat detection"],
    },
    "grc": {
        "label": "Governance, Risk & Compliance",
        "naics_codes": ["541512", "541519", "541611", "541690"],
        "search_templates": [
            "{geo} GRC consulting firm team page",
            "{geo} governance risk compliance company staff",
            "{geo} cybersecurity compliance consulting about us",
            "{geo} NIST compliance assessor firm people",
            "{geo} SOC 2 audit firm leadership",
            "{geo} ISO 27001 certification assessor team",
            "{geo} risk management consulting company about",
            "{geo} compliance automation platform team",
            "{geo} third party risk management firm staff",
            "{geo} security assessment company leadership",
        ],
        "job_search_templates": [
            "{geo} GRC consultant hiring",
            "{geo} compliance analyst cybersecurity jobs",
            "{geo} risk management auditor position",
        ],
        "target_titles": [
            "CEO", "Managing Partner", "Principal Consultant",
            "Director of GRC", "VP Compliance", "CISO",
            "Risk Manager", "Compliance Director",
        ],
        "keywords": ["GRC", "governance", "compliance", "risk management", "SOC 2", "ISO 27001", "NIST"],
    },
    "cleared_it": {
        "label": "Cleared IT Staffing & Services",
        "naics_codes": ["541512", "541519", "561311", "561312"],
        "search_templates": [
            "{geo} cleared IT staffing company team",
            "{geo} security clearance IT firm about us",
            "{geo} cleared technology consulting staff",
            "{geo} DoD IT services company leadership",
            "{geo} cleared software development firm people",
            "{geo} TS/SCI cleared staffing firm team",
            "{geo} federal IT contractor small business about",
            "{geo} cleared DevSecOps company staff",
            "{geo} government IT modernization firm team",
            "{geo} classified network IT provider leadership",
        ],
        "job_search_templates": [
            "{geo} cleared software engineer hiring",
            "{geo} TS/SCI developer position",
            "{geo} cleared IT project manager jobs",
        ],
        "target_titles": [
            "CEO", "President", "VP Business Development",
            "Director of Recruiting", "COO", "CTO",
            "Program Manager", "VP Federal Sales",
        ],
        "keywords": ["cleared", "TS/SCI", "clearance", "DoD", "federal IT", "DevSecOps"],
    },
    "supply_chain": {
        "label": "Supply Chain Security",
        "naics_codes": ["541512", "541519", "541690", "541614"],
        "search_templates": [
            "{geo} supply chain security company team",
            "{geo} SCRM risk management firm staff",
            "{geo} software supply chain security about us",
            "{geo} SBOM management platform leadership",
            "{geo} supply chain cyber risk company people",
            "{geo} vendor risk management firm team",
            "{geo} third party cyber risk company about",
            "{geo} software composition analysis firm staff",
            "{geo} supply chain integrity company leadership",
            "{geo} C-SCRM consulting firm team page",
        ],
        "job_search_templates": [
            "{geo} supply chain security analyst hiring",
            "{geo} SBOM engineer jobs",
            "{geo} vendor risk assessor position",
        ],
        "target_titles": [
            "CEO", "CTO", "VP Product", "Director of Supply Chain Security",
            "CISO", "VP Engineering", "Chief Risk Officer",
        ],
        "keywords": ["supply chain", "SCRM", "SBOM", "vendor risk", "software supply chain", "C-SCRM"],
    },
    "zero_trust": {
        "label": "Zero Trust Architecture",
        "naics_codes": ["541512", "541519"],
        "search_templates": [
            "{geo} zero trust security company team",
            "{geo} ZTNA platform provider about us",
            "{geo} zero trust architecture consulting staff",
            "{geo} identity access management firm people",
            "{geo} zero trust network company leadership",
            "{geo} microsegmentation security firm team",
            "{geo} SASE provider company about",
            "{geo} zero trust federal contractor staff",
            "{geo} identity security platform team page",
            "{geo} privileged access management company leadership",
        ],
        "job_search_templates": [
            "{geo} zero trust architect hiring",
            "{geo} ZTNA security engineer jobs",
            "{geo} identity security consultant position",
        ],
        "target_titles": [
            "CEO", "CTO", "VP Product", "VP Sales",
            "Director of Zero Trust", "Chief Security Architect",
            "VP Engineering", "CISO",
        ],
        "keywords": ["zero trust", "ZTNA", "SASE", "microsegmentation", "IAM", "PAM", "identity"],
    },
    "cyber_training": {
        "label": "Cybersecurity Training & Workforce",
        "naics_codes": ["541512", "541519", "611430", "611420"],
        "search_templates": [
            "{geo} cybersecurity training company team",
            "{geo} security awareness training firm about us",
            "{geo} cyber workforce development staff",
            "{geo} cybersecurity certification training leadership",
            "{geo} security education company people",
            "{geo} cyber range training provider team",
            "{geo} phishing simulation company about",
            "{geo} cybersecurity bootcamp firm staff",
            "{geo} security certification training team page",
            "{geo} cyber skills assessment company leadership",
        ],
        "job_search_templates": [
            "{geo} cybersecurity instructor hiring",
            "{geo} security training content developer jobs",
            "{geo} cyber workforce development position",
        ],
        "target_titles": [
            "CEO", "President", "VP Sales", "Director of Training",
            "Chief Learning Officer", "VP Business Development",
            "Director of Curriculum", "VP Partnerships",
        ],
        "keywords": ["cyber training", "security awareness", "cyber range", "phishing simulation", "workforce"],
    },
}


def get_segment_config(key: str) -> dict | None:
    """Return a segment configuration by key, or None if not found."""
    return SEGMENTS.get(key)


def get_all_segment_keys() -> list[str]:
    """Return all valid segment keys."""
    return list(SEGMENTS.keys())


def get_naics_codes_for_segments(segment_keys: list[str]) -> list[str]:
    """Return deduplicated NAICS codes for the given segment keys."""
    codes: list[str] = []
    seen: set[str] = set()
    for key in segment_keys:
        seg = SEGMENTS.get(key)
        if seg:
            for code in seg["naics_codes"]:
                if code not in seen:
                    seen.add(code)
                    codes.append(code)
    return codes


def get_search_queries_for_segments(
    segment_keys: list[str],
    geography: str = "",
    include_job_queries: bool = True,
) -> list[str]:
    """Generate search queries for the given segments with geography substitution."""
    geo = geography.strip() if geography else ""
    queries: list[str] = []

    for key in segment_keys:
        seg = SEGMENTS.get(key)
        if not seg:
            continue
        for template in seg["search_templates"]:
            q = template.replace("{geo}", geo).strip()
            if q not in queries:
                queries.append(q)
        if include_job_queries:
            for template in seg["job_search_templates"]:
                q = template.replace("{geo}", geo).strip()
                if q not in queries:
                    queries.append(q)

    return queries


def get_target_titles_for_segments(segment_keys: list[str]) -> list[str]:
    """Return deduplicated target titles for the given segments."""
    titles: list[str] = []
    seen: set[str] = set()
    for key in segment_keys:
        seg = SEGMENTS.get(key)
        if seg:
            for t in seg["target_titles"]:
                t_lower = t.lower()
                if t_lower not in seen:
                    seen.add(t_lower)
                    titles.append(t)
    return titles
