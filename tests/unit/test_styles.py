"""Tests for the MapLibre style documents."""

from __future__ import annotations

import json
import re
from typing import Any

import pyarrow.parquet as pq
import pytest

from rgi_catalog import glyphs, styles, tiles
from rgi_catalog.paths import STAGING
from rgi_catalog.pipeline import output_path

GLACIERS_FILE = output_path(STAGING, "7.0", "glaciers")


def test_styles_reference_the_shared_archive() -> None:
    # Styles live in v7.0/<collection>/styles/. The archive is v7.0/rgi7.0.pmtiles.
    assert styles.archive_href("7.0") == "../../rgi7.0.pmtiles"
    style = styles.collection_style("glaciers", styles.archive_href(), ["glaciers"])
    assert style["version"] == 8
    assert style["sources"]["data"]["url"] == "pmtiles://../../rgi7.0.pmtiles"
    full = styles.glaciers_style(styles.archive_href())
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


def test_glacier_styles_default_is_the_glaciers_style() -> None:
    assert list(ALL_STYLES) == [
        "glaciers",
        "median-elevation",
        "surge-evidence",
        "terminus-type",
        "same-as-rgi6",
    ]
    assert styles.DEFAULT_STYLE == "glaciers"
    assert ALL_STYLES["glaciers"]["name"] == "Glaciers"
    assert ALL_STYLES["glaciers"] == styles.glaciers_style("../../rgi7.0.pmtiles")


@pytest.mark.parametrize("style", ALL_STYLES.values())
def test_styles_label_glaciers_on_top(style: dict[str, Any]) -> None:
    labels = [layer for layer in style["layers"] if layer["source-layer"] == "glacier-labels"]
    assert len(labels) == 1
    assert labels[0]["type"] == "symbol"
    assert labels[0]["layout"]["text-field"] == ["get", "display_name"]
    assert "{fontstack}" in style["glyphs"]
    assert labels[0] is style["layers"][-1]


@pytest.mark.parametrize("style", ALL_STYLES.values())
def test_styles_draw_glacier_names_along_label_lines(style: dict[str, Any]) -> None:
    # The tiles step fits each label line to this text, in this font.
    labels = next(layer for layer in style["layers"] if layer["source-layer"] == "glacier-labels")
    assert labels["filter"] == [
        "==",
        ["get", "label_zoom"],
        ["min", ["zoom"], tiles.LABEL_MAXZOOM],
    ]
    assert labels["layout"]["symbol-placement"] == "line-center"
    assert labels["layout"]["text-font"] == [glyphs.FONT]
    assert labels["layout"]["text-size"] == glyphs.LABEL_TEXT_SIZE
    assert labels["layout"]["text-letter-spacing"] == glyphs.LABEL_LETTER_SPACING
    assert style["glyphs"] == glyphs.GLYPHS


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
    assert _legend(ALL_STYLES["glaciers"]) == []


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
    # A dot has the colour of the fill, so it reads as a glacier too small to
    # draw rather than as a different feature.
    fill = next(
        layer
        for layer in style["layers"]
        if layer["type"] == "fill" and layer["source-layer"] == "glaciers"
    )
    assert dots[0]["paint"]["circle-color"] == fill["paint"]["fill-color"]


HREF = "../../rgi7.0.pmtiles"
COLLECTIONS = ("glaciers", "complexes", "centerlines", "intersects", "regions")


@pytest.mark.parametrize("name", COLLECTIONS)
def test_every_collection_has_a_default_and_the_glaciers_style(name: str) -> None:
    found = styles.collection_styles(name, HREF)
    assert next(iter(found)) == styles.DEFAULT_STYLES[name]
    assert "glaciers" in found
    assert found["glaciers"] == styles.glaciers_style(HREF)
    default = found[styles.DEFAULT_STYLES[name]]
    if name != "glaciers":
        assert name in {layer["source-layer"] for layer in default["layers"]}
    for style in found.values():
        assert style["sources"]["data"]["url"] == f"pmtiles://{HREF}"


