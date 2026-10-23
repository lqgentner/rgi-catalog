"""``display_name``: the glacier name drawn on the map (design §5.4).

The rules are deterministic and run in this order:

1. Underscores become spaces, runs of whitespace collapse to one space, and
   a trailing comma is dropped.
2. Inventory codes (GLIMS and WGI style: two capital letters, a digit, then
   five or more letters or digits, e.g. ``CN5Y673P0037``, with an optional
   range or query suffix such as ``-10``, ``+05`` or ``?``) are removed as
   whole tokens at either end of the name.
3. No name (null) when nothing is left; for ``S/N``, ``NN`` and ``Unnamed``
   with an optional number; for names that are only digits; for codes of one
   to three capitals; and for names that are only a bracket, such as
   ``(Severny Island)``.
4. A hyphen before a compass point or a Roman numeral becomes a space, as in
   the Swiss Glacier Inventory: ``Tälligletscher-E`` → ``Tälligletscher E``.
5. A name with no lowercase letter is re-cased: each word starts with a
   capital and continues in lowercase. Roman numerals and compass points stay
   in capitals, and so does a Swiss canton code that ends the name
   (``FIESCHERGLETSCHER VS`` → ``Fieschergletscher VS``). Particles (``de``,
   ``du``, ``del``, ``la``, ``d'``, …) are lowercase unless they start the name.
   Words are never reordered. Mixed-case names are kept as written.

``glac_name`` keeps RGI's value. ``rgi_id`` is the key, never the name.
"""

from __future__ import annotations

import re

import pandas as pd

RULES: tuple[str, ...] = (
    "empty",
    "underscores",
    "trailing-comma",
    "inventory-code-stripped",
    "code-only",
    "no-name-marker",
    "numeric-only",
    "short-code",
    "bracket-only",
    "suffix-hyphen",
    "recased",
    "unchanged",
)

_CODE = re.compile(r"[A-Z]{2}\d[A-Za-z0-9]{5,}(?:[-+][A-Za-z0-9]+)*\?*")
_NO_NAME = re.compile(r"s\s*/\s*n\.?|nn|unnamed(?: \d+)?", re.IGNORECASE)
_DIGITS = re.compile(r"\d+")
_SHORT_CODE = re.compile(r"[A-Z]{1,3}")
_BRACKET_ONLY = re.compile(r"\(.*\)")
_ROMAN = r"(?:X{0,3}(?:IX|IV|V?I{1,3}|V)|X{1,3})"
_COMPASS = r"(?:[NS][EW]?|[EW])"
_SUFFIX_HYPHEN = re.compile(rf"-(?=(?:{_COMPASS}|{_ROMAN})(?:-|\s|$))")
_KEEP_UPPER = re.compile(rf"{_COMPASS}|{_ROMAN}", re.IGNORECASE)
_PARTICLES = frozenset(
    {"da", "de", "del", "della", "der", "des", "di", "du", "la", "las", "le", "les", "los", "von"},
)
# The Swiss Glacier Inventory ends some names with the canton code.
_CANTONS = frozenset(
    {
        "AG", "AI", "AR", "BE", "BL", "BS", "FR", "GE", "GL", "GR", "JU", "LU", "NE",
        "NW", "OW", "SG", "SH", "SO", "SZ", "TG", "TI", "UR", "VD", "VS", "ZG", "ZH",
    },
)  # fmt: skip
_ELISION = re.compile(r"([dl])'(.*)", re.IGNORECASE)
# A word starts at the beginning, or after a space, hyphen, slash, bracket or
# full stop. An apostrophe does not start one: "D'ARGENTIERE" → "D'argentiere".
_WORD_START = re.compile(r"(^|[\s\-/(.])(\w)")


def _recase_word(word: str, *, first: bool, last: bool) -> str:
    if _KEEP_UPPER.fullmatch(word) or (last and not first and word in _CANTONS):
        return word.upper()
    if not first and word.lower() in _PARTICLES:
        return word.lower()
    elision = _ELISION.fullmatch(word)
    if not first and elision:
        rest = elision.group(2)
        return f"{elision.group(1).lower()}'{rest[:1].upper()}{rest[1:].lower()}"
    return _WORD_START.sub(lambda m: m.group(1) + m.group(2).upper(), word.lower())


