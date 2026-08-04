from pathlib import Path
import re


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise SystemExit(f"Patch anchor missing: {label}")
    return text.replace(old, new, 1)


thread_path = Path("src/graphics/TacticalDisplayMirrorThread.cpp")
thread_path.write_text(
    r'''#include "TacticalDisplayMirrorThread.h"

#if defined(HAS_TACTICAL_DISPLAY_MIRROR) && HAS_TACTICAL_DISPLAY_MIRROR && HAS_SCREEN

#include "TacticalDisplayMirror.h"
#include "graphics/Screen.h"
#include "input/InputBroker.h"
#include "main.h"

#include <Arduino.h>
#include <cstdlib>
#include <cstring>

namespace graphics
{
namespace
{
constexpr size_t COMMAND_BUFFER_SIZE = 96;
constexpr uint32_t PAGE_NAVIGATION_INTERVAL_MS = 240;
constexpr uint32_t MENU_NAVIGATION_INTERVAL_MS = 110;
constexpr uint32_t ACTION_INTERVAL_MS = 180;

enum class MirrorInputClass : uint8_t { PAGE, MENU, ACTION };

struct PendingMirrorInput {
    bool valid = false;
    bool hasRequestId = false;
    uint32_t requestId = 0;
    input_broker_event eventType = INPUT_BROKER_NONE;
    MirrorInputClass inputClass = MirrorInputClass::ACTION;
};

char commandBuffer[COMMAND_BUFFER_SIZE];
size_t commandLength = 0;
bool discardUntilNewline = false;
PendingMirrorInput pendingInput;
uint32_t lastPageInputAt = 0;
uint32_t lastMenuInputAt = 0;
uint32_t lastActionInputAt = 0;

bool injectMirrorInput(input_broker_event eventType)
{
    if (!inputBroker)
        return false;

    const InputEvent event{
        .source = "usb-display-mirror",
        .inputEvent = eventType,
        .kbchar = 0,
        .touchX = 0,
        .touchY = 0,
    };
#if defined(HAS_FREE_RTOS) && !defined(ARCH_RP2040)
    inputBroker->queueInputEvent(&event);
#else
    inputBroker->injectInputEvent(&event);
#endif
    return true;
}

void emitMirrorAck(uint32_t requestId, const char *status)
{
    Serial.printf("@TMA %lu %s %lu\n", static_cast<unsigned long>(requestId), status,
                  static_cast<unsigned long>(millis()));
}

bool resolveMirrorKey(const char *key, input_broker_event &eventType, MirrorInputClass &inputClass)
{
    if (strcmp(key, "LEFT") == 0) {
        eventType = INPUT_BROKER_LEFT;
        inputClass = MirrorInputClass::PAGE;
    } else if (strcmp(key, "RIGHT") == 0) {
        eventType = INPUT_BROKER_RIGHT;
        inputClass = MirrorInputClass::PAGE;
    } else if (strcmp(key, "UP") == 0) {
        eventType = INPUT_BROKER_UP;
        inputClass = MirrorInputClass::MENU;
    } else if (strcmp(key, "DOWN") == 0) {
        eventType = INPUT_BROKER_DOWN;
        inputClass = MirrorInputClass::MENU;
    } else if (strcmp(key, "SPACE") == 0 || strcmp(key, "SELECT") == 0 || strcmp(key, "ENTER") == 0) {
        eventType = INPUT_BROKER_SELECT;
        inputClass = MirrorInputClass::ACTION;
    } else if (strcmp(key, "BACK") == 0 || strcmp(key, "ESC") == 0) {
        eventType = INPUT_BROKER_BACK;
        inputClass = MirrorInputClass::ACTION;
    } else {
        return false;
    }
    return true;
}

void queueMirrorInput(uint32_t requestId, bool hasRequestId, input_broker_event eventType, MirrorInputClass inputClass)
{
    if (pendingInput.valid && pendingInput.hasRequestId)
        emitMirrorAck(pendingInput.requestId, "COALESCED");

    pendingInput.valid = true;
    pendingInput.hasRequestId = hasRequestId;
    pendingInput.requestId = requestId;
    pendingInput.eventType = eventType;
    pendingInput.inputClass = inputClass;
}

bool intervalElapsed(uint32_t now, uint32_t previous, uint32_t interval)
{
    return !previous || static_cast<uint32_t>(now - previous) >= interval;
}

void processPendingMirrorInput()
{
    if (!pendingInput.valid)
        return;

    const uint32_t now = millis();
    uint32_t *lastInputAt = &lastActionInputAt;
    uint32_t minimumInterval = ACTION_INTERVAL_MS;
    if (pendingInput.inputClass == MirrorInputClass::PAGE) {
        lastInputAt = &lastPageInputAt;
        minimumInterval = PAGE_NAVIGATION_INTERVAL_MS;
    } else if (pendingInput.inputClass == MirrorInputClass::MENU) {
        lastInputAt = &lastMenuInputAt;
        minimumInterval = MENU_NAVIGATION_INTERVAL_MS;
    }

    if (!intervalElapsed(now, *lastInputAt, minimumInterval))
        return;

    const PendingMirrorInput command = pendingInput;
    pendingInput = PendingMirrorInput{};

    prioritizeMirrorInput();
    const bool injected = injectMirrorInput(command.eventType);
    if (injected)
        *lastInputAt = now;
    if (command.hasRequestId)
        emitMirrorAck(command.requestId, injected ? "OK" : "NOINPUT");
}

void handleMirrorCommand(char *command)
{
    if (!command || strncmp(command, "@TMC ", 5) != 0)
        return;

    char *payload = command + 5;
    while (*payload == ' ')
        ++payload;

    if (strncmp(payload, "CAPS", 4) == 0) {
        Serial.printf("@TMA CAPS TMF3 ACK1 SAFE-NAV1 RECONNECT1\n");
        return;
    }

    uint32_t requestId = 0;
    bool hasRequestId = false;
    char *key = payload;
    char *numberEnd = nullptr;
    const unsigned long parsedId = strtoul(payload, &numberEnd, 10);
    if (numberEnd != payload && *numberEnd == ' ') {
        while (*numberEnd == ' ')
            ++numberEnd;
        if (*numberEnd != '\0') {
            requestId = static_cast<uint32_t>(parsedId);
            hasRequestId = true;
            key = numberEnd;
        }
    }

    char *keyEnd = key + strlen(key);
    while (keyEnd > key && keyEnd[-1] == ' ')
        *--keyEnd = '\0';

    input_broker_event eventType;
    MirrorInputClass inputClass;
    if (!resolveMirrorKey(key, eventType, inputClass)) {
        if (hasRequestId)
            emitMirrorAck(requestId, "ERR");
        return;
    }

    queueMirrorInput(requestId, hasRequestId, eventType, inputClass);
}

void readMirrorCommands()
{
    while (Serial.available() > 0) {
        const int value = Serial.read();
        if (value < 0)
            return;

        const char character = static_cast<char>(value);
        if (character == '\r')
            continue;

        if (character == '\n') {
            if (!discardUntilNewline) {
                commandBuffer[commandLength] = '\0';
                handleMirrorCommand(commandBuffer);
            }
            commandLength = 0;
            discardUntilNewline = false;
            continue;
        }

        if (discardUntilNewline)
            continue;

        if (commandLength + 1 < COMMAND_BUFFER_SIZE) {
            commandBuffer[commandLength++] = character;
        } else {
            commandLength = 0;
            discardUntilNewline = true;
        }
    }
}
} // namespace

TacticalDisplayMirrorThread::TacticalDisplayMirrorThread() : concurrency::OSThread("display-mirror", 5) {}

int32_t TacticalDisplayMirrorThread::runOnce()
{
    readMirrorCommands();
    processPendingMirrorInput();

    if (screen != nullptr && screen->isScreenOn())
        mirrorDisplayFrame(screen->getDisplayDevice());
    return 5;
}
} // namespace graphics

#endif
''',
    encoding="utf-8",
)

