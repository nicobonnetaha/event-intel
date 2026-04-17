from typing import Optional

# Tier 1: financial institutions — direct potential clients for The Aha Company
TIER1_KEYWORDS = [
    "bank", "banking", "banque", "banquier",
    "asset management", "asset manager", "gestionnaire d'actifs",
    "family office", "family-office", "wealth management", "wealth manager",
    "private banking", "private bank",
    "hedge fund", "investment fund", "fonds d'investissement",
    "private equity", "venture capital",
    "custodian", "custody", "dépositaire",
    "insurance", "assurance", "assureur",
    "pension fund", "fonds de pension",
    "sovereign wealth", "sovereign fund",
    "financial institution", "institution financière",
    "securities", "capital markets", "marchés financiers",
    "clearing", "settlement", "règlement-livraison",
    "treasury", "trésorerie", "trésorier",
    "portfolio manager", "gestionnaire de portefeuille",
    "trading desk", "salle des marchés",
    "central bank", "banque centrale",
    "investment bank", "banque d'investissement",
    "retail bank", "banque de détail",
    "brokerage", "broker", "courtier",
    "remittance", "money transfer",
]

# Tier 2: blockchain/crypto ecosystem + fintech — good for partnerships and ecosystem
TIER2_KEYWORDS = [
    "blockchain", "crypto", "cryptocurrency", "web3",
    "defi", "decentralized finance",
    "stablecoin", "stable coin", "cbdc",
    "tokenization", "tokenisation", "tokenized", "tokenisé",
    "digital assets", "digital currency", "actifs numériques",
    "stellar", "xrpl", "ripple", "ethereum", "hyperledger", "canton",
    "smart contract", "solidity",
    "nft", "dao",
    "fintech", "regtech", "paytech", "wealthtech",
    "compliance blockchain", "mica", "dora", "aml", "kyc",
    "payments", "payment", "paiements",
    "exchange", "market maker", "liquidity",
    "wallet", "custody solution",
    "big four", "deloitte", "pwc", "kpmg", "ey", "ernst",
    "consulting blockchain", "conseil blockchain",
    "protocol", "infrastructure web3",
]

# Seniority boost
SENIORITY_TERMS = [
    "ceo", "cfo", "cto", "coo", "ciso",
    "founder", "co-founder", "cofoundeur", "fondateur",
    "managing director", "directeur général", "directeur",
    "managing partner", "general partner",
    "head of", "responsable", "directeur de",
    "vice president", "vp ", " vp",
    "president", "chairman",
    "partner", "associé",
    "principal",
    "chief ",
]


def score_participant(
    name: str,
    company: Optional[str],
    job_title: Optional[str],
    bio: Optional[str],
    company_description: Optional[str],
) -> tuple[float, str, str]:
    """Returns (score 0-100, label, reason)."""

    text = " ".join(
        filter(None, [
            (company or "").lower(),
            (job_title or "").lower(),
            (bio or "").lower(),
            (company_description or "").lower(),
        ])
    )

    tier1_hits = [kw for kw in TIER1_KEYWORDS if kw in text]
    tier2_hits = [kw for kw in TIER2_KEYWORDS if kw in text]

    score = 0
    reasons = []

    if tier1_hits:
        score = min(60 + len(tier1_hits) * 8, 95)
        reasons.append(f"Institution financière ({', '.join(tier1_hits[:3])})")
    elif tier2_hits:
        score = min(30 + len(tier2_hits) * 7, 72)
        reasons.append(f"Ecosystème blockchain/fintech ({', '.join(tier2_hits[:3])})")
    else:
        score = 10

    title_lower = (job_title or "").lower()
    if any(term in title_lower for term in SENIORITY_TERMS):
        score = min(score + 12, 100)
        reasons.append("Profil senior")

    score = round(min(score, 100))

    if score >= 70:
        label = "Haute priorité"
    elif score >= 40:
        label = "Priorité moyenne"
    else:
        label = "Faible priorité"

    reason = " · ".join(reasons) if reasons else "Aucun signal identifié"

    return float(score), label, reason
