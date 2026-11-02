"""Tests for the map-label names."""

from __future__ import annotations

import pandas as pd
import pytest

from rgi_catalog.names import RULES, apply_rules, display_name, load_overrides, rule_report

CASES = [
    ("GROSSER ALETSCH GLETSCHER", "Grosser Aletsch Gletscher"),
    ("FR4N01236A01 Mer de Glace/Geant", "Mer de Glace/Geant"),
    ("Marmolada IT4L00101101", "Marmolada"),
    ("CN5Y673P0037 Tuomuer Glacier", "Tuomuer Glacier"),
    ("VOLCAN MICHINMAHUIDA_2", "Volcan Michinmahuida 2"),
    ("CN5O261B0076", None),
    ("S/N", None),
    ("WA", None),
    ("NEF", None),
    ("147", None),
    (None, None),
    ("", None),
    ("Hintereisferner", "Hintereisferner"),
    ("McCall Glacier", "McCall Glacier"),
    ("Ледник Безенги", "Ледник Безенги"),
    ("Brousilov Ice Cap (Prince George Land)", "Brousilov Ice Cap (Prince George Land)"),
    # Roman numerals stay capitals. A hyphen before a compass point or a Roman
    # numeral becomes a space, as in the Swiss Glacier Inventory.
    ("ROTBLATTGLETSCHER-III", "Rotblattgletscher III"),
    ("WEINGARTENGLETSCHER-N-II", "Weingartengletscher N II"),
    ("Tälligletscher-E", "Tälligletscher E"),
    ("Fründenhorn-NW", "Fründenhorn NW"),
    ("Mont Vélan-W", "Mont Vélan W"),
    ("Vostok-4 Ice Cap (Eva-Liv Island)", "Vostok-4 Ice Cap (Eva-Liv Island)"),
    ("SAINT-SORLIN", "Saint-Sorlin"),
    # Particles in re-cased names are lowercase unless first. No reordering.
    ("CORDÓN DEL PICO ALTO", "Cordón del Pico Alto"),
    ("TRIENT GLACIER DU", "Trient Glacier du"),
    ("PETIT COMBIN GLACIER DU-III", "Petit Combin Glacier du III"),
    ("GLACIER D'ARGENTIERE", "Glacier d'Argentiere"),
    ("ORNY GLACIER D'", "Orny Glacier d'"),
    ("DE LA PLAINE MORTE", "De la Plaine Morte"),
    # A Swiss canton code at the end stays in capitals. Elsewhere it is a word.
    ("FIESCHERGLETSCHER VS", "Fieschergletscher VS"),
    ("FIESCHERGLETSCHER BE", "Fieschergletscher BE"),
    ("UR GLETSCHER", "Ur Gletscher"),
    # In a mixed-case name, a word of four or more capitals is re-cased. A word
    # that mixes cases stays. "Mitte" is a Swiss suffix like a compass point.
    ("TUNGELGLETSCHER09n", "Tungelgletscher09n"),
    ("HINT. TRIFTGLETSCHER-Mitte", "Hint. Triftgletscher Mitte"),
    ("UNNERBÄCHGLETSCHER-Mitte", "Unnerbächgletscher Mitte"),
    ("PLAN NEVE  l'", "Plan Neve l'"),
    ("MIIGAiK", "MIIGAiK"),
    ("SHCHuchij", "SHCHuchij"),
    ("Mitter Kees M", "Mitter Kees M"),
    # Inventory codes with range or query suffixes are stripped. Outside
    # region 11 a name that starts in lowercase gets a capital.
    ("FR4N01166H08-10 de la Grande Montagne", "De la Grande Montagne"),
    ("FR4N01166D14+66D15 du Says", "Du Says"),
    ("FR4N01172C04? de Porteras", "De Porteras"),
    ("FR4N01083A?? de Malamort", "De Malamort"),
    # No name: "NN,", "Unnamed_23", and names that are only a bracket.
    ("NN,", None),
    ("Unnamed_23", None),
    ("(Severny Island)", None),
    # Trailing commas are dropped.
    ("Alexander Island,", "Alexander Island"),
    # A word that holds a digit keeps its case.
    ("HPS34", "HPS34"),
    ("HPN1", "HPN1"),
    ("48A", "48A"),
    ("VERDE-U1", "Verde-U1"),
    ("JOTABECHE 1", "Jotabeche 1"),
    # Romansh and Italian particles.
    ("MURTEL VADRET DAL", "Murtel Vadret dal"),
    ("GREINA GLATSCHER  DALLA", "Greina Glatscher dalla"),
    ("TUORS GLATSCHER  DALLAS", "Tuors Glatscher dallas"),
    ("LAI BLAU GLATSCHER DIL", "Lai Blau Glatscher dil"),
    ("ROSSI VADRET DEI", "Rossi Vadret dei"),
    # The suffix hyphen leaves no space after an apostrophe or a second space.
    ("A NEUVE GLACIER DE L'-N", "A Neuve Glacier de l'N"),
    ("Tour Sallière Glacier de la -II", "Tour Sallière Glacier de la II"),
    # A Cyrillic letter after digits becomes the Latin letter.
    ("101а", "101a"),
    ("359е", "359e"),
    ("260в", "260v"),
    ("Ледник Безенги", "Ледник Безенги"),
    # A dash as an empty second name is dropped.
    ("Austfonna, -", "Austfonna"),
    ("Cima Vertana Sud Ovest / -", "Cima Vertana Sud Ovest"),
    # Words that mean "no name".
    ("<Null>", None),
    ("None", None),
    ("Namenlos", None),
    ("Namenlos-II", None),
    ("No Name Glacier", None),
    # A backtick or an acute accent used as an apostrophe.
    ("Shkhel`dy", "Shkhel'dy"),
    ("Stal`nova (severny`j)", "Stal'nova (severny'j)"),
    ("O´HIGGINS", "O'Higgins"),
    # Spacing around brackets and slashes.
    ("SOROESTE(NORTH) 38", "Soroeste (North) 38"),
    ("Osand  (Sabbione Nord )", "Osand (Sabbione Nord)"),
    ("Croda Rossa /Rotwand", "Croda Rossa / Rotwand"),
    ("Capro Ovest o Ghiacciaio Alto/ Hochferner", "Capro Ovest o Ghiacciaio Alto / Hochferner"),
    ("Finale / Finail", "Finale / Finail"),
    ("Marvine/Hayden Glacier", "Marvine/Hayden Glacier"),
    # A name that starts in lowercase gets a capital.
    ("tiutiun", "Tiutiun"),
    ("le Fauteuil Glacier", "Le Fauteuil Glacier"),
    ("d'Iberville", "D'Iberville"),
    # A trailing question mark marks an uncertain name, and it stays.
    ("FR4N01172F02 du Col de Sirac?", "Du Col de Sirac?"),
]


