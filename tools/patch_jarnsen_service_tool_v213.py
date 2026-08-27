"""v2.1.3: ask selected-vs-all for BLE log downloads and skip failed nodes."""
from __future__ import annotations

import re
import sys
from pathlib import Path

APP_VERSION = "2.1.3"


def method_span(text: str, name: str) -> tuple[int, int]:
    start = text.find(f"    def {name}(")
    if start < 0:
        raise SystemExit(f"method {name} not found")
    next_method = text.find("\n    def ", start + 1)
    next_decorator = text.find("\n    @", start + 1)
    candidates = [value for value in (next_method, next_decorator) if value >= 0]
    return start, min(candidates) if candidates else len(text)


def replace_method(text: str, name: str, updater) -> str:
    start, end = method_span(text, name)
    return text[:start] + updater(text[start:end]) + text[end:]


def patch(source: str) -> str:
    source = re.sub(r'APP_VERSION = "[^"]+"', f'APP_VERSION = "{APP_VERSION}"', source, count=1)
    source = source.replace('APP_VERSION != "2.1.2"', 'APP_VERSION != "2.1.3"')
    source = source.replace("App-Version ist nicht v2.1.2", "App-Version ist nicht v2.1.3")

    def patch_continue(method: str) -> str:
        if "BLE_MULTI_DOWNLOAD_PROMPT" in method:
            return method
        anchor = '''        if not action or (self.worker and self.worker.is_alive()):\n            return\n'''
        if method.count(anchor) != 1:
            raise SystemExit("smart-action guard anchor not found")
        multi = anchor + r'''        # Log downloads are the one workflow where multiple discovered Nodes
        # are useful. Ask explicitly instead of silently picking one Node.
        if action == "download" and len(self.ble_map) > 1:
            labels = list(self.ble_map)
            # v2.1.1 may expose unrelated named Windows BLE devices as a
            # fallback. Those are useful for manual diagnostics, but must not
            # be pulled into an automatic fleet download.
            candidates = [label for label in labels if not label.startswith("[BLE] ")]
            if len(candidates) > 1:
                self.pending_smart_action = ""
                preferred = self._preferred_ble_name().strip()
                matching = [
                    label for label in candidates
                    if preferred and preferred.lower() in label.lower()
                ]
                tool_log(
                    "BLE_MULTI_DOWNLOAD_PROMPT",
                    discovered=len(labels),
                    candidates=len(candidates),
                    preferred=preferred or "--",
                )
                choice = messagebox.askyesnocancel(
                    "Mehrere Nodes gefunden",
                    f"{len(candidates)} passende Bluetooth-Nodes wurden gefunden.\n\n"
                    "Ja = nur die oben ausgewählte Node herunterladen\n"
                    "Nein = Logs von allen gefundenen Nodes nacheinander herunterladen\n"
                    "Abbrechen = nichts herunterladen\n\n"
                    "Nicht erreichbare Nodes werden bei 'Alle' übersprungen; die Warteschlange läuft weiter.",
                )
                if choice is None:
                    tool_log("BLE_MULTI_DOWNLOAD_CHOICE", choice="cancel")
                    self.status_level = "normal"
                    self.status.configure(text="Mehrfachdownload abgebrochen")
                    self._update_status_badge()
                    return
                if choice:
                    tool_log("BLE_MULTI_DOWNLOAD_CHOICE", choice="selected", preferred=preferred or "--")
                    if len(matching) != 1:
                        if not self.advanced_visible:
                            self.toggle_advanced_controls()
                        self.show_controls_page("Bluetooth")
                        self.notebook.select(self.service_tab)
                        self.status_level = "warning"
                        self.status.configure(
                            text="Ausgewählte Node nicht eindeutig unter den BLE-Treffern gefunden – bitte Node markieren"
                        )
                        self._update_status_badge()
                        messagebox.showwarning(
                            "Ausgewählte Node nicht gefunden",
                            "Die im Kopf ausgewählte Node konnte keinem Bluetooth-Treffer eindeutig zugeordnet werden. "
                            "Es wurde nichts von einer anderen Node geladen. Bitte die gewünschte Node markieren und erneut starten.",
                        )
                        return
                    wanted = matching[0]
                    index = labels.index(wanted)
                    self.ble_device.selection_clear(0, "end")
                    self.ble_device.selection_set(index)
                    self.ble_device.see(index)
                    tool_log("BLE_MULTI_DOWNLOAD_SELECTED", node=wanted)
                    self.start_ble_download()
                    return

                self.ble_device.selection_clear(0, "end")
                selected_count = 0
                for label in candidates:
                    index = labels.index(label)
                    self.ble_device.selection_set(index)
                    selected_count += 1
                if selected_count:
                    self.ble_device.see(labels.index(candidates[0]))
                tool_log("BLE_MULTI_DOWNLOAD_CHOICE", choice="all", count=selected_count)
                self.status_level = "normal"
                self.status.configure(text=f"Mehrfachdownload: {selected_count} Nodes werden nacheinander geprüft")
                self._update_status_badge()
                self.start_ble_download()
                return
'''
        return method.replace(anchor, multi, 1)

    source = replace_method(source, "_continue_smart_action", patch_continue)

    def patch_download_worker(method: str) -> str:
        if 'tool_log("BLE_MULTI_DOWNLOAD_SKIP"' in method:
            return method
        anchor = '''                except Exception as exc:\n                    failures.append(f"{label}: {exc}")\n'''
        if method.count(anchor) != 1:
            raise SystemExit("BLE download skip anchor not found")
        replacement = '''                except Exception as exc:\n                    failures.append(f"{label}: {exc}")\n                    tool_log("BLE_MULTI_DOWNLOAD_SKIP", node=label, error=exc)\n'''
        return method.replace(anchor, replacement, 1)

    source = replace_method(source, "_ble_download_worker", patch_download_worker)

    def patch_events(method: str) -> str:
        if "Übersprungen / nicht abgeschlossen:" in method:
            return method
        old = '                        + "Fehlgeschlagen:\\n"\n'
        new = '                        + "Übersprungen / nicht abgeschlossen:\\n"\n'
        if old not in method:
            raise SystemExit("multi-download result wording anchor not found")
        return method.replace(old, new, 1)

    source = replace_method(source, "_pump_events", patch_events)

    required = (
        'APP_VERSION = "2.1.3"',
        'BLE_MULTI_DOWNLOAD_PROMPT',
        'BLE_MULTI_DOWNLOAD_CHOICE',
        'BLE_MULTI_DOWNLOAD_SELECTED',
        'BLE_MULTI_DOWNLOAD_SKIP',
        'nur die oben ausgewählte Node herunterladen',
        'Logs von allen gefundenen Nodes nacheinander herunterladen',
        'Nicht erreichbare Nodes werden bei \'Alle\' übersprungen',
        'Übersprungen / nicht abgeschlossen:',
    )
    for marker in required:
        if marker not in source:
            raise SystemExit(f"missing v2.1.3 marker: {marker}")
    return source


def main() -> None:
    target = Path(sys.argv[1] if len(sys.argv) > 1 else "tools/JARNSEN_NODE_SERVICE_TOOL.py")
    target.write_text(patch(target.read_text(encoding="utf-8")), encoding="utf-8")
    print("Service tool v2.1.3: selected/all BLE log download prompt + skip-on-failure")


if __name__ == "__main__":
    main()
