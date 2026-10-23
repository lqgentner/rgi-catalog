"""Tests for the map-label names."""

from __future__ import annotations

import pandas as pd
import pytest

from rgi_catalog.names import RULES, display_name, rule_report

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
    # Inventory codes with range or query suffixes are stripped.
    ("FR4N01166H08-10 de la Grande Montagne", "de la Grande Montagne"),
    ("FR4N01166D14+66D15 du Says", "du Says"),
    ("FR4N01172C04? de Porteras", "de Porteras"),
    ("FR4N01083A?? de Malamort", "de Malamort"),
    # No name: "NN,", "Unnamed_23", and names that are only a bracket.
    ("NN,", None),
    ("Unnamed_23", None),
    ("(Severny Island)", None),
    # Trailing commas are dropped.
    ("Alexander Island,", "Alexander Island"),
]


@pytest.mark.parametrize(("raw", "want"), CASES)
def test_display_name(raw: str | None, want: str | None) -> None:
    assert display_name(raw) == want


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