def test_glaciers_style_draws_the_glaciers_and_the_regions() -> None:
    full = styles.glaciers_style(HREF)
    assert {layer["source-layer"] for layer in full["layers"]} == {
        "region-boundaries",
        "region-labels",
        "glaciers",
        "glacier-labels",
    }
    # Only the glacier fill is a fill, so the style has no legend.
    assert [layer["id"] for layer in full["layers"] if layer["type"] == "fill"] == [
        "glaciers-fill",
    ]


def test_regions_style_legend_names_the_levels() -> None:
    regions = styles.collection_styles("regions", HREF)["regions"]
    assert _legend(regions) == ["First-order region", "Second-order region"]


@pytest.mark.parametrize("name", ["centerlines", "intersects"])
def test_line_styles_draw_the_glaciers_as_context(name: str) -> None:
    default = styles.collection_styles(name, HREF)[name]
    layers = [layer["source-layer"] for layer in default["layers"]]
    assert layers.index("glaciers") < layers.index(name)


@pytest.mark.parametrize("name", ["centerlines", "intersects"])
def test_glaciers_under_lines_recede_in_the_glacier_colours(name: str) -> None:
    # The same glacier colours in every style, but fainter under the lines,
    # so the lines are the subject.
    def paint(style: dict[str, Any], kind: str) -> dict[str, Any]:
        return next(
            layer["paint"]
            for layer in style["layers"]
            if layer.get("source-layer") == "glaciers" and layer["type"] == kind
        )

    own = styles.collection_styles(name, HREF)[name]
    ref = styles.glaciers_style(HREF)
    assert paint(own, "fill")["fill-color"] == paint(ref, "fill")["fill-color"]
    assert paint(own, "line")["line-color"] == paint(ref, "line")["line-color"]
    assert paint(own, "fill")["fill-opacity"] < paint(ref, "fill")["fill-opacity"]
    assert paint(own, "line").get("line-opacity", 1) < paint(ref, "line").get("line-opacity", 1)


COLOR_WORDS = re.compile(
    r"\b(red|orange|yellow|green|teal|blue|purple|violet|pink|grey|gray|black|white|"
    r"light|dark|pale)\b",
    re.IGNORECASE,
)


@pytest.mark.parametrize("name", COLLECTIONS)
def test_style_descriptions_name_no_colour(name: str) -> None:
    # The style and its legend show the colours. A description that names them
    # drifts when the palette changes.
    for key, style in styles.collection_styles(name, HREF).items():
        assert not COLOR_WORDS.search(style["metadata"]["description"]), (name, key)


@pytest.mark.parametrize("name", COLLECTIONS)
def test_every_style_draws_region_boundaries_and_names(name: str) -> None:
    # The boundaries come from the layer that stores each border once, so
    # their dash patterns stay in step. A first-order dash is the longer.
    for key, style in styles.collection_styles(name, HREF).items():
        layers = style["layers"]
        ids = [layer["id"] for layer in layers]
        bounds = [i for i, x in enumerate(ids) if x.startswith("region-boundaries-")]
        assert [ids[i] for i in bounds] == ["region-boundaries-2", "region-boundaries-1"], key
        assert {layers[i]["source-layer"] for i in bounds} == {"region-boundaries"}, key
        dash = [layers[i]["paint"]["line-dasharray"] for i in bounds]
        assert dash[1][0] > dash[0][0], key
        data = [
            i
            for i, layer in enumerate(layers)
            if layer["source-layer"] not in {"regions", "region-boundaries", "region-labels"}
        ]
        assert max(bounds) < min(data, default=len(layers)), (name, key)
        assert {"region-labels-1", "region-labels-2"} <= set(ids), (name, key)


@pytest.mark.parametrize(("level", "code"), [(1, "o1region"), (2, "o2region")])
def test_region_labels_show_the_number(level: int, code: str) -> None:
    label = next(
        layer
        for layer in styles.glaciers_style(HREF)["layers"]
        if layer["id"] == f"region-labels-{level}"
    )
    assert ["get", code] in label["layout"]["text-field"]
    assert ["get", "full_name"] in label["layout"]["text-field"]
