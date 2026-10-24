"""A miniature RGI 7.0 release, laid out like the real nested zips."""

from __future__ import annotations

from dataclasses import dataclass
import io
import json
from pathlib import Path
from typing import Any
import zipfile

import geopandas as gpd
import pandas as pd
import pytest
from shapely.geometry import LineString, Polygon

G_COLUMNS: dict[str, str] = {
    "rgi_id": "str",
    "o1region": "str",
    "o2region": "str",
    "glims_id": "str",
    "anlys_id": "int",
    "subm_id": "int",
    "src_date": "str",
    "cenlon": "float",
    "cenlat": "float",
    "utm_zone": "int",
    "area_km2": "float",
    "primeclass": "int",
    "conn_lvl": "int",
    "surge_type": "int",
    "term_type": "int",
    "glac_name": "str",
    "is_rgi6": "int",
    "termlon": "float",
    "termlat": "float",
    "zmin_m": "float",
    "zmax_m": "float",
    "zmed_m": "float",
    "zmean_m": "float",
    "slope_deg": "float",
    "aspect_deg": "float",
    "aspect_sec": "int",
    "dem_source": "str",
    "lmax_m": "int",
}
C_COLUMNS: dict[str, str] = {
    "rgi_id": "str",
    "o1region": "str",
    "o2region": "str",
    "cenlon": "float",
    "cenlat": "float",
    "utm_zone": "int",
    "area_km2": "float",
}
L_COLUMNS: dict[str, str] = {
    "rgi_id": "str",
    "rgi_g_id": "str",
    "segment_id": "int",
    "is_main": "int",
    "outflow_id": "int",
    "strahler_n": "int",
    "length_m": "int",
}
I_COLUMNS: dict[str, str] = {
    "rgi_id": "str",
    "rgi_g_id_1": "str",
    "rgi_g_id_2": "str",
    "length_m": "float",
}
SUBM_COLUMNS = [
    "subm_id",
    "n_outlines",
    "area_km2",
    "anlys_time",
    "release_dt",
    "proc_desc",
    "chief_affl",
    "submitters",
    "analysts",
    "rc_id",
]


def _square(lon: float, lat: float, size: float = 0.01) -> Polygon:
    return Polygon(
        [(lon, lat), (lon + size, lat), (lon + size, lat + size), (lon, lat + size)],
    )


def _spiked(lon: float, lat: float, size: float = 0.01) -> Polygon:
    """Return a square with a zero-width spike, which is invalid (rgi_issue_tracker#48)."""
    top = lat + size
    return Polygon(
        [
            (lon, lat),
            (lon + size, lat),
            (lon + size, top),
            (lon + 2 * size, top),
            (lon + size, top),
            (lon, top),
        ],
    )


def _square_z(lon: float, lat: float, size: float = 0.01) -> Polygon:
    return Polygon(
        [
            (lon, lat, 0.0),
            (lon + size, lat, 0.0),
            (lon + size, lat + size, 0.0),
            (lon, lat + size, 0.0),
        ],
    )


def _glacier(
    rgi_id: str,
    o2region: str,
    subm_id: int,
    lon: float,
    lat: float,
    name: str,
) -> dict[str, Any]:
    return {
        "rgi_id": rgi_id,
        "o1region": o2region[:2],
        "o2region": o2region,
        "glims_id": f"G{lon:07.3f}E{lat:06.3f}N",
        "anlys_id": 700000 + int(rgi_id[-5:]),
        "subm_id": subm_id,
        "src_date": "2003-08-13T00:00:00",
        "cenlon": lon + 0.005,
        "cenlat": lat + 0.005,
        "utm_zone": 32,
        "area_km2": 0.8125,
        "primeclass": 0,
        "conn_lvl": 0,
        "surge_type": 0,
        "term_type": 0,
        "glac_name": name,
        "is_rgi6": 1,
        "termlon": lon + 0.001,
        "termlat": lat + 0.001,
        "zmin_m": 2206.1677,
        "zmax_m": 2341.86,
        "zmed_m": 2256.1104,
        "zmean_m": 2260.9812,
        "slope_deg": 32.483784,
        "aspect_deg": 8.992585,
        "aspect_sec": 1,
        "dem_source": "COPDEM30",
        "lmax_m": 206,
    }


