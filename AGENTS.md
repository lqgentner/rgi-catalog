# rgi-catalog agent notes

## This Repository

An unofficial, cloud-native mirror of the Randolph Glacier Inventory (RGI),
built as a git-backed Portolan catalog from `portolan-catalog-template`. It is
not endorsed by the RGI Consortium. The design is in
`docs/superpowers/specs/2026-10-22-rgi-mirror-design.md`.

### The publish boundary

`catalog/` is the published catalog. Everything in it is published, and
nothing outside it ever is. Do not move a file into `catalog/` to make it
publish, and do not add a path outside `publish_dir` to `tools/publish.py`.
The boundary is the only thing standing between a scratch file and a public
bucket, and it holds because it is structural rather than a list of
exclusions.

### Data never enters git

Never commit a GeoParquet, COG, PMTiles, Zarr, or COPC file. If a gate needs
bytes to check, generate them in CI. Git keeps every version of a binary
forever and deleting it later reclaims nothing.

### The conformance allow-list

`ACCEPTED` in `tests/test_conformance.py` ships empty. Never add an entry
without a matching row in `docs/conformance.md` giving the rule, where it
fires, why it is accepted, and the issue tracking its removal.

### Published agent guides

Every claim in a `catalog/**/AGENTS.md` is either quoted from a source or
measured from the data. An invented join key or column name produces a
confident wrong answer that nothing downstream catches.

### The links back to this repository

`catalog/catalog.json` ships a `vcs` link and an `issues` link. Both hrefs are
setup placeholders, so `tests/test_setup.py` catches a half-edited repository.
The Portolan spec recommends these two links for a git-backed catalog. See
[git-backed catalogs](https://github.com/portolan-sdi/portolan-spec/blob/main/specs/best-practices/git-backed-catalogs.md),
which merged in August 2026.

Keep both hrefs absolute. The repository sits outside the published catalog,
so a relative href resolves against the public base URL. Each placeholder
holds a `://`, because `tests/test_links.py` treats an href without one as a
path and looks for it on disk.

## Working in this repository

### Commands

Every command runs inside the pixi environment.

```bash
pixi install                                         # create the environment
pixi run check                                       # lint, typecheck, unit tests, catalog gates
pixi run python -m rgi_catalog download --version 7.0
pixi run python -m rgi_catalog convert --version 7.0
pixi run python -m rgi_catalog tiles --version 7.0
pixi run python -m rgi_catalog render --version 7.0
pixi run python -m rgi_catalog preview --version 7.0
```

### The render rule

`render` generates `catalog/`. Do not edit a file in `catalog/` by hand. Edit
`metadata/`, then run `pixi run python -m rgi_catalog render --version 7.0`.
A unit test fails when `catalog/` differs from a fresh render.

### The data policy

Restructuring is allowed, and fixing documented upstream errors is allowed.
Values never change otherwise. Every fix is listed in `docs/PROVENANCE.md`. A
cleaned `display_name` is allowed because `rgi_id` stays authoritative. Never
alter or re-mint an `rgi_id`.

### Publishing

Publish with `tools/upload_data.py` (the data in `staging/`) and then
`tools/publish.py` (the catalog documents). Run both without `--confirm`
first. Never use `portolan push`.

### A mirror revision

A fix to the conversion or the catalog overwrites the files at the same paths.
Each fix is a mirror revision, named `7.0-r1`, `7.0-r2`, and so on.

1. Rebuild: `download`, `convert`, `tiles`.
2. Bump the revision in `metadata/catalog.yaml`.
3. Run `render`, then `pixi run check`.
4. Upload the data, then publish the catalog.
5. Add a `CHANGELOG.md` entry.
6. Tag the commit with the revision name.
