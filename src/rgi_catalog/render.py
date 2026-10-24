"""The ``render`` step: write ``catalog/`` from ``metadata/``.

Every published document comes from tracked files: ``metadata/catalog.yaml``,
``columns.yaml``, ``codes.yaml``, the build records in ``metadata/builds/`` and
the templates in ``metadata/templates/``. The render is deterministic, so a
test can compare ``catalog/`` with a fresh render.
"""

from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING, Any

import jinja2
import yaml

from rgi_catalog import styles
from rgi_catalog.paths import CATALOG, METADATA, STAGING, version_dir
from rgi_catalog.pipeline import PRODUCT_SOURCES
from rgi_catalog.record import record_path, write_build_record
from rgi_catalog.sources import load_pins
from rgi_catalog.tiles import GLACIERS_COMPLETE_ZOOM, OVERVIEW_COLUMNS, SHAPE_MIN_PX

if TYPE_CHECKING:
    import argparse
    from pathlib import Path

STAC_VERSION = "1.1.0"
PORTOLAN = "https://schemas.portolan-sdi.org/portolan/v0.2.0/schema.json"
COLLECTION_EXTENSIONS = [
    PORTOLAN,
    "https://stac-extensions.github.io/table/v1.2.0/schema.json",
    "https://stac-extensions.github.io/version/v1.2.0/schema.json",
    "https://stac-extensions.github.io/scientific/v1.0.0/schema.json",
    "https://stac-extensions.github.io/file/v2.1.0/schema.json",
    "https://stac-extensions.github.io/web-map-links/v1.3.0/schema.json",
    "https://stac-extensions.github.io/alternate-assets/v1.2.0/schema.json",
    "https://stac-extensions.github.io/classification/v2.0.0/schema.json",
]
PARQUET = "application/vnd.apache.parquet"
PMTILES = "application/vnd.pmtiles"
STYLE = "application/vnd.mapbox.style+json"
JSON = "application/json"
HTML = "text/html"
MARKDOWN = "text/markdown"
WEBP = "image/webp"
TEMPLATES = METADATA / "templates"
THUMBNAILS = METADATA / "thumbnails"
THUMBNAIL = "thumbnail.webp"
# The products NSIDC distributes as global zips, by pin key.
NSIDC_PRODUCTS = {
    "G": "glacier",
    "C": "glacier complex",
    "I": "glacier intersects",
    "L": "glacier centerlines",
}


def _load(name: str) -> Any:
    return yaml.safe_load((METADATA / name).read_text())


def _dump(doc: dict[str, Any]) -> str:
    return json.dumps(doc, indent=2, ensure_ascii=False) + "\n"


def _file_fields(data: bytes) -> dict[str, Any]:
    return {"file:size": len(data), "file:checksum": "1220" + hashlib.sha256(data).hexdigest()}


def version_id(meta: dict[str, Any], version: str) -> str:
    """Return the id of a version catalog, such as ``rgi-v7-0``.

    Ids keep to lowercase letters, digits and hyphens (PTL-COL-003).

    Parameters
    ----------
    meta
        The parsed ``catalog.yaml``.
    version
        The RGI version.

    Returns
    -------
    str
        The id.
    """
    return f"{meta['id']}-v{version.replace('.', '-')}"


def collection_styles(name: str, version: str) -> dict[str, str]:
    """Return the style documents of a collection, as rendered JSON text.

    Parameters
    ----------
    name
        The collection name.
    version
        The RGI version.

    Returns
    -------
    dict[str, str]
        The JSON text by style key, the default first.
    """
    return {
        key: _dump(style)
        for key, style in styles.collection_styles(name, styles.archive_href(version)).items()
    }


def _plain(citation: str) -> str:
    """Return a Markdown citation as plain text, without the italics."""
    return citation.replace("*", "")


def _slug(label: str) -> str:
    return "".join(c if c.isalnum() else "-" for c in label.lower()).strip("-")


