"""MapLibre style documents for the collections that draw from the web-map archive."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# The archive lives in the glaciers collection. Styles live in each
# collection's styles/ directory.
ARCHIVE_COLLECTION = "glaciers"
SOURCE_ID = "data"
# The glyphs of the browser's default basemaps (CARTO), which cover Latin,
# Cyrillic and Greek.
GLYPHS = "https://tiles.basemaps.cartocdn.com/fonts/{fontstack}/{range}.pbf"
LABEL_FONT = ["Open Sans Italic"]

GLACIER_FILL = "#9ecae1"
GLACIER_LINE = "#2171b5"
LABEL_COLOR = "#08306b"
NO_DATA = "#bdbdbd"
# At world scale a glacier is smaller than a pixel, so a fill alone draws
# nothing. An outline of about one pixel keeps every tiled glacier visible.
OUTLINE_WIDTH = ["interpolate", ["linear"], ["zoom"], 0, 1.2, 8, 0.6, 12, 1.0]

LABELS: dict[str, Any] = {
    "id": "glacier-labels",
    "type": "symbol",
    "layout": {
        "text-field": ["get", "display_name"],
        "text-font": LABEL_FONT,
        "text-size": 12,
        # Larger glaciers win label collisions.
        "symbol-sort-key": ["-", ["get", "area_km2"]],
    },
    "paint": {
        "text-color": LABEL_COLOR,
        "text-halo-color": "#ffffff",
        "text-halo-width": 1.2,
    },
}

# The style layers that draw each archive layer, bottom to top.
LAYER_STYLES: dict[str, list[dict[str, Any]]] = {
    "glaciers": [
        {
            "id": "glaciers-fill",
            "type": "fill",
            "paint": {"fill-color": GLACIER_FILL, "fill-opacity": 0.5},
        },
        {
            "id": "glaciers-outline",
            "type": "line",
            "paint": {"line-color": GLACIER_LINE, "line-width": OUTLINE_WIDTH},
        },
    ],
    "glacier-labels": [LABELS],
}
FULL_MAP_LAYERS = ("glaciers", "glacier-labels")


@dataclass(frozen=True)
class Theme:
    """A glacier style that colours the outlines by one column.

    A theme has either ``codes`` (a ``match`` on coded values) or ``stops``
    (a ``step`` on a measured value). Both give a legend in the browser.
    """

    title: str
    description: str
    column: str
    colors: tuple[str, ...]
    # Each coded value and the label the legend shows, in legend order. The
    # labels quote the RGI 7.0 user guide.
    codes: dict[Any, str] = field(default_factory=dict)
    # The lower bounds of the classes after the first.
    stops: tuple[float, ...] = ()

    def fill_color(self) -> list[Any]:
        """Return the ``fill-color`` expression.

        A ``match`` is keyed on the code's label, so the browser's legend,
        which shows the branch values, reads in words.

        Returns
        -------
        list[Any]
            A ``match`` or ``step`` expression.
        """
        value = ["get", self.column]
        if self.stops:
            pairs = [
                x
                for stop, color in zip(self.stops, self.colors[1:], strict=True)
                for x in (stop, color)
            ]
            return ["step", value, self.colors[0], *pairs]
        labels = list(self.codes.values())
        if all(isinstance(code, bool) for code in self.codes):
            label = ["case", value, self.codes[True], self.codes[False]]
        else:
            label = ["match", value, *[x for kv in self.codes.items() for x in kv], ""]
        branches = [x for pair in zip(labels, self.colors, strict=True) for x in pair]
        return ["match", label, *branches, NO_DATA]


THEMES: dict[str, Theme] = {
    "median-elevation": Theme(
        title="Median elevation",
        description=(
            "Glaciers coloured by median elevation (zmed_m) in 1,000 m classes, "
            "from below 1,000 m (dark purple) to 5,000 m and above (yellow)."
        ),
        column="zmed_m",
        stops=(1000, 2000, 3000, 4000, 5000),
        colors=("#440154", "#414487", "#2a788e", "#22a884", "#7ad151", "#fde725"),
    ),
    "surge-evidence": Theme(
        title="Surge evidence",
        description=(
            "Glaciers coloured by the evidence for surging (surge_type): no evidence, "
            "possible, probable or observed."
        ),
        column="surge_type",
        codes={0: "No evidence", 1: "Possible", 2: "Probable", 3: "Observed"},
        colors=("#c6dbef", "#fdd0a2", "#fd8d3c", "#d94801"),
    ),
    "terminus-type": Theme(
        title="Terminus type",
        description=(
            "Glaciers coloured by terminus type (term_type). RGI 7.0 assigns only the "
            "marine-terminating class. Every other glacier is not assigned."
        ),
        column="term_type",
        codes={1: "Marine-terminating", 9: "Not assigned"},
        colors=("#08519c", NO_DATA),
    ),
    "same-as-rgi6": Theme(
        title="Same as RGI 6.0",
        description=(
            "Glaciers coloured by whether the outline is the same as in RGI 6.0 "
            "(is_rgi6) or was remapped."
        ),
        column="is_rgi6",
        codes={True: "Same outline as RGI 6.0", False: "Remapped from RGI 6.0"},
        colors=("#1b9e77", "#d95f02"),
    ),
}
DEFAULT_STYLE = "full-map"


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


def _style(name: str, description: str, href: str, layers: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "version": 8,
        "name": name,
        "metadata": {"description": description},
        "glyphs": GLYPHS,
        "sources": {SOURCE_ID: {"type": "vector", "url": f"pmtiles://{href}"}},
        "layers": [{**layer, "source": SOURCE_ID} for layer in layers],
    }


def _layers_of(names: list[str]) -> list[dict[str, Any]]:
    return [{**spec, "source-layer": name} for name in names for spec in LAYER_STYLES[name]]


def collection_style(collection: str, archive_href: str, layers: list[str]) -> dict[str, Any]:
    """Return a style that draws a collection's own layers.

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
    return _style(
        f"RGI 7.0 {collection}",
        f"The {collection} of RGI 7.0.",
        archive_href,
        _layers_of(layers),
    )


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
    return _style(
        "Glaciers with names",
        "Glacier outlines (blue) with glacier names. Larger glaciers are named at lower zooms.",
        archive_href,
        _layers_of(list(FULL_MAP_LAYERS)),
    )


