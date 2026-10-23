"""The ``tiles`` step: build the web-map archive from the staged GeoParquet files."""

from __future__ import annotations

from dataclasses import dataclass
import gzip
import json
import math
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile
from typing import TYPE_CHECKING, Any

import geopandas as gpd
from pmtiles.tile import Compression, deserialize_header, serialize_header
import pyarrow as pa
import pyarrow.parquet as pq

from rgi_catalog.paths import CACHE, STAGING, version_dir
from rgi_catalog.pipeline import output_path
from rgi_catalog.sources import SourcePin, fetch

if TYPE_CHECKING:
    import argparse
    from collections.abc import Sequence

TYLERTOO = SourcePin(
    key="tylertoo",
    url=(
        "https://github.com/geoparquet-io/tylertoo/releases/download/v0.8.0/"
        "tylertoo-0.8.0-x86_64-unknown-linux-musl.tar.gz"
    ),
    sha256="d294ec4b1447d33d0201d316035daaf09bf1ba8eeccf5e5eb8a2cbfc592a41a7",
    size=12_780_986,
    filename="tylertoo-0.8.0-x86_64-unknown-linux-musl.tar.gz",
)
TYLERTOO_MEMBER = "tylertoo-0.8.0-x86_64-unknown-linux-musl/tylertoo"

ARCHIVE_NAME = "Randolph Glacier Inventory 7.0 Mirror"
ARCHIVE_ATTRIBUTION = "RGI 7.0 Consortium (2023)"
ARCHIVE_DESCRIPTION = (
    "Glacier outlines and names from the Randolph Glacier Inventory 7.0. "
    "Unofficial mirror, not endorsed by the RGI Consortium."
)

# Every layer stops at this zoom, because a client overzooms one source as a
# whole. A z12 tile resolves about 2.4 m at the equator, finer than the
# imagery the outlines were drawn from.
MAXZOOM = 12
GLACIERS_MINZOOM = 0
# Up to this zoom each glacier is a point, one per grid cell, because a
# glacier is smaller than a pixel there. Up to the zoom before the complete
# band, a polygon too small for the zoom is a placeholder square.
GLACIERS_POINT_MAXZOOM = 6
# From this zoom on, the glaciers layer holds every glacier.
GLACIERS_COMPLETE_ZOOM = 10
LABEL_MINZOOM = 7
# A glacier of this area gets its label at GLACIERS_COMPLETE_ZOOM + 1.
LABEL_REFERENCE_KM2 = 1.0

# Arrow types a vector tile cannot store as a property.
_NESTED = (pa.types.is_list, pa.types.is_large_list, pa.types.is_struct, pa.types.is_map)


class TileDropError(Exception):
    """The tiler dropped features in a band that must keep all of them."""


@dataclass(frozen=True)
class LayerSpec:
    """One zoom band of one vector layer.

    Several specs with the same ``name`` and disjoint zoom ranges build one
    layer with different settings per band.
    """

    name: str
    source: Path
    minzoom: int
    maxzoom: int
    extra_args: tuple[str, ...] = ()
    # The band must keep every feature. The build fails if the tiler drops one.
    complete: bool = False
    # The column of a feature's entry zoom (``--entry-zoom``). A complete band
    # must keep a feature from that zoom on.
    entry_zoom_column: str | None = None


def tylertoo_binary(cache_dir: Path = CACHE) -> Path:
    """Return the pinned tylertoo executable, downloading it if needed.

    The PyPI wheel has only the Python API, which cannot build a multi-layer
    archive. The release binary has the full command line.

    Parameters
    ----------
    cache_dir
        The directory that holds verified downloads.

    Returns
    -------
    Path
        The executable.
    """
    exe = cache_dir / "bin" / "tylertoo-0.8.0"
    if exe.exists():
        return exe
    archive = fetch(TYLERTOO, cache_dir)
    exe.parent.mkdir(parents=True, exist_ok=True)
    part = exe.with_suffix(".part")
    with tarfile.open(archive) as tar:
        member = tar.extractfile(TYLERTOO_MEMBER)
        if member is None:
            msg = f"{archive.name} has no {TYLERTOO_MEMBER}"
            raise FileNotFoundError(msg)
        with member, part.open("wb") as out:
            shutil.copyfileobj(member, out)
    part.chmod(0o755)
    part.rename(exe)
    return exe


