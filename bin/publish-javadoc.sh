#!/bin/bash
#
# publish-javadoc.sh - publish a pombast javadoc build tree atomically.
#
# Usage: publish-javadoc.sh [-n] [-k KEEP] BUILD RELEASES LIVE
#
#   BUILD     the tree `pombast javadoc -o` writes to (never modified here)
#   RELEASES  directory holding published snapshots, one per publish
#   LIVE      symlink the web server serves (e.g. its DocumentRoot); it is
#             switched to the new snapshot in a single rename
#   -n        dry run: show what would happen, change nothing
#   -k KEEP   snapshots to keep (default 3); the live one is never removed
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
while getopts "nk:" opt; do
  case "$opt" in
    n) dry=1 ;;
    k) keep=$OPTARG ;;
    *) sed -n '3,14s/^# \{0,1\}//p' "$0" >&2; exit 2 ;;
  esac
done
shift $((OPTIND - 1))
if [ $# -ne 3 ]; then
  sed -n '3,14s/^# \{0,1\}//p' "$0" >&2
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

stamp=$(date +%Y%m%d-%H%M%S)
snapshot=$releases/$stamp
[ -e "$snapshot" ] && die "$snapshot already exists"

# Hard-link the build into a new snapshot, skipping pombast's in-progress
# staging dirs and swapped-out copies.
run mkdir -p "$releases"
run rsync -a --link-dest="$build" \
  --exclude='.*.staging/' --exclude='.*.old/' \
  "$build/" "$snapshot/"

for map in redirects latest latest-fallback; do
  run httxt2dbm -f SDBM -i "$snapshot/$map.map" -o "$snapshot/$map.map.db"
done

# Switch: rename a fresh symlink over the old one, so a request sees either
# the old snapshot or the new one, never a missing or partial site.
target=$(realpath -m "$snapshot")
run ln -sfn "$target" "$live.new"
run mv -T "$live.new" "$live"
echo "Published $snapshot"

# Prune the oldest snapshots beyond KEEP, sparing whichever one is live.
current=$( [ -L "$live" ] && realpath "$live" || true)
mapfile -t snapshots < <(find "$releases" -mindepth 1 -maxdepth 1 -type d \
  -name '[0-9]*-[0-9]*' | sort -r)
for old in "${snapshots[@]:$keep}"; do
  [ "$(realpath "$old")" = "$current" ] && continue
  run rm -rf -- "$old"
done
