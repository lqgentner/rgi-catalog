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
    assert list(sample.columns) == ["glac_name", "display_name", "rules"]
    assert len(sample) == 2
    # The sample draws only from names that a rule changed.
    assert (sample["glac_name"] != sample["display_name"]).all()
