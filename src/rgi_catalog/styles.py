"""MapLibre style documents for the collections that draw from the web-map archive."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from rgi_catalog import glyphs
from rgi_catalog.tiles import LABEL_MAXZOOM

# The archive lives in the version directory. Styles live in each
# collection's styles/ directory.
SOURCE_ID = "data"
# OpenFreeMap's glyphs. The label lines in the archive are fitted to the
# glyph advances of LABEL_FONT from the same server.
GLYPHS = glyphs.GLYPHS
LABEL_FONT = [glyphs.FONT]
REGION_FONTS = {1: ["Noto Sans Bold"], 2: ["Noto Sans Regular"]}

# One colour per product, the same in every style. Each clears 3:1 against a
# light grey basemap, and the four stay apart for colour-blind readers.
GLACIER_FILL = "#1e88e5"
GLACIER_LINE = "#0d47a1"
LABEL_COLOR = "#0d2a5c"
NO_DATA = "#9e9e9e"
COMPLEX_FILL = "#8e24aa"
COMPLEX_LINE = "#4a148c"
CENTERLINE_COLOR = "#d55e00"
INTERSECT_COLOR = "#00897b"
REGION_LINE = "#757575"
REGION_LINE_2 = "#9e9e9e"
REGION_LABEL = "#37474f"
# At world scale a glacier is smaller than a pixel, so a fill alone draws
# nothing. An outline of about one pixel keeps every tiled glacier visible.
OUTLINE_WIDTH = ["interpolate", ["linear"], ["zoom"], 0, 1.2, 8, 0.6, 12, 1.0]
# Below z10 the archive holds a glacier too small to draw as a point. A
# glacier at the antimeridian is a MultiPoint where the tile buffer wraps.
POINTS = ["in", ["geometry-type"], ["literal", ["Point", "MultiPoint"]]]
# The archive has a label line per glacier and zoom, with its zoom in
# label_zoom. Past MAXZOOM the tiles of MAXZOOM are overzoomed. A line shows
# from its zoom up to the next zoom, and the line of LABEL_MAXZOOM shows at
# every zoom past it. A renderer that evaluates the filter at a fractional
# zoom then also matches one line per glacier.
LABEL_LINES = [
    "all",
    [">=", ["zoom"], ["get", "label_zoom"]],
    [
        "any",
        ["<", ["zoom"], ["+", ["get", "label_zoom"], 1]],
        [">=", ["get", "label_zoom"], LABEL_MAXZOOM],
    ],
]
DOT_RADIUS = ["interpolate", ["linear"], ["zoom"], 0, 1.5, 6, 2.5]


def _dots(color: Any, layer: str = "glaciers", opacity: float = 0.85) -> dict[str, Any]:
    """Return the circle layer that draws a polygon layer's points."""
    return {
        "id": f"{layer}-dots",
        "type": "circle",
        "source-layer": layer,
        "filter": POINTS,
        "paint": {"circle-color": color, "circle-radius": DOT_RADIUS, "circle-opacity": opacity},
    }


def _polygons(
    layer: str, fill: Any, line: Any, opacity: float, line_opacity: float = 1.0
) -> list[dict[str, Any]]:
    """Return the fill, outline and dot layers of a polygon layer."""
    outline: dict[str, Any] = {"line-color": line, "line-width": OUTLINE_WIDTH}
    if line_opacity < 1:
        outline["line-opacity"] = line_opacity
    return [
        {
            "id": f"{layer}-fill",
            "type": "fill",
            "source-layer": layer,
            "paint": {"fill-color": fill, "fill-opacity": opacity},
        },
        {"id": f"{layer}-outline", "type": "line", "source-layer": layer, "paint": outline},
        _dots(fill, layer, min(0.85, line_opacity)),
    ]


def _region_labels(level: int, minzoom: int, maxzoom: int, size: int) -> dict[str, Any]:
    return {
        "id": f"region-labels-{level}",
        "type": "symbol",
        "source-layer": "region-labels",
        "filter": ["==", ["get", "level"], level],
        "minzoom": minzoom,
        "maxzoom": maxzoom,
        "layout": {
            # A region shows its number above its name.
            "text-field": [
                "concat",
                ["get", "o1region" if level == 1 else "o2region"],
                "\n",
                ["get", "full_name"],
            ],
            "text-font": REGION_FONTS[level],
            "text-size": size,
            "text-transform": "uppercase" if level == 1 else "none",
            "text-letter-spacing": 0.08 if level == 1 else 0,
        },
        "paint": {
            "text-color": REGION_LABEL,
            "text-halo-color": "#ffffff",
            "text-halo-width": 1.2,
        },
    }


