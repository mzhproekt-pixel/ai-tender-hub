"""Text normalisation for entity matching.

`normalize_name` produces a key suitable for trigram comparison:
- Cyrillic transliterated to Latin (so 'Газпром' / 'Gazprom' collide)
- Unicode NFKD fold to ASCII
- Common legal-form suffixes stripped (Inc, Ltd, GmbH, ООО, OAO, ...)
- Lowercase, collapse whitespace, drop punctuation

Pure functions, no I/O — easy to test.
"""
from __future__ import annotations

import re
import unicodedata

# Minimal Cyrillic → Latin map. Covers RU/UA/KZ/BY company names well enough
# for matching (it's not a transliteration standard, it's a join key).
_CYR_TO_LAT = {
    "а": "a", "б": "b", "в": "v", "г": "g", "ғ": "g", "д": "d", "е": "e",
    "ё": "e", "ж": "zh", "з": "z", "и": "i", "й": "i", "к": "k", "қ": "k",
    "л": "l", "м": "m", "н": "n", "ң": "n", "о": "o", "ө": "o", "п": "p",
    "р": "r", "с": "s", "т": "t", "у": "u", "ү": "u", "ұ": "u", "ф": "f",
    "х": "h", "һ": "h", "ц": "c", "ч": "ch", "ш": "sh", "щ": "sch",
    "ъ": "", "ы": "y", "і": "i", "ї": "i", "є": "e", "ь": "", "э": "e",
    "ю": "yu", "я": "ya", "ә": "a",
}

# Legal-form suffixes (in Latinised form, after transliteration).
_LEGAL_FORMS = {
    "inc", "incorporated", "corp", "corporation", "co", "company",
    "ltd", "limited", "llc", "llp", "lp", "plc", "pllc",
    "gmbh", "ag", "kg", "ohg", "se",
    "sa", "sas", "sarl", "spa", "srl", "bv", "nv", "oy", "ab", "as",
    "ooo", "oao", "zao", "pao", "ip", "ao", "tov", "tova",
    "tm",
}


def _transliterate(text: str) -> str:
    out: list[str] = []
    for ch in text:
        lower = ch.lower()
        if lower in _CYR_TO_LAT:
            mapped = _CYR_TO_LAT[lower]
            out.append(mapped.upper() if ch.isupper() else mapped)
        else:
            out.append(ch)
    return "".join(out)


def normalize_name(name: str | None) -> str:
    """Produce a stable matching key from a free-form company name."""
    if not name:
        return ""
    s = _transliterate(name)
    # NFKD: '№' → 'No', ligatures decompose, accents drop after ascii encode
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")
    s = s.lower()
    s = re.sub(r"[^a-z0-9\s]", " ", s)
    tokens = [t for t in s.split() if t and t not in _LEGAL_FORMS]
    return " ".join(tokens)


def normalize_country(value: str | None) -> str | None:
    """Return ISO 3166-1 alpha-2 if input looks like one, else None."""
    if not value:
        return None
    v = value.strip().upper()
    return v if len(v) == 2 and v.isalpha() else None
