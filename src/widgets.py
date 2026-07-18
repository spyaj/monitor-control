from __future__ import annotations

from typing import Callable

import gi

from .constants import SLIDER_DEBOUNCE_MS

gi.require_version("Adw", "1")
gi.require_version("Gtk", "4.0")
from gi.repository import Adw, GLib, Gtk  # noqa: E402


class DebouncedSliderRow(Adw.ActionRow):
    def __init__(
        self,
        title: str,
        on_change: Callable[[int], None],
        *,
        minimum: int = 0,
        maximum: int = 100,
        step: int = 1,
        value_css_class: str | None = None,
        scale_css_class: str | None = None,
    ) -> None:
        super().__init__(title=title)
        self._on_change = on_change
        self._timer_id: int | None = None
        self._suppress_emit = False
        self._repeat_timer_id: int | None = None
        self._repeat_step = 0
        self._minimum = minimum
        self._maximum = maximum

        self._value_label = Gtk.Label(label="--")
        self._value_label.add_css_class("dim-label")
        if value_css_class:
            self._value_label.add_css_class(value_css_class)

        self._scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, minimum, maximum, step)
        self._scale.set_draw_value(False)
        self._scale.set_size_request(140, -1)
        self._scale.connect("value-changed", self._on_scale_changed)
        self._scale.set_sensitive(False)
        if scale_css_class:
            self._scale.add_css_class(scale_css_class)
        self._disable_scroll_wheel_changes()

        self._decrease_button = Gtk.Button(icon_name="list-remove-symbolic")
        self._decrease_button.add_css_class("flat")
        self._decrease_button.add_css_class("circular")
        self._decrease_button.add_css_class("stepper-button")
        self._decrease_button.set_size_request(18, 18)
        self._decrease_button.set_focus_on_click(False)
        self._decrease_button.set_sensitive(False)
        self._attach_stepper_behavior(self._decrease_button, -1)

        self._increase_button = Gtk.Button(icon_name="list-add-symbolic")
        self._increase_button.add_css_class("flat")
        self._increase_button.add_css_class("circular")
        self._increase_button.add_css_class("stepper-button")
        self._increase_button.set_size_request(18, 18)
        self._increase_button.set_focus_on_click(False)
        self._increase_button.set_sensitive(False)
        self._attach_stepper_behavior(self._increase_button, 1)

        self.add_suffix(self._decrease_button)
        self.add_suffix(self._scale)
        self.add_suffix(self._increase_button)
        self.add_suffix(self._value_label)
        self.set_activatable(False)

    def set_value(self, value: int) -> None:
        self._suppress_emit = True
        bounded = max(self._minimum, min(self._maximum, value))
        self._scale.set_value(bounded)
        self._value_label.set_label(self._format_value(bounded))
        self._scale.set_sensitive(True)
        self._decrease_button.set_sensitive(True)
        self._increase_button.set_sensitive(True)
        self._suppress_emit = False

    def _on_scale_changed(self, scale: Gtk.Scale) -> None:
        value = int(scale.get_value())
        self._value_label.set_label(self._format_value(value))
        if self._suppress_emit:
            return

        if self._timer_id:
            GLib.source_remove(self._timer_id)

        def emit() -> bool:
            self._timer_id = None
            self._on_change(value)
            return GLib.SOURCE_REMOVE

        self._timer_id = GLib.timeout_add(SLIDER_DEBOUNCE_MS, emit)

    def allow_manual_control(self) -> None:
        self._scale.set_sensitive(True)
        self._decrease_button.set_sensitive(True)
        self._increase_button.set_sensitive(True)

    def set_bounds(self, minimum: int, maximum: int) -> None:
        if maximum < minimum:
            return
        self._minimum = minimum
        self._maximum = maximum
        self._scale.set_range(minimum, maximum)
        current = int(self._scale.get_value())
        bounded = max(minimum, min(maximum, current))
        self._suppress_emit = True
        self._scale.set_value(bounded)
        self._value_label.set_label(self._format_value(bounded))
        self._suppress_emit = False

    def commit_pending(self) -> None:
        if not self._timer_id:
            return
        GLib.source_remove(self._timer_id)
        self._timer_id = None
        self._on_change(int(self._scale.get_value()))

    def _disable_scroll_wheel_changes(self) -> None:
        controller = Gtk.EventControllerScroll.new(
            Gtk.EventControllerScrollFlags.VERTICAL | Gtk.EventControllerScrollFlags.HORIZONTAL
        )
        controller.connect("scroll", self._on_scroll)
        self._scale.add_controller(controller)

    def _on_scroll(self, _controller: Gtk.EventControllerScroll, _dx: float, _dy: float) -> bool:
        return True

    def _attach_stepper_behavior(self, button: Gtk.Button, step: int) -> None:
        gesture = Gtk.GestureClick.new()
        gesture.set_button(1)
        gesture.connect("pressed", lambda *_args: self._start_repeat(step))
        gesture.connect("released", lambda *_args: self._stop_repeat())
        gesture.connect("cancel", lambda *_args: self._stop_repeat())
        button.add_controller(gesture)

    def _apply_step(self, step: int) -> None:
        current = int(self._scale.get_value())
        self._scale.set_value(max(self._minimum, min(self._maximum, current + step)))

    def _format_value(self, value: int) -> str:
        if self._minimum == 0 and self._maximum == 100:
            return f"{value}%"
        if self._minimum == 0 and self._maximum > 0:
            return f"{value}/{self._maximum}"
        return str(value)

    def _start_repeat(self, step: int) -> None:
        self._stop_repeat()
        self._repeat_step = step
        self._apply_step(step)

        def start_fast_repeat() -> bool:
            self._repeat_timer_id = GLib.timeout_add(60, self._repeat_tick)
            return GLib.SOURCE_REMOVE

        self._repeat_timer_id = GLib.timeout_add(350, start_fast_repeat)

    def _repeat_tick(self) -> bool:
        self._apply_step(self._repeat_step)
        return GLib.SOURCE_CONTINUE

    def _stop_repeat(self) -> None:
        if self._repeat_timer_id:
            GLib.source_remove(self._repeat_timer_id)
            self._repeat_timer_id = None