def _recase(name: str) -> str:
    words = name.split(" ")
    return " ".join(
        _recase_word(w, first=i == 0, last=i == len(words) - 1) for i, w in enumerate(words)
    )


def _normalise(raw: str) -> tuple[str, list[str]]:
    """Apply rules 1 and 2: spacing, the trailing comma, and inventory codes at the ends."""
    fired: list[str] = []
    name = raw
    if "_" in name:
        name = name.replace("_", " ")
        fired.append("underscores")
    name = " ".join(name.split())
    if name.endswith(","):
        name = name.rstrip(",").rstrip()
        fired.append("trailing-comma")
    tokens = name.split(" ")
    while tokens and _CODE.fullmatch(tokens[0]):
        tokens.pop(0)
        fired.append("inventory-code-stripped")
    while tokens and _CODE.fullmatch(tokens[-1]):
        tokens.pop()
        fired.append("inventory-code-stripped")
    return " ".join(tokens), list(dict.fromkeys(fired))


def apply_rules(raw: str | None) -> tuple[str | None, list[str]]:
    """Derive the display name and name the rules that fired.

    Parameters
    ----------
    raw
        ``glac_name`` after the encoding repair.

    Returns
    -------
    tuple[str | None, list[str]]
        The display name, or ``None``, and the rules from :data:`RULES` that
        applied (``["unchanged"]`` when none did).
    """
    if raw is None or not raw.strip():
        return None, ["empty"]
    name, fired = _normalise(raw)
    if not name:
        return None, [*(r for r in fired if r != "inventory-code-stripped"), "code-only"]
    for rule, pattern in (
        ("no-name-marker", _NO_NAME),
        ("numeric-only", _DIGITS),
        ("short-code", _SHORT_CODE),
        ("bracket-only", _BRACKET_ONLY),
    ):
        if pattern.fullmatch(name):
            return None, [*fired, rule]
    if _SUFFIX_HYPHEN.search(name):
        name = _SUFFIX_HYPHEN.sub(" ", name)
        fired.append("suffix-hyphen")
    if not any(c.islower() for c in name) and any(c.isupper() for c in name):
        name = _recase(name)
        fired.append("recased")
    return name, fired or ["unchanged"]


def display_name(raw: str | None) -> str | None:
    """Return the name drawn on the map for a ``glac_name``.

    Parameters
    ----------
    raw
        ``glac_name`` after the encoding repair.

    Returns
    -------
    str | None
        The cleaned name, or ``None`` when there is no usable name.
    """
    return apply_rules(raw)[0]


def rule_report(
    names: pd.Series,
    sample: int = 40,
    seed: int = 0,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Count how often each rule fires, and draw changed names for review.

    Parameters
    ----------
    names
        ``glac_name`` values after the encoding repair.
    sample
        How many changed names to draw.
    seed
        The random seed of the draw.

    Returns
    -------
    tuple[pd.DataFrame, pd.DataFrame]
        Columns ``rule`` and ``count`` over every name (``empty`` counts the
        missing ones), and a sample with columns ``glac_name``, ``display_name``
        and ``rules``.
    """
    raws = [v if isinstance(v, str) else None for v in names]
    results = [apply_rules(v) for v in raws]
    table = pd.DataFrame(
        {
            "glac_name": raws,
            "display_name": [r[0] for r in results],
            "rules": [", ".join(r[1]) for r in results],
        },
    )
    fired = pd.Series([rule for _, rules in results for rule in rules], dtype=object)
    counts = (
        fired.value_counts()
        .reindex(list(RULES), fill_value=0)
        .rename_axis("rule")
        .reset_index(name="count")
    )
    changed = table[table["glac_name"].notna() & (table["glac_name"] != table["display_name"])]
    drawn = changed.sample(n=min(sample, len(changed)), random_state=seed)
    return counts, drawn.reset_index(drop=True)