@pytest.mark.parametrize(("raw", "want"), CASES)
def test_display_name(raw: str | None, want: str | None) -> None:
    assert display_name(raw) == want


# The French Glacier Inventory leaves out "Glacier" before a particle.
FRENCH = [
    ("FR4N01154Q12 d'Ambin", "Glacier d'Ambin"),
    ("FR4N01153C19 du Baounet 1", "Glacier du Baounet 1"),
    ("FR4N01xxxxxx de la Grande Valloire?", "Glacier de la Grande Valloire?"),
    ("FR4N01144E22+E24 des Sources de l'Isere", "Glacier des Sources de l'Isere"),
    ("de Clouzis", "Glacier de Clouzis"),
    ("FR4N01083B21 Blanc", "Blanc"),
    ("DE LA PLAINE MORTE", "De la Plaine Morte"),
]


@pytest.mark.parametrize(("raw", "want"), FRENCH)
def test_display_name_french_inventory(raw: str, want: str) -> None:
    assert display_name(raw, region="11") == want


def test_display_name_particle_outside_region_11() -> None:
    assert display_name("d'Iberville", region="03") == "D'Iberville"


def test_override_replaces_the_rules() -> None:
    overrides = {"Hallsttter Gletscher,": "Hallstätter Gletscher", "Group of small glaciers": None}
    assert apply_rules("Hallsttter Gletscher,", overrides=overrides) == (
        "Hallstätter Gletscher",
        ["override"],
    )
    assert apply_rules("Group of small glaciers", overrides=overrides) == (None, ["override"])
    unchanged = apply_rules("Hintereisferner", overrides=overrides)
    assert unchanged == ("Hintereisferner", ["unchanged"])


def test_overrides_file_gives_a_reason() -> None:
    entries = load_overrides()
    assert entries
    for entry in entries:
        assert set(entry) == {"glac_name", "display_name", "reason"}
        assert entry["reason"]
    keys = [e["glac_name"] for e in entries]
    assert len(keys) == len(set(keys))


def test_rule_report_counts_and_sample() -> None:
    names = pd.Series(["S/N", "GROSSER ALETSCH GLETSCHER", "Hintereisferner", None, "147"])
    counts, sample = rule_report(names, sample=2, seed=0)
    assert set(counts["rule"]) <= set(RULES)
    by_rule = dict(zip(counts["rule"], counts["count"], strict=True))
    assert by_rule["no-name-marker"] == 1
    assert by_rule["recased"] == 1
    assert by_rule["numeric-only"] == 1
    assert by_rule["unchanged"] == 1
    # A name that is only a code counts once, as code-only.
    code_counts, _ = rule_report(pd.Series(["CN5O261B0076"]), sample=1)
    by_code = dict(zip(code_counts["rule"], code_counts["count"], strict=True))
    assert by_code["code-only"] == 1
    assert by_code["inventory-code-stripped"] == 0
    assert list(sample.columns) == ["glac_name", "display_name", "rules"]
    assert len(sample) == 2
    # The sample draws only from names that a rule changed.
    assert (sample["glac_name"] != sample["display_name"]).all()
