"""Tests that docs/PROVENANCE.md states the fixes the build made."""

from __future__ import annotations

import json

import pytest

from rgi_catalog.names import load_overrides
from rgi_catalog.paths import METADATA, REPO, STAGING

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
