"""``display_name``: the glacier name drawn on the map (design §5.4).

An override in ``metadata/name_overrides.yaml`` replaces the rules for one
``glac_name``. Otherwise the rules are deterministic and run in this order:

1. Underscores become spaces, and runs of whitespace collapse to one space.
   A trailing comma is dropped, and so is a dash that stands for an empty
   second name (``Austfonna, -``, ``Cima Vertana Sud Ovest / -``).
2. Inventory codes (GLIMS and WGI style: two capital letters, a digit, then
   five or more letters or digits, e.g. ``CN5Y673P0037``, with an optional
   range or query suffix such as ``-10``, ``+05`` or ``?``) are removed as
   whole tokens at either end of the name.
3. No name (null) when nothing is left. No name also for ``S/N``, ``NN``,
   ``Unnamed`` with an optional number, ``None``, ``<Null>``, ``No Name``,
   ``No Name Glacier`` and ``Namenlos`` with an optional Roman numeral. No
   name for names that are only digits, for codes of one to three capitals,
   and for names that are only a bracket, such as ``(Severny Island)``.
4. A Cyrillic letter a, ie or ve (U+0430, U+0435, U+0432) after digits
   becomes the Latin ``a``, ``e`` or ``v``. Most names of this form use the
   Latin letter.
5. A backtick or an acute accent used as an apostrophe becomes ``'``.
6. A bracket has a space before it and no space inside it. A slash with a
   space on one side only gets a space on both sides.
7. A hyphen before a compass point, a Roman numeral or ``Mitte`` becomes a
   space, as in the Swiss Glacier Inventory: ``Tälligletscher-E`` →
   ``Tälligletscher E``. After an apostrophe the hyphen is dropped:
   ``DE L'-N`` → ``de l'N``.
8. A name with no lowercase letter is re-cased: each word starts with a
   capital and continues in lowercase. Roman numerals and compass points stay
   in capitals, and so does a Swiss canton code that ends the name
   (``FIESCHERGLETSCHER VS`` → ``Fieschergletscher VS``). A word that holds a
   digit keeps its case (``HPS34``). Particles (``de``, ``du``, ``del``,
   ``dal``, ``la``, ``d'``, …) are lowercase unless they start the name, and
   the letter after ``O'`` is a capital. In a
   mixed-case name only the words of four or more capitals are re-cased
   (``TUNGELGLETSCHER09n`` → ``Tungelgletscher09n``). A word that mixes cases
   is kept as written (``MIIGAiK``).
9. A name that ends with a glacier word and a particle starts with them,
   as in the Swiss Glacier Inventory's index order: ``CHEILON GLACIER DE``
   → ``Glacier de Cheilon``. A compass point or a Roman numeral after the
   particle stays at the end: ``Glacier du Petit Combin III``. The glacier
   words are ``Glacier``, ``Haut Glacier``, ``Ghiacciaio``, ``Vadret``,
   ``Vadrec``, ``Vadrecc``, ``Vadrettin``, ``Vedreit``, ``Glatscher``,
   ``Glatschiu`` and the abbreviations ``Gl.`` and ``Gh.``. ``Gh.`` becomes
   ``Ghiacciaio``. ``Gl.`` becomes ``Glacier`` before a French particle and
   ``Glatscher`` before a Romansh particle (``da``, ``dal``, ``dil``, …).
   Before another particle it stays. ``Gl. Inf.`` becomes
   ``Glacier Inferieur``.
10. In regions 17 and 19, ``Gl.`` that starts a name becomes ``Glaciar``.
    These Spanish names put the glacier word first. Outside region 11, ``Gl.``
    or ``Gl`` that ends a name, or comes before a one-letter suffix, becomes
    ``Glacier``. These English names put the glacier word last.
11. In region 11, a name that starts with ``d'``, ``de``, ``du`` or ``des``
    gets ``Glacier`` in front. The French Glacier Inventory leaves the word
    out: ``d'Ambin`` → ``Glacier d'Ambin``.
12. A name that starts with a lowercase letter gets a capital.

``glac_name`` keeps RGI's value. ``rgi_id`` is the key, never the name.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

import pandas as pd
import yaml

from rgi_catalog.paths import METADATA

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path

OVERRIDES = METADATA / "name_overrides.yaml"

RULES: tuple[str, ...] = (
    "empty",
    "override",
    "underscores",
    "trailing-comma",
    "empty-second-name",
    "inventory-code-stripped",
    "code-only",
    "no-name-marker",
    "numeric-only",
    "short-code",
    "bracket-only",
    "cyrillic-suffix",
    "apostrophe",
    "spacing",
    "suffix-hyphen",
    "recased",
    "glacier-word-first",
    "glaciar-expanded",
    "glacier-expanded",
    "french-glacier",
    "initial-capital",
    "unchanged",
)

_CODE = re.compile(r"[A-Z]{2}\d[A-Za-z0-9]{5,}(?:[-+][A-Za-z0-9]+)*\?*")
_EMPTY_SECOND_NAME = re.compile(r"\s*[,/]\s*-+$")
_NO_NAME = re.compile(
    r"s\s*/\s*n\.?|nn|unnamed(?: \d+)?|none|<null>|no name(?: glacier)?"
    r"|namenlos(?:[ -][ivx]+)?",
    re.IGNORECASE,
)
_DIGITS = re.compile(r"\d+")
_SHORT_CODE = re.compile(r"[A-Z]{1,3}")
_BRACKET_ONLY = re.compile(r"\(.*\)")
_CYRILLIC_SUFFIX = re.compile("(?<=\\d)[\u0430\u0435\u0432](?![^\\W\\d_])")
_CYRILLIC_TO_LATIN = str.maketrans("\u0430\u0435\u0432", "aev")
# A backtick or an acute accent (U+00B4) used as an apostrophe.
_APOSTROPHE_LOOKALIKES = re.compile("[`\u00b4]")
_SPACING = (
    (re.compile(r"(?<=\w)\("), " ("),
    (re.compile(r"\(\s+"), "("),
    (re.compile(r"\s+\)"), ")"),
    (re.compile(r"(?<=\S) /(?=\S)|(?<=\S)/ (?=\S)"), " / "),
)
_ROMAN = r"(?:X{0,3}(?:IX|IV|V?I{1,3}|V)|X{1,3})"
_COMPASS = r"(?:[NS][EW]?|[EW])"
_SUFFIX_HYPHEN = re.compile(rf"(')?-(?=(?:{_COMPASS}|{_ROMAN}|Mitte|MITTE)(?:-|\s|$))")
# A word of four or more letters, all capitals, bounded by non-letters.
_CAPITAL_WORD = re.compile(r"(?<![^\W\d_])[^\W\d_]{4,}(?![^\W\d_])")
_KEEP_UPPER = re.compile(rf"{_COMPASS}|{_ROMAN}", re.IGNORECASE)
_PARTICLES = frozenset(
    {
        "da", "dal", "dalla", "dallas", "de", "dei", "del", "della", "der", "des",
        "di", "dil", "du", "la", "las", "le", "les", "los", "von",
    },
)  # fmt: skip
# The Swiss Glacier Inventory ends some names with the canton code.
_CANTONS = frozenset(
    {
        "AG", "AI", "AR", "BE", "BL", "BS", "FR", "GE", "GL", "GR", "JU", "LU", "NE",
        "NW", "OW", "SG", "SH", "SO", "SZ", "TG", "TI", "UR", "VD", "VS", "ZG", "ZH",
    },
)  # fmt: skip
_ELISION = re.compile(r"([dl])'(.*)", re.IGNORECASE)
_O_PREFIX = re.compile(r"(O)'(.+)", re.IGNORECASE)
# A word starts at the beginning, or after a space, hyphen, slash, bracket or
# full stop. An apostrophe does not start one: "D'ARGENTIERE" → "D'argentiere".
_WORD_START = re.compile(r"(^|[\s\-/(.])(\w)")
_PART_SEPARATOR = re.compile(r"([-/])")
_FRENCH_REGION = "11"
# A glacier word, with an optional adjective after it, then the particle.
_GLACIER_WORD = (
    r"(?:Haut )?(?:Glacier|Ghiacciaio|Vadret|Vadrec|Vadrecc|Vadrettin|Vedreit|Glatscher|Glatschiu"
    r"|Gl\.|Gh\.)(?: (?:Superieur|Inf\.))?"
)
_TRAILING_PARTICLE = (
    r"(?:de la|de l'|da la|da las|da l'|de|du|des|d'|da|dal|dalla|dallas|dei|del|di|dil)"
)
# A compass point or a Roman numeral may follow the particle. After an
# apostrophe it follows without a space: "Glacier de l'S".
_GLACIER_WORD_LAST = re.compile(
    rf"(?P<place>.+?),? (?P<word>{_GLACIER_WORD}) (?P<particle>{_TRAILING_PARTICLE})"
    rf"(?:(?:(?<=')| )(?P<suffix>{_COMPASS}|{_ROMAN}))?"
)
# The language of the particle gives the word that Gl. abbreviates.
_GL_BY_PARTICLE = {
    **dict.fromkeys(("de", "du", "des", "d'", "de la", "de l'"), "Glacier"),
    **dict.fromkeys(
        ("da", "dal", "dalla", "dallas", "da la", "da las", "da l'", "dil"), "Glatscher"
    ),
}
# The Spanish names of regions 17 and 19 abbreviate Glaciar.
_SPANISH_REGIONS = frozenset({"17", "19"})
_GLACIAR_ABBREVIATION = re.compile(r"G[Ll]\. ?")
# The English names abbreviate Glacier at the end, before an optional
# one-letter suffix: "Diamond Gl B". Region 11 puts the glacier word last in
# its index order instead.
_GLACIER_ABBREVIATION_LAST = re.compile(r" Gl\.?(?= [A-Z]$|$)")
_FRENCH_PARTICLE_START = re.compile(r"(?:d'|de |du |des )")


def _recase_word(word: str, *, first: bool, last: bool) -> str:
    if any(c.isdigit() for c in word):
        parts = _PART_SEPARATOR.split(word)
        return "".join(
            p
            if any(c.isdigit() for c in p) or _PART_SEPARATOR.fullmatch(p) or not p
            else _recase_word(p, first=first and i == 0, last=False)
            for i, p in enumerate(parts)
        )
    if _KEEP_UPPER.fullmatch(word) or (last and not first and word in _CANTONS):
        return word.upper()
    if not first and word.lower() in _PARTICLES:
        return word.lower()
    elision = _ELISION.fullmatch(word)
    if not first and elision:
        rest = elision.group(2)
        return f"{elision.group(1).lower()}'{rest[:1].upper()}{rest[1:].lower()}"
    o_prefix = _O_PREFIX.fullmatch(word)
    if o_prefix:
        rest = o_prefix.group(2)
        return f"O'{rest[:1].upper()}{rest[1:].lower()}"
    return _WORD_START.sub(lambda m: m.group(1) + m.group(2).upper(), word.lower())


def _recase(name: str) -> str:
    words = name.split(" ")
    return " ".join(
        _recase_word(w, first=i == 0, last=i == len(words) - 1) for i, w in enumerate(words)
    )


def _normalise(raw: str) -> tuple[str, list[str]]:
    """Apply rules 1 and 2: spacing, trailing separators, and inventory codes at the ends."""
    fired: list[str] = []
    name = raw
    if "_" in name:
        name = name.replace("_", " ")
        fired.append("underscores")
    name = " ".join(name.split())
    if name.endswith(","):
        name = name.rstrip(",").rstrip()
        fired.append("trailing-comma")
    if _EMPTY_SECOND_NAME.search(name):
        name = _EMPTY_SECOND_NAME.sub("", name)
        fired.append("empty-second-name")
    tokens = name.split(" ")
    while tokens and _CODE.fullmatch(tokens[0]):
        tokens.pop(0)
        fired.append("inventory-code-stripped")
    while tokens and _CODE.fullmatch(tokens[-1]):
        tokens.pop()
        fired.append("inventory-code-stripped")
    return " ".join(tokens), list(dict.fromkeys(fired))


def _substitute(name: str) -> tuple[str, list[str]]:
    """Apply rules 4 to 7: Cyrillic suffixes, apostrophes, spacing and suffix hyphens."""
    fired: list[str] = []
    if _CYRILLIC_SUFFIX.search(name):
        name = _CYRILLIC_SUFFIX.sub(lambda m: m.group().translate(_CYRILLIC_TO_LATIN), name)
        fired.append("cyrillic-suffix")
    if _APOSTROPHE_LOOKALIKES.search(name):
        name = _APOSTROPHE_LOOKALIKES.sub("'", name)
        fired.append("apostrophe")
    spaced = name
    for pattern, replacement in _SPACING:
        spaced = pattern.sub(replacement, spaced)
    if spaced != name:
        name = spaced
        fired.append("spacing")
    if _SUFFIX_HYPHEN.search(name):
        name = _SUFFIX_HYPHEN.sub(lambda m: "'" if m.group(1) else " ", name)
        name = " ".join(name.split())
        fired.append("suffix-hyphen")
    return name, fired


def _recase_capitals(name: str) -> str | None:
    """Apply rule 8, or return ``None`` when no word needs re-casing."""
    if not any(c.islower() for c in name) and any(c.isupper() for c in name):
        return _recase(name)
    if any(m.group().isupper() for m in _CAPITAL_WORD.finditer(name)):
        return _CAPITAL_WORD.sub(
            lambda m: (
                _recase_word(m.group(), first=m.start() == 0, last=False)
                if m.group().isupper()
                else m.group()
            ),
            name,
        )
    return None


def _glacier_word_first(name: str) -> str | None:
    """Apply rule 9, or return ``None`` when the name does not end with a glacier word."""
    match = _GLACIER_WORD_LAST.fullmatch(name)
    if match is None:
        return None
    particle = match["particle"]
    word = match["word"].replace("Gh.", "Ghiacciaio")
    if "Gl." in word and particle in _GL_BY_PARTICLE:
        word = word.replace("Gl.", _GL_BY_PARTICLE[particle]).replace(" Inf.", " Inferieur")
    space = "" if particle.endswith("'") else " "
    suffix = f" {match['suffix']}" if match["suffix"] else ""
    return f"{word} {particle}{space}{match['place']}{suffix}"


def _glacier_word(name: str, region: str | None) -> tuple[str, list[str]]:
    """Apply rules 9 and 10: the glacier word first, and ``Gl.`` expanded."""
    fired: list[str] = []
    reordered = _glacier_word_first(name)
    if reordered is not None:
        name = reordered
        fired.append("glacier-word-first")
    if region in _SPANISH_REGIONS and _GLACIAR_ABBREVIATION.match(name):
        name = _GLACIAR_ABBREVIATION.sub("Glaciar ", name, count=1)
        fired.append("glaciar-expanded")
    if region != _FRENCH_REGION and _GLACIER_ABBREVIATION_LAST.search(name):
        name = _GLACIER_ABBREVIATION_LAST.sub(" Glacier", name)
        fired.append("glacier-expanded")
    return name, fired


def apply_rules(
    raw: str | None,
    region: str | None = None,
    overrides: Mapping[str, str | None] | None = None,
) -> tuple[str | None, list[str]]:
    """Derive the display name and name the rules that fired.

    Parameters
    ----------
    raw
        ``glac_name`` after the encoding repair.
    region
        The first-order region (``o1region``), such as ``"11"``.
    overrides
        Display names by ``glac_name``. A match replaces the rules.

    Returns
    -------
    tuple[str | None, list[str]]
        The display name, or ``None``, and the rules from :data:`RULES` that
        applied (``["unchanged"]`` when none did).
    """
    if raw is None or not raw.strip():
        return None, ["empty"]
    if overrides is not None and raw in overrides:
        return overrides[raw], ["override"]
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
    name, substituted = _substitute(name)
    fired += substituted
    recased = _recase_capitals(name)
    if recased is not None:
        name = recased
        fired.append("recased")
    name, glacier_word = _glacier_word(name, region)
    fired += glacier_word
    if region == _FRENCH_REGION and _FRENCH_PARTICLE_START.match(name):
        name = f"Glacier {name}"
        fired.append("french-glacier")
    if name[0].islower():
        name = name[0].upper() + name[1:]
        fired.append("initial-capital")
    return name, fired or ["unchanged"]


def display_name(
    raw: str | None,
    region: str | None = None,
    overrides: Mapping[str, str | None] | None = None,
) -> str | None:
    """Return the name drawn on the map for a ``glac_name``.

    Parameters
    ----------
    raw
        ``glac_name`` after the encoding repair.
    region
        The first-order region (``o1region``), such as ``"11"``.
    overrides
        Display names by ``glac_name``. A match replaces the rules.

    Returns
    -------
    str | None
        The cleaned name, or ``None`` when there is no usable name.
    """
    return apply_rules(raw, region, overrides)[0]


def load_overrides(path: Path = OVERRIDES) -> list[dict[str, str | None]]:
    """Read the display-name overrides.

    Parameters
    ----------
    path
        The YAML file. Each entry has ``glac_name``, ``display_name`` (null
        for no name) and ``reason``.

    Returns
    -------
    list[dict[str, str | None]]
        The entries in file order.
    """
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def override_map(entries: list[dict[str, str | None]]) -> dict[str, str | None]:
    """Map each ``glac_name`` of :func:`load_overrides` to its display name.

    Parameters
    ----------
    entries
        The entries of :func:`load_overrides`.

    Returns
    -------
    dict[str, str | None]
        Display names by ``glac_name``.
    """
    return {str(e["glac_name"]): e["display_name"] for e in entries}


def rule_report(
    names: pd.Series,
    regions: pd.Series | None = None,
    overrides: Mapping[str, str | None] | None = None,
    sample: int = 40,
    seed: int = 0,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Count how often each rule fires, and draw changed names for review.

    Parameters
    ----------
    names
        ``glac_name`` values after the encoding repair.
    regions
        The ``o1region`` of each name, in the same order.
    overrides
        Display names by ``glac_name``.
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
    region_list = [None] * len(raws) if regions is None else list(regions)
    results = [apply_rules(v, r, overrides) for v, r in zip(raws, region_list, strict=True)]
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
