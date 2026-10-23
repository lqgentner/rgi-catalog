#!/usr/bin/env bash
# Render the thumbnails into metadata/thumbnails/ and run the blank probe.
#
# Usage: SKILL=<portolan-thumbnails skill dir> scripts/thumbnails.sh
#
# Needs a chiitiler server on port 13579 that can read this repository at its
# own path (docs/DESIGN.md, "Local preview"), and the staged archive. Look at
# every image before you commit it. The probe finds only an empty frame.
set -euo pipefail

: "${SKILL:?set SKILL to the portolan-thumbnails skill directory}"
REPO="$(cd "$(dirname "$0")/.." && pwd)"
PM="$REPO/staging/v7.0/rgi7.0.pmtiles"
STYLES="$REPO/catalog/v7.0"
OUT="$REPO/metadata/thumbnails"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
BASEMAP='https://services.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Light_Gray_Base/MapServer/tile/{z}/{y}/{x}'
WORLD="-170,-60.3,170,82"

frame() {  # lon,lat zoom
    python3 "$SKILL/scripts/frame.py" --center "$1" --zoom "$2" --size 1024 |
        python3 -c "import json, sys; print(json.load(sys.stdin)['bbox'])"
}

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

thumb() {  # target style bbox
    local target="$OUT/$1/thumbnail.webp" dir="$WORK/$1"
    mkdir -p "$dir" "$(dirname "$target")"
    python3 "$SKILL/scripts/buildstyle.py" "$2" "$PM" true "$BASEMAP" 0.55 "$dir" > /dev/null
    render "$dir/render-style.json" "$3" 1024 "$target" webp
    render "$dir/probe-style.json" "$3" 256 "$dir/probe.png" png
    render "$dir/blank-style.json" "$3" 256 "$dir/blank.png" png
    if cmp -s "$dir/probe.png" "$dir/blank.png"; then
        echo "FAIL $target: the frame holds no data" >&2
        return 1
    fi
    echo "ok   $target $(stat -c%s "$target") bytes"
}

thumb . "$STYLES/glaciers/styles/reference.json" "$WORLD"
thumb v7.0 "$STYLES/glaciers/styles/reference.json" "$WORLD"
thumb v7.0/regions "$STYLES/regions/styles/regions.json" "$WORLD"
thumb v7.0/glaciers "$STYLES/glaciers/styles/reference.json" "$(frame 7.85,46.2 9.5)"
thumb v7.0/complexes "$STYLES/complexes/styles/complexes.json" "$(frame 76.45,35.75 9.5)"
thumb v7.0/centerlines "$STYLES/centerlines/styles/centerlines.json" "$(frame -73.4,-49.6 9.5)"
thumb v7.0/intersects "$STYLES/intersects/styles/intersects.json" "$(frame 86.85,27.95 11.5)"
