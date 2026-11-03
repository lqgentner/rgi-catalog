"""Write the styles that render one thumbnail with chiitiler.

Usage::

    pixi run python scripts/thumbnail_style.py STYLE ARCHIVE OUT_DIR [--land LAND]

Reads a published style and writes three styles to ``OUT_DIR``:

- ``render-style.json``: the thumbnail. The style's layers over a white
  background, and over the Natural Earth land when ``--land`` names its
  archive (``scripts/naturalearth_land.py``).
- ``probe-style.json``: the style's layers over white, for the blank probe.
- ``blank-style.json``: the white background alone.

Every source points at the local archive and declares its zoom range, so
MapLibre overzooms the deepest stored tile. Symbol layers are left out,
because chiitiler fetches no glyphs.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

LAND_COLOR = "#e3e5e8"
WHITE = {"id": "background", "type": "background", "paint": {"background-color": "#ffffff"}}


def _source(archive: Path) -> dict[str, Any]:
    header = archive.read_bytes()[:127]
    return {
        "type": "vector",
        "tiles": [f"pmtiles://{archive.resolve()}/{{z}}/{{x}}/{{y}}"],
        "minzoom": header[100],
        "maxzoom": header[101],
    }


def main() -> None:
    """Write the render, probe and blank styles."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("style", type=Path)
    parser.add_argument("archive", type=Path)
    parser.add_argument("out_dir", type=Path)
    parser.add_argument("--land", type=Path)
    args = parser.parse_args()

    style = json.loads(args.style.read_text())
    layers = [layer for layer in style["layers"] if layer["type"] != "symbol"]
    sources = {key: _source(args.archive) for key in style["sources"]}
    base = [WHITE]
    render_sources = dict(sources)
    if args.land:
        render_sources["land"] = _source(args.land)
        base.append(
            {
                "id": "land",
                "type": "fill",
                "source": "land",
                "source-layer": "land",
                "paint": {"fill-color": LAND_COLOR},
            }
        )
    styles = {
        "render": {**style, "sources": render_sources, "layers": [*base, *layers]},
        "probe": {**style, "sources": sources, "layers": [WHITE, *layers]},
        "blank": {"version": 8, "sources": {}, "layers": [WHITE]},
    }
    args.out_dir.mkdir(parents=True, exist_ok=True)
    for name, doc in styles.items():
        (args.out_dir / f"{name}-style.json").write_text(json.dumps(doc))


if __name__ == "__main__":
    main()
