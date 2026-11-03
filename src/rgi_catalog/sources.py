"""Pinned upstream sources: load the pins, download, and verify the bytes."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import http.client
import shutil
from typing import TYPE_CHECKING
import urllib.request

import yaml

from rgi_catalog.paths import CACHE, METADATA

if TYPE_CHECKING:
    import argparse
    from pathlib import Path

CHUNK = 1 << 20


class SourceMismatchError(Exception):
    """A file does not match its pinned size or sha256."""


@dataclass(frozen=True)
class SourcePin:
    """One upstream input, pinned by URL, sha256 and size."""

    key: str
    url: str
    sha256: str
    size: int
    filename: str


def load_pins(version: str, path: Path = METADATA / "sources.yaml") -> dict[str, SourcePin]:
    """Read the pins of one RGI version from ``metadata/sources.yaml``.

    Parameters
    ----------
    version
        The RGI version, for example ``"7.0"``.
    path
        The pin file.

    Returns
    -------
    dict[str, SourcePin]
        The pins by key (``G``, ``C``, ``I``, ``L``, ``regions``, ``rgi6_links``).
    """
    entries: dict[str, dict[str, str | int]] = yaml.safe_load(path.read_text())[version]
    return {
        key: SourcePin(
            key=key,
            url=str(entry["url"]),
            sha256=str(entry["sha256"]),
            size=int(entry["size"]),
            filename=str(entry["url"]).rsplit("/", 1)[1],
        )
        for key, entry in entries.items()
    }


def sha256_file(path: Path) -> str:
    """Return the hex sha256 of a file, read in chunks.

    Parameters
    ----------
    path
        The file.

    Returns
    -------
    str
        The hex digest.
    """
    digest = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


def verify(path: Path, pin: SourcePin) -> None:
    """Check a file against its pin.

    Parameters
    ----------
    path
        The file.
    pin
        The pin it must match.

    Raises
    ------
    SourceMismatchError
        If the size or the sha256 differs.
    """
    size = path.stat().st_size
    if size != pin.size:
        msg = f"{path.name}: size {size} != pinned {pin.size}"
        raise SourceMismatchError(msg)
    digest = sha256_file(path)
    if digest != pin.sha256:
        msg = f"{path.name}: sha256 {digest} != pinned {pin.sha256}"
        raise SourceMismatchError(msg)


def fetch(pin: SourcePin, cache_dir: Path = CACHE) -> Path:
    """Return a verified local copy of a pinned file, downloading it if needed.

    The download goes to ``<filename>.part`` and is renamed only after it
    verifies, so a truncated or changed download never sits in the cache
    under the final name.

    Parameters
    ----------
    pin
        The pin to fetch.
    cache_dir
        The directory that holds verified downloads.

    Returns
    -------
    Path
        The verified file.

    Raises
    ------
    SourceMismatchError
        If the downloaded bytes do not match the pin.
    """
    cache_dir.mkdir(parents=True, exist_ok=True)
    final = cache_dir / pin.filename
    if final.exists():
        try:
            verify(final, pin)
        except SourceMismatchError:
            final.unlink()
        else:
            return final
    part = cache_dir / f"{pin.filename}.part"
    try:
        with urllib.request.urlopen(pin.url) as response, part.open("wb") as out:  # noqa: S310
            try:
                shutil.copyfileobj(response, out, CHUNK)
            except http.client.IncompleteRead as exc:
                out.write(exc.partial)
        verify(part, pin)
        part.rename(final)
    finally:
        part.unlink(missing_ok=True)
    return final


def _download(args: argparse.Namespace) -> None:
    for pin in load_pins(args.version).values():
        path = fetch(pin)
        print(f"ok  {path.name}  {pin.size} bytes  sha256 {pin.sha256}")


def add_parser(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    """Register the ``download`` command.

    Parameters
    ----------
    subparsers
        The CLI's subparser collection.
    """
    parser = subparsers.add_parser("download", help="fetch and verify the pinned sources")
    parser.add_argument("--version", required=True)
    parser.set_defaults(func=_download)
