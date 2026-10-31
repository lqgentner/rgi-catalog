"""Tests for the catalog render."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq
import pytest

from rgi_catalog import render
from rgi_catalog.paths import CATALOG, METADATA, STAGING
from rgi_catalog.pipeline import output_path
from rgi_catalog.render import CATEGORIES_IN_GUIDE

DISCLAIMER = (
    "unofficial mirror",
    "not endorsed by the rgi consortium",
    "https://doi.org/10.5067/f6jmovy5navz",
)
# The citations in APA 7 style.
CITATION = (
    "RGI 7.0 Consortium. (2023). *Randolph Glacier Inventory: A dataset of global glacier"
    " outlines* (Version 7.0) [Data set]. NSIDC: National Snow and Ice Data Center."
    " https://doi.org/10.5067/F6JMOVY5NAVZ"
)
USER_GUIDE = (
    "Maussion, F., Hock, R., Paul, F., Raup, B., Rastner, P., Zemp, M., Andreassen, L.,"
    " Barr, I., Bolch, T., Kochtitzky, W., McNabb, R., & Tielidze, L. (2023)."
    " *The Randolph Glacier Inventory version 7.0 user guide*. Zenodo."
    " https://doi.org/10.5281/zenodo.8362857"
)
# Files in catalog/ that the render does not write.
NOT_RENDERED = ("_assets/",)


@pytest.fixture(scope="module")
def rendered(tmp_path_factory: pytest.TempPathFactory) -> Path:
    out = tmp_path_factory.mktemp("catalog")
    render.render(out)
    return out


def _files(root: Path) -> dict[str, bytes]:
    return {
        p.relative_to(root).as_posix(): p.read_bytes()
        for p in sorted(root.rglob("*"))
        if p.is_file() and not p.relative_to(root).as_posix().startswith(NOT_RENDERED)
    }


def _stac(root: Path) -> dict[str, dict[str, Any]]:
    out = {}
    for path in [*root.rglob("catalog.json"), *root.rglob("collection.json")]:
        out[path.relative_to(root).as_posix()] = json.loads(path.read_text())
    return out


def _collections(root: Path) -> list[dict[str, Any]]:
    return [d for d in _stac(root).values() if d["type"] == "Collection"]


def test_render_is_idempotent(rendered: Path, tmp_path: Path) -> None:
    render.render(tmp_path)
    assert _files(tmp_path) == _files(rendered)


def test_tracked_catalog_matches_render(rendered: Path) -> None:
    tracked, fresh = _files(CATALOG), _files(rendered)
    assert sorted(tracked) == sorted(fresh)
    stale = [name for name in fresh if tracked[name] != fresh[name]]
    assert not stale, f"catalog/ differs from a fresh render: {stale}; run the render command"


def test_disclaimer_everywhere(rendered: Path) -> None:
    readmes = list(rendered.rglob("README.md"))
    assert len(readmes) >= 3
    texts = [p.read_text() for p in readmes]
    texts += [doc["description"] for doc in _stac(rendered).values()]
    for text in texts:
        for phrase in DISCLAIMER:
            assert phrase in text.lower(), (phrase, text[:200])
        assert f"\n> {CITATION}\n" in f"{text}\n", text[:600]


def test_descriptions_open_with_the_data(rendered: Path) -> None:
    for doc in _stac(rendered).values():
        assert not doc["description"].lower().startswith("this is an unofficial mirror")
        assert doc["description"].index("unofficial mirror") > 0


def test_titles_name_the_data(rendered: Path) -> None:
    docs = _stac(rendered)
    assert docs["catalog.json"]["title"] == "Randolph Glacier Inventory Mirror"
    assert docs["v7.0/catalog.json"]["title"] == "RGI 7.0"
    assert docs["v7.0/glaciers/collection.json"]["title"] == "RGI 7.0 glaciers"
    for doc in docs.values():
        assert "(unofficial mirror)" not in json.dumps(doc)


def test_citations_in_apa7(rendered: Path) -> None:
    glaciers = json.loads((rendered / "v7.0" / "glaciers" / "collection.json").read_text())
    # The sci fields are plain text, so they carry no Markdown italics.
    assert glaciers["sci:citation"] == CITATION.replace("*", "")
    assert [p["citation"] for p in glaciers["sci:publications"]] == [USER_GUIDE.replace("*", "")]
    readme = (rendered / "v7.0" / "glaciers" / "README.md").read_text()
    assert f"> {USER_GUIDE}\n" in readme


def test_upstream_columns_described_from_rgi(rendered: Path) -> None:
    rec = json.loads((METADATA / "builds" / "v7.0.json").read_text())
    upstream = rec["attributes_metadata"]["G"]
    glaciers = json.loads((rendered / "v7.0" / "glaciers" / "collection.json").read_text())
    columns = {c["name"]: c for c in glaciers["assets"]["data"]["table:columns"]}
    for name, meta in upstream.items():
        # RGI's pointer to the user guide is dropped from a coded column.
        if CATEGORIES_IN_GUIDE in meta["description"]:
            assert "classification:classes" in columns[name]
        expected = meta["description"].replace(CATEGORIES_IN_GUIDE, "")
        assert columns[name]["description"] == expected


def test_every_column_documented(rendered: Path) -> None:
    rec = json.loads((METADATA / "builds" / "v7.0.json").read_text())
    for collection in _collections(rendered):
        name = collection["id"].removeprefix("rgi-v7-0-")
        documented = [c["name"] for c in collection["assets"]["data"]["table:columns"]]
        assert documented == [c["name"] for c in rec["collections"][name]["columns"]]
        assert all(c["description"] for c in collection["assets"]["data"]["table:columns"])
        staged = output_path(STAGING, "7.0", name)
        if staged.exists():
            assert documented == pq.read_schema(staged).names


def test_coded_columns_decoded(rendered: Path) -> None:
    glaciers = json.loads((rendered / "v7.0" / "glaciers" / "collection.json").read_text())
    columns = {c["name"]: c for c in glaciers["assets"]["data"]["table:columns"]}
    classes = {
        c["value"]: c["description"] for c in columns["surge_type"]["classification:classes"]
    }
    assert classes == {
        0: "No evidence",
        1: "Possible",
        2: "Probable",
        3: "Observed",
        9: "Not assigned",
    }


def test_providers_and_mirror_links(rendered: Path) -> None:
    for path, doc in _stac(rendered).items():
        rels = [link["rel"] for link in doc["links"]]
        for rel in (
            "via",
            "vcs",
            "issues",
            "about",
            "describedby",
            "agents",
        ):
            assert rel in rels, (path, rel)
        # The DOI is in sci:doi and the citation, and a reader is already in
        # the browser. The user guide link takes their place.
        assert "cite-as" not in rels, path
        assert "alternate" not in rels, path
        if doc["type"] == "Collection":
            assert "producer" in doc["providers"][0]["roles"]
            assert doc["providers"][-1]["roles"] == ["host"]
            assert doc["providers"][-1]["name"] == "Luis Q. Gentner"
            assert doc["providers"][-1]["url"] == "https://orcid.org/0009-0006-4453-0881"
            assert "pmtiles" in rels


def test_root_self_link_is_absolute(rendered: Path) -> None:
    root = json.loads((rendered / "catalog.json").read_text())
    self_links = [link for link in root["links"] if link["rel"] == "self"]
    assert [link["href"] for link in self_links] == [
        "https://data.source.coop/lqgentner/rgi/catalog.json",
    ]
    for path, doc in _stac(rendered).items():
        if path != "catalog.json":
            assert "self" not in [link["rel"] for link in doc["links"]]


def test_assets_and_links_resolve_relatively(rendered: Path) -> None:
    glaciers = json.loads((rendered / "v7.0" / "glaciers" / "collection.json").read_text())
    data = glaciers["assets"]["data"]
    assert data["href"] == "./rgi7.0-glaciers.parquet"
    assert data["file:checksum"].startswith("1220")
    assert data["alternate"]["s3"]["href"].endswith("/v7.0/glaciers/rgi7.0-glaciers.parquet")
    assert data["alternate"]["s3"]["href"].startswith("s3://")
    assert "opendata.source.coop" in data["alternate"]["s3"]["href"]
    pmtiles = next(link for link in glaciers["links"] if link["rel"] == "pmtiles")
    assert pmtiles["href"] == "../rgi7.0.pmtiles"
    assert pmtiles["pmtiles:layers"] == ["glaciers", "glacier-labels"]
    asset = glaciers["assets"]["pmtiles"]
    assert asset["href"] == pmtiles["href"]
    assert asset["type"] == "application/vnd.pmtiles"
    assert asset["roles"] == ["visual"]
    assert asset["file:checksum"] == pmtiles["file:checksum"]


def test_styles_written_with_one_default(rendered: Path) -> None:
    glaciers = json.loads((rendered / "v7.0" / "glaciers" / "collection.json").read_text())
    styles = {k: a for k, a in glaciers["assets"].items() if "style" in a["roles"]}
    assert len(styles) == 5
    defaults = [k for k, a in styles.items() if "default" in a["roles"]]
    assert len(defaults) == 1
    for asset in styles.values():
        assert asset["type"] == "application/vnd.mapbox.style+json"
        style = json.loads((rendered / "v7.0" / "glaciers" / asset["href"]).read_text())
        assert style["version"] == 8


def test_sources_are_links_not_assets(rendered: Path) -> None:
    glaciers = json.loads((rendered / "v7.0" / "glaciers" / "collection.json").read_text())
    assert not [k for k, a in glaciers["assets"].items() if "source" in a["roles"]]
    # rel:via is for the HTML landing page (PTL-PRO-001), so files are related.
    related = {link["href"]: link for link in glaciers["links"] if link["rel"] == "related"}
    nsidc = "https://daacdata.apps.nsidc.org/pub/DATASETS/nsidc0770_rgi_v7/global_files"
    assert f"{nsidc}/RGI2000-v7.0-G-global.zip" in related
    assert f"{nsidc}/RGI2000-v7.0-C-global.zip" in related
    links_csv = [h for h in related if h.endswith("RGI2000-v7.0-G-global-rgi6_links.csv")]
    assert len(links_csv) == 1
    assert related[links_csv[0]]["type"] == "text/csv"


def test_thumbnails_registered_and_copied(rendered: Path) -> None:
    docs = _stac(rendered)
    assert len(docs) == 7
    for path, doc in docs.items():
        if doc["type"] == "Catalog":
            # Catalogs carry no assets (PTL-AST-005). A client reads the
            # thumbnail of a catalog from its rel:preview link.
            assert "assets" not in doc
            thumbs = [link for link in doc["links"] if link["rel"] == "preview"]
        else:
            thumbs = [a for a in doc["assets"].values() if "thumbnail" in a["roles"]]
        assert len(thumbs) == 1, path
        thumb = thumbs[0]
        assert thumb["href"] == "./thumbnail.webp"
        assert thumb["type"] == "image/webp"
        rel = (Path(path).parent / "thumbnail.webp").as_posix()
        data = (rendered / rel).read_bytes()
        assert data == (METADATA / "thumbnails" / rel).read_bytes()
        assert thumb["file:size"] == len(data)
        assert thumb["file:checksum"] == "1220" + hashlib.sha256(data).hexdigest()
        # The world views draw Natural Earth land, which needs no credit, and no
        # thumbnail draws a basemap that does.
        assert "Natural Earth" in thumb["description"]
        assert "Esri" not in thumb["description"]


def _section(text: str, heading: str) -> str:
    return text.split(f"## {heading}\n", 1)[1].split("\n## ", 1)[0]


def test_processing_notes_state_the_computed_fix_counts(rendered: Path) -> None:
    record = json.loads((METADATA / "builds" / "v7.0.json").read_text())
    for name, fixes in record["fixes"].items():
        readme = (rendered / "v7.0" / name / "README.md").read_text()
        notes = _section(readme, "Processing notes")
        assert "docs/PROVENANCE.md" in notes
        lines = [line for line in notes.splitlines() if line.startswith("- ")]
        for fix in fixes:
            stated = [line for line in lines if f"`{fix['fix']}`" in line]
            if fix["count"]:
                assert len(stated) == 1, (name, fix)
                assert f"{fix['count']:,} " in stated[0]
                assert f"`{fix['column']}`" in stated[0]
            else:
                assert not stated, (name, fix)


def _link(doc: dict[str, Any], rel: str, href_end: str) -> dict[str, Any]:
    return next(x for x in doc["links"] if x["rel"] == rel and x["href"].endswith(href_end))


def test_readmes_are_named_for_the_mirror(rendered: Path) -> None:
    # "Documentation" is the RGI user guide. The README and the AGENTS file
    # describe this mirror.
    for path, doc in _stac(rendered).items():
        kind = "Collection" if doc["type"] == "Collection" else "Catalog"
        assert _link(doc, "describedby", "README.md")["title"] == f"{kind} README", path
        assert _link(doc, "agents", "AGENTS.md")["title"] == f"{kind} agents guide", path
        for link in doc["links"]:
            if link["href"].endswith(".md"):
                assert "documentation" not in link["title"].lower(), path


def test_user_guide_linked_as_official_documentation(rendered: Path) -> None:
    meta = render.Context().meta
    specs = meta["versions"]["7.0"]["collections"]
    for path, doc in _stac(rendered).items():
        guide = [x for x in doc["links"] if x["rel"] == "describedby" and x["type"] == "text/html"]
        assert len(guide) == 1, path
        assert "official documentation" in guide[0]["title"]
        if doc["type"] == "Collection":
            name = path.split("/")[1]
            assert guide[0]["href"] == specs[name]["user_guide"]["url"]
        else:
            assert guide[0]["href"] == meta["user_guide"]


def test_product_description_quoted_from_the_user_guide(rendered: Path) -> None:
    specs = render.Context().meta["versions"]["7.0"]["collections"]
    for name, spec in specs.items():
        quote = " ".join(spec["user_guide"]["quote"].split())
        for doc_name in ("README.md", "AGENTS.md"):
            text = (rendered / "v7.0" / name / doc_name).read_text()
            flat = " ".join(text.replace("\n>", "\n").split())
            assert quote in flat, (name, doc_name)
            assert spec["user_guide"]["url"] in text, (name, doc_name)


def test_collections_in_product_order(rendered: Path) -> None:
    version = json.loads((rendered / "v7.0" / "catalog.json").read_text())
    children = [x["href"] for x in version["links"] if x["rel"] == "child"]
    assert children == [
        f"./{name}/collection.json"
        for name in ("glaciers", "complexes", "intersects", "centerlines", "regions")
    ]


def test_root_keeps_the_link_order_in_the_browser(rendered: Path) -> None:
    root = json.loads((rendered / "catalog.json").read_text())
    assert root["stac_browser"] == {"defaultCollectionSort": None}
    for path, doc in _stac(rendered).items():
        if path != "catalog.json":
            assert "stac_browser" not in doc, path