def _run(*args: str | Path) -> None:
    """Run tylertoo and raise with its output if it fails."""
    cmd = [str(tylertoo_binary()), *(str(a) for a in args)]
    done = subprocess.run(cmd, capture_output=True, text=True, check=False)  # noqa: S603
    if done.returncode != 0:
        msg = f"{' '.join(cmd)} failed:\n{done.stderr[-4000:]}"
        raise RuntimeError(msg)


def label_minzoom(area_km2: float) -> int:
    """Return the first zoom at which a glacier's name is drawn.

    Each zoom step quadruples a glacier's area on screen, so the entry zoom
    falls by one for every factor of 4 in area. A glacier of 1 km² gets its
    label at z11.

    Parameters
    ----------
    area_km2
        The glacier's area.

    Returns
    -------
    int
        A zoom from :data:`LABEL_MINZOOM` to :data:`MAXZOOM`.
    """
    if area_km2 <= 0:
        return MAXZOOM
    zoom = GLACIERS_COMPLETE_ZOOM + 1 - math.floor(math.log2(area_km2 / LABEL_REFERENCE_KM2) / 2)
    return min(MAXZOOM, max(LABEL_MINZOOM, zoom))


def tile_properties(parquet: Path) -> list[str]:
    """Return the columns of a file that a vector tile can store.

    List, struct and map columns (the hypsometry, the RGI 6 links,
    ``glacier_ids``, ``bbox``) and the geometry are left out.

    Parameters
    ----------
    parquet
        A GeoParquet file.

    Returns
    -------
    list[str]
        The scalar columns, in file order.
    """
    schema = pq.read_schema(parquet)
    geo = json.loads((schema.metadata or {}).get(b"geo", b"{}"))
    geometry = geo.get("primary_column", "geometry")
    return [
        field.name
        for field in schema
        if field.name != geometry and not any(is_nested(field.type) for is_nested in _NESTED)
    ]


def write_labels(glaciers_parquet: Path, out: Path) -> Path:
    """Write the label points: one per named glacier, at RGI's own point.

    Parameters
    ----------
    glaciers_parquet
        The glaciers GeoParquet file.
    out
        The label GeoParquet file to write.

    Returns
    -------
    Path
        ``out``.
    """
    table = pq.read_table(
        glaciers_parquet,
        columns=["rgi_id", "display_name", "area_km2", "cenlon", "cenlat"],
    ).to_pandas()
    named = table.loc[table["display_name"].notna()]
    labels = gpd.GeoDataFrame(
        {
            "rgi_id": named["rgi_id"].to_numpy(),
            "display_name": named["display_name"].to_numpy(),
            "area_km2": named["area_km2"].to_numpy(),
            "label_minzoom": [label_minzoom(a) for a in named["area_km2"]],
        },
        geometry=gpd.points_from_xy(named["cenlon"], named["cenlat"]),
        crs="EPSG:4326",
    ).astype({"label_minzoom": "uint8"})
    out.parent.mkdir(parents=True, exist_ok=True)
    labels.to_parquet(out, index=False)
    return out


