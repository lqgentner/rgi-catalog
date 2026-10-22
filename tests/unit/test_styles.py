"""Tests for the MapLibre style documents."""

from __future__ import annotations

import json
from typing import Any

import pyarrow.parquet as pq
import pytest

from rgi_catalog import styles
from rgi_catalog.paths import STAGING
from rgi_catalog.pipeline import output_path

GLACIERS_FILE = output_path(STAGING, "7.0", "glaciers")


def test_styles_reference_archive_relatively() -> None:
    assert styles.archive_href("glaciers") == "../rgi7.0.pmtiles"
    assert styles.archive_href("complexes") == "../../glaciers/rgi7.0.pmtiles"
    style = styles.collection_style("glaciers", styles.archive_href("glaciers"), ["glaciers"])
    assert style["version"] == 8
    assert style["sources"]["data"]["url"] == "pmtiles://../rgi7.0.pmtiles"
    full = styles.full_map_style(styles.archive_href("complexes"))
    assert full["version"] == 8
    assert full["sources"]["data"]["url"] == "pmtiles://../../glaciers/rgi7.0.pmtiles"


ALL_STYLES = styles.glacier_styles("../rgi7.0.pmtiles")


@pytest.mark.parametrize(
    "style",
    [styles.collection_style("glaciers", "../rgi7.0.pmtiles", ["glaciers"]), *ALL_STYLES.values()],
)
def test_style_layers_draw_from_the_archive(style: dict[str, Any]) -> None:
    layers = style["layers"]
    assert {layer["source"] for layer in layers} == {"data"}
    assert {layer["source-layer"] for layer in layers} <= {"glaciers", "glacier-labels"}
    assert len({layer["id"] for layer in layers}) == len(layers)
    assert style["metadata"]["description"]
    json.dumps(style)


def test_glacier_styles_default_is_the_full_map() -> None:
    assert list(ALL_STYLES) == [
        "full-map",
        "median-elevation",
        "surge-evidence",
        "terminus-type",
        "same-as-rgi6",
    ]
    assert styles.DEFAULT_STYLE == "full-map"
    assert ALL_STYLES["full-map"] == styles.full_map_style("../rgi7.0.pmtiles")


@pytest.mark.parametrize("style", ALL_STYLES.values())
def test_styles_label_glaciers_on_top(style: dict[str, Any]) -> None:
    labels = [layer for layer in style["layers"] if layer["source-layer"] == "glacier-labels"]
    assert len(labels) == 1
    assert labels[0]["type"] == "symbol"
    assert labels[0]["layout"]["text-field"] == ["get", "display_name"]
    assert "{fontstack}" in style["glyphs"]
    assert labels[0] is style["layers"][-1]


def _legend(style: dict[str, Any]) -> list[str]:
    """Return the legend labels the browser derives (match or step on a fill)."""
    fill = next(layer for layer in style["layers"] if layer["type"] == "fill")
    color = fill["paint"]["fill-color"]
    if color[0] == "match":
        return [str(v) for v in color[2:-1:2]]
    if color[0] == "step":
        return [f"< {color[3]}", *(str(v) for v in color[3::2])]
    return []


def test_thematic_styles_have_readable_legends() -> None:
    assert _legend(ALL_STYLES["surge-evidence"]) == [
        "No evidence",
        "Possible",
        "Probable",
        "Observed",
    ]
    assert _legend(ALL_STYLES["terminus-type"]) == ["Marine-terminating", "Not assigned"]
    assert _legend(ALL_STYLES["same-as-rgi6"]) == [
        "Same outline as RGI 6.0",
        "Remapped from RGI 6.0",
    ]
    assert _legend(ALL_STYLES["median-elevation"]) == [
        "< 1000",
        "1000",
        "2000",
        "3000",
        "4000",
        "5000",
    ]
    assert _legend(ALL_STYLES["full-map"]) == []


@pytest.mark.skipif(not GLACIERS_FILE.exists(), reason="needs the staged glaciers file")
@pytest.mark.parametrize("theme", [t for t in styles.THEMES.values() if t.codes])
def test_match_branches_exist_in_data(theme: styles.Theme) -> None:
    column = pq.read_table(GLACIERS_FILE, columns=[theme.column]).column(0)
    present = set(column.unique().to_pylist())
    assert set(theme.codes) == present


def test_collection_style_rejects_unknown_layer() -> None:
    with pytest.raises(KeyError, match="nonsense"):
        styles.collection_style("glaciers", "../rgi7.0.pmtiles", ["nonsense"])
