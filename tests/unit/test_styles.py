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


def test_styles_reference_the_shared_archive() -> None:
    # Styles live in v7.0/<collection>/styles/. The archive is v7.0/rgi7.0.pmtiles.
    assert styles.archive_href("7.0") == "../../rgi7.0.pmtiles"
    style = styles.collection_style("glaciers", styles.archive_href(), ["glaciers"])
    assert style["version"] == 8
    assert style["sources"]["data"]["url"] == "pmtiles://../../rgi7.0.pmtiles"
    full = styles.full_map_style(styles.archive_href())
    assert full["sources"]["data"]["url"] == "pmtiles://../../rgi7.0.pmtiles"


ALL_STYLES = styles.glacier_styles("../../rgi7.0.pmtiles")


@pytest.mark.parametrize(
    "style",
    [
        styles.collection_style("glaciers", "../../rgi7.0.pmtiles", ["glaciers"]),
        *ALL_STYLES.values(),
    ],
)
def test_style_layers_draw_from_the_archive(style: dict[str, Any]) -> None:
    layers = style["layers"]
    assert {layer["source"] for layer in layers} == {"data"}
    assert {layer["source-layer"] for layer in layers} <= set(styles.ARCHIVE_LAYERS)
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
    assert ALL_STYLES["full-map"] == styles.full_map_style("../../rgi7.0.pmtiles")


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
        "Same as RGI 6.0",
        "New in RGI 7.0",
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


@pytest.mark.parametrize("style", ALL_STYLES.values())
def test_glacier_outlines_drawn_from_zoom_0(style: dict[str, Any]) -> None:
    # At world scale a glacier is smaller than a pixel. A fill alone draws
    # nothing there, a line of about one pixel shows it.
    lines = [
        layer
        for layer in style["layers"]
        if layer["type"] == "line" and layer["source-layer"] == "glaciers"
    ]
    assert len(lines) == 1
    assert "minzoom" not in lines[0]
    width = lines[0]["paint"]["line-width"]
    assert width[:3] == ["interpolate", ["linear"], ["zoom"]]
    assert width[3:5] == [0, 1.2]


def test_thematic_outline_uses_the_theme_colour() -> None:
    style = ALL_STYLES["surge-evidence"]
    fill = next(layer for layer in style["layers"] if layer["type"] == "fill")
    line = next(
        layer
        for layer in style["layers"]
        if layer["type"] == "line" and layer["source-layer"] == "glaciers"
    )
    assert line["paint"]["line-color"] == fill["paint"]["fill-color"]


def test_collection_style_rejects_unknown_layer() -> None:
    with pytest.raises(KeyError, match="nonsense"):
        styles.collection_style("glaciers", "../../rgi7.0.pmtiles", ["nonsense"])


@pytest.mark.parametrize("style", ALL_STYLES.values())
def test_glaciers_drawn_as_dots_at_low_zoom(style: dict[str, Any]) -> None:
    # The archive holds each glacier as a point at the lowest zooms. A fill
    # or a line layer ignores points, so a circle layer draws them.
    dots = [layer for layer in style["layers"] if layer["type"] == "circle"]
    assert len(dots) == 1
    assert dots[0]["source-layer"] == "glaciers"
    assert dots[0]["filter"] == [
        "in",
        ["geometry-type"],
        ["literal", ["Point", "MultiPoint"]],
    ]
    line = next(
        layer
        for layer in style["layers"]
        if layer["type"] == "line" and layer["source-layer"] == "glaciers"
    )
    assert dots[0]["paint"]["circle-color"] == line["paint"]["line-color"]


HREF = "../../rgi7.0.pmtiles"
COLLECTIONS = ("glaciers", "complexes", "centerlines", "intersects", "regions")


@pytest.mark.parametrize("name", COLLECTIONS)
def test_every_collection_has_a_default_and_the_full_map(name: str) -> None:
    found = styles.collection_styles(name, HREF)
    assert next(iter(found)) == styles.DEFAULT_STYLES[name]
    assert "full-map" in found
    assert found["full-map"] == styles.full_map_style(HREF)
    default = found[styles.DEFAULT_STYLES[name]]
    if name != "glaciers":
        assert name in {layer["source-layer"] for layer in default["layers"]}
    for style in found.values():
        assert style["sources"]["data"]["url"] == f"pmtiles://{HREF}"


def test_full_map_draws_regions_glaciers_and_centerlines() -> None:
    full = styles.full_map_style(HREF)
    assert {layer["source-layer"] for layer in full["layers"]} == {
        "regions",
        "region-labels",
        "glaciers",
        "centerlines",
        "glacier-labels",
    }
    # Only the glacier fill is a fill, so the full map has no legend.
    assert [layer["id"] for layer in full["layers"] if layer["type"] == "fill"] == [
        "glaciers-fill",
    ]
    lines = next(layer for layer in full["layers"] if layer["source-layer"] == "centerlines")
    assert lines["paint"]["line-color"] == styles.CENTERLINE_COLOR


def test_regions_style_legend_names_the_levels() -> None:
    regions = styles.collection_styles("regions", HREF)["regions"]
    assert _legend(regions) == ["First-order region", "Second-order region"]


@pytest.mark.parametrize("name", ["centerlines", "intersects"])
def test_line_styles_draw_the_glaciers_as_context(name: str) -> None:
    default = styles.collection_styles(name, HREF)[name]
    layers = [layer["source-layer"] for layer in default["layers"]]
    assert layers.index("glaciers") < layers.index(name)
