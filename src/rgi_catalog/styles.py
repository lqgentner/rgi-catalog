"""MapLibre style documents for the collections that draw from the web-map archive."""

from __future__ import annotations

from typing import Any

# The archive lives in the glaciers collection. Styles live in each
# collection's styles/ directory.
ARCHIVE_COLLECTION = "glaciers"
SOURCE_ID = "data"
# The glyphs of the browser's default basemaps (CARTO), which cover Latin,
# Cyrillic and Greek.
GLYPHS = "https://tiles.basemaps.cartocdn.com/fonts/{fontstack}/{range}.pbf"
LABEL_FONT = ["Open Sans Italic"]

GLACIER_FILL = "#5b9bd5"
GLACIER_LINE = "#1f4e79"

# The style layers that draw each archive layer, bottom to top.
LAYER_STYLES: dict[str, list[dict[str, Any]]] = {
    "glaciers": [
        {
            "id": "glaciers-fill",
            "type": "fill",
            "paint": {"fill-color": GLACIER_FILL, "fill-opacity": 0.6},
        },
        {
            "id": "glaciers-outline",
            "type": "line",
            "minzoom": 10,
            "paint": {"line-color": GLACIER_LINE, "line-width": 0.5},
        },
    ],
    "glacier-labels": [
        {
            "id": "glacier-labels",
            "type": "symbol",
            "layout": {
                "text-field": ["get", "display_name"],
                "text-font": LABEL_FONT,
                "text-size": 12,
                "symbol-sort-key": ["-", ["get", "area_km2"]],
            },
            "paint": {
                "text-color": GLACIER_LINE,
                "text-halo-color": "#ffffff",
                "text-halo-width": 1.2,
            },
        },
    ],
}
FULL_MAP_LAYERS = ("glaciers", "glacier-labels")


def archive_href(collection: str, version: str = "7.0") -> str:
    """Return the archive's href relative to a collection's ``styles/`` directory.

    Parameters
    ----------
    collection
        The collection whose style links the archive.
    version
        The RGI version.

    Returns
    -------
    str
        For example ``../rgi7.0.pmtiles`` for the glaciers collection.
    """
    name = f"rgi{version}.pmtiles"
    if collection == ARCHIVE_COLLECTION:
        return f"../{name}"
    return f"../../{ARCHIVE_COLLECTION}/{name}"


def _style(name: str, href: str, layers: list[str]) -> dict[str, Any]:
    style_layers = [
        {**spec, "source": SOURCE_ID, "source-layer": layer}
        for layer in layers
        for spec in LAYER_STYLES[layer]
    ]
    return {
        "version": 8,
        "name": name,
        "glyphs": GLYPHS,
        "sources": {SOURCE_ID: {"type": "vector", "url": f"pmtiles://{href}"}},
        "layers": style_layers,
    }


def collection_style(collection: str, archive_href: str, layers: list[str]) -> dict[str, Any]:
    """Return a collection's default style, which draws its own layers.

    Parameters
    ----------
    collection
        The collection name.
    archive_href
        The archive's href relative to the style file.
    layers
        The archive layers to draw, bottom to top.

    Returns
    -------
    dict[str, Any]
        A MapLibre style (version 8).
    """
    return _style(f"RGI 7.0 {collection}", archive_href, layers)


def full_map_style(archive_href: str) -> dict[str, Any]:
    """Return the style that draws every archive layer with labels.

    Parameters
    ----------
    archive_href
        The archive's href relative to the style file.

    Returns
    -------
    dict[str, Any]
        A MapLibre style (version 8). The labels are the top layer.
    """
    return _style("RGI 7.0 full map", archive_href, list(FULL_MAP_LAYERS))
