"""The ``convert`` step: build the staged GeoParquet files from the pinned sources."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
from typing import TYPE_CHECKING, cast

import yaml

from rgi_catalog.assemble import (
    centerlines,
    complexes,
    glaciers,
    intersects,
    load_glacier_sources,
    regions,
)
from rgi_catalog.geoparquet import write_geoparquet
from rgi_catalog.paths import METADATA, STAGING, version_dir
from rgi_catalog.sources import fetch, load_pins

if TYPE_CHECKING:
    import argparse
    from collections.abc import Callable, Sequence
    from pathlib import Path

    import geopandas as gpd

    from rgi_catalog.fixes import FixReport

# The pinned inputs each product reads.
PRODUCT_SOURCES: dict[str, tuple[str, ...]] = {
    "glaciers": ("G", "C", "rgi6_links"),
    "complexes": ("C",),
    "centerlines": ("L",),
    "intersects": ("I",),
    "regions": ("regions",),
}


@dataclass
class ConvertResult:
    """What ``convert`` wrote."""

    paths: dict[str, Path] = field(default_factory=dict)
    row_counts: dict[str, int] = field(default_factory=dict)
    fixes: FixReport = field(default_factory=list)


def source_files(version: str) -> dict[str, tuple[Path, str]]:
    """Fetch every pinned input of a version.

    Parameters
    ----------
    version
        The RGI version.

    Returns
    -------
    dict[str, tuple[Path, str]]
        The verified local file and its sha256, by pin key.
    """
    return {key: (fetch(pin), pin.sha256) for key, pin in load_pins(version).items()}


def catalog_metadata() -> dict[str, object]:
    """Read ``metadata/catalog.yaml``.

    Returns
    -------
    dict[str, object]
        The parsed file.
    """
    return yaml.safe_load((METADATA / "catalog.yaml").read_text())


def _build_glaciers(files: dict[str, tuple[Path, str]]) -> tuple[gpd.GeoDataFrame, FixReport]:
    return glaciers(
        load_glacier_sources(files["G"][0], files["C"][0], files["rgi6_links"][0]),
    )


BUILDERS: dict[
    str, Callable[[dict[str, tuple[Path, str]]], tuple[gpd.GeoDataFrame, FixReport]]
] = {
    "glaciers": _build_glaciers,
    "complexes": lambda files: complexes(files["C"][0]),
    "centerlines": lambda files: centerlines(files["L"][0]),
    "intersects": lambda files: intersects(files["I"][0]),
    "regions": lambda files: regions(files["regions"][0]),
}


def output_path(staging: Path, version: str, product: str) -> Path:
    """Return the staged file of a product, laid out like ``catalog/``.

    Parameters
    ----------
    staging
        The staging root.
    version
        The RGI version.
    product
        The collection name.

    Returns
    -------
    Path
        ``staging/v{version}/{product}/rgi{version}-{product}.parquet``.
    """
    return staging / version_dir(version) / product / f"rgi{version}-{product}.parquet"


def convert(
    version: str,
    products: Sequence[str],
    *,
    staging: Path = STAGING,
) -> ConvertResult:
    """Build the GeoParquet file of each product and the fix report.

    Parameters
    ----------
    version
        The RGI version.
    products
        Collection names, a subset of :data:`BUILDERS`.
    staging
        The staging root.

    Returns
    -------
    ConvertResult
        The written files, their row counts and the fixes applied.

    Raises
    ------
    ValueError
        If a product is unknown.
    """
    if unknown := [p for p in products if p not in BUILDERS]:
        msg = f"unknown products {unknown}; choose from {sorted(BUILDERS)}"
        raise ValueError(msg)
    files = source_files(version)
    meta = catalog_metadata()
    versions = cast("dict[str, dict[str, str]]", meta["versions"])
    kv_base = {
        "rgi:version": version,
        "rgi:mirror_revision": versions[version]["mirror_revision"],
        "rgi:citation": " ".join(str(meta["citation"]).split()),
        "rgi:catalog": f"{meta['public_base']}/catalog.json",
    }
    result = ConvertResult()
    for product in products:
        gdf, fixes = BUILDERS[product](files)
        used = {files[k][0].name: files[k][1] for k in PRODUCT_SOURCES[product]}
        out = output_path(staging, version, product)
        kv = {**kv_base, "rgi:sources": json.dumps(used, sort_keys=True)}
        write_geoparquet(gdf, out, kv=kv)
        result.paths[product] = out
        result.row_counts[product] = len(gdf)
        result.fixes.extend(fixes)
    reports = staging / version_dir(version) / ".reports"
    reports.mkdir(parents=True, exist_ok=True)
    (reports / "fixes.json").write_text(
        json.dumps([asdict(f) for f in result.fixes], indent=2, ensure_ascii=False) + "\n",
    )
    return result


def _convert(args: argparse.Namespace) -> None:
    products = args.products.split(",") if args.products else list(BUILDERS)
    result = convert(args.version, products)
    for product, path in result.paths.items():
        size = path.stat().st_size / 1e6
        print(f"ok  {product}: {result.row_counts[product]:,} rows, {size:.1f} MB  {path}")
    for fix in result.fixes:
        print(f"fix {fix.product} {fix.fix} {fix.column}: {fix.count}")


def add_parser(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    """Register the ``convert`` command.

    Parameters
    ----------
    subparsers
        The CLI's subparser collection.
    """
    parser = subparsers.add_parser("convert", help="build the staged GeoParquet files")
    parser.add_argument("--version", required=True)
    parser.add_argument("--products", help="comma-separated; default: all")
    parser.set_defaults(func=_convert)
