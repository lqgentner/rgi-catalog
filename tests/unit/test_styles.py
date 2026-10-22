"""Tests for the MapLibre style documents."""

from __future__ import annotations

import json

import pytest

from rgi_catalog import styles


def test_styles_reference_archive_relatively() -> None:
    assert styles.archive_href("glaciers") == "../rgi7.0.pmtiles"
    assert styles.archive_href("complexes") == "../../glaciers/rgi7.0.pmtiles"
    style = styles.collection_style("glaciers", styles.archive_href("glaciers"), ["glaciers"])
    assert style["version"] == 8
    assert style["sources"]["data"]["url"] == "pmtiles://../rgi7.0.pmtiles"
    full = styles.full_map_style(styles.archive_href("complexes"))
    assert full["version"] == 8
    assert full["sources"]["data"]["url"] == "pmtiles://../../glaciers/rgi7.0.pmtiles"


@pytest.mark.parametrize(
    "style",
    [
        styles.collection_style("glaciers", "../rgi7.0.pmtiles", ["glaciers"]),
        styles.full_map_style("../rgi7.0.pmtiles"),
    ],
)
def test_style_layers_draw_from_the_archive(style: dict[str, object]) -> None:
    layers = style["layers"]
    assert isinstance(layers, list)
    assert {layer["source"] for layer in layers} == {"data"}
    assert {layer["source-layer"] for layer in layers} <= {"glaciers", "glacier-labels"}
    assert len({layer["id"] for layer in layers}) == len(layers)
    json.dumps(style)


def test_full_map_style_labels_glaciers() -> None:
    style = styles.full_map_style("../rgi7.0.pmtiles")
    labels = [layer for layer in style["layers"] if layer["source-layer"] == "glacier-labels"]
    assert len(labels) == 1
    assert labels[0]["type"] == "symbol"
    assert labels[0]["layout"]["text-field"] == ["get", "display_name"]
    assert "{fontstack}" in style["glyphs"]
    assert labels[0] is style["layers"][-1]


def test_collection_style_rejects_unknown_layer() -> None:
    with pytest.raises(KeyError, match="nonsense"):
        styles.collection_style("glaciers", "../rgi7.0.pmtiles", ["nonsense"])