def glacier_layers(glaciers: Path, labels: Path) -> list[LayerSpec]:
    """Return the bands of the ``glaciers`` and ``glacier-labels`` layers.

    Parameters
    ----------
    glaciers
        The glaciers GeoParquet file.
    labels
        The label file from :func:`write_labels`.

    Returns
    -------
    list[LayerSpec]
        Up to :data:`GLACIERS_POINT_MAXZOOM` glaciers are points, one per
        grid cell. Below :data:`GLACIERS_COMPLETE_ZOOM` small glaciers are
        squares, one per grid cell. From it on every glacier is kept. Each label enters at its
        ``label_minzoom`` and is never thinned.
    """
    entry = ",".join(f"{z}={z}" for z in range(LABEL_MINZOOM, MAXZOOM + 1))
    return [
        LayerSpec(
            "glaciers",
            glaciers,
            GLACIERS_MINZOOM,
            GLACIERS_COMPLETE_ZOOM - 1,
            # The finest zoom of a band keeps the source geometry, so the
            # squares stop one zoom before it. The largest glacier wins each
            # grid cell. Without the density budget every cell keeps one.
            (
                "--representation",
                (
                    f"{GLACIERS_MINZOOM}-{GLACIERS_POINT_MAXZOOM}:point,"
                    f"{GLACIERS_POINT_MAXZOOM + 1}-{GLACIERS_COMPLETE_ZOOM - 2}:square"
                ),
                "--no-density-drop",
                "--sort-key",
                "area_km2",
            ),
        ),
        LayerSpec(
            "glaciers",
            glaciers,
            GLACIERS_COMPLETE_ZOOM,
            MAXZOOM,
            # Density drop, cell thinning and the visibility gate each drop
            # glaciers. Simplification at the default 1 GSD collapses two
            # slivers of 0.01 km² at z10. Half a GSD keeps them.
            (
                "--no-density-drop",
                "--polygon-thinning",
                "0",
                "--polygon-visibility",
                "0",
                "--simplify-factor",
                "0.5",
            ),
            complete=True,
        ),
        LayerSpec(
            "glacier-labels",
            labels,
            LABEL_MINZOOM,
            MAXZOOM,
            ("--entry-zoom", f"label_minzoom:{entry}", "--no-density-drop"),
            complete=True,
            entry_zoom_column="label_minzoom",
        ),
    ]


def build_archive(
    layers: Sequence[LayerSpec],
    out: Path,
    *,
    name: str,
    attribution: str,
    description: str,
) -> Path:
    """Build one PMTiles archive with one vector layer per layer name.

    Each band is tiled on its own, then ``tylertoo pyramid`` joins the bands.
    Bands of different layers may share zooms.

    Parameters
    ----------
    layers
        The bands.
    out
        The archive to write. It is replaced only once the new one is complete.
    name, attribution, description
        The archive's metadata.

    Returns
    -------
    Path
        ``out``.

    Raises
    ------
    TileDropError
        If a band marked ``complete`` dropped a feature.
    """
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=out.parent, prefix=f".{out.stem}-") as tmp:
        work = Path(tmp)
        bands: list[str] = []
        for i, layer in enumerate(layers):
            band = work / f"band-{i}.pmtiles"
            report = work / f"band-{i}.json"
            props = [a for p in tile_properties(layer.source) for a in ("--include-property", p)]
            _run(
                "tiles",
                layer.source,
                band,
                "--layer-name",
                layer.name,
                "--min-zoom",
                str(layer.minzoom),
                "--max-zoom",
                str(layer.maxzoom),
                "--no-simple-clip-fastpath",
                "--report",
                report,
                *props,
                *layer.extra_args,
            )
            if layer.complete:
                _check_complete(layer, json.loads(report.read_text())["export"])
            bands.extend(["--band", f"{layer.minzoom}-{layer.maxzoom}:{band}:{layer.name}"])
        joined = work / "archive.pmtiles"
        _run("pyramid", "--work-dir", work, *bands, joined)
        # The bands are as large as the archive. Free the disk before the
        # metadata pass writes its copy.
        for band in work.glob("band-*.pmtiles"):
            band.unlink()
        set_metadata(
            joined, {"name": name, "attribution": attribution, "description": description}
        )
        joined.replace(out)
    return out


def _check_complete(layer: LayerSpec, export: dict[str, Any]) -> None:
    """Refuse a band that lost a feature it must keep, at any zoom."""
    where = f"layer {layer.name} z{layer.minzoom}-{layer.maxzoom}"
    dropped = export["oversized_tiles"], export["encode_dropped_features"]
    if any(dropped):
        msg = f"{where}: {dropped[0]} oversized tiles and {dropped[1]} features dropped"
        raise TileDropError(msg)
    if layer.entry_zoom_column is None:
        n = pq.ParquetFile(layer.source).metadata.num_rows
        expected = dict.fromkeys(range(layer.minzoom, layer.maxzoom + 1), n)
    else:
        entry = pq.read_table(layer.source, columns=[layer.entry_zoom_column]).column(0)
        zooms = entry.to_numpy()
        expected = {z: int((zooms <= z).sum()) for z in range(layer.minzoom, layer.maxzoom + 1)}
    kept = {z["zoom"]: z["level_feature_count"] for z in export["zooms"]}
    for zoom, n in expected.items():
        if kept.get(zoom, 0) != n:
            msg = f"{where}: z{zoom} keeps {kept.get(zoom, 0)} of {n} features"
            raise TileDropError(msg)