mirror_path = Path("src/graphics/TacticalDisplayMirror.cpp")
mirror = mirror_path.read_text(encoding="utf-8")
mirror = replace_once(
    mirror,
    """constexpr uint32_t MIRROR_FRAME_INTERVAL_MS = 60;
constexpr uint32_t MIRROR_ACTIVE_FRAME_INTERVAL_MS = 100;
constexpr uint32_t MIRROR_INPUT_PRIORITY_MS = 8;
constexpr uint32_t MIRROR_INPUT_BURST_MS = 260;""",
    """constexpr uint32_t MIRROR_FRAME_INTERVAL_MS = 50;
constexpr uint32_t MIRROR_ACTIVE_FRAME_INTERVAL_MS = 160;
constexpr uint32_t MIRROR_INPUT_PRIORITY_MS = 180;
constexpr uint32_t MIRROR_INPUT_BURST_MS = 420;""",
    "mirror timing constants",
)
mirror, count = re.subn(
    r"""void prioritizeMirrorInput\(\)
\{
.*?
\}

void mirrorDisplayFrame""",
    """void prioritizeMirrorInput()
{
    const uint32_t now = millis();
    lastInputAt = now;
    inputPriorityUntil = now + MIRROR_INPUT_PRIORITY_MS;
    lastFrameCompletedAt = now;

    // Every accepted control event cancels the old partial image. This keeps
    // stale USB chunks and page transitions away from the normal UI input path.
    clearPendingFrame();
    havePreviousMono = false;
    {
        concurrency::LockGuard guard(&colorLock);
        emittedColorSequence = colorSequence;
    }
}

void mirrorDisplayFrame""",
    mirror,
    count=1,
    flags=re.S,
)
if count != 1:
    raise SystemExit("Patch anchor missing: prioritizeMirrorInput")