LABELS: dict[str, Any] = {
    "id": "glacier-labels",
    "type": "symbol",
    # A name follows the label line of its glacier at the zoom.
    "filter": LABEL_LINES,
    "layout": {
        "text-field": ["get", "display_name"],
        "text-font": LABEL_FONT,
        "text-size": glyphs.LABEL_TEXT_SIZE,
        "text-letter-spacing": glyphs.LABEL_LETTER_SPACING,
        "symbol-placement": "line-center",
        # Larger glaciers win label collisions.
        "symbol-sort-key": ["-", ["get", "area_km2"]],
    },
    "paint": {
        "text-color": LABEL_COLOR,
        "text-halo-color": "#ffffff",
        "text-halo-width": glyphs.LABEL_HALO_WIDTH,
    },
}

# The style layers that draw each archive layer, bottom to top.
LAYER_STYLES: dict[str, list[dict[str, Any]]] = {
    # The archive stores each border once, so a dash pattern stays in step.
    # A first-order border is a long dash, a second-order border a short one,
    # thinner and lighter. A dash is measured in line widths.
    "region-boundaries": [
        {
            "id": "region-boundaries-2",
            "type": "line",
            "filter": ["==", ["get", "level"], 2],
            "minzoom": 3,
            "paint": {
                "line-color": REGION_LINE_2,
                "line-width": 0.8,
                "line-dasharray": [2.5, 2.5],
            },
        },
        {
            "id": "region-boundaries-1",
            "type": "line",
            "filter": ["==", ["get", "level"], 1],
            "paint": {
                "line-color": REGION_LINE,
                "line-width": 1.2,
                "line-dasharray": [5, 2.5],
            },
        },
    ],
    "region-labels": [_region_labels(1, 1, 6, 12), _region_labels(2, 4, 9, 11)],
    "complexes": _polygons("complexes", COMPLEX_FILL, COMPLEX_LINE, 0.5),
    "glaciers": _polygons("glaciers", GLACIER_FILL, GLACIER_LINE, 0.5),
    "centerlines": [
        {
            "id": "centerlines",
            "type": "line",
            "paint": {
                "line-color": CENTERLINE_COLOR,
                # The main centerline of each glacier is drawn wider.
                "line-width": [
                    "interpolate",
                    ["linear"],
                    ["zoom"],
                    8,
                    ["case", ["get", "is_main"], 1.0, 0.5],
                    12,
                    ["case", ["get", "is_main"], 2.0, 1.0],
                ],
            },
        },
    ],
    "intersects": [
        {
            "id": "intersects",
            "type": "line",
            "paint": {"line-color": INTERSECT_COLOR, "line-width": 2.0},
        },
    ],
    "glacier-labels": [LABELS],
}
# The region polygons give only the fill of the regions style.
ARCHIVE_LAYERS = ("regions", *LAYER_STYLES)
GLACIERS_LAYERS = ("region-boundaries", "glaciers", "region-labels", "glacier-labels")
# The region boundaries, drawn under the data of every style, and the region
# names, drawn over it.
BOUNDARIES = [
    {"source-layer": "region-boundaries", **spec} for spec in LAYER_STYLES["region-boundaries"]
]
REGION_NAMES = [
    {"source-layer": "region-labels", **spec} for spec in LAYER_STYLES["region-labels"]
]
# The glaciers under the centerlines or the intersects: the glacier colours,
# faint, so the lines are the subject.
GLACIER_CONTEXT = _polygons("glaciers", GLACIER_FILL, GLACIER_LINE, 0.2, line_opacity=0.35)


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
        description=("Glaciers by median elevation (zmed_m), in 1,000 m classes."),
        column="zmed_m",
        stops=(1000, 2000, 3000, 4000, 5000),
        colors=("#a88bd9", "#8c69c8", "#7050b2", "#573a96", "#3f2875", "#291852"),
    ),
    "surge-evidence": Theme(
        title="Surge evidence",
        description=("Glaciers by evidence for surging (surge_type)."),
        column="surge_type",
        codes={0: "No evidence", 1: "Possible", 2: "Probable", 3: "Observed"},
        colors=(NO_DATA, "#ea8a3a", "#d4471f", "#9c1b12"),
    ),
    "terminus-type": Theme(
        title="Terminus type",
        description=(
            "Glaciers by terminus type (term_type). RGI 7.0 assigns only the "
            "marine-terminating class."
        ),
        column="term_type",
        codes={1: "Marine-terminating", 9: "Not assigned"},
        colors=("#0072b2", NO_DATA),
    ),
    "same-as-rgi6": Theme(
        title="Same as RGI 6.0",
        description=(
            "Glaciers by whether the outline is the same as in RGI 6.0 (is_rgi6), "
            "as in the map of the RGI 7.0 user guide."
        ),
        column="is_rgi6",
        codes={True: "Same as RGI 6.0", False: "New in RGI 7.0"},
        colors=("#0072b2", "#d55e00"),
    ),
}
DEFAULT_STYLE = "glaciers"
# The default style of each collection.
DEFAULT_STYLES = {
    "glaciers": DEFAULT_STYLE,
    "complexes": "complexes",
    "centerlines": "centerlines",
    "intersects": "intersects",
    "regions": "regions",
}
REGION_LEVELS = Theme(
    title="Glacier regions",
    description="",
    column="level",
    codes={1: "First-order region", 2: "Second-order region"},
    colors=("#e69f00", "#0072b2"),
)


