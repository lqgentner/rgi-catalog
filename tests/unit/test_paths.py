"""Tests for the repository paths."""

from __future__ import annotations

from rgi_catalog.paths import REPO, STAGING, version_dir


def test_version_dir() -> None:
    assert version_dir("7.0") == "v7.0"
    assert STAGING.name == "staging"
    assert STAGING.parent == REPO
