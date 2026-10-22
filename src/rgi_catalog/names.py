"""``display_name``: the glacier name drawn on the map (design §5.4).

The rules are deterministic and run in this order:

1. Underscores become spaces, and runs of whitespace collapse to one space.
2. Inventory codes (GLIMS and WGI style: two capital letters, a digit, then
   five or more letters or digits, e.g. ``CN5Y673P0037``) are removed as
   whole tokens at either end of the name.
3. No name (null) when nothing is left, for ``S/N`` and its variants, for
   names that are only digits, and for codes of one to three capitals.
4. A name with no lowercase letter is re-cased: each word starts with a
   capital and continues in lowercase. Mixed-case names are kept as written.

``glac_name`` keeps RGI's value. ``rgi_id`` is the key, never the name.
"""

from __future__ import annotations

import re

import pandas as pd

RULES: tuple[str, ...] = (
    "empty",
    "underscores",
    "inventory-code-stripped",
    "code-only",
    "no-name-marker",
    "numeric-only",
    "short-code",
    "recased",
    "unchanged",
)

_CODE = re.compile(r"[A-Z]{2}\d[A-Za-z0-9]{5,}")
_NO_NAME = re.compile(r"s\s*/\s*n\.?", re.IGNORECASE)
_DIGITS = re.compile(r"\d+")
_SHORT_CODE = re.compile(r"[A-Z]{1,3}")
# A word starts at the beginning, or after a space, hyphen, slash, bracket or
# full stop. An apostrophe does not start one: "D'ARGENTIERE" → "D'argentiere".
_WORD_START = re.compile(r"(^|[\s\-/(.])(\w)")


def _recase(name: str) -> str:
    return _WORD_START.sub(lambda m: m.group(1) + m.group(2).upper(), name.lower())


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
    fired: list[str] = []
    name = raw
    if "_" in name:
        name = name.replace("_", " ")
        fired.append("underscores")
    name = " ".join(name.split())
    tokens = name.split(" ")
    while tokens and _CODE.fullmatch(tokens[0]):
        tokens.pop(0)
        fired.append("inventory-code-stripped")
    while tokens and _CODE.fullmatch(tokens[-1]):
        tokens.pop()
        fired.append("inventory-code-stripped")
    fired = list(dict.fromkeys(fired))
    name = " ".join(tokens)
    for rule, pattern in (
        ("no-name-marker", _NO_NAME),
        ("numeric-only", _DIGITS),
        ("short-code", _SHORT_CODE),
    ):
        if pattern.fullmatch(name):
            return None, [*fired, rule]
    if not name:
        return None, ["code-only"]
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
