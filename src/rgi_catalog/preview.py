"""The ``preview`` step: serve ``catalog/`` and the staged data as one tree.

The published layout puts the catalog documents and the data under one root.
Locally they live apart, in ``catalog/`` and ``staging/``. The preview joins
them with symlinks and serves the result with HTTP Range and CORS, which the
browser, DuckDB and PMTiles readers need.
"""

from __future__ import annotations

from functools import partial
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import mimetypes
from pathlib import Path
import re
import shutil
from typing import TYPE_CHECKING, override

from rgi_catalog.paths import CACHE, CATALOG, STAGING

if TYPE_CHECKING:
    import argparse

PREVIEW = CACHE / "preview"
BROWSER = "http://localhost:8080/#/external/http:/localhost:{port}/catalog.json"
CONTENT_TYPES = {
    ".json": "application/json",
    ".md": "text/markdown; charset=utf-8",
    ".parquet": "application/vnd.apache.parquet",
    ".pmtiles": "application/vnd.pmtiles",
    ".webp": "image/webp",
}
CORS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Expose-Headers": "Content-Length, Content-Range, Accept-Ranges",
}
_RANGE = re.compile(r"bytes=(\d*)-(\d*)")


class PreviewOverlapError(Exception):
    """A path exists in both the catalog and the staging tree."""


def _files(root: Path) -> dict[str, Path]:
    """Return the files under a root by relative path, without dot paths."""
    out = {}
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root)
        if path.is_file() and not any(part.startswith(".") for part in rel.parts):
            out[rel.as_posix()] = path
    return out


def assemble_preview(catalog: Path, staging: Path, out: Path) -> Path:
    """Join the catalog and the staged data into one tree of symlinks.

    Parameters
    ----------
    catalog
        The rendered catalog.
    staging
        The staged data, laid out like the catalog. Dot paths (reports,
        intermediates) are left out, as the upload leaves them out.
    out
        The preview root. It is rebuilt from scratch.

    Returns
    -------
    Path
        ``out``.

    Raises
    ------
    PreviewOverlapError
        If a path exists in both trees.
    """
    docs, data = _files(catalog), _files(staging)
    if both := sorted(docs.keys() & data.keys()):
        msg = f"present in both {catalog} and {staging}: {', '.join(both)}"
        raise PreviewOverlapError(msg)
    if out.exists():
        shutil.rmtree(out)
    for rel, src in {**docs, **data}.items():
        link = out / rel
        link.parent.mkdir(parents=True, exist_ok=True)
        link.symlink_to(src.resolve())
    return out


class RangeHandler(SimpleHTTPRequestHandler):
    """Serve files with exact lengths, single-range ``206`` responses and CORS."""

    @override
    def end_headers(self) -> None:
        for key, value in CORS.items():
            self.send_header(key, value)
        super().end_headers()

    def do_OPTIONS(self) -> None:
        """Answer a CORS preflight."""
        self.send_response(HTTPStatus.NO_CONTENT)
        self.send_header("Access-Control-Allow-Methods", "GET, HEAD, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Range, If-None-Match, If-Match")
        self.send_header("Content-Length", "0")
        self.end_headers()

    @override
    def do_HEAD(self) -> None:
        self._respond(body=False)

    @override
    def do_GET(self) -> None:
        self._respond(body=True)

    def _respond(self, *, body: bool) -> None:
        path = Path(self.translate_path(self.path))
        if not path.is_file():
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        size = path.stat().st_size
        start, end = 0, size - 1
        match = _RANGE.fullmatch(self.headers.get("Range", "").strip())
        if match and (match.group(1) or match.group(2)):
            if not match.group(1):
                start = max(size - int(match.group(2)), 0)
            else:
                start = int(match.group(1))
                if match.group(2):
                    end = min(int(match.group(2)), size - 1)
            if start > end or start >= size:
                self.send_response(HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE)
                self.send_header("Content-Range", f"bytes */{size}")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            self.send_response(HTTPStatus.PARTIAL_CONTENT)
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        else:
            self.send_response(HTTPStatus.OK)
        content_type = CONTENT_TYPES.get(path.suffix) or mimetypes.guess_type(path.name)[0]
        self.send_header("Content-Type", content_type or "application/octet-stream")
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(end - start + 1))
        self.end_headers()
        if body:
            with path.open("rb") as f:
                f.seek(start)
                remaining = end - start + 1
                while remaining:
                    chunk = f.read(min(remaining, 1 << 20))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    remaining -= len(chunk)

    @override
    def log_message(self, format: str, *args: object) -> None:
        del format, args


def serve(
    root: Path,
    port: int = 8000,
    handler: type[RangeHandler] = RangeHandler,
) -> ThreadingHTTPServer:
    """Return a server for a directory, bound but not yet serving.

    Parameters
    ----------
    root
        The directory to serve.
    port
        The port on 127.0.0.1. ``0`` picks a free one.
    handler
        The request handler class, :class:`RangeHandler` or a subclass.

    Returns
    -------
    ThreadingHTTPServer
        Call ``serve_forever`` to start it.
    """
    return ThreadingHTTPServer(("127.0.0.1", port), partial(handler, directory=str(root)))


def _preview(args: argparse.Namespace) -> None:
    root = assemble_preview(CATALOG, STAGING, PREVIEW)
    server = serve(root, args.port)
    port = server.server_address[1]
    print(f"serving {root} at http://localhost:{port}/catalog.json")
    print(f"browser: {BROWSER.format(port=port)}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


def add_parser(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    """Register the ``preview`` command.

    Parameters
    ----------
    subparsers
        The CLI's subparser collection.
    """
    parser = subparsers.add_parser("preview", help="serve catalog/ and staging/ as one tree")
    parser.add_argument("--version", required=True)
    parser.add_argument("--port", type=int, default=8000)
    parser.set_defaults(func=_preview)
