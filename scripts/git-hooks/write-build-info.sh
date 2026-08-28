#!/bin/sh
# Writes build_info.json (commit hash, date, branch, commit count) at the repo
# root. Called by the post-commit/post-checkout/post-merge/post-rewrite hooks
# in this folder. The file is gitignored but deployed with the plugin, where
# version_info.py reads it to show the running build inside QGIS.
#
# One-time setup per clone (activates these hooks):
#   git config core.hooksPath scripts/git-hooks
set -e
root="$(git rev-parse --show-toplevel)"
hash_short="$(git log -1 --format=%h)"
hash_full="$(git log -1 --format=%H)"
date_iso="$(git log -1 --format=%cs)"
branch="$(git rev-parse --abbrev-ref HEAD)"
count="$(git rev-list --count HEAD)"
printf '{\n  "commit": "%s",\n  "commit_full": "%s",\n  "date": "%s",\n  "branch": "%s",\n  "commit_count": %s\n}\n' \
  "$hash_short" "$hash_full" "$date_iso" "$branch" "$count" > "$root/build_info.json"