# Region 08 holds one glacier stored as Polygon Z (Z = 0) with a mojibake
# name. Region 11 holds a named glacier, and one that every side table misses:
# no hypsometry row, no complex, no RGI 6 link, an unknown submission.
G_ROWS: dict[str, list[dict[str, Any]]] = {
    "08_scandinavia": [
        _glacier("RGI2000-v7.0-G-08-00001", "08-01", 731, 7.0, 61.0, "BessedÃ¸rbreen"),
    ],
    "11_central_europe": [
        _glacier("RGI2000-v7.0-G-11-00001", "11-01", 731, 10.75, 46.8, "Hintereisferner"),
        _glacier("RGI2000-v7.0-G-11-00002", "11-01", 999, 10.8, 46.85, ""),
    ],
}
HYPSOMETRY: dict[str, pd.DataFrame] = {
    "08_scandinavia": pd.DataFrame(
        {
            "rgi_id": ["RGI2000-v7.0-G-08-00001"],
            "area_km2": [0.8125],
            "2175": [0],
            "2225": [500],
            "2275": [500],
        },
    ),
    "11_central_europe": pd.DataFrame(
        {
            "rgi_id": ["RGI2000-v7.0-G-11-00001"],
            "area_km2": [0.8125],
            "2175": [0],
            "2225": [423],
            "2275": [464],
            "2325": [113],
            "2375": [0],
        },
    ),
}
SUBMISSION = pd.DataFrame(
    {
        "subm_id": [731],
        "n_outlines": [4034],
        "area_km2": [2120.0642146721034],
        "anlys_time": ["2021-09-01T00:00:00"],
        "release_dt": ["2021-10-09T09:00:00"],
        "proc_desc": ["Semi-automated glacier classification"],
        "chief_affl": ["University of Zurich-Irchel"],
        "submitters": ["Paul, Frank"],
        "analysts": ["Izagirre, EÃ±aut"],
        "rc_id": [30],
    },
)
CTOG: dict[str, dict[str, list[str]]] = {
    "08_scandinavia": {"RGI2000-v7.0-C-08-00001": ["RGI2000-v7.0-G-08-00001"]},
    "11_central_europe": {"RGI2000-v7.0-C-11-00001": ["RGI2000-v7.0-G-11-00001"]},
}
# Glacier 11-00001 has a main segment and a tributary. Glacier 08-00001 has one
# main segment. The intersect between the two region-11 glaciers is LineString
# Z (Z = 0), as in the release.
L_ROWS: dict[str, list[dict[str, Any]]] = {
    "08_scandinavia": [
        {
            "rgi_id": "RGI2000-v7.0-L-08-00001",
            "rgi_g_id": "RGI2000-v7.0-G-08-00001",
            "segment_id": 0,
            "is_main": 1,
            "outflow_id": -1,
            "strahler_n": 1,
            "length_m": 812,
        },
    ],
    "11_central_europe": [
        {
            "rgi_id": "RGI2000-v7.0-L-11-00001",
            "rgi_g_id": "RGI2000-v7.0-G-11-00001",
            "segment_id": 0,
            "is_main": 1,
            "outflow_id": -1,
            "strahler_n": 2,
            "length_m": 950,
        },
        {
            "rgi_id": "RGI2000-v7.0-L-11-00002",
            "rgi_g_id": "RGI2000-v7.0-G-11-00001",
            "segment_id": 1,
            "is_main": 0,
            "outflow_id": 0,
            "strahler_n": 1,
            "length_m": 300,
        },
    ],
}
I_ROWS: dict[str, list[dict[str, Any]]] = {
    "11_central_europe": [
        {
            "rgi_id": "RGI2000-v7.0-I-11-00001",
            "rgi_g_id_1": "RGI2000-v7.0-G-11-00001",
            "rgi_g_id_2": "RGI2000-v7.0-G-11-00002",
            "length_m": 123.456789,
        },
    ],
}
# Region 10 crosses the antimeridian and is two rows, as in the release. The
# second-order region 08-01 has a garbled name, and 11-01 has a spike.
O1_REGIONS = [
    ("08", "Scandinavia", "08_scandinavia", _square(5.0, 58.0, 10.0)),
    ("10", "North Asia", "10_north_asia", _square(170.0, 60.0, 10.0)),
    ("10", "North Asia", "10_north_asia", _square(-180.0, 60.0, 5.0)),
    ("11", "Central Europe", "11_central_europe", _square(5.0, 43.0, 10.0)),
]
O2_REGIONS = [
    ("08", "08-01", "SÃ¸r-Norge", "08-01_sor_norge", _square(5.0, 58.0, 5.0)),
    ("11", "11-01", "Alps", "11-01_alps", _spiked(5.0, 43.0, 5.0)),
]
RGI6_LINKS = pd.DataFrame(
    {
        "rgi7_id": [
            "RGI2000-v7.0-G-08-00001",
            "RGI2000-v7.0-G-11-00001",
            "RGI2000-v7.0-G-11-00001",
        ],
        "rgi6_id": ["RGI60-08.00001", "RGI60-11.00897", "RGI60-11.00898"],
        "rgi7_reg": ["08", "11", "11"],
        "rgi6_reg": ["08", "11", "11"],
        "overlap_area_km2": [0.8, 0.5, 0.3],
        "rgi7_area_fraction": [0.98, 0.6, 0.4],
        "rgi6_area_fraction": [0.99, 0.97, 0.95],
        "cluster_id": [0, 1, 1],
        "n_rgi7": [1, 1, 1],
        "n_rgi6": [1, 2, 2],
    },
)


