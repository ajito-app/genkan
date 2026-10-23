#!/usr/bin/env bash
set -euo pipefail

master="${1:?usage: export-scene.sh still-master.png}"
out="$(dirname "$0")/../site"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

for width in 1500 2250 3000 4500 6000; do
    magick "$master" -resize "${width}x" -quality 92 -define webp:sharp-yuv=true "$out/scene/master-$width.webp"
done

glow() {
    local name="$1"
    local box="$2"

    magick "$master" -crop "$box" +repage -colorspace Gray -level 30%,50% "$tmp/mask.png"
    magick "$tmp/mask.png" -morphology Dilate Disk:5 "$tmp/wide.png"
    magick "$tmp/wide.png" "$tmp/mask.png" -compose MinusSrc -composite -blur 0x2 "$tmp/ring.png"
    magick "$tmp/wide.png" -blur 0x14 -evaluate multiply 0.55 "$tmp/halo.png"
    magick "$tmp/ring.png" "$tmp/halo.png" -compose Lighten -composite "$tmp/alpha.png"

    local size
    size="$(magick identify -format "%wx%h" "$tmp/alpha.png")"
    magick -size "$size" xc:"#fff3dc" "$tmp/alpha.png" -alpha off -compose CopyOpacity -composite -quality 90 "$out/scene/glow-$name.webp"
}

glow a 247x270+2566+1547
glow ji 258x276+2876+1540
glow to 185x272+3226+1543

magick "$master" -crop 4750x2493+625+413 +repage -resize 1200x630! -quality 88 "$out/og.jpg"
