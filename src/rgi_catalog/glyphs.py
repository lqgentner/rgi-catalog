"""The glyph advances of the label font, which the ``tiles`` step uses to measure names."""

from __future__ import annotations

from functools import cache
import hashlib
from typing import TYPE_CHECKING
import urllib.parse
import urllib.request

import yaml

from rgi_catalog.paths import METADATA

if TYPE_CHECKING:
    import argparse
    from collections.abc import Iterator
    from pathlib import Path

# The glyphs of OpenFreeMap, which the styles load.
GLYPHS = "https://tiles.openfreemap.org/fonts/{fontstack}/{range}.pbf"
# The styles draw glacier names along the label lines in this text, and the
# tiles step fits each label line to it. The letter spacing is in em.
FONT = "Noto Sans Italic"
LABEL_TEXT_SIZE = 14
LABEL_LETTER_SPACING = 0.2
# The width of the white halo around the text, in pixels.
LABEL_HALO_WIDTH = 1.2
# Every glacier name uses code points 0 to 255 only.
GLYPHS_URL = GLYPHS.format(fontstack=urllib.parse.quote(FONT), range="0-255")
ADVANCES = METADATA / "glyph_advances.yaml"
# MapLibre's glyphs are drawn at 24 px. A glyph's advance scales with the text size.
GLYPH_PX = 24

# Protocol buffer wire types.
_VARINT, _I64, _LEN, _I32 = 0, 1, 2, 5


def _varint(buf: bytes, i: int) -> tuple[int, int]:
    """Return the varint at ``i`` and the offset after it."""
    shift = value = 0
    while True:
        byte = buf[i]
        i += 1
        value |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return value, i
        shift += 7


def _fields(buf: bytes) -> Iterator[tuple[int, int | bytes]]:
    """Yield the field number and value of each field of a protocol buffer message."""
    i = 0
    while i < len(buf):
        key, i = _varint(buf, i)
        field, wire = key >> 3, key & 7
        value: int | bytes
        if wire == _VARINT:
            value, i = _varint(buf, i)
        elif wire == _LEN:
            n, i = _varint(buf, i)
            value, i = buf[i : i + n], i + n
        elif wire == _I32:
            value, i = buf[i : i + 4], i + 4
        elif wire == _I64:
            value, i = buf[i : i + 8], i + 8
        else:
            msg = f"unsupported wire type {wire}"
            raise ValueError(msg)
        yield field, value


def read_advances(pbf: bytes) -> dict[int, int]:
    """Return the advance of each glyph in a MapLibre glyph range.

    The range is a ``glyphs`` message. Field 1 holds a ``fontstack``,
    whose field 3 holds each ``glyph``. A glyph has its code point in
    field 1 and its advance in field 7.

    Parameters
    ----------
    pbf
        The bytes of one glyph range, such as ``0-255.pbf``.

    Returns
    -------
    dict[int, int]
        The advance by code point, in pixels at :data:`GLYPH_PX`.
    """
    advances = {}
    for field, stack in _fields(pbf):
        if field != 1 or not isinstance(stack, bytes):
            continue
        for stack_field, glyph in _fields(stack):
            if stack_field != 3 or not isinstance(glyph, bytes):  # noqa: PLR2004
                continue
            values = dict(_fields(glyph))
            advances[int(values[1])] = int(values.get(7, 0))  # type: ignore[arg-type]
    return advances


def write_advances(pbf: bytes, url: str, out: Path = ADVANCES) -> Path:
    """Write the advances of a glyph range to the metadata.

    Parameters
    ----------
    pbf
        The bytes of the glyph range.
    url
        Where the bytes came from.
    out
        The YAML file to write.

    Returns
    -------
    Path
        ``out``.
    """
    document = {
        "font": FONT,
        "url": url,
        "sha256": hashlib.sha256(pbf).hexdigest(),
        "glyph_px": GLYPH_PX,
        "advances": dict(sorted(read_advances(pbf).items())),
    }
    header = "# Written by `python -m rgi_catalog glyphs`. Do not edit by hand.\n"
    out.write_text(header + yaml.safe_dump(document, sort_keys=False))
    return out


@cache
def load_advances(path: Path = ADVANCES) -> dict[int, int]:
    """Return the advances from the metadata.

    Parameters
    ----------
    path
        The YAML file from :func:`write_advances`.

    Returns
    -------
    dict[int, int]
        The advance by code point, in pixels at :data:`GLYPH_PX`.
    """
    return {int(k): int(v) for k, v in yaml.safe_load(path.read_text())["advances"].items()}


def _glyphs(args: argparse.Namespace) -> None:
    request = urllib.request.Request(args.url, headers={"User-Agent": "rgi-catalog"})  # noqa: S310
    with urllib.request.urlopen(request) as response:  # noqa: S310
        pbf = response.read()
    out = write_advances(pbf, args.url)
    print(f"ok  {out}: {len(load_advances.__wrapped__(out))} glyphs")


def add_parser(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    """Register the ``glyphs`` command.

    Parameters
    ----------
    subparsers
        The CLI's subparser collection.
    """
    parser = subparsers.add_parser("glyphs", help="record the advances of the label font")
    parser.add_argument("--url", default=GLYPHS_URL)
    parser.set_defaults(func=_glyphs)
