"""
Shared name-normalization helper for matching player names across
providers that don't share a common player ID system (e.g. MLB Stats API
IDs vs. SportsDataIO PlayerIDs vs. ESPN athlete IDs).
"""
import re
import unicodedata


def normalize_name(name: str) -> str:
    """Strips accents, periods, and common suffixes, lowercases, and
    collapses whitespace, so e.g. 'J.T. Realmuto Jr.' and 'JT Realmuto'
    both reduce to the same comparable key."""
    if not name:
        return ""
    nfkd = unicodedata.normalize("NFKD", name)
    no_accents = "".join(c for c in nfkd if not unicodedata.combining(c))
    cleaned = re.sub(r"\b(jr|sr|ii|iii|iv)\b\.?", "", no_accents.lower())
    cleaned = re.sub(r"[.\-']", "", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned
