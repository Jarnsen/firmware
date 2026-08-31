#!/usr/bin/env bash
set -euo pipefail

if [[ "$(git rev-parse --is-shallow-repository 2>/dev/null || echo false)" == "true" ]]; then
  echo "Fetching full git history for deterministic daily versioning..."
  git fetch --unshallow origin || git fetch --deepen=5000 origin "${BUILDKITE_BRANCH:-refactor/jarn-mesh-unified-core}"
fi

if [[ "$(git rev-parse --is-shallow-repository 2>/dev/null || echo false)" == "true" ]]; then
  echo "Cannot resolve daily version from incomplete git history" >&2
  exit 1
fi

if command -v node >/dev/null 2>&1; then
  VERSION_CMD=(node tools/jarnsen_version.mjs)
elif command -v python3 >/dev/null 2>&1; then
  VERSION_CMD=(python3 tools/jarnsen_version.py)
else
  echo "Neither node nor python3 is available for daily version resolution" >&2
  exit 1
fi

JARNSEN_VERSION="$("${VERSION_CMD[@]}")"
export JARNSEN_VERSION

printf 'Resolved JARN-MESH version: %s\n' "$JARNSEN_VERSION"
"${VERSION_CMD[@]}" --json
buildkite-agent meta-data set jarnsen-version "$JARNSEN_VERSION"
buildkite-agent pipeline upload .buildkite/pipeline.template.yml
