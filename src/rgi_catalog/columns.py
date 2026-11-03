"""The ``columns`` command: compare ``metadata/columns.yaml`` with RGI's column text.

``columns.yaml`` describes every column. The columns of the RGI files start
from the text of RGI's ``attributes_metadata.json``, and a description can be
reworded there. This command reads RGI's text from the pinned downloads and
lists each column whose entry differs from it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

import yaml

from rgi_catalog.paths import METADATA
from rgi_catalog.pipeline import catalog_metadata
from rgi_catalog.sources import fetch, load_pins
from rgi_catalog.upstream import read_attribute_metadata

if TYPE_CHECKING:
    import argparse
    from pathlib import Path

    from rgi_catalog.upstream import Product

# The products that ship an attributes_metadata.json file.
DESCRIBED_PRODUCTS = ("G", "C", "I", "L")
# RGI's pointer to the user guide. A coded column lists its codes in the
# catalog, so columns.yaml leaves the pointer out.
CATEGORIES_IN_GUIDE = " For a categories description, see user guide."


def differences(
    described: dict[str, Any],
    upstream: dict[str, dict[str, str]],
) -> list[tuple[str, str, str, str]]:
    """Compare the entries of one collection with RGI's metadata of its product.

    Parameters
    ----------
    described
        The entries of the collection in ``columns.yaml``.
    upstream
        RGI's metadata of the product, per column.

    Returns
    -------
    list[tuple[str, str, str, str]]
        Per difference: the column, the field (``description`` or ``unit``),
        RGI's text and the text in ``columns.yaml``. A column that RGI
        describes and ``columns.yaml`` does not has the text ``"(none)"``.
    """
    out = []
    for column, meta in upstream.items():
        entry = described.get(column)
        rgi_description = meta["description"].replace(CATEGORIES_IN_GUIDE, "")
        if entry is None:
            out.append((column, "description", rgi_description, "(none)"))
            continue
        description = " ".join(entry["description"].split())
        if description != " ".join(rgi_description.split()):
            out.append((column, "description", rgi_description, description))
        if (entry.get("unit") or "") != (meta["units"] or ""):
            out.append((column, "unit", meta["units"], entry.get("unit") or ""))
    return out


def _columns(args: argparse.Namespace) -> None:
    versions = cast("dict[str, Any]", catalog_metadata()["versions"])
    spec = versions[args.version]
    pins = load_pins(args.version)
    described = yaml.safe_load((METADATA / "columns.yaml").read_text())
    for name, collection in spec["collections"].items():
        product = collection["product"]
        if product not in DESCRIBED_PRODUCTS:
            continue
        zip_path: Path = fetch(pins[product])
        upstream = read_attribute_metadata(zip_path, cast("Product", product))
        for column, field, rgi, ours in differences(described.get(name, {}), upstream):
            print(f"{name}.{column} {field}")
            print(f"  RGI:          {rgi}")
            print(f"  columns.yaml: {ours}")


def add_parser(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    """Register the ``columns`` command.

    Parameters
    ----------
    subparsers
        The CLI's subparser collection.
    """
    parser = subparsers.add_parser(
        "columns", help="list the column descriptions that differ from RGI's text"
    )
    parser.add_argument("--version", required=True)
    parser.set_defaults(func=_columns)