def set_metadata(archive: Path, updates: dict[str, str]) -> None:
    """Merge keys into a PMTiles archive's metadata and leave the tiles as they are.

    The header, directories and tile data are copied byte for byte. Only the
    metadata block and the offsets that follow it change.

    Parameters
    ----------
    archive
        The archive, rewritten in place.
    updates
        The metadata keys to set.
    """
    with archive.open("rb") as src:
        header = deserialize_header(src.read(127))
        sections: dict[str, bytes] = {}
        for key, offset, length in (
            ("root", header["root_offset"], header["root_length"]),
            ("metadata", header["metadata_offset"], header["metadata_length"]),
            ("leaf_directory", header["leaf_directory_offset"], header["leaf_directory_length"]),
        ):
            src.seek(offset)
            sections[key] = src.read(length)
        meta_bytes = sections["metadata"]
        gzipped = header["internal_compression"] == Compression.GZIP
        meta = json.loads(gzip.decompress(meta_bytes) if gzipped else meta_bytes)
        meta.update(updates)
        new_meta = json.dumps(meta, sort_keys=True, ensure_ascii=False).encode()
        if gzipped:
            new_meta = gzip.compress(new_meta, mtime=0)
        header["root_offset"] = 127
        header["metadata_offset"] = 127 + len(sections["root"])
        header["metadata_length"] = len(new_meta)
        header["leaf_directory_offset"] = header["metadata_offset"] + len(new_meta)
        tile_data_offset = header["tile_data_offset"]
        header["tile_data_offset"] = header["leaf_directory_offset"] + len(
            sections["leaf_directory"]
        )
        tmp = archive.with_suffix(".tmp")
        with tmp.open("wb") as dst:
            dst.write(serialize_header(header))
            dst.write(sections["root"])
            dst.write(new_meta)
            dst.write(sections["leaf_directory"])
            src.seek(tile_data_offset)
            _copy_exact(src, dst, header["tile_data_length"])
    tmp.replace(archive)


def _copy_exact(src: Any, dst: Any, length: int) -> None:
    while length:
        chunk = src.read(min(length, 1 << 20))
        if not chunk:
            msg = "archive ends inside its tile data"
            raise EOFError(msg)
        dst.write(chunk)
        length -= len(chunk)


def decode(archive: Path, out: Path, *, layer: str | None = None) -> Path:
    """Decode an archive's tiles to GeoParquet, one row per feature per tile.

    Parameters
    ----------
    archive
        The PMTiles archive.
    out
        The GeoParquet file to write.
    layer
        Decode only this layer.

    Returns
    -------
    Path
        ``out``.
    """
    _run("decode", "--force", archive, out, *(("--layer", layer) if layer else ()))
    return out


def archive_path(staging: Path, version: str) -> Path:
    """Return the staged archive. Every collection of the version draws from it.

    Parameters
    ----------
    staging
        The staging root.
    version
        The RGI version.

    Returns
    -------
    Path
        ``staging/v{version}/rgi{version}.pmtiles``.
    """
    return staging / version_dir(version) / f"rgi{version}.pmtiles"


def build_tiles(version: str, *, staging: Path = STAGING) -> Path:
    """Build the web-map archive of a version from its staged files.

    Parameters
    ----------
    version
        The RGI version.
    staging
        The staging root.

    Returns
    -------
    Path
        The archive.
    """
    glaciers = output_path(staging, version, "glaciers")
    labels = write_labels(glaciers, staging / version_dir(version) / ".tiles" / "labels.parquet")
    return build_archive(
        glacier_layers(glaciers, labels),
        archive_path(staging, version),
        name=ARCHIVE_NAME,
        attribution=ARCHIVE_ATTRIBUTION,
        description=ARCHIVE_DESCRIPTION,
    )


def _tiles(args: argparse.Namespace) -> None:
    out = build_tiles(args.version)
    print(f"ok  {out}: {out.stat().st_size / 1e6:.1f} MB")


def add_parser(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    """Register the ``tiles`` command.

    Parameters
    ----------
    subparsers
        The CLI's subparser collection.
    """
    parser = subparsers.add_parser("tiles", help="build the web-map archive")
    parser.add_argument("--version", required=True)
    parser.set_defaults(func=_tiles)
