#!/usr/bin/env bash
# Construit la page de relecture de la spécification v1.0.
#
#   docs/tools/spec-review/build.sh <révision-de-base> [fichier-de-sortie]
#
# La révision de base est le point de comparaison : tout ce qui a changé depuis
# est signalé sur la page. En pratique, c'est l'état que le relecteur a déjà lu.
set -euo pipefail

BASE="${1:?usage: build.sh <révision-de-base> [sortie.html]}"
OUT="${2:-${TMPDIR:-/tmp}/spec-v1.html}"
ROOT="$(git rev-parse --show-toplevel)"
SPEC="$ROOT/docs/waterfall-v1.0-specification.md"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

git -C "$ROOT" diff --unified=0 "$BASE..HEAD" -- "$SPEC" > "$WORK/spec.diff"
git -C "$ROOT" log --format='%h|%s' --reverse "$BASE..HEAD" -- "$SPEC" > "$WORK/commits.txt"

python3 "$ROOT/docs/tools/spec-review/build.py" \
  --base "$BASE" --spec "$SPEC" --diff "$WORK/spec.diff" \
  --commits "$WORK/commits.txt" --out "$OUT"
