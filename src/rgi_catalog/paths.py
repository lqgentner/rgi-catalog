"""Repository-relative paths shared by every build step."""

from __future__ import annotations

from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
CACHE = REPO / ".cache"
STAGING = REPO / "staging"
CATALOG = REPO / "catalog"
METADATA = REPO / "metadata"


def version_dir(version: str) -> str:
    """Return the catalog directory name of an RGI version.

    Parameters
    ----------
    version
        The RGI version, for example ``"7.0"``.

    Returns
    -------
    str
        The directory name, for example ``"v7.0"``.
    """
    return f"v{version}"
