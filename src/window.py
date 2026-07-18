from __future__ import annotations

import logging
from typing import Callable

import gi

from .constants import APP_NAME, COLOR_PRESETS, POWER_MODES
from .monitor import DdcutilBackend, Monitor, MonitorInfo, VcpValue
from .widgets import DebouncedSliderRow

gi.require_version("Adw", "1")
gi.require_version("Gdk", "4.0")
gi.require_version("Gtk", "4.0")
from gi.repository import Adw, Gdk, GLib, Gtk  # noqa: E402


class MonitorControlWindow(Adw.ApplicationWindow):
    def __init__(self, app: Adw.Application) -> None:
        super().__init__(application=app, title=APP_NAME, default_width=460, default_height=620)
        self._logger = logging.getLogger(__name__)
        self._monitor = Monitor(DdcutilBackend())
        self._pending_refresh_reads = 0
        self._refresh_generation = 0
        self._refresh_failed_names: list[str] = []
        self._display_ids: list[str] = []
        self._ignore_display_dropdown_changes = False

        self._toast_overlay = Adw.ToastOverlay()
        self.set_content(self._toast_overlay)
        self._setup_styles()

        self._root_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self._toast_overlay.set_child(self._root_box)

        header = Adw.HeaderBar()
        title = Adw.WindowTitle(title=APP_NAME, subtitle="Detecting monitor...")
        header.set_title_widget(title)
        self._window_title = title
        self._refresh_button = Gtk.Button(icon_name="view-refresh-symbolic")
        self._refresh_button.set_tooltip_text("Refresh monitor values")
        self._refresh_button.connect("clicked", self._on_refresh_clicked)
        header.pack_end(self._refresh_button)
        self._root_box.append(header)

        scrolled = Gtk.ScrolledWindow(vexpand=True, hexpand=True)
        self._root_box.append(scrolled)

        clamp = Adw.Clamp(maximum_size=560, tightening_threshold=420)
        scrolled.set_child(clamp)

        viewport = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=16,
            margin_start=16,
            margin_end=16,
            margin_top=16,
            margin_bottom=16,
        )
        clamp.set_child(viewport)

        self._display_group = Adw.PreferencesGroup(title="🖥 Display Information")
        viewport.append(self._display_group)
        self._display_selector_row = Adw.ActionRow(title="Monitor")
        self._display_dropdown = Gtk.DropDown.new_from_strings(["Detecting..."])
        self._display_dropdown.connect("notify::selected", self._on_display_selected)
        self._display_selector_row.add_suffix(self._display_dropdown)
        self._display_selector_row.set_activatable(False)
        self._display_group.add(self._display_selector_row)
        self._info_rows = self._create_info_rows(self._display_group)

        self._brightness_group = Adw.PreferencesGroup(title="🌞 Brightness")
        viewport.append(self._brightness_group)
        self._brightness_row = DebouncedSliderRow(
            "Brightness",
            self._set_brightness,
            value_css_class="value-brightness",
            scale_css_class="scale-brightness",
        )
        self._brightness_group.add(self._brightness_row)

        self._contrast_group = Adw.PreferencesGroup(title="⚫ Contrast")
        viewport.append(self._contrast_group)
        self._contrast_row = DebouncedSliderRow(
            "Contrast",
            self._set_contrast,
            value_css_class="value-contrast",
            scale_css_class="scale-contrast",
        )
        self._contrast_group.add(self._contrast_row)

        self._volume_group = Adw.PreferencesGroup(title="🔊 Volume")
        viewport.append(self._volume_group)
        self._volume_row = DebouncedSliderRow(
            "Volume",
            self._set_volume,
            value_css_class="value-volume",
            scale_css_class="scale-volume",
        )
        self._volume_group.add(self._volume_row)

        self._color_group = Adw.PreferencesGroup(title="🎨 Colors")
        viewport.append(self._color_group)
        self._preset_row = Adw.ActionRow(title="Preset")
        self._preset_dropdown = Gtk.DropDown.new_from_strings(list(COLOR_PRESETS.keys()))
        self._preset_dropdown.connect("notify::selected", self._on_preset_selected)
        self._preset_row.add_suffix(self._preset_dropdown)
        self._preset_row.set_activatable(False)
        self._color_group.add(self._preset_row)

        self._red_row = DebouncedSliderRow("🔴 Red", self._set_red_gain, value_css_class="value-red")
        self._green_row = DebouncedSliderRow("🟢 Green", self._set_green_gain, value_css_class="value-green")
        self._blue_row = DebouncedSliderRow("🔵 Blue", self._set_blue_gain, value_css_class="value-blue")
        self._color_group.add(self._red_row)
        self._color_group.add(self._green_row)
        self._color_group.add(self._blue_row)

        self._advanced_group = Adw.PreferencesGroup(title="🪄 Advanced")
        viewport.append(self._advanced_group)
        self._sharpness_row = DebouncedSliderRow(
            "Sharpness",
            self._set_sharpness,
            value_css_class="value-sharpness",
            scale_css_class="scale-sharpness",
        )
        self._advanced_group.add(self._sharpness_row)
        self._power_row = Adw.ActionRow(title="Power Mode", subtitle="Only On is enabled for safety")
        self._power_dropdown = Gtk.DropDown.new_from_strings(list(POWER_MODES.keys()))
        self._power_dropdown.set_selected(0)
        self._power_dropdown.set_sensitive(False)
        self._power_row.add_suffix(self._power_dropdown)
        self._power_row.set_activatable(False)
        self._advanced_group.add(self._power_row)

        self._load_monitor()

    def _create_info_rows(self, group: Adw.PreferencesGroup) -> dict[str, Adw.ActionRow]:
        rows: dict[str, Adw.ActionRow] = {}
        for title in ("Model", "Manufacturer", "Connection", "Firmware", "VCP Version", "Refresh Rate", "Resolution"):
            row = Adw.ActionRow(title=title, subtitle="Unknown")
            row.set_activatable(False)
            group.add(row)
            rows[title] = row
        return rows

    def _toast(self, message: str) -> None:
        self._toast_overlay.add_toast(Adw.Toast(title=message))

    def _run_setter(self, setter: Callable[[int, Callable[[object | None, Exception | None], None]], None], value: int) -> None:
        setter(value, lambda _data, error: self._on_set_result(error))

    def _on_set_result(self, error: Exception | None) -> None:
        if error:
            self._logger.error("Monitor write failed: %s", error)
            self._toast(str(error))

    def _set_brightness(self, value: int) -> None:
        self._run_setter(self._monitor.set_brightness, value)

    def _set_contrast(self, value: int) -> None:
        self._run_setter(self._monitor.set_contrast, value)

    def _set_volume(self, value: int) -> None:
        self._run_setter(self._monitor.set_volume, value)

    def _set_red_gain(self, value: int) -> None:
        self._run_setter(self._monitor.set_red_gain, value)

    def _set_green_gain(self, value: int) -> None:
        self._run_setter(self._monitor.set_green_gain, value)

    def _set_blue_gain(self, value: int) -> None:
        self._run_setter(self._monitor.set_blue_gain, value)

    def _set_sharpness(self, value: int) -> None:
        self._run_setter(self._monitor.set_sharpness, value)

    def _load_monitor(self) -> None:
        self._monitor.detect_all(self._on_displays_detected)

    def _on_displays_detected(self, displays: object | None, error: Exception | None) -> None:
        if error:
            self._window_title.set_subtitle("No monitor")
            self._toast(str(error))
            return

        detected = [str(display) for display in list(displays or [])]
        self._display_ids = detected
        self._display_dropdown.set_sensitive(bool(self._display_ids))
        self._ignore_display_dropdown_changes = True
        self._display_dropdown.set_model(Gtk.StringList.new([f"Display {display}" for display in self._display_ids]))
        active_display = self._monitor.display_id or (self._display_ids[0] if self._display_ids else None)
        if active_display and active_display in self._display_ids:
            self._display_dropdown.set_selected(self._display_ids.index(active_display))
            self._window_title.set_subtitle(f"Display {active_display}")
        self._ignore_display_dropdown_changes = False
        self._refresh_monitor_state(show_toast=False)

    def _on_info_loaded(self, info: object | None, error: Exception | None, generation: int) -> None:
        if generation != self._refresh_generation:
            return

        if error:
            self._toast(str(error))
            return

        monitor_info = info if isinstance(info, MonitorInfo) else MonitorInfo(display_id=str(self._monitor.display_id or "1"))
        self._populate_runtime_display_info(monitor_info)
        self._info_rows["Model"].set_subtitle(monitor_info.model)
        self._info_rows["Manufacturer"].set_subtitle(monitor_info.manufacturer)
        self._info_rows["Connection"].set_subtitle(monitor_info.connection)
        self._info_rows["Firmware"].set_subtitle(monitor_info.firmware)
        self._info_rows["VCP Version"].set_subtitle(monitor_info.vcp_version)
        self._info_rows["Refresh Rate"].set_subtitle(monitor_info.refresh_rate)
        self._info_rows["Resolution"].set_subtitle(monitor_info.resolution)

    def _populate_runtime_display_info(self, monitor_info: MonitorInfo) -> None:
        display = Gdk.Display.get_default()
        if not display:
            return

        monitors = display.get_monitors()
        if not monitors:
            return

        fallback: Gdk.Monitor | None = None
        best: Gdk.Monitor | None = None
        best_score = -1
        for index in range(monitors.get_n_items()):
            monitor = monitors.get_item(index)
            if not isinstance(monitor, Gdk.Monitor):
                continue
            if fallback is None:
                fallback = monitor
            score = 0
            model = monitor.get_model() or ""
            manufacturer = monitor.get_manufacturer() or ""
            if monitor_info.model != "Unknown" and monitor_info.model.lower() in model.lower():
                score += 2
            if monitor_info.manufacturer != "Unknown" and monitor_info.manufacturer.lower() in manufacturer.lower():
                score += 1
            if score > best_score:
                best = monitor
                best_score = score

        selected = best or fallback
        if not selected:
            return

        geometry = selected.get_geometry()
        if monitor_info.resolution == "Unknown":
            monitor_info.resolution = f"{geometry.width}x{geometry.height}"

        if monitor_info.refresh_rate == "Unknown":
            refresh_mhz = selected.get_refresh_rate()
            if refresh_mhz > 0:
                monitor_info.refresh_rate = f"{refresh_mhz / 1000:.2f} Hz"

    def _load_value(
        self,
        getter: Callable[[Callable[[object | None, Exception | None], None]], None],
        row: DebouncedSliderRow,
        name: str,
        generation: int,
        show_toast: bool,
        retries: int = 4,
    ) -> None:
        def on_loaded(data: object | None, error: Exception | None) -> None:
            if generation != self._refresh_generation:
                return

            self._pending_refresh_reads = max(0, self._pending_refresh_reads - 1)
            if error:
                if retries > 0:
                    self._logger.warning("Retrying monitor read for %s after error: %s", name, error)
                    self._pending_refresh_reads += 1
                    GLib.timeout_add(
                        180,
                        lambda: self._retry_load_value(getter, row, name, generation, show_toast, retries - 1),
                    )
                    self._finish_refresh_if_ready(generation, show_toast)
                    return
                self._logger.warning("Monitor read failed for %s: %s", name, error)
                self._refresh_failed_names.append(name)
                row.allow_manual_control()
                self._finish_refresh_if_ready(generation, show_toast)
                return
            if isinstance(data, VcpValue):
                if data.maximum > 0:
                    row.set_bounds(0, data.maximum)
                row.set_value(data.current)
            else:
                self._refresh_failed_names.append(name)
                row.allow_manual_control()
            self._finish_refresh_if_ready(generation, show_toast)

        getter(on_loaded)

    def _retry_load_value(
        self,
        getter: Callable[[Callable[[object | None, Exception | None], None]], None],
        row: DebouncedSliderRow,
        name: str,
        generation: int,
        show_toast: bool,
        retries: int,
    ) -> bool:
        if generation == self._refresh_generation:
            self._load_value(getter, row, name, generation, show_toast, retries)
        return GLib.SOURCE_REMOVE

    def _load_current_values(self, generation: int, show_toast: bool) -> None:
        controls = (
            (self._monitor.get_brightness, self._brightness_row, "brightness"),
            (self._monitor.get_contrast, self._contrast_row, "contrast"),
            (self._monitor.get_volume, self._volume_row, "volume"),
            (self._monitor.get_red_gain, self._red_row, "red gain"),
            (self._monitor.get_green_gain, self._green_row, "green gain"),
            (self._monitor.get_blue_gain, self._blue_row, "blue gain"),
            (self._monitor.get_sharpness, self._sharpness_row, "sharpness"),
        )
        self._pending_refresh_reads = len(controls)
        for getter, row, name in controls:
            self._load_value(getter, row, name, generation, show_toast)

    def _commit_pending_slider_changes(self) -> None:
        rows = (
            self._brightness_row,
            self._contrast_row,
            self._volume_row,
            self._red_row,
            self._green_row,
            self._blue_row,
            self._sharpness_row,
        )
        for row in rows:
            row.commit_pending()

    def _on_preset_selected(self, _dropdown: Gtk.DropDown, _param_spec: object) -> None:
        selected = self._preset_dropdown.get_selected()
        if selected == Gtk.INVALID_LIST_POSITION:
            return
        value = list(COLOR_PRESETS.values())[selected]
        self._monitor.set_color_preset(value, lambda _data, error: self._on_set_result(error))

    def _on_refresh_clicked(self, _button: Gtk.Button) -> None:
        self._commit_pending_slider_changes()
        self._refresh_monitor_state(show_toast=True)

    def _on_display_selected(self, _dropdown: Gtk.DropDown, _param_spec: object) -> None:
        if self._ignore_display_dropdown_changes:
            return
        selected = self._display_dropdown.get_selected()
        if selected == Gtk.INVALID_LIST_POSITION:
            return
        if selected >= len(self._display_ids):
            return
        display_id = self._display_ids[selected]
        if display_id == self._monitor.display_id:
            return
        self._commit_pending_slider_changes()
        try:
            self._monitor.set_display(display_id)
        except Exception as error:
            self._toast(str(error))
            return
        self._window_title.set_subtitle(f"Display {display_id}")
        self._refresh_monitor_state(show_toast=True)

    def _refresh_monitor_state(self, show_toast: bool) -> None:
        self._refresh_generation += 1
        generation = self._refresh_generation
        self._refresh_failed_names = []
        self._refresh_button.set_sensitive(False)
        self._monitor.get_info(lambda data, error: self._on_info_loaded(data, error, generation))
        self._load_current_values(generation, show_toast)
        if show_toast:
            self._toast("Refreshing monitor values...")

    def _finish_refresh_if_ready(self, generation: int, show_toast: bool) -> None:
        if generation != self._refresh_generation:
            return
        if self._pending_refresh_reads == 0:
            self._refresh_button.set_sensitive(True)
            if show_toast:
                if self._refresh_failed_names:
                    self._toast("Some monitor values could not be read")
                else:
                    self._toast("Monitor values updated")

    def _setup_styles(self) -> None:
        display = Gdk.Display.get_default()
        if display is None:
            return

        provider = Gtk.CssProvider()
        provider.load_from_data(
            """
            .value-brightness { color: @warning_color; font-weight: 600; }
            .value-contrast { color: @accent_color; font-weight: 600; }
            .value-volume { color: @success_color; font-weight: 600; }
            .value-red { color: #d64550; font-weight: 600; }
            .value-green { color: #2ca24c; font-weight: 600; }
            .value-blue { color: #4285f4; font-weight: 600; }
            .value-sharpness { color: @purple_2; font-weight: 600; }
            .scale-brightness trough > highlight { background: @warning_color; }
            .scale-volume trough > highlight { background: @success_color; }
            .scale-sharpness trough > highlight { background: @purple_2; }
            .stepper-button {
                min-width: 18px;
                min-height: 18px;
                padding: 0;
                border-radius: 999px;
            }
            """
        )
        Gtk.StyleContext.add_provider_for_display(
            display,
            provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
        )
