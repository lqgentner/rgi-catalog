"""The build record: what the build wrote, measured from the staged files.

The record is committed. It holds every number the catalog states about the
data, so ``render`` needs neither the staged files nor the downloads.
"""

from __future__ import annotations

from datetime import UTC, datetime
import json
from typing import TYPE_CHECKING, Any, cast

from pmtiles.reader import MmapSource, Reader
import pyarrow.parquet as pq

from rgi_catalog.paths import METADATA, STAGING, version_dir
from rgi_catalog.pipeline import PRODUCT_SOURCES, catalog_metadata, output_path
from rgi_catalog.sources import fetch, load_pins, sha256_file
from rgi_catalog.tiles import archive_path
from rgi_catalog.upstream import read_attribute_metadata

if TYPE_CHECKING:
    from pathlib import Path

    from rgi_catalog.upstream import Product

# The temporal extent of a collection comes from this column, if it has it.
DATE_COLUMN = "src_date"
# The products that ship an attributes_metadata.json file.
DESCRIBED_PRODUCTS = ("G", "C", "I", "L")


def checksum(path: Path) -> str:
    """Return a file's ``file:checksum``: a sha256 multihash in hex.

    Parameters
    ----------
    path
        The file.

    Returns
    -------
    str
        ``"1220"`` followed by the hex sha256.
    """
    return "1220" + sha256_file(path)


def _file_entry(path: Path) -> dict[str, Any]:
    return {"size": path.stat().st_size, "file:checksum": checksum(path)}


def _iso(value: datetime) -> str:
    return value.replace(tzinfo=UTC).isoformat().replace("+00:00", "Z")


def _collection(path: Path) -> dict[str, Any]:
    pf = pq.ParquetFile(path)
    meta = pf.metadata
    schema = pf.schema_arrow
    geo = json.loads((schema.metadata or {})[b"geo"])
    primary = geo["primary_column"]
    entry: dict[str, Any] = {
        "href": path.name,
        "row_count": meta.num_rows,
        "bbox": geo["columns"][primary]["bbox"],
        "geoparquet_version": geo["version"],
        "row_groups": meta.num_row_groups,
        "row_group_size": max(meta.row_group(i).num_rows for i in range(meta.num_row_groups)),
        "columns": [{"name": f.name, "type": str(f.type)} for f in schema],
    }
    if DATE_COLUMN in schema.names:
        dates = pq.read_table(path, columns=[DATE_COLUMN]).column(0).to_pandas()
        entry["temporal"] = [_iso(dates.min()), _iso(dates.max())]
    return entry


def _archive(path: Path) -> dict[str, Any]:
    with path.open("rb") as f:
        reader = Reader(MmapSource(f))
        header = reader.header()
        meta = reader.metadata()
    return {
        "layers": [layer["id"] for layer in meta["vector_layers"]],
        "minzoom": header["min_zoom"],
        "maxzoom": header["max_zoom"],
    }


def build_record(version: str, *, staging: Path = STAGING) -> dict[str, Any]:
    """Measure the staged files of a version.

    Parameters
    ----------
    version
        The RGI version.
    staging
        The staging root.

    Returns
    -------
    dict[str, Any]
        Sizes, checksums, extents, row counts and schemas of the staged files,
        the archive's layers, the upstream pins, and RGI's column metadata of
        each product used.
    """
    meta = catalog_metadata()
    versions = cast("dict[str, Any]", meta["versions"])
    spec = versions[version]
    pins = load_pins(version)
    vdir = staging / version_dir(version)
    files: dict[str, Any] = {}
    collections: dict[str, Any] = {}
    products: set[str] = set()
    for name, collection in spec["collections"].items():
        path = output_path(staging, version, name)
        files[path.relative_to(vdir).as_posix()] = _file_entry(path)
        collections[name] = _collection(path)
        products.update((collection["product"], *PRODUCT_SOURCES[name]))
    archive = archive_path(staging, version)
    files[archive.relative_to(vdir).as_posix()] = _file_entry(archive)
    return {
        "version": version,
        "mirror_revision": spec["mirror_revision"],
        "updated": _iso(datetime.now(UTC).replace(microsecond=0, tzinfo=None)),
        "sources": {k: {"filename": p.filename, "sha256": p.sha256} for k, p in pins.items()},
        "files": files,
        "collections": collections,
        "archive": {"href": archive.relative_to(vdir).as_posix(), **_archive(archive)},
        "attributes_metadata": {
            product: read_attribute_metadata(fetch(pins[product]), cast("Product", product))
            for product in sorted(products & set(DESCRIBED_PRODUCTS))
        },
    }


def merge_updated(old: dict[str, Any] | None, new: dict[str, Any]) -> dict[str, Any]:
    """Keep the old ``updated`` time when nothing else in the record changed.

    Parameters
    ----------
    old
        The committed record, or ``None``.
    new
        The fresh record.

    Returns
    -------
    dict[str, Any]
        ``new``, with ``old``'s ``updated`` if the rest is equal.
    """
    if old is not None:
        rest_old = {k: v for k, v in old.items() if k != "updated"}
        rest_new = {k: v for k, v in new.items() if k != "updated"}
        if rest_old == rest_new:
            return {**new, "updated": old["updated"]}
    return new


def record_path(version: str) -> Path:
    """Return the committed record of a version.

    Parameters
    ----------
    version
        The RGI version.

    Returns
    -------
    Path
        ``metadata/builds/v{version}.json``.
    """
    return METADATA / "builds" / f"{version_dir(version)}.json"


def write_build_record(version: str, *, staging: Path = STAGING) -> Path:
    """Measure the staged files and write the record, if it changed.

    Parameters
    ----------
    version
        The RGI version.
    staging
        The staging root.

    Returns
    -------
    Path
        The record file.
    """
    path = record_path(version)
    old = json.loads(path.read_text()) if path.exists() else None
    new = merge_updated(old, build_record(version, staging=staging))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(new, indent=2, sort_keys=True, ensure_ascii=False) + "\n")
    return path
