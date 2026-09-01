#!/usr/bin/env bash
set -euo pipefail

resolve_version() {
  if command -v node >/dev/null 2>&1; then
    node tools/jarnsen_version.mjs
  elif command -v python3 >/dev/null 2>&1; then
    python3 tools/jarnsen_version.py
  else
    echo "Neither node nor python3 is available for version resolution" >&2
    return 1
  fi
}

if [[ -z "${JARNSEN_VERSION:-}" ]]; then
  JARNSEN_VERSION="$(resolve_version)"
  export JARNSEN_VERSION
fi

: "${JARNSEN_VERSION:?JARNSEN_VERSION is required}"
: "${BUILDKITE_AGENT_ACCESS_TOKEN:?BUILDKITE_AGENT_ACCESS_TOKEN is required}"
: "${BUILDKITE_AGENT_ENDPOINT:?BUILDKITE_AGENT_ENDPOINT is required}"
: "${BUILDKITE_JOB_ID:?BUILDKITE_JOB_ID is required}"
: "${BUILDKITE_REPO:?BUILDKITE_REPO is required}"
: "${BUILDKITE_BUILD_NUMBER:?BUILDKITE_BUILD_NUMBER is required}"

REPO="${JARNSEN_GITHUB_REPO:-Jarnsen/firmware}"
SOURCE_SHA="${BUILDKITE_COMMIT:-$(git rev-parse HEAD)}"
BUILD_NUMBER="${BUILDKITE_BUILD_NUMBER}"
BUILD_URL="${BUILDKITE_BUILD_URL:-https://buildkite.com/jarnsen/jarn-mesh-unified-core/builds/${BUILD_NUMBER}}"
TAG="jarn-mesh-${JARNSEN_VERSION}-buildkite-${BUILD_NUMBER}"
RELEASE_NAME="JARNSEN-MESH ${JARNSEN_VERSION} · Buildkite #${BUILD_NUMBER}"
WORK_DIR="$PWD/github-release-assets"
PUBLISH_DIR="$WORK_DIR/publish"

printf '\n=== Collect firmware artifacts for GitHub ===\n'
printf 'Version: %s\n' "$JARNSEN_VERSION"
rm -rf "$WORK_DIR"
mkdir -p "$PUBLISH_DIR"
buildkite-agent artifact download 'firmware-artifact/*.bin' "$WORK_DIR"