def archive_href(version: str = "7.0") -> str:
    """Return the archive's href relative to a collection's ``styles/`` directory.

    Parameters
    ----------
    version
        The RGI version.

    Returns
    -------
    str
        For example ``../../rgi7.0.pmtiles``.
    """
    return f"../../rgi{version}.pmtiles"


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
    return [{"source-layer": name, **spec} for name in names for spec in LAYER_STYLES[name]]


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


def glaciers_style(archive_href: str) -> dict[str, Any]:
    """Return the glaciers style: the glacier outlines and names, with the regions.

    Every other product has its own style.

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
        "Glaciers",
        "Glacier outlines and names.",
        archive_href,
        _layers_of(list(GLACIERS_LAYERS)),
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
        *BOUNDARIES,
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
        _dots(spec.fill_color()),
        *REGION_NAMES,
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
        DEFAULT_STYLE: glaciers_style(archive_href),
        **{theme: thematic_style(theme, archive_href) for theme in THEMES},
    }


def _own_style(name: str, archive_href: str) -> dict[str, Any]:
    """Return the default style of a collection other than the glaciers."""
    labels = {"source-layer": "glacier-labels", **LABELS}
    if name == "complexes":
        return _style(
            "Glacier complexes",
            "Glacier complexes: connected glaciers merged into one outline.",
            archive_href,
            [*BOUNDARIES, *_layers_of(["complexes"]), *REGION_NAMES],
        )
    if name in {"centerlines", "intersects"}:
        what = {
            "centerlines": (
                "Glacier centerlines over the glacier outlines. The main "
                "centerlines are drawn wider and show from z8, the others "
                "from z9. A longer line shows from the first zoom at which "
                "it spans 32 pixels, from z4 on."
            ),
            "intersects": (
                "Glacier intersects over the glacier outlines. An intersect "
                "is a line that divides two adjacent glaciers. The intersects "
                "show from z9. A longer line shows from the first zoom at "
                "which it spans 32 pixels, from z4 on."
            ),
        }[name]
        return _style(
            name.capitalize(),
            what,
            archive_href,
            [*BOUNDARIES, *GLACIER_CONTEXT, *_layers_of([name]), *REGION_NAMES, labels],
        )
    fill = {
        "id": "regions-fill",
        "type": "fill",
        "source-layer": "regions",
        "paint": {"fill-color": REGION_LEVELS.fill_color(), "fill-opacity": 0.15},
    }
    return _style(
        "Glacier regions",
        "First-order and second-order glacier regions, with their names.",
        archive_href,
        [fill, *_layers_of(["region-boundaries", "region-labels"])],
    )


def collection_styles(name: str, archive_href: str) -> dict[str, dict[str, Any]]:
    """Return every style of a collection, the default first.

    Parameters
    ----------
    name
        The collection name, a key of :data:`DEFAULT_STYLES`.
    archive_href
        The archive's href relative to the style files.

    Returns
    -------
    dict[str, dict[str, Any]]
        Styles by file stem. The glaciers have the glaciers style and the
        thematic styles. Every other collection has its own style and the
        glaciers style.
    """
    if name == "glaciers":
        return glacier_styles(archive_href)
    return {name: _own_style(name, archive_href), DEFAULT_STYLE: glaciers_style(archive_href)}