mirror_path.write_text(mirror, encoding="utf-8")

viewer_path = Path("tools/tactical-display-mirror/tactical_display_mirror.py")
viewer = viewer_path.read_text(encoding="utf-8")
viewer = replace_once(
    viewer,
    "from PIL import Image, ImageTk",
    "from PIL import Image, ImageFilter, ImageTk",
    "Pillow imports",
)
viewer = replace_once(
    viewer,
    """RENDER_DEBOUNCE_MS = 12
KEY_REPEAT_DELAY_MS = 180
KEY_REPEAT_INTERVAL_MS = 45
MAX_NAVIGATION_IN_FLIGHT = 2""",
    """RENDER_DEBOUNCE_MS = 8
KEY_REPEAT_DELAY_MS = 300
KEY_REPEAT_INTERVAL_MS = 110
MAX_NAVIGATION_IN_FLIGHT = 1
SERIAL_LINE_LIMIT = 4096
RECONNECT_DELAY_SECONDS = 1.0""",
    "viewer timing constants",
)
viewer = replace_once(
    viewer,
    'REPEATABLE_COMMANDS = frozenset({"LEFT", "RIGHT", "UP", "DOWN"})',
    'REPEATABLE_COMMANDS = frozenset({"LEFT", "RIGHT", "UP", "DOWN"})\nACCEPTED_ACK_STATUSES = frozenset({"OK", "QUEUED", "COALESCED"})',
    "accepted ACK statuses",
)
viewer = replace_once(
    viewer,
    """    def __init__(self) -> None:
        self._assemblies: Dict[Tuple[str, int], _ChunkAssembly] = {}""",
    """    def __init__(self) -> None:
        self._assemblies: Dict[Tuple[str, int], _ChunkAssembly] = {}
        self._latest_sequence: Dict[str, Optional[int]] = {"M": None, "C": None}""",
    "decoder sequence state",
)
viewer = replace_once(
    viewer,
    """        now = time.monotonic()
        self._discard_stale(now)
        key = (mode, sequence)""",
    """        latest_sequence = self._latest_sequence[mode]
        if latest_sequence is not None and sequence != latest_sequence:
            delta = (sequence - latest_sequence) & 0xFFFFFFFF
            if delta == 0 or delta >= 0x80000000:
                return None
        if latest_sequence != sequence:
            self._latest_sequence[mode] = sequence

        now = time.monotonic()
        self._discard_stale(now)
        key = (mode, sequence)""",
    "decoder stale sequence guard",
)
viewer = replace_once(
    viewer,
    '        self.next_command_id = 1\n\n        self.connection_state = "Verbinde"',
    '        self.next_command_id = 1\n        self.reconnect_count = 0\n        self.ever_connected = False\n\n        self.connection_state = "Verbinde"',
    "reconnect state",
)
viewer = viewer.replace('"HD geglättet"', '"HD klar"')
viewer = viewer.replace('values=("Pixel scharf", "HD klar")', 'values=("Pixel exakt", "HD klar")')
viewer = viewer.replace('else "Pixel scharf"', 'else "Pixel exakt"')