class Context:
    """The tracked metadata, loaded once per render."""

    def __init__(self) -> None:
        self.meta: dict[str, Any] = _load("catalog.yaml")
        self.columns: dict[str, Any] = _load("columns.yaml")
        self.codes: dict[str, Any] = _load("codes.yaml")
        self.records = {v: json.loads(record_path(v).read_text()) for v in self.meta["versions"]}
        env = jinja2.Environment(
            loader=jinja2.FileSystemLoader(TEMPLATES),
            keep_trailing_newline=True,
            trim_blocks=True,
            lstrip_blocks=True,
            undefined=jinja2.StrictUndefined,
            autoescape=False,  # noqa: S701 - the templates write Markdown, not HTML
        )
        self.env = env
        citation = " ".join(self.meta["citation"].split())
        self.citation = citation
        # The notice that follows the text of every page: the disclaimer, then
        # the citation as a Markdown block quote.
        self.disclaimer = f"{' '.join(self.meta['disclaimer'].split())}\n\n> {citation}"

    def public(self, path: str) -> str:
        """Return the public URL of a path under the catalog root."""
        return f"{self.meta['public_base']}/{path}"

    def browser(self, path: str) -> str:
        """Return the data browser URL of a published JSON document."""
        return self.meta["browser"] + self.public(path).split("://", 1)[1]

    def describe(self, text: str) -> str:
        """Return a STAC description: the text, then the disclaimer."""
        return f"{' '.join(text.split())}\n\n{self.disclaimer}"

    def thumbnail(self, doc_dir: str) -> dict[str, Any]:
        """Return the thumbnail asset of the document in a catalog directory.

        The image is ``metadata/thumbnails/<doc_dir>/thumbnail.webp``. The
        render copies it next to the document.
        """
        data = (THUMBNAILS / doc_dir / THUMBNAIL).read_bytes()
        return {
            "href": f"./{THUMBNAIL}",
            "type": WEBP,
            "title": "Thumbnail",
            "description": " ".join(self.meta["thumbnail"].split()),
            "roles": ["thumbnail"],
            **_file_fields(data),
        }

    def nav_links(self, spec: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        """Return the mirror and navigation links every document carries.

        A collection's ``license`` in ``catalog.yaml`` replaces the catalog's
        in the ``license`` link.
        """
        meta = self.meta
        spec = spec or {}
        license_link = {
            "rel": "license",
            "href": spec.get("license_url", meta["license_url"]),
            "type": HTML,
            "title": " ".join(spec.get("license_title", meta["license"]).split()),
        }
        return [
            {
                "rel": "via",
                "href": meta["via"]["href"],
                "type": HTML,
                "title": meta["via"]["title"],
            },
            license_link,
            {
                "rel": "vcs",
                "href": meta["repository"],
                "type": HTML,
                "title": "Source repository",
            },
            {
                "rel": "issues",
                "href": f"{meta['repository']}/issues",
                "type": HTML,
                "title": "Issue tracker",
            },
            {
                "rel": "about",
                "href": meta["about"],
                "type": HTML,
                "title": "Hosting page on Source Cooperative",
            },
        ]

    def docs_links(self, kind: str, spec: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        """Return the README, AGENTS and user guide links of a document.

        The README and the AGENTS file describe this mirror. The RGI 7.0 user
        guide is the official documentation, so only its link says so. A
        collection links the guide's page of its product.
        """
        if spec is None:
            guide_title = "RGI 7.0 user guide (official documentation)"
            guide_url = self.meta["user_guide"]
        else:
            guide = spec["user_guide"]
            guide_title = f"RGI 7.0 user guide, {guide['title']} (official documentation)"
            guide_url = guide["url"]
        return [
            {
                "rel": "describedby",
                "href": "./README.md",
                "type": MARKDOWN,
                "title": f"{kind} README",
            },
            {
                "rel": "agents",
                "href": "./AGENTS.md",
                "type": MARKDOWN,
                "title": f"{kind} agents guide",
            },
            {"rel": "describedby", "href": guide_url, "type": HTML, "title": guide_title},
        ]


def _table_columns(ctx: Context, name: str, record: dict[str, Any]) -> list[dict[str, Any]]:
    collection = ctx.meta["versions"][record["version"]]["collections"][name]
    upstream = record["attributes_metadata"].get(collection["product"], {})
    derived = ctx.columns.get(name, {})
    out = []
    for column in record["collections"][name]["columns"]:
        col = column["name"]
        entry: dict[str, Any] = {"name": col, "type": column["type"]}
        if col in upstream:
            entry["description"] = upstream[col]["description"]
            if upstream[col].get("units"):
                entry["unit"] = upstream[col]["units"]
        else:
            entry["description"] = " ".join(derived[col]["description"].split())
            if derived[col].get("unit"):
                entry["unit"] = derived[col]["unit"]
        if col in ctx.codes:
            entry["classification:classes"] = [
                {"value": value, "name": _slug(str(label)), "description": label}
                for value, label in ctx.codes[col]["classes"].items()
            ]
        out.append(entry)
    return out


def _collection(ctx: Context, version: str, name: str) -> dict[str, Any]:
    meta = ctx.meta
    record = ctx.records[version]
    spec = meta["versions"][version]["collections"][name]
    stats = record["collections"][name]
    vdir = version_dir(version)
    data_rel = f"{name}/{stats['href']}"
    archive = record["archive"]["href"]
    files = record["files"]
    publications = [
        {"doi": p["doi"], "citation": _plain(" ".join(p["citation"].split()))}
        for p in [*meta["publications"], *spec.get("publications", [])]
    ]
    citation = " ".join(spec["citation"].split()) if "citation" in spec else ctx.citation
    # Only the glaciers have a date column. Every other product of the version
    # derives from the same outlines, so it takes their time span.
    temporal = stats.get("temporal", record["collections"]["glaciers"]["temporal"])
    assets: dict[str, Any] = {
        "data": {
            "href": f"./{stats['href']}",
            "type": PARQUET,
            "title": f"{spec['title']}, GeoParquet",
            "roles": ["data"],
            "file:size": files[data_rel]["size"],
            "file:checksum": files[data_rel]["file:checksum"],
            "alternate": {
                "s3": {
                    "href": f"{meta['public_s3_base']}/{vdir}/{data_rel}",
                    "title": "Anonymous S3 access",
                },
            },
            "table:primary_geometry": "geometry",
            "table:row_count": stats["row_count"],
            "table:columns": _table_columns(ctx, name, record),
        },
    }
    pins = load_pins(version)
    # The upstream files are links, so a client lists them with the other
    # resources and does not offer them as data of this collection.
    source_links = []
    for key in PRODUCT_SOURCES[name]:
        if key in NSIDC_PRODUCTS:
            source_links.append(
                {
                    "rel": "related",
                    "href": f"{meta['nsidc_files']}/RGI2000-v{version}-{key}-global.zip",
                    "type": "application/zip",
                    "title": (
                        f"Source: RGI {version} {NSIDC_PRODUCTS[key]} product, global zip "
                        "at NSIDC (Earthdata login required)"
                    ),
                }
            )
        else:
            source_links.append(
                {
                    "rel": "related",
                    "href": pins[key].url,
                    "type": "text/csv",
                    "title": (
                        f"Source: {pins[key].filename}, the corrected file "
                        "(GLIMS-RGI/rgi_issue_tracker#41) on the University of Bremen server"
                    ),
                }
            )
    for key, text in collection_styles(name, version).items():
        style = json.loads(text)
        roles = ["style", "default"] if key == styles.DEFAULT_STYLES[name] else ["style"]
        assets[f"style-{key}"] = {
            "href": f"./styles/{key}.json",
            "type": STYLE,
            "title": style["name"],
            "description": style["metadata"]["description"],
            "roles": roles,
            **_file_fields(text.encode()),
        }
    archive_rel = f"../{archive}"
    archive_file = {
        "file:size": files[archive]["size"],
        "file:checksum": files[archive]["file:checksum"],
    }
    # The browser draws a collection from its assets, so the archive is an
    # asset as well as the rel:pmtiles link that the Portolan spec requires.
    # Every collection of the version shares the one archive.
    assets["pmtiles"] = {
        "href": archive_rel,
        "type": PMTILES,
        "title": "Web map archive (vector tiles)",
        "roles": ["visual"],
        **archive_file,
    }
    assets["thumbnail"] = ctx.thumbnail(f"{vdir}/{name}")
    links = [
        {"rel": "root", "href": "../../catalog.json", "type": JSON, "title": meta["title"]},
        {
            "rel": "parent",
            "href": "../catalog.json",
            "type": JSON,
            "title": meta["versions"][version]["title"],
        },
        *ctx.docs_links("Collection", spec),
        *ctx.nav_links(spec),
        *source_links,
        {
            "rel": "pmtiles",
            "href": archive_rel,
            "type": PMTILES,
            "title": "Web map archive (vector tiles)",
            "pmtiles:layers": spec["pmtiles_layers"],
            **archive_file,
        },
    ]
    return {
        "type": "Collection",
        "stac_version": STAC_VERSION,
        "stac_extensions": COLLECTION_EXTENSIONS,
        "id": f"{version_id(meta, version)}-{name}",
        "title": spec["title"],
        "description": ctx.describe(spec["description"]),
        "license": spec.get("license", meta["license"]),
        "keywords": [*meta["keywords"], *spec.get("keywords", [])],
        "version": record["mirror_revision"],
        "updated": record["updated"],
        "sci:doi": spec.get("doi", meta["doi"]),
        "sci:citation": _plain(citation),
        "sci:publications": publications,
        "providers": meta["providers"],
        "extent": {
            "spatial": {"bbox": [stats["bbox"]]},
            "temporal": {"interval": [temporal]},
        },
        "assets": assets,
        "links": links,
    }


def _catalog(
    ctx: Context,
    *,
    path: str,
    cat_id: str,
    title: str,
    description: str,
    children: list[tuple[str, str]],
    updated: str,
) -> dict[str, Any]:
    depth = path.count("/")
    up = "../" * depth
    links = [
        {
            "rel": "root",
            "href": f"{up or './'}catalog.json",
            "type": JSON,
            "title": ctx.meta["title"],
        }
    ]
    if depth == 0:
        links.append({"rel": "self", "href": ctx.public("catalog.json"), "type": JSON})
    else:
        links.append(
            {"rel": "parent", "href": "../catalog.json", "type": JSON, "title": ctx.meta["title"]}
        )
    links += ctx.docs_links("Catalog")
    # A catalog carries no assets (PTL-AST-005), so its thumbnail is a
    # rel:preview link, which clients read when a document has no assets.
    thumbnail = ctx.thumbnail(path.rpartition("/")[0])
    del thumbnail["roles"]
    links.append({"rel": "preview", **thumbnail})
    links += [
        {"rel": "child", "href": f"./{href}", "type": JSON, "title": t} for href, t in children
    ]
    links += ctx.nav_links()
    return {
        "type": "Catalog",
        "stac_version": STAC_VERSION,
        "stac_extensions": [PORTOLAN],
        "id": cat_id,
        "title": title,
        "description": ctx.describe(description),
        "updated": updated,
        "links": links,
    }


def _write(out: Path, rel: str, text: str | bytes, written: list[Path]) -> None:
    path = out / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(text, bytes):
        path.write_bytes(text)
    else:
        path.write_text(text)
    written.append(path)


def _write_thumbnail(out: Path, doc_dir: str, written: list[Path]) -> None:
    rel = f"{doc_dir}/{THUMBNAIL}" if doc_dir else THUMBNAIL
    _write(out, rel, (THUMBNAILS / rel).read_bytes(), written)


def render(out: Path = CATALOG) -> list[Path]:
    """Write every published document of the catalog.

    Parameters
    ----------
    out
        The catalog root to write into.

    Returns
    -------
    list[Path]
        The files written.
    """
    ctx = Context()
    meta = ctx.meta
    written: list[Path] = []
    nav = {"browser": ctx.browser, "public": ctx.public}
    common = {"meta": meta, "citation": ctx.citation, "disclaimer": ctx.disclaimer, **nav}

    version_children = []
    version_updated = []
    for version, vspec in meta["versions"].items():
        record = ctx.records[version]
        vdir = version_dir(version)
        version_children.append((f"{vdir}/catalog.json", vspec["title"]))
        version_updated.append(record["updated"])
        collections = []
        for name, cspec in vspec["collections"].items():
            doc = _collection(ctx, version, name)
            collections.append((name, cspec, doc))
            base = f"{vdir}/{name}"
            _write(out, f"{base}/collection.json", _dump(doc), written)
            _write_thumbnail(out, base, written)
            for key, text in collection_styles(name, version).items():
                _write(out, f"{base}/styles/{key}.json", text, written)
            scope = {
                **common,
                "version": version,
                "record": record,
                "name": name,
                "spec": cspec,
                "collection": doc,
                "path": f"{base}/collection.json",
                "codes": ctx.codes,
                "complete_zoom": GLACIERS_COMPLETE_ZOOM,
                "shape_min_px": SHAPE_MIN_PX,
                "has_timestamps": any(
                    c["type"].startswith("timestamp")
                    for c in record["collections"][name]["columns"]
                ),
                # The columns vector tiles cannot store.
                # The columns of the overview zooms, if the layer has an overview.
                "overview": list(OVERVIEW_COLUMNS.get(name, ())),
                "untiled": [
                    c["name"]
                    for c in record["collections"][name]["columns"]
                    if c["type"].startswith(("list", "struct"))
                ],
            }
            for doc_name in ("README.md", "AGENTS.md"):
                text = ctx.env.get_template(f"collection.{doc_name}.j2").render(scope)
                _write(out, f"{base}/{doc_name}", text, written)
        catalog = _catalog(
            ctx,
            path=f"{vdir}/catalog.json",
            cat_id=version_id(meta, version),
            title=vspec["title"],
            description=vspec["description"],
            children=[(f"{n}/collection.json", s["title"]) for n, s, _ in collections],
            updated=record["updated"],
        )
        _write(out, f"{vdir}/catalog.json", _dump(catalog), written)
        _write_thumbnail(out, vdir, written)
        scope = {
            **common,
            "version": version,
            "vspec": vspec,
            "record": record,
            "collections": collections,
            "path": f"{vdir}/catalog.json",
        }
        for doc_name in ("README.md", "AGENTS.md"):
            text = ctx.env.get_template(f"version.{doc_name}.j2").render(scope)
            _write(out, f"{vdir}/{doc_name}", text, written)

    root = _catalog(
        ctx,
        path="catalog.json",
        cat_id=meta["id"],
        title=meta["title"],
        description=meta["description"],
        children=version_children,
        updated=max(version_updated),
    )
    _write(out, "catalog.json", _dump(root), written)
    _write_thumbnail(out, "", written)
    scope = {
        **common,
        "versions": meta["versions"],
        "records": ctx.records,
        "path": "catalog.json",
    }
    for doc_name in ("README.md", "AGENTS.md"):
        text = ctx.env.get_template(f"root.{doc_name}.j2").render(scope)
        _write(out, doc_name, text, written)
    return sorted(written)


def _render(args: argparse.Namespace) -> None:
    if not args.no_record:
        print(f"ok  {write_build_record(args.version, staging=STAGING)}")
    for path in render():
        print(f"ok  {path}")


def add_parser(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    """Register the ``render`` command.

    Parameters
    ----------
    subparsers
        The CLI's subparser collection.
    """
    parser = subparsers.add_parser("render", help="write the build record and catalog/")
    parser.add_argument("--version", required=True)
    parser.add_argument(
        "--no-record",
        action="store_true",
        help="render from the committed build record; the staged files are not needed",
    )
    parser.set_defaults(func=_render)
