"""Tests that docs/PROVENANCE.md states the fixes the build made."""

from __future__ import annotations

import json
import re

import pyarrow.parquet as pq
import pytest

from rgi_catalog.names import load_overrides, override_map, rule_report
from rgi_catalog.paths import METADATA, REPO, STAGING
from rgi_catalog.pipeline import output_path

PROVENANCE = REPO / "docs" / "PROVENANCE.md"


def test_fix_table_matches_the_build_record() -> None:
    text = PROVENANCE.read_text()
    record = json.loads((METADATA / "builds" / "v7.0.json").read_text())
    for name, fixes in record["fixes"].items():
        for fix in fixes:
            row = f"| {name} | `{fix['fix']}` | `{fix['column']}` | {fix['count']:,} |"
            assert row in text, row


def test_every_changed_id_listed() -> None:
    report = STAGING / "v7.0" / ".reports" / "fixes.json"
    if not report.exists():
        pytest.skip("no staged fix report; run convert")
    text = PROVENANCE.read_text()
    for entry in json.loads(report.read_text()):
        missing = [i for i in entry["ids"] if f"`{i}`" not in text]
        assert not missing, (entry["fix"], entry["product"], missing[:5])


def test_every_name_override_listed() -> None:
    text = PROVENANCE.read_text()
    for entry in load_overrides():
        shown = entry["display_name"] if entry["display_name"] is not None else "null"
        row = f"| `{entry['glac_name']}` | {shown} | {entry['reason']} |"
        assert row in text, row


def test_display_name_rule_counts_match_the_rules() -> None:
    staged = output_path(STAGING, "7.0", "glaciers")
    if not staged.exists():
        pytest.skip("no staged glaciers file; run convert")
    table = pq.read_table(staged, columns=["glac_name", "o1region"]).to_pandas()
    counts, _ = rule_report(table["glac_name"], table["o1region"], override_map(load_overrides()))
    rows = re.findall(
        r"^\| `([a-z-]+)`[^|\n]*\| ([\d,]+) \|$", PROVENANCE.read_text(), re.MULTILINE
    )
    stated = {rule: int(n.replace(",", "")) for rule, n in rows}
    for rule, count in zip(counts["rule"], counts["count"], strict=True):
        assert stated.get(rule) == count, (rule, stated.get(rule), count)
