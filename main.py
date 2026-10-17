import re
import sys
from threading import Lock

from pynput import keyboard, mouse
from PySide6.QtCore import QObject, QPoint, QRect, Qt, Signal
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QApplication, QWidget


MODIFIERS = {
    "alt",
    "alt_gr",
    "alt_l",
    "alt_r",
    "cmd",
    "cmd_l",
    "cmd_r",
    "ctrl",
    "ctrl_l",
    "ctrl_r",
    "shift",
    "shift_l",
    "shift_r",
}
SPECIAL_KEYS = {
    "backspace",
    "caps_lock",
    "delete",
    "down",
    "end",
    "enter",
    "esc",
    "home",
    "insert",
    "left",
    "page_down",
    "page_up",
    "right",
    "space",
    "tab",
    "up",
}
ALIASES = {"control": "ctrl", "option": "alt", "command": "cmd", "win": "cmd", "windows": "cmd"}


def parse_hotkey(value: str) -> set:
    parts = [part.strip().strip("<>").lower() for part in value.split("+")]
    if len(parts) < 2 or any(not part for part in parts):
        raise ValueError("Enter at least one modifier key and one additional key.")

    parts = [ALIASES.get(part, part) for part in parts]
    if len(set(parts)) != len(parts):
        raise ValueError("Each key may only appear once.")
    if not any(part in MODIFIERS for part in parts) or all(part in MODIFIERS for part in parts):
        raise ValueError("The combination must include a modifier key and a normal key.")

    hotkey_parts = []
    for part in parts:
        if part in MODIFIERS or part in SPECIAL_KEYS or re.fullmatch(r"f([1-9]|1[0-9]|20)", part):
            hotkey_parts.append(f"<{part}>")
        else:
            hotkey_parts.append(part)

    return set(keyboard.HotKey.parse("+".join(hotkey_parts)))


class BlackBarOverlay(QWidget):
    def __init__(self) -> None:
        super().__init__()
        bounds = QRect(QApplication.screens()[0].geometry())
        for screen in QApplication.screens()[1:]:
            bounds = bounds.united(screen.geometry())
        self._desktop_bounds = bounds
        self._rectangle: QRect | None = None
        self._preview = False

        flags = (
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.WindowTransparentForInput
            | Qt.WindowType.WindowDoesNotAcceptFocus
            | Qt.WindowType.Tool
        )
        self.setWindowFlags(flags)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setGeometry(bounds)

    def begin_drag(self, x: int, y: int) -> None:
        self._rectangle = QRect(QPoint(x, y), QPoint(x, y))
        self._preview = True
        self.update()

    def update_drag(self, x: int, y: int) -> None:
        if self._rectangle is None or not self._preview:
            return
        self._rectangle.setBottomRight(QPoint(x, y))
        self.update()

    def finish_drag(self, x: int, y: int) -> None:
        if self._rectangle is None or not self._preview:
            return
        self._rectangle.setBottomRight(QPoint(x, y))
        self._preview = False
        self.update()

    def paintEvent(self, _event) -> None:
        if self._rectangle is None:
            return
        rectangle = self._rectangle.normalized().translated(
            -self._desktop_bounds.x(), -self._desktop_bounds.y()
        )
        painter = QPainter(self)
        painter.fillRect(rectangle, QColor(0, 0, 0, 255))


class OverlayEvents(QObject):
    begin_drag = Signal(int, int)
    update_drag = Signal(int, int)
    finish_drag = Signal(int, int)


class GlobalInputController:
    def __init__(self, hotkey: set, events: OverlayEvents) -> None:
        self._events = events
        self._hotkey_keys = hotkey
        self._pressed_keys = set()
        self._hotkey_lock = Lock()
        self._dragging = False

        self._keyboard_listener = keyboard.Listener(
            on_press=self._on_key_press,
            on_release=self._on_key_release,
        )
        self._mouse_listener = mouse.Listener(
            on_move=self._on_move,
            on_click=self._on_click,
        )

    def _on_key_press(self, key) -> None:
        with self._hotkey_lock:
            self._pressed_keys.add(self._keyboard_listener.canonical(key))

    def _on_key_release(self, key) -> None:
        with self._hotkey_lock:
            self._pressed_keys.discard(self._keyboard_listener.canonical(key))

    def _on_move(self, x: int, y: int) -> None:
        if self._dragging:
            self._events.update_drag.emit(x, y)

    def _on_click(self, x: int, y: int, button, pressed: bool) -> None:
        if button != mouse.Button.left:
            return

        if pressed:
            with self._hotkey_lock:
                can_start = self._hotkey_keys.issubset(self._pressed_keys)
            if can_start:
                self._dragging = True
                self._events.begin_drag.emit(x, y)
        elif self._dragging:
            self._dragging = False
            self._events.finish_drag.emit(x, y)

    def start(self) -> None:
        self._keyboard_listener.start()
        self._mouse_listener.start()

    def stop(self) -> None:
        self._keyboard_listener.stop()
        self._mouse_listener.stop()


def main() -> int:
    while True:
        try:
            hotkey = parse_hotkey(input("Hotkey (e.g. ctrl+alt+b): "))
            break
        except ValueError as error:
            print(f"Invalid combination: {error}")
        except (EOFError, KeyboardInterrupt):
            print()
            return 0

    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    overlay = BlackBarOverlay()
    events = OverlayEvents()
    events.begin_drag.connect(overlay.begin_drag)
    events.update_drag.connect(overlay.update_drag)
    events.finish_drag.connect(overlay.finish_drag)
    controller = GlobalInputController(hotkey, events)
    overlay.show()
    print("Ready. Hold the hotkey and drag with the left mouse button; exit with Ctrl+C.")

    try:
        controller.start()
        return app.exec()
    except KeyboardInterrupt:
        return 0
    except Exception as error:
        print(f"Input listeners could not be started: {error}", file=sys.stderr)
        return 1
    finally:
        controller.stop()
        overlay.close()


if __name__ == "__main__":
    raise SystemExit(main())