def _metadata(columns: dict[str, str]) -> str:
    return json.dumps(
        {
            name: {
                "long_name": name,
                "description": f"Description of {name}.",
                "datatype": datatype,
                "units": "",
                "source": "RGI",
                "rgi6_name": "",
            }
            for name, datatype in columns.items()
        },
        indent=2,
    )


def _shapefile_members(gdf: gpd.GeoDataFrame, stem: str, tmp: Path) -> dict[str, bytes]:
    out = tmp / f"{stem}.shp"
    gdf.to_file(out, driver="ESRI Shapefile", encoding="UTF-8")
    return {p.name: p.read_bytes() for p in sorted(tmp.iterdir()) if p.stem == stem}


def _zip_bytes(members: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        for name, data in members.items():
            zf.writestr(name, data)
    return buffer.getvalue()


@dataclass(frozen=True)
class FakeRGI:
    """Paths of the miniature release."""

    g_zip: Path
    c_zip: Path
    rgi6_links: Path
    l_zip: Path
    i_zip: Path
    regions_zip: Path


def _line(lon: float, lat: float, *, z: bool = False) -> LineString:
    if z:
        return LineString([(lon, lat, 0.0), (lon + 0.005, lat + 0.005, 0.0)])
    return LineString([(lon, lat), (lon + 0.005, lat + 0.005)])


def _line_product(
    root: Path,
    letter: str,
    rows: dict[str, list[dict[str, Any]]],
    columns: dict[str, str],
) -> Path:
    regions: dict[str, bytes] = {}
    for region, region_rows in rows.items():
        stem = f"RGI2000-v7.0-{letter}-{region}"
        attrs = pd.DataFrame(region_rows)
        geoms = [_line(7.0 + i * 0.01, 46.0, z=letter == "I") for i in range(len(region_rows))]
        gdf = gpd.GeoDataFrame(attrs.copy(), geometry=geoms, crs="EPSG:4326")
        work = root / "work" / stem
        work.mkdir(parents=True)
        members = _shapefile_members(gdf, stem, work)
        members[f"{stem}-attributes.csv"] = attrs.to_csv(index=False).encode()
        members[f"{stem}-attributes_metadata.json"] = _metadata(columns).encode()
        members["README.md"] = b"# RGI 7.0\n"
        regions[f"{stem}.zip"] = _zip_bytes(members)
    out = root / f"RGI2000-v7.0-{letter}-global.zip"
    out.write_bytes(_zip_bytes({"README.md": b"# RGI 7.0\n", **regions}))
    return out


def _regions_zip(root: Path) -> Path:
    work = root / "work" / "regions"
    work.mkdir(parents=True)
    members: dict[str, bytes] = {"README.md": b"# RGI 7.0 regions\n"}
    o1 = gpd.GeoDataFrame(
        pd.DataFrame([r[:3] for r in O1_REGIONS], columns=["o1region", "full_name", "long_code"]),
        geometry=[r[3] for r in O1_REGIONS],
        crs="EPSG:4326",
    )
    o2 = gpd.GeoDataFrame(
        pd.DataFrame(
            [r[:4] for r in O2_REGIONS],
            columns=["o1region", "o2region", "full_name", "long_code"],
        ),
        geometry=[r[4] for r in O2_REGIONS],
        crs="EPSG:4326",
    )
    for level, gdf in (("o1regions", o1), ("o2regions", o2)):
        stem = f"RGI2000-v7.0-{level}"
        members.update(_shapefile_members(gdf, stem, work))
        # The summaries carry an unnamed index column, as in the release.
        summary = pd.DataFrame(gdf.drop(columns="geometry"))
        members[f"{stem}-summary.csv"] = summary.to_csv(index_label="").encode()
    out = root / "RGI2000-v7.0-regions.zip"
    out.write_bytes(_zip_bytes(members))
    return out


def build_fake_rgi(root: Path) -> FakeRGI:
    """Write the miniature global zips for G, C, L and I, the regions zip, and the RGI 6 links CSV.

    Parameters
    ----------
    root
        An empty directory.

    Returns
    -------
    FakeRGI
        The paths of the written files.
    """
    g_regions: dict[str, bytes] = {}
    c_regions: dict[str, bytes] = {}
    for region, rows in G_ROWS.items():
        stem = f"RGI2000-v7.0-G-{region}"
        attrs = pd.DataFrame(rows)
        make = _square_z if region.startswith("08") else _square
        geoms = [make(float(r["cenlon"]) - 0.005, float(r["cenlat"]) - 0.005) for r in rows]
        gdf = gpd.GeoDataFrame(attrs.copy(), geometry=geoms, crs="EPSG:4326")
        work = root / "work" / stem
        work.mkdir(parents=True)
        members = _shapefile_members(gdf, stem, work)
        members[f"{stem}-attributes.csv"] = attrs.to_csv(index=False).encode()
        members[f"{stem}-attributes_metadata.json"] = _metadata(G_COLUMNS).encode()
        members[f"{stem}-hypsometry.csv"] = HYPSOMETRY[region].to_csv(index=False).encode()
        members[f"{stem}-submission_info.csv"] = SUBMISSION.to_csv(index=False).encode()
        members[".ipynb_checkpoints/"] = b""
        members[f".ipynb_checkpoints/{stem}-attributes-checkpoint.csv"] = b"junk\n"
        members["README.md"] = b"# RGI 7.0\n"
        g_regions[f"{stem}.zip"] = _zip_bytes(members)

        c_stem = f"RGI2000-v7.0-C-{region}"
        c_rows = [
            {
                **{k: r[k] for k in C_COLUMNS},
                "rgi_id": r["rgi_id"].replace("-G-", "-C-"),
            }
            for r in rows
            if r["rgi_id"] != "RGI2000-v7.0-G-11-00002"
        ]
        c_attrs = pd.DataFrame(c_rows)
        # The region-08 complex has a spike, which makes it invalid.
        c_make = _spiked if region.startswith("08") else _square
        c_geoms = [c_make(float(r["cenlon"]) - 0.005, float(r["cenlat"]) - 0.005) for r in c_rows]
        c_gdf = gpd.GeoDataFrame(c_attrs.copy(), geometry=c_geoms, crs="EPSG:4326")
        c_work = root / "work" / c_stem
        c_work.mkdir(parents=True)
        c_members = _shapefile_members(c_gdf, c_stem, c_work)
        c_members[f"{c_stem}-attributes.csv"] = c_attrs.to_csv(index=False).encode()
        c_members[f"{c_stem}-attributes_metadata.json"] = _metadata(C_COLUMNS).encode()
        c_members[f"{c_stem}-CtoG_links.json"] = json.dumps(CTOG[region]).encode()
        c_members["README.md"] = b"# RGI 7.0\n"
        c_regions[f"{c_stem}.zip"] = _zip_bytes(c_members)

    g_zip = root / "RGI2000-v7.0-G-global.zip"
    g_zip.write_bytes(_zip_bytes({"README.md": b"# RGI 7.0\n", **g_regions}))
    c_zip = root / "RGI2000-v7.0-C-global.zip"
    c_zip.write_bytes(
        _zip_bytes({".ipynb_checkpoints/": b"", "README.md": b"# RGI 7.0\n", **c_regions}),
    )
    links = root / "RGI2000-v7.0-G-global-rgi6_links.csv"
    links.write_text(RGI6_LINKS.to_csv(index=False))
    return FakeRGI(
        g_zip=g_zip,
        c_zip=c_zip,
        rgi6_links=links,
        l_zip=_line_product(root, "L", L_ROWS, L_COLUMNS),
        i_zip=_line_product(root, "I", I_ROWS, I_COLUMNS),
        regions_zip=_regions_zip(root),
    )


@pytest.fixture
def fake_rgi(tmp_path: Path) -> FakeRGI:
    """Return a miniature RGI 7.0 release in a temporary directory."""
    return build_fake_rgi(tmp_path)
