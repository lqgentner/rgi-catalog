"""Tile the Natural Earth land polygons for the world-view thumbnails.

Usage::

    pixi run python scripts/naturalearth_land.py

Writes ``.cache/basemap/ne_50m_land.pmtiles`` with one layer, ``land``. The
archive is a thumbnail input and is never published. Natural Earth is in the
public domain, and its terms of use state: "Crediting the authors is
unnecessary."
"""

from __future__ import annotations

import geopandas as gpd

from rgi_catalog.paths import CACHE
from rgi_catalog.sources import SourcePin, fetch
from rgi_catalog.tiles import _run

LAND = SourcePin(
    key="ne_50m_land",
    url="https://naciscdn.org/naturalearth/50m/physical/ne_50m_land.zip",
    sha256="0b8e670cf80dce9cbebe2a193bc44ba5602758c22e1fa603980553646d7ff162",
    size=457183,
    filename="ne_50m_land.zip",
)
OUT = CACHE / "basemap" / "ne_50m_land.pmtiles"
# The world views render at about z2. A few zooms more cover a wider frame.
MAXZOOM = 6


def main() -> None:
    """Download, verify and tile the land polygons."""
    archive = fetch(LAND)
    land = gpd.read_file(f"/vsizip/{archive}/ne_50m_land.shp")[["geometry"]]
    OUT.parent.mkdir(parents=True, exist_ok=True)
    source = OUT.with_suffix(".parquet")
    land.to_parquet(source, index=False)
    _run(
        "tiles", source, OUT, "--layer-name", "land", "--min-zoom", "0", "--max-zoom", str(MAXZOOM)
    )
    print(f"ok  {OUT}")


if __name__ == "__main__":
    main()
