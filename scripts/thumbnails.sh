#!/usr/bin/env bash
# Render the thumbnails into metadata/thumbnails/ and run the blank probe.
#
# Usage: scripts/thumbnails.sh
#
# Needs a chiitiler server on port 13579 that can read this repository at its
# own path (docs/DESIGN.md, "Local preview"), the staged archive, and the land
# archive of scripts/naturalearth_land.py. Look at every image before you
# commit it. The probe finds only an empty frame.
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
ARCHIVE="$REPO/staging/v7.0/rgi7.0.pmtiles"
LAND="$REPO/.cache/basemap/ne_50m_land.pmtiles"
STYLES="$REPO/catalog/v7.0"
OUT="$REPO/metadata/thumbnails"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
# The world views, on Natural Earth land. The frame runs once around the
# world from 169°W, the border between Alaska and North Asia, so no region
# box is cut at the image edges.
WORLD="-169,-62.15,191,83"
# The Garibaldi and Marinelli glaciers, Cordillera Darwin, just above map
# zoom 10, where the tiles hold every glacier. At exactly z10 chiitiler draws
# the z9 tiles, which hold the glacier overview. The four glacier products
# share this frame, so they compare at a glance.
FRAME="-70.078019,-54.786293,-69.421981,-54.533313"

clip() {  # style bbox size out format
    curl -s -X POST "http://localhost:13579/clip.$5?bbox=$2&size=$3&quality=85" \
        -H "Content-Type: application/json" -d "{\"style\": $(cat "$1")}" \
        -o "$4" -w "%{http_code}"
}

# chiitiler can answer before every tile has loaded. Repeat the request until
# two images are identical.
render() {
    local prev="" code hash
    for _ in 1 2 3 4 5 6; do
        code=$(clip "$@")
        [ "$code" = 200 ] || { echo "http $code: $(head -c 200 "$4")" >&2; return 1; }
        hash=$(sha256sum "$4" | cut -d' ' -f1)
        [ "$hash" = "$prev" ] && return 0
        prev=$hash
    done
    echo "unstable render: $4" >&2
    return 1
}

thumb() {  # target style bbox [--land LAND]
    local target="$OUT/$1/thumbnail.webp" dir="$WORK/$1"
    mkdir -p "$dir" "$(dirname "$target")"
    pixi run --manifest-path "$REPO/pyproject.toml" python "$REPO/scripts/thumbnail_style.py" \
        "$2" "$ARCHIVE" "$dir" "${@:4}"
    render "$dir/render-style.json" "$3" 1024 "$target" webp
    render "$dir/probe-style.json" "$3" 256 "$dir/probe.png" png
    render "$dir/blank-style.json" "$3" 256 "$dir/blank.png" png
    if cmp -s "$dir/probe.png" "$dir/blank.png"; then
        echo "FAIL $target: the frame holds no data" >&2
        return 1
    fi
    echo "ok   $target $(stat -c%s "$target") bytes"
}

thumb . "$STYLES/glaciers/styles/glaciers.json" "$WORLD" --land "$LAND"
thumb v7.0 "$STYLES/glaciers/styles/glaciers.json" "$WORLD" --land "$LAND"
thumb v7.0/regions "$STYLES/regions/styles/regions.json" "$WORLD" --land "$LAND"
thumb v7.0/glaciers "$STYLES/glaciers/styles/glaciers.json" "$FRAME"
thumb v7.0/complexes "$STYLES/complexes/styles/complexes.json" "$FRAME"
thumb v7.0/centerlines "$STYLES/centerlines/styles/centerlines.json" "$FRAME"
thumb v7.0/intersects "$STYLES/intersects/styles/intersects.json" "$FRAME"
