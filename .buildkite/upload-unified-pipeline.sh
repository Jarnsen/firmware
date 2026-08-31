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

JARNSEN_VERSION="$(python3 tools/jarnsen_version.py)"
export JARNSEN_VERSION

printf 'Resolved JARN-MESH version: %s\n' "$JARNSEN_VERSION"
python3 tools/jarnsen_version.py --json
buildkite-agent meta-data set jarnsen-version "$JARNSEN_VERSION"
buildkite-agent pipeline upload .buildkite/pipeline.template.yml