def thematic_style(theme: str, archive_href: str) -> dict[str, Any]:
    """Return a style that colours the glaciers by one column, with labels.

    Parameters
    ----------
    theme
        A key of :data:`THEMES`.
    archive_href
        The archive's href relative to the style file.

    Returns
    -------
    dict[str, Any]
        A MapLibre style (version 8) whose fill layer gives a legend.
    """
    spec = THEMES[theme]
    layers = [
        {
            "id": f"glaciers-{theme}",
            "type": "fill",
            "source-layer": "glaciers",
            "paint": {"fill-color": spec.fill_color(), "fill-opacity": 0.8},
        },
        {
            "id": "glaciers-outline",
            "type": "line",
            "source-layer": "glaciers",
            "paint": {"line-color": spec.fill_color(), "line-width": OUTLINE_WIDTH},
        },
        {**LABELS, "source-layer": "glacier-labels"},
    ]
    return _style(spec.title, spec.description, archive_href, layers)


def glacier_styles(archive_href: str) -> dict[str, dict[str, Any]]:
    """Return every style of the glaciers collection, the default first.

    Parameters
    ----------
    archive_href
        The archive's href relative to the style files.

    Returns
    -------
    dict[str, dict[str, Any]]
        Styles by file stem. :data:`DEFAULT_STYLE` is the first.
    """
    return {
        DEFAULT_STYLE: full_map_style(archive_href),
        **{theme: thematic_style(theme, archive_href) for theme in THEMES},
    }
