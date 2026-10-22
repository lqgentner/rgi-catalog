"""Command-line entry point: ``python -m rgi_catalog <command>``."""

from __future__ import annotations

import argparse


def build_parser() -> argparse.ArgumentParser:
    """Return the argument parser with one subparser per build step.

    Returns
    -------
    argparse.ArgumentParser
        The parser. Each subparser sets ``func`` to its handler.
    """
    parser = argparse.ArgumentParser(prog="rgi_catalog", description=__doc__)
    parser.add_subparsers(dest="command", required=True)
    return parser


def main(argv: list[str] | None = None) -> None:
    """Parse the arguments and run the selected command.

    Parameters
    ----------
    argv
        The arguments. ``None`` reads them from ``sys.argv``.
    """
    args = build_parser().parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
