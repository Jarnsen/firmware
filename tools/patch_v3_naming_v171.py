from pathlib import Path

workflow_path = Path('.github/workflows/build-heltec-v3-repeater-light-sleep.yml')
workflow = workflow_path.read_text(encoding='utf-8')
replacements = [
    ('name: Build Heltec V3 Repeater - JARN-MESH V3 v1.7.1\n', 'name: Build Heltec V3 Repeater\nrun-name: "Heltec V3 Repeater - JARN-MESH V3 Repeater v1.7.1"\n'),
    ('  V3_PRODUCT: "JARN-MESH V3"\n', '  V3_PRODUCT: "JARN-MESH V3 Repeater"\n'),
    ('      - name: Download verified shared Node Service Tool\n        shell: pwsh\n', '      - name: Download verified shared Node Service Tool\n        id: shared_tool\n        shell: pwsh\n'),
    ('          Write-Host "Shared Node Service Tool v$($manifest.version) SHA256=$hash"\n          New-Item -ItemType Directory -Force app-artifact | Out-Null\n', '          Write-Host "Shared Node Service Tool v$($manifest.version) SHA256=$hash"\n          Add-Content -Path $env:GITHUB_OUTPUT -Value "version=$($manifest.version)" -Encoding utf8\n          New-Item -ItemType Directory -Force app-artifact | Out-Null\n'),
    ('          name: v3-service-tool-part\n', '          name: v3-service-tool-v${{ steps.shared_tool.outputs.version }}-part\n'),
    ('          assert f"name: Build Heltec V3 Repeater - JARN-MESH V3 v{version}" in workflow\n', '          assert "name: Build Heltec V3 Repeater" in workflow\n          assert f\'run-name: "Heltec V3 Repeater - JARN-MESH V3 Repeater v{version}"\' in workflow\n'),
    ('          assert f\'#define JARNSEN_V3_FIRMWARE_VERSION "JARN-MESH V3 v{version}"\' in build_info\n', '          assert f\'#define JARNSEN_V3_FIRMWARE_VERSION "JARN-MESH V3 Repeater v{version}"\' in build_info\n'),
    ('          printf \'#pragma once\\n#define JARNSEN_V3_FIRMWARE_SEMVER "v%s"\\n#define JARNSEN_V3_FIRMWARE_VERSION "JARN-MESH V3 v%s"\\n#define JARNSEN_V3_BUILD_SHA "%s"\\n#define JARNSEN_V3_BUILD_NUMBER %s\\n\' \\\n            "$V3_VERSION" "$V3_VERSION" "$SHORT_SHA" "$GITHUB_RUN_NUMBER" > src/infrastructure/HeltecV3BuildGenerated.h\n', '          printf \'#pragma once\\n#define JARNSEN_V3_FIRMWARE_SEMVER "v%s"\\n#define JARNSEN_V3_FIRMWARE_VERSION "%s v%s"\\n#define JARNSEN_V3_BUILD_SHA "%s"\\n#define JARNSEN_V3_BUILD_NUMBER %s\\n\' \\\n            "$V3_VERSION" "$V3_PRODUCT" "$V3_VERSION" "$SHORT_SHA" "$GITHUB_RUN_NUMBER" > src/infrastructure/HeltecV3BuildGenerated.h\n'),
    ('PREFIX="heltec-v3-jarn-mesh-v${V3_VERSION}"', 'PREFIX="heltec-v3-repeater-jarn-mesh-v${V3_VERSION}"'),
    ('            "product": "JARN-MESH V3",\n', '            "product": "${V3_PRODUCT}",\n'),
    ('            "display_version": "JARN-MESH V3 v${V3_VERSION}",\n', '            "display_version": "${V3_PRODUCT} v${V3_VERSION}",\n'),
    ('          name: heltec-v3-jarn-mesh-v${{ env.V3_VERSION }}-build-${{ github.run_number }}\n', '          name: heltec-v3-repeater-jarn-mesh-v${{ env.V3_VERSION }}-build-${{ github.run_number }}\n'),
    ('--title "Heltec V3 - JARN-MESH V3 v${V3_VERSION}"', '--title "Heltec V3 Repeater - ${V3_PRODUCT} v${V3_VERSION}"'),
    ('--notes "Automatisch geprüftes V3-Update JARN-MESH V3 v${V3_VERSION}, Build ${GITHUB_RUN_NUMBER}."', '--notes "Automatisch geprüftes V3-Repeater-Update ${V3_PRODUCT} v${V3_VERSION}, Build ${GITHUB_RUN_NUMBER}."'),
]
for old, new in replacements:
    count = workflow.count(old)
    if count == 0:
        raise SystemExit(f'Expected workflow anchor not found: {old[:120]!r}')
    workflow = workflow.replace(old, new)
workflow_path.write_text(workflow, encoding='utf-8')

build_info_path = Path('src/infrastructure/HeltecV3BuildInfo.h')
build_info = build_info_path.read_text(encoding='utf-8')
old = '#define JARNSEN_V3_FIRMWARE_VERSION "JARN-MESH V3 v1.7.1"'
new = '#define JARNSEN_V3_FIRMWARE_VERSION "JARN-MESH V3 Repeater v1.7.1"'
if old not in build_info:
    raise SystemExit('V3 BuildInfo version anchor not found')
build_info_path.write_text(build_info.replace(old, new, 1), encoding='utf-8')

print('V3 naming migration prepared: JARN-MESH V3 Repeater v1.7.1')
