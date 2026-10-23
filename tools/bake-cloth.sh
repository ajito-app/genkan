#!/usr/bin/env bash
set -euo pipefail

src="${1:-$(dirname "$0")/../../ajito/brand/source/noren-transparent.svg}"
out="$(dirname "$0")/cloth.webp"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

python3 - "$src" "$tmp/cloth.svg" <<'PY'
import sys
import xml.etree.ElementTree as ET

ET.register_namespace("", "http://www.w3.org/2000/svg")
tree = ET.parse(sys.argv[1])
root = tree.getroot()

for child in list(root):
    tag = child.tag.split("}")[1]
    if not (tag == "defs" or (tag == "g" and child.get("clip-path"))):
        root.remove(child)

left, top, right, bottom = 43.6, 33, 561.4, 496
root.set("viewBox", f"{left} {top} {right - left} {bottom - top}")
root.set("width", "2048")
root.set("height", str(round(2048 * (bottom - top) / (right - left))))
tree.write(sys.argv[2])
PY

rsvg-convert "$tmp/cloth.svg" -o "$tmp/cloth.png"
magick "$tmp/cloth.png" -quality 90 -define webp:alpha-quality=100 "$out"
