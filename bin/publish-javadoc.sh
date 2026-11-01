#!/bin/bash
#
# publish-javadoc.sh - publish a pombast javadoc build tree atomically.
#
# Usage: publish-javadoc.sh [-n] [-k KEEP] [-s SITE] BUILD RELEASES LIVE
#
#   BUILD     the tree `pombast javadoc -o` writes to (never modified here)
#   RELEASES  directory holding published snapshots, one per publish
#   LIVE      symlink the web server serves (e.g. its DocumentRoot); it is
#             switched to the new snapshot in a single rename
#   -n        dry run: show what would happen, change nothing
#   -k KEEP   snapshots to keep (default 3); the live one is never removed
#   -s SITE   also copy the site's own static files (front page, styles,
#             icons) from this dir into the snapshot, over the build; its
#             hidden files, *.md and licenses are not published
#
# A snapshot hard-links every unchanged file to the build tree, so it costs
# little more than its directories. This is safe because pombast never
# modifies a file in place: it writes a new file and renames it over the old
# one, leaving published copies untouched.
#
# The site-wide maps (redirects.map, latest.map, latest-fallback.map) are
# converted to SDBM in the snapshot, for Apache's RewriteMap "dbm=sdbm:".

set -euo pipefail

dry=
keep=3
site=
while getopts "nk:s:" opt; do
  case "$opt" in
    n) dry=1 ;;
    k) keep=$OPTARG ;;
    s) site=$(realpath "$OPTARG") ;;
    *) sed -n '3,17s/^# \{0,1\}//p' "$0" >&2; exit 2 ;;
  esac
done
shift $((OPTIND - 1))
if [ $# -ne 3 ]; then
  sed -n '3,17s/^# \{0,1\}//p' "$0" >&2
  exit 2
fi
build=$(realpath "$1")
releases=$2
live=$3

die() { echo "error: $*" >&2; exit 1; }
run() {
  echo "+ $*"
  [ -n "$dry" ] || "$@"
}

[ -z "$site" ] || [ -f "$site/index.html" ] || die "$site has no index.html"
[ -f "$build/latest.map" ] || die "$build has no latest.map; not a pombast javadoc tree?"
[ -s "$build/latest.map" ] || die "$build/latest.map is empty"
if [ -e "$live" ] && [ ! -L "$live" ]; then
  die "$live exists and is not a symlink; move it aside first"
fi
command -v httxt2dbm >/dev/null || PATH=$PATH:/usr/sbin
command -v httxt2dbm >/dev/null || die "httxt2dbm not found (apache2-utils)"

# SDBM stores each key/value pair in one 1 KB page.
for map in redirects latest latest-fallback; do
  [ -f "$build/$map.map" ] || die "$build/$map.map is missing"
  longest=$(awk '{ if (length($0) > n) n = length($0) } END { print n + 0 }' "$build/$map.map")
  [ "$longest" -lt 1000 ] || die "$map.map has a $longest-byte line, too long for SDBM"
done

# UTC, so names sort in time order even across a daylight saving change.
stamp=$(date -u +%Y%m%dT%H%M%SZ)
snapshot=$releases/$stamp
[ -e "$snapshot" ] && die "$snapshot already exists"

# Hard-link the build into a new snapshot, skipping pombast's in-progress
# staging dirs and swapped-out copies.
run mkdir -p "$releases"
run rsync -a --link-dest="$build" \
  --exclude='.*.staging/' --exclude='.*.old/' \
  "$build/" "$snapshot/"

# Lay the site's static files over the build. rsync writes each to a temp
# file and renames it into place, so files hard-linked to the build are
# replaced in the snapshot only, never modified.
if [ -n "$site" ]; then
  run rsync -rlt --checksum --chmod=D755,F644 \
    --exclude='.*' --exclude='*.md' --exclude='LICENSE*' --exclude='UNLICENSE' \
    "$site/" "$snapshot/"
fi

for map in redirects latest latest-fallback; do
  run httxt2dbm -f SDBM -i "$snapshot/$map.map" -o "$snapshot/$map.map.db"
done

# Switch: rename a fresh symlink over the old one, so a request sees either
# the old snapshot or the new one, never a missing or partial site.
target=$(realpath -m "$snapshot")
run ln -sfn "$target" "$live.new"
run mv -T "$live.new" "$live"
if [ -n "$dry" ]; then echo "Would publish $snapshot (dry run)"; exit 0; fi
echo "Published $snapshot"

# Prune the oldest snapshots beyond KEEP, sparing whichever one is live.
current=$( [ -L "$live" ] && realpath "$live" || true)
# (Snapshots named before UTC stamps were adopted look like 20261101-012917.)
mapfile -t snapshots < <(find "$releases" -mindepth 1 -maxdepth 1 -type d \
  \( -name '[0-9]*T[0-9]*Z' -o -name '[0-9]*-[0-9]*' \) | sort -r)
for old in "${snapshots[@]:$keep}"; do
  [ "$(realpath "$old")" = "$current" ] && continue
  run rm -rf -- "$old"
done