reader_pattern = re.compile(
    r"""    def _reader_loop\(self\) -> None:
.*?
    def _writer_loop\(self\) -> None:""",
    re.S,
)
reader_replacement = """    def _reader_loop(self) -> None:
        while not self.stop_event.is_set():
            decoder = FrameDecoder()
            port: Optional[serial.Serial] = None
            try:
                self.connection_state = (
                    "Verbinde" if not self.ever_connected else "Neu verbinden"
                )
                port = serial.Serial(
                    self.port,
                    self.baudrate,
                    timeout=0.15,
                    write_timeout=0.05,
                )
                with self.serial_lock:
                    self.serial_port = port
                if self.ever_connected:
                    self.reconnect_count += 1
                self.ever_connected = True
                self.connection_state = "Verbunden"
                self._queue_wire_message(b"@TMC CAPS TMF3 ACK1\\n", priority=-100)
                self._put_message(
                    f"Verbunden: {self.port} @ {self.baudrate} Baud"
                )

                while not self.stop_event.is_set():
                    raw = port.read_until(b"\\n", SERIAL_LINE_LIMIT)
                    if not raw:
                        continue
                    if len(raw) >= SERIAL_LINE_LIMIT and not raw.endswith(b"\\n"):
                        port.reset_input_buffer()
                        self._put_message("Zu lange USB-Zeile verworfen")
                        continue

                    ack = parse_ack(raw)
                    if ack is not None:
                        self._handle_ack(*ack)
                        continue

                    frame = decoder.feed(raw)
                    if frame is not None:
                        self._publish_newest_frame(frame)
            except (serial.SerialException, OSError) as exc:
                if not self.stop_event.is_set():
                    self.connection_state = "Getrennt"
                    self._put_message(
                        f"USB getrennt: {exc} - automatischer Neuaufbau"
                    )
            finally:
                with self.serial_lock:
                    if self.serial_port is port:
                        self.serial_port = None
                if port is not None and port.is_open:
                    try:
                        port.close()
                    except (serial.SerialException, OSError):
                        pass
                self._clear_transport_state()

            if not self.stop_event.is_set():
                self.stop_event.wait(RECONNECT_DELAY_SECONDS)

    def _clear_transport_state(self) -> None:
        with self.pending_lock:
            self.pending_commands.clear()
        with self.coalesce_lock:
            self.coalesce_generation.clear()
        while True:
            try:
                self.outgoing.get_nowait()
            except queue.Empty:
                break

    def _writer_loop(self) -> None:"""
viewer, count = reader_pattern.subn(lambda _match: reader_replacement, viewer, count=1)
if count != 1:
    raise SystemExit("Patch anchor missing: reader loop")

viewer = replace_once(
    viewer,
    '        if status != "OK":\n            self._put_message(f"Tracker-ACK {request_id}: {status}")',
    '        if status not in ACCEPTED_ACK_STATUSES:\n            self._put_message(f"Tracker-ACK {request_id}: {status}")',
    "ACK handling",
)
viewer = replace_once(
    viewer,
    """            f"Frame-Alter {frame_age} | USB-RTT {latency}"
        )""",
    """            f"Frame-Alter {frame_age} | USB-RTT {latency} | "
            f"Neuverbunden {self.reconnect_count}x"
        )""",
    "status reconnect counter",
)