mapfile -t BIN_FILES < <(find "$WORK_DIR" -type f -name '*.bin' | sort)
if (( ${#BIN_FILES[@]} != 18 )); then
  printf 'Expected 18 firmware BIN files (6 boards x 3 images), found %s\n' "${#BIN_FILES[@]}" >&2
  printf '%s\n' "${BIN_FILES[@]}" >&2
  exit 1
fi

for file in "${BIN_FILES[@]}"; do
  cp "$file" "$PUBLISH_DIR/$(basename "$file")"
done

cat > "$PUBLISH_DIR/BUILD-INFO.txt" <<EOF
JARNSEN-MESH ${JARNSEN_VERSION}
Buildkite build: ${BUILD_NUMBER}
Source SHA: ${SOURCE_SHA}
Branch: ${BUILDKITE_BRANCH:-unknown}
Buildkite: ${BUILD_URL}

Boards:
- Heltec Tracker V1.1
- Heltec V3
- Heltec V4
- Seeed Wio Tracker L1
- LILYGO T-Beam
- LILYGO T-Beam Supreme

Each board contains:
- .factory.bin     USB first installation / complete flash
- .update.bin      JARNSEN Service Tool / OTA update
- .webflasher.bin  Meshtastic Web Flasher local update
EOF

(
  cd "$PUBLISH_DIR"
  sha256sum ./*.bin > SHA256SUMS.txt
)

printf '\n=== Request short-lived GitHub token from Buildkite ===\n'
REQUEST_BODY='{"repo_url":"'"${BUILDKITE_REPO}"'","workflow":"buildkite-release.yml","permissions":{"contents":"write"}}'
if ! RESPONSE=$(curl --fail-with-body --silent --show-error \
  --request POST \
  --header "Authorization: Token ${BUILDKITE_AGENT_ACCESS_TOKEN}" \
  --header "Content-Type: application/json" \
  --data "$REQUEST_BODY" \
  "${BUILDKITE_AGENT_ENDPOINT}/jobs/${BUILDKITE_JOB_ID}/github_workflow_access_token"); then
  printf '%s\n' "${RESPONSE:-GitHub workflow token request failed}" >&2
  printf '\nIf this is a permissions error, enable "Allow workflow-authorized GitHub access tokens" in the Buildkite pipeline GitHub settings.\n' >&2
  exit 1
fi

if ! printf '%s' "$RESPONSE" | buildkite-agent redactor add --format json; then
  unset RESPONSE
  exit 1
fi

GITHUB_TOKEN=$(printf '%s' "$RESPONSE" | python3 -c 'import json,sys; print(json.load(sys.stdin)["token"])')
export GITHUB_TOKEN
unset RESPONSE

API="https://api.github.com"
AUTH_HEADER="Authorization: Bearer ${GITHUB_TOKEN}"
ACCEPT_HEADER="Accept: application/vnd.github+json"
VERSION_HEADER="X-GitHub-Api-Version: 2022-11-28"

printf '\n=== Create or reuse GitHub prerelease ===\n'
HTTP_CODE=$(curl --silent --show-error \
  --output "$WORK_DIR/release.json" \
  --write-out '%{http_code}' \
  --header "$AUTH_HEADER" \
  --header "$ACCEPT_HEADER" \
  --header "$VERSION_HEADER" \
  "${API}/repos/${REPO}/releases/tags/${TAG}")

if [[ "$HTTP_CODE" == "404" ]]; then
  python3 - "$TAG" "$SOURCE_SHA" "$RELEASE_NAME" "$BUILD_URL" "$JARNSEN_VERSION" "$BUILD_NUMBER" > "$WORK_DIR/create-release.json" <<'PY'
import json
import sys

tag, source_sha, name, build_url, version, build_number = sys.argv[1:]
body = f"""Automatisch veröffentlichte Firmware aus dem erfolgreichen JARN-MESH Unified-Core Build.

Version: {version}
Buildkite Build: #{build_number}
Source SHA: {source_sha}
Build: {build_url}

Enthalten sind Factory-, Update- und Webflasher-BINs für alle sechs unterstützten Boards sowie BUILD-INFO.txt und SHA256SUMS.txt.
"""
json.dump({
    "tag_name": tag,
    "target_commitish": source_sha,
    "name": name,
    "body": body,
    "draft": False,
    "prerelease": True,
    "make_latest": "false",
}, sys.stdout)
PY

  curl --fail-with-body --silent --show-error \
    --request POST \
    --header "$AUTH_HEADER" \
    --header "$ACCEPT_HEADER" \
    --header "$VERSION_HEADER" \
    --header "Content-Type: application/json" \
    --data-binary "@$WORK_DIR/create-release.json" \
    "${API}/repos/${REPO}/releases" > "$WORK_DIR/release.json"
elif [[ "$HTTP_CODE" != "200" ]]; then
  printf 'GitHub release lookup failed with HTTP %s\n' "$HTTP_CODE" >&2
  cat "$WORK_DIR/release.json" >&2 || true
  exit 1
fi

RELEASE_ID=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["id"])' "$WORK_DIR/release.json")
RELEASE_URL=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["html_url"])' "$WORK_DIR/release.json")

curl --fail-with-body --silent --show-error \
  --header "$AUTH_HEADER" \
  --header "$ACCEPT_HEADER" \
  --header "$VERSION_HEADER" \
  "${API}/repos/${REPO}/releases/${RELEASE_ID}/assets?per_page=100" > "$WORK_DIR/assets.json"

declare -A EXISTING_ASSET_IDS
while IFS=$'\t' read -r asset_id asset_name; do
  [[ -n "$asset_id" && -n "$asset_name" ]] || continue
  EXISTING_ASSET_IDS["$asset_name"]="$asset_id"
done < <(python3 - "$WORK_DIR/assets.json" <<'PY'
import json
import sys
for asset in json.load(open(sys.argv[1])):
    print(f'{asset["id"]}\t{asset["name"]}')
PY
)

printf '\n=== Upload firmware to GitHub Release ===\n'
for file in "$PUBLISH_DIR"/*; do
  name=$(basename "$file")
  if [[ -n "${EXISTING_ASSET_IDS[$name]:-}" ]]; then
    curl --fail-with-body --silent --show-error \
      --request DELETE \
      --header "$AUTH_HEADER" \
      --header "$ACCEPT_HEADER" \
      --header "$VERSION_HEADER" \
      "${API}/repos/${REPO}/releases/assets/${EXISTING_ASSET_IDS[$name]}" >/dev/null
  fi

  encoded_name=$(python3 - "$name" <<'PY'
import sys
from urllib.parse import quote
print(quote(sys.argv[1], safe=""))
PY
)

  printf 'Uploading %s\n' "$name"
  curl --fail-with-body --silent --show-error \
    --request POST \
    --header "$AUTH_HEADER" \
    --header "$ACCEPT_HEADER" \
    --header "$VERSION_HEADER" \
    --header "Content-Type: application/octet-stream" \
    --data-binary "@$file" \
    "https://uploads.github.com/repos/${REPO}/releases/${RELEASE_ID}/assets?name=${encoded_name}" >/dev/null
done

printf '\nGitHub release published: %s\n' "$RELEASE_URL"
buildkite-agent annotate \
  --style success \
  --context github-release \
  "Firmware is available centrally on GitHub: [${RELEASE_NAME}](${RELEASE_URL})"