render_pattern = re.compile(
    r"""    def _render_current\(self\) -> None:
.*?
    def _toggle_fullscreen""",
    re.S,
)
render_replacement = """    def _render_current(self) -> None:
        self.render_after_id = None
        image = self.last_native_image
        if image is None:
            return

        canvas_width = max(1, self.canvas.winfo_width())
        canvas_height = max(1, self.canvas.winfo_height())
        scale = min(canvas_width / image.width, canvas_height / image.height)

        if self.render_mode.get() == "Pixel exakt" and scale >= 1.0:
            integer_scale = max(1, int(scale))
            target_width = image.width * integer_scale
            target_height = image.height * integer_scale
            rendered = image.resize(
                (target_width, target_height), resample=RESAMPLING.NEAREST
            )
        else:
            target_width = max(1, int(round(image.width * scale)))
            target_height = max(1, int(round(image.height * scale)))
            if scale >= 1.0:
                integer_scale = max(1, int(scale))
                prescaled = image.resize(
                    (image.width * integer_scale, image.height * integer_scale),
                    resample=RESAMPLING.NEAREST,
                )
                rendered = prescaled.resize(
                    (target_width, target_height), resample=RESAMPLING.BICUBIC
                )
                rendered = rendered.filter(
                    ImageFilter.UnsharpMask(radius=0.8, percent=180, threshold=1)
                )
            else:
                rendered = image.resize(
                    (target_width, target_height), resample=RESAMPLING.LANCZOS
                )

        self.photo_slot ^= 1
        photo = ImageTk.PhotoImage(rendered)
        self.photo_buffers[self.photo_slot] = photo
        self.canvas.coords(self.canvas_image, canvas_width // 2, canvas_height // 2)
        self.canvas.itemconfigure(self.canvas_image, image=photo)

    def _toggle_fullscreen"""
viewer, count = render_pattern.subn(lambda _match: render_replacement, viewer, count=1)
if count != 1:
    raise SystemExit("Patch anchor missing: render function")

viewer = viewer.replace(
    'help="Darstellung: pixel = scharf, hd = geglättet",',
    'help="Darstellung: pixel = exakt, hd = klar hochskaliert",',
)
viewer_path.write_text(viewer, encoding="utf-8")

launcher_path = Path("tools/tactical-display-mirror/START-DISPLAY-MIRROR-WINDOWS.bat")
launcher = launcher_path.read_text(encoding="utf-8")
launcher = launcher.replace("1 = Pixel scharf", "1 = Pixel exakt")
launcher = launcher.replace("2 = HD geglaettet", "2 = HD klar")
launcher_path.write_text(launcher, encoding="utf-8", newline="")

readme_path = Path("tools/tactical-display-mirror/README.md")
readme = readme_path.read_text(encoding="utf-8")
readme = readme.replace(
    "sharp pixel mode and smoothed HD mode",
    "pixel-exact mode and sharpened clear-HD mode",
)
readme = readme.replace("180 ms / 45 ms", "300 ms / 110 ms")
readme = readme.replace(
    "at most two commands in flight",
    "only one navigation command in flight",
)
readme = readme.replace(
    "`Pixel scharf` or `HD geglaettet`",
    "`Pixel exakt` or `HD klar`",
)
readme = readme.replace("### Pixel sharp", "### Pixel exact")
readme = readme.replace("### HD smoothed", "### Clear HD")
readme = readme.replace(
    "Uses high-quality Lanczos scaling. It is visually smoother in a large window or fullscreen, while the underlying tracker frame remains unchanged.",
    "Uses an integer nearest-neighbour pre-scale, a light bicubic final fit and controlled unsharp masking. Small fonts stay substantially clearer without changing the tracker framebuffer.",
)
stability_note = """
## Page-change stability

- Left/right page changes are firmware-throttled to one accepted event every 240 ms.
- Up/down menu movement remains faster at 110 ms.
- ACKs are sent only when an event is admitted to the normal InputBroker path, so the PC cannot flood page transitions.
- Every accepted input cancels a partial USB frame and waits for a fresh settled frame.
- The Windows viewer automatically reconnects after a tracker reset or temporary USB disconnect and discards stale queued controls.
- Serial lines are size-bounded and stale frame sequences are ignored.
"""
if "## Page-change stability" not in readme:
    readme = readme.rstrip() + "\n" + stability_note
readme_path.write_text(readme, encoding="utf-8")
