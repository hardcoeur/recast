import gi
import os
from gi.repository import Gtk, Adw, Gio, Pango, GObject, GLib, Gdk

import threading
from ..audio.capture import AudioCapturer, list_audio_input_devices
from ..utils.models import list_local_models, get_available_models, download_model, APP_MODEL_DIR

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

class PreferencesWindow(Adw.PreferencesDialog):
    """
    A window for managing application preferences.
    """

    DEVICE_DISPLAY_TO_VALUE = {"Auto": "auto", "CPU": "cpu", "CUDA": "cuda"}
    DEVICE_VALUE_TO_DISPLAY = {v: k for k, v in DEVICE_DISPLAY_TO_VALUE.items()}

    def __init__(self, **kwargs):
        """
        Initializes the PreferencesWindow.
        """
        super().__init__(**kwargs)

        self.add_css_class("preferences-dialog")
        self.settings = Gio.Settings.new("org.gnome.GnomeRecast")

        self.set_search_enabled(False)
        self.set_title("Preferences")


        self.is_testing = False
        self.test_capturer = None
        self.test_audio_level = 0.0
        self.level_update_timer_id = None

        self.connect("destroy", self._on_destroy)

        self.available_models = get_available_models()
        self.local_model_names = {m['name'] for m in list_local_models()}
        self.pref_active_download = None


        general_page = Adw.PreferencesPage()
        general_page.set_title("General")
        general_page.set_icon_name("preferences-system-symbolic")
        self.add(general_page)

        general_group = Adw.PreferencesGroup()
        general_group.set_title("General Settings")
        general_page.add(general_group)

        autosave_row = Adw.ActionRow()
        autosave_row.set_title("Autosave location")
        general_group.add(autosave_row)

        autosave_widget_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.autosave_path_label = Gtk.Label(label="Not Set", halign=Gtk.Align.START, hexpand=True, ellipsize=Pango.EllipsizeMode.MIDDLE)
        autosave_widget_box.append(self.autosave_path_label)

        autosave_button = Gtk.Button(label="Choose Folder...")
        autosave_button.connect("clicked", self._on_choose_autosave_folder_clicked)
        autosave_widget_box.append(autosave_button)

        autosave_row.add_suffix(autosave_widget_box)
        initial_autosave_path = self.settings.get_string("autosave-location")
        if initial_autosave_path and os.path.isdir(initial_autosave_path):
            self.autosave_path_label.set_text(initial_autosave_path)
        elif initial_autosave_path:
            self.autosave_path_label.set_text("Saved path invalid")


        autolaunch_row = Adw.SwitchRow()
        autolaunch_row.add_css_class("preferences-row-autolaunch")
        autolaunch_row.set_title("Auto-launch at login")
        self.settings.bind(
            "auto-launch", autolaunch_row, "active", Gio.SettingsBindFlags.DEFAULT
        )
        general_group.add(autolaunch_row)

        autolaunch_row.connect("notify::active", self._on_autolaunch_changed)
        self._on_autolaunch_changed(autolaunch_row, None)

        microphone_page = Adw.PreferencesPage()
        microphone_page.set_title("Microphone")
        microphone_page.set_icon_name("audio-input-microphone-symbolic")
        self.add(microphone_page)

        input_device_group = Adw.PreferencesGroup()
        input_device_group.set_title("Input Device")
        microphone_page.add(input_device_group)

        input_device_row = Adw.ComboRow()
        input_device_row.set_title("Input device")
        audio_devices = list_audio_input_devices()
        device_list_model = Gtk.StringList()
        if audio_devices:
            device_list_model.splice(0, device_list_model.get_n_items(), audio_devices)
        else:
            device_list_model.append("No Input Devices Found")
            input_device_row.set_sensitive(False)

        input_device_row.set_model(device_list_model)
        input_device_group.add(input_device_row)
        self._bind_combo_row_string(
            input_device_row, "mic-input-device"
        )

        input_level_row = Adw.ActionRow()
        input_level_row.set_title("Input Level")
        self.input_level_bar = Gtk.LevelBar()
        self.input_level_bar.set_mode(Gtk.LevelBarMode.CONTINUOUS)
        self.input_level_bar.set_value(0.0)
        input_level_row.add_suffix(self.input_level_bar)
        input_device_group.add(input_level_row)

        test_recording_row = Adw.ActionRow()
        test_recording_row.set_title("Test Recording")
        self.test_button = Gtk.Button(label="Start Test")
        self.test_button.connect("clicked", self._on_test_button_clicked)
        test_recording_row.add_suffix(self.test_button)
        input_device_group.add(test_recording_row)
        transcription_page = Adw.PreferencesPage()
        transcription_page.set_title("Transcription")
        transcription_page.set_icon_name("accessories-text-editor-symbolic")
        self.add(transcription_page)

        transcription_group = Adw.PreferencesGroup()
        transcription_page.add(transcription_group)

        self.model_row = Adw.ComboRow()
        self.model_row.set_title("Default model")
        model_list = ["tiny", "base", "small", "medium", "large"]
        model_list_model = Gtk.StringList.new(model_list)
        self.model_row.set_model(model_list_model)
        transcription_group.add(self.model_row)
        self._bind_combo_row_string(
            self.model_row, "default-model"
        )

        device_row = Adw.ComboRow()
        device_row.set_title("Transcription Device")
        device_values = list(PreferencesWindow.DEVICE_DISPLAY_TO_VALUE.keys())
        device_list_model = Gtk.StringList.new(device_values)
        device_row.set_model(device_list_model)
        transcription_group.add(device_row)
        self._bind_device_combo_row(device_row, "whisper-device-mode")


        model_suffix_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)

        self.download_model_button = Gtk.Button(label="Download")
        self.download_model_button.set_visible(False)
        self.download_model_button.connect("clicked", self._on_download_model_clicked)
        model_suffix_box.append(self.download_model_button)

        self.download_spinner = Gtk.Spinner()
        self.download_spinner.set_visible(False)
        model_suffix_box.append(self.download_spinner)

        self.model_row.add_suffix(model_suffix_box)

        self.model_row.connect("notify::selected-item", self._on_selected_model_changed)
        self._on_selected_model_changed(self.model_row, None)


        concurrency_row = Adw.SpinRow()
        concurrency_row.set_title("Concurrency limit")
        concurrency_adjustment = Gtk.Adjustment.new(
            value=1, lower=1, upper=8, step_increment=1, page_increment=1, page_size=0
        )
        concurrency_row.set_adjustment(concurrency_adjustment)
        concurrency_row.set_numeric(True)
        self.settings.bind(
            "concurrency-limit",
            concurrency_adjustment,
            "value",
            Gio.SettingsBindFlags.DEFAULT,
        )
        transcription_group.add(concurrency_row)

        temperature_row = Adw.ActionRow()
        temperature_row.set_title("Temperature setting")
        temperature_scale = Gtk.Scale.new_with_range(
            Gtk.Orientation.HORIZONTAL, 0.0, 1.0, 0.1
        )
        temperature_adjustment = Gtk.Adjustment.new(
             value=0.0, lower=0.0, upper=1.0, step_increment=0.1, page_increment=0.2, page_size=0
        )
        temperature_scale.set_adjustment(temperature_adjustment)
        temperature_scale.set_digits(1)
        temperature_scale.set_draw_value(True)
        temperature_row.add_suffix(temperature_scale)
        temperature_scale.set_hexpand(True)
        self.temperature_adjustment = temperature_adjustment
        self.settings.bind(
            "temperature",
            self.temperature_adjustment,
            "value",
            Gio.SettingsBindFlags.DEFAULT,
        )
        transcription_group.add(temperature_row)


        autodetect_row = Adw.SwitchRow()
        autodetect_row.set_title("Auto-detect language")
        self.settings.bind(
            "auto-detect-language",
            autodetect_row,
            "active",
            Gio.SettingsBindFlags.DEFAULT,
        )
        transcription_group.add(autodetect_row)
        translation_page = Adw.PreferencesPage()
        translation_page.set_title("Translation")
        translation_page.set_icon_name("accessories-dictionary-symbolic")
        self.add(translation_page)

        translation_group = Adw.PreferencesGroup()
        translation_page.add(translation_group)

        enable_translation_row = Adw.SwitchRow()
        enable_translation_row.set_title("Enable translation")
        self.settings.bind(
            "enable-translation",
            enable_translation_row,
            "active",
            Gio.SettingsBindFlags.DEFAULT,
        )
        translation_group.add(enable_translation_row)


        target_language_row = Adw.ComboRow()
        target_language_row.set_title("Target language")
        language_list = ["English", "Spanish", "French", "German"]
        language_list_model = Gtk.StringList.new(language_list)
        target_language_row.set_model(language_list_model)
        translation_group.add(target_language_row)
        self._bind_combo_row_string(
            target_language_row, "target-language"
        )

        enable_translation_row.bind_property(
            "active", target_language_row, "sensitive", GObject.BindingFlags.DEFAULT
        )

        output_format_row = Adw.ComboRow()
        output_format_row.set_title("Default output format")
        format_list = [".txt", ".md", ".srt"]
        format_list_model = Gtk.StringList.new(format_list)
        output_format_row.set_model(format_list_model)
        translation_group.add(output_format_row)
        self._bind_combo_row_string(
            output_format_row, "default-output-format"
        )
        appearance_page = Adw.PreferencesPage()
        appearance_page.set_title("Appearance")
        appearance_page.set_icon_name("preferences-desktop-theme-symbolic")
        self.add(appearance_page)

        appearance_group = Adw.PreferencesGroup()
        appearance_page.add(appearance_group)

        theme_mode_row = Adw.ComboRow()
        theme_mode_row.set_title("Theme Mode")
        theme_modes = ["System", "Light", "Dark"]
        theme_mode_model = Gtk.StringList.new(theme_modes)
        theme_mode_row.set_model(theme_mode_model)
        appearance_group.add(theme_mode_row)
        self._bind_combo_row_string(
            theme_mode_row, "theme-mode"
        )

        font_size_row = Adw.ActionRow()
        font_size_row.set_title("Font size scale")
        font_size_adjustment = Gtk.Adjustment.new(
            value=12, lower=12, upper=24, step_increment=1, page_increment=2, page_size=0
        )
        font_size_scale = Gtk.Scale.new(Gtk.Orientation.HORIZONTAL, font_size_adjustment)
        font_size_scale.set_digits(0)
        font_size_scale.set_draw_value(True)
        font_size_row.add_suffix(font_size_scale)
        self.font_size_adjustment = font_size_adjustment
        self.settings.bind(
            "font-size",
            self.font_size_adjustment,
            "value",
            Gio.SettingsBindFlags.DEFAULT,
        )
        appearance_group.add(font_size_row)

        speaker_color_row = Adw.ActionRow()
        speaker_color_row.set_title("Speaker label colors")
        configure_colors_button = Gtk.Button(label="Configure Colors...")
        speaker_color_row.add_suffix(configure_colors_button)
        configure_colors_button.connect("clicked", self._on_configure_speaker_colors_clicked)
        appearance_group.add(speaker_color_row)

    def _on_choose_autosave_folder_clicked(self, button):
        """Handles click on the 'Choose Folder...' button for autosave location."""
        dialog = Gtk.FileDialog(modal=True)
        dialog.set_title("Select Autosave Folder")

        parent_window = self.get_native()
        dialog.select_folder(parent_window, None, self._on_folder_selected)

    def _on_folder_selected(self, dialog, result):
        """Callback for when the folder selection dialog is closed."""
        try:
            folder_file = dialog.select_folder_finish(result)
            if folder_file:
                folder_path = folder_file.get_path()
                self.settings.set_string("autosave-location", folder_path)
                self.autosave_path_label.set_text(folder_path)
                print(f"Autosave location set to: {folder_path}")
            else:
                print("Folder selection cancelled.")
        except GLib.Error as e:
            print(f"Error selecting folder: {e.message}")
        except Exception as e:
            print(f"Unexpected error during folder selection: {e}")


    def _find_string_in_model(self, model: Gtk.StringList, text: str) -> int:
        """Finds the index of a string in a Gtk.StringList model."""
        n_items = model.get_n_items()
        for i in range(n_items):
            item = model.get_string(i)
            if item == text:
                return i
        return -1

    def _bind_combo_row_string(self, combo_row: Adw.ComboRow, key: str):
        """Binds a ComboRow's selected string to a GSettings string key."""
        saved_value = self.settings.get_string(key)
        if saved_value:
            model = combo_row.get_model()
            if isinstance(model, Gtk.StringList):
                idx = self._find_string_in_model(model, saved_value)
                if idx != -1:
                    combo_row.set_selected(idx)
            else:
                 print(f"Warning: Model for ComboRow bound to '{key}' is not a Gtk.StringList.")


        def on_notify_selected_item(combobox, _param):
            selected_item = combobox.get_selected_item()
            if selected_item:
                value_to_save = selected_item.get_string()
                self.settings.set_string(key, value_to_save)

        combo_row.connect("notify::selected-item", on_notify_selected_item)


    def _bind_device_combo_row(self, combo_row: Adw.ComboRow, key: str):
        """Binds a ComboRow's selected item to a GSettings string key with mapping."""
        saved_value = self.settings.get_string(key)
        display_value = PreferencesWindow.DEVICE_VALUE_TO_DISPLAY.get(saved_value, "Auto")

        model = combo_row.get_model()
        if isinstance(model, Gtk.StringList):
            idx = self._find_string_in_model(model, display_value)
            if idx != -1:
                combo_row.set_selected(idx)
            else:
                print(f"Warning: Initial display value '{display_value}' (from setting '{saved_value}') not found in model for key '{key}'. Setting to 'Auto'.")
                default_idx = self._find_string_in_model(model, "Auto")
                if default_idx != -1:
                    combo_row.set_selected(default_idx)
        else:
            print(f"Warning: Model for ComboRow bound to '{key}' is not a Gtk.StringList.")

        def on_notify_selected_item(combobox, _param):
            selected_item = combobox.get_selected_item()
            if selected_item:
                selected_display = selected_item.get_string()
                value_to_save = PreferencesWindow.DEVICE_DISPLAY_TO_VALUE.get(selected_display)
                if value_to_save:
                    if self.settings.get_string(key) != value_to_save:
                         self.settings.set_string(key, value_to_save)
                         print(f"Set GSetting '{key}' to '{value_to_save}'")
                else:
                    print(f"Warning: Could not map display value '{selected_display}' back to setting value for key '{key}'.")

        combo_row.connect("notify::selected-item", on_notify_selected_item)


    def _on_autolaunch_changed(self, switch_row, _param):
        """Handles the state change of the auto-launch switch."""
        is_active = switch_row.get_active()
        autostart_dir = os.path.join(GLib.get_user_config_dir(), "autostart")
        desktop_file_name = "gnomerecast.desktop"
        desktop_file_path = os.path.join(autostart_dir, desktop_file_name)

        desktop_content = """[Desktop Entry]
Type=Application
Name=GnomeRecast
Comment=Record and Transcribe Audio
Exec=gnomerecast
Icon=org.gnome.GnomeRecast
Terminal=false
Categories=GNOME;GTK;AudioVideo;Audio;
X-GNOME-Autostart-enabled=true
"""

        if is_active:
            try:
                os.makedirs(autostart_dir, exist_ok=True)
                with open(desktop_file_path, "w") as f:
                    f.write(desktop_content)
                print(f"Created autostart file: {desktop_file_path}")
            except IOError as e:
                print(f"Error creating autostart file {desktop_file_path}: {e}")
            except Exception as e:
                print(f"Unexpected error creating autostart file: {e}")
        else:
            if os.path.exists(desktop_file_path):
                try:
                    os.remove(desktop_file_path)
                    print(f"Removed autostart file: {desktop_file_path}")
                except OSError as e:
                    print(f"Error removing autostart file {desktop_file_path}: {e}")
                except Exception as e:
                    print(f"Unexpected error removing autostart file: {e}")
            else:
                pass

    def _on_test_button_clicked(self, button):
        """Handles the Start/Stop Test button click."""
        if not self.is_testing:
            self.is_testing = True
            self.test_button.set_label("Stop Test")
            self.test_audio_level = 0.0
            self.input_level_bar.set_value(0.0)


            try:
                self.test_capturer = AudioCapturer(
                    callback=self._on_test_audio_data
                )
                self.test_capturer.start()
                self.level_update_timer_id = GLib.timeout_add(100, self._update_level_bar)
                print("Microphone test started.")
            except Exception as e:
                print(f"Error starting audio capture: {e}")
                self.is_testing = False
                self.test_button.set_label("Start Test")
                self.test_capturer = None
        else:
            self._stop_audio_test()

    def _stop_audio_test(self):
        """Stops the audio test cleanly."""
        if not self.is_testing:
            return

        print("Stopping microphone test...")
        self.is_testing = False
        self.test_button.set_label("Start Test")

        if self.level_update_timer_id:
            GLib.source_remove(self.level_update_timer_id)
            self.level_update_timer_id = None

        if self.test_capturer:
            try:
                self.test_capturer.stop()
            except Exception as e:
                print(f"Error stopping audio capturer: {e}")
            finally:
                 self.test_capturer = None

        self.input_level_bar.set_value(0.0)
        self.test_audio_level = 0.0


    def _on_test_audio_data(self, audio_data: bytes):
        """Callback receiving audio data during testing."""
        if not audio_data or not self.is_testing:
            return

        try:
            width = 2
            if len(audio_data) % width != 0:
                 print(f"Warning: Received audio data with incomplete frame size ({len(audio_data)} bytes)")
                 audio_data = audio_data[:len(audio_data) - (len(audio_data) % width)]
                 if not audio_data: return

            peak = 0
            for i in range(0, len(audio_data), width):
                sample_bytes = audio_data[i:i+width]
                if len(sample_bytes) == width:
                    sample = int.from_bytes(sample_bytes, byteorder='little', signed=True)
                    peak = max(peak, abs(sample))

            max_amplitude = 32767
            normalized_level = min(peak / max_amplitude, 1.0)
            self.test_audio_level = normalized_level

        except Exception as e:
             print(f"Unexpected error processing audio data: {e}")


    def _update_level_bar(self):
        """Periodically updates the input level bar during testing."""
        if not self.is_testing:
            return GLib.SOURCE_REMOVE

        self.input_level_bar.set_value(self.test_audio_level)
        return GLib.SOURCE_CONTINUE


    def _on_destroy(self, window, *args):
        """Ensure audio test is stopped and check for pending model download."""
        print("Preferences window close requested.")

        selected_item = self.model_row.get_selected_item()
        if selected_item:
            model_name = selected_item.get_string()
            if model_name:
                self.local_model_names = {m['name'] for m in list_local_models()}
                print(f"Checking close-download for '{model_name}'. Local models: {self.local_model_names}")

                is_available = model_name in self.available_models
                is_local = model_name in self.local_model_names
                if is_available and not is_local and self.pref_active_download is None:
                    print(f"Selected model '{model_name}' not downloaded. Starting download on close.")
                    self._start_model_download(model_name)

        if self.is_testing:
            print("Stopping ongoing audio test due to window close.")
            self._stop_audio_test()

        return Gdk.EVENT_PROPAGATE

    def _on_configure_speaker_colors_clicked(self, button):
        """Handles click on the 'Configure Colors...' button."""
        print("Speaker color configuration dialog not yet implemented.")


    def _on_selected_model_changed(self, combo_row, _param):
        """
        Shows or hides the download button based on the selected model's status.
        Also updates sensitivity based on active download.
        """
        selected_item = combo_row.get_selected_item()
        if selected_item:
            model_name = selected_item.get_string()
            if model_name:
                is_available = model_name in self.available_models
                is_local = model_name in self.local_model_names
                show_button = is_available and not is_local

                if self.pref_active_download and self.pref_active_download['name'] == model_name:
                    show_button = False

                self.download_model_button.set_visible(show_button)
                self.download_model_button.set_sensitive(self.pref_active_download is None)
                return

        self.download_model_button.set_visible(False)


    def _on_download_model_clicked(self, button):
        """Handles the click on the 'Download' button for a model."""
        selected_item = self.model_row.get_selected_item()
        if selected_item:
            model_name = selected_item.get_string()
            if model_name:
                is_available = model_name in self.available_models
                is_local = model_name in self.local_model_names
                if is_available and not is_local:
                    print(f"Download button clicked for model: {model_name}")
                    self._start_model_download(model_name)
                else:
                    print(f"Model '{model_name}' is already local or not available.")
        else:
            print("No model selected for download.")


    def _start_model_download(self, model_name: str):
        """Initiates the download process for the specified model."""
        if self.pref_active_download is not None:
            print(f"Another download is already active: {self.pref_active_download['name']}")
            return

        model_info = self.available_models.get(model_name)
        if not model_info or 'url' not in model_info:
            print(f"Error: Could not find download URL for model '{model_name}'.")
            return

        download_url = model_info['url']
        print(f"Starting download for '{model_name}' from {download_url}...")

        self.model_row.set_sensitive(False)
        self.download_model_button.set_visible(False)
        self.download_spinner.set_visible(True)
        self.download_spinner.start()

        cancel_event = threading.Event()
        self.pref_active_download = {'name': model_name, 'cancel_event': cancel_event}

        download_thread = threading.Thread(
            target=download_model,
            args=(model_name, download_url, APP_MODEL_DIR, self._update_pref_download_progress, cancel_event),
            daemon=True
        )
        download_thread.start()


    def _update_pref_download_progress(self, model_name: str, percentage: float, error_message: str | None):
        """
        Callback executed by the download thread. Schedules UI update on the main thread.
        Percentage: 0.0 to 100.0, -1.0 for error, -2.0 for cancelled.
        """
        GLib.idle_add(self._update_pref_download_ui, model_name, percentage, error_message)


    def _update_pref_download_ui(self, model_name: str, percentage: float, error_message: str | None):
        """Updates the UI elements related to model download based on progress."""
        if not self.pref_active_download or self.pref_active_download['name'] != model_name:
            return GLib.SOURCE_REMOVE

        print(f"Download UI Update for '{model_name}': {percentage}%, Error: {error_message}")

        is_finished = percentage >= 100.0 or percentage < 0


        if is_finished:
            self.download_spinner.stop()
            self.download_spinner.set_visible(False)

            self.model_row.set_sensitive(True)

            self.local_model_names = {m['name'] for m in list_local_models()}
            print(f"Local models after download attempt: {self.local_model_names}")

            self._on_selected_model_changed(self.model_row, None)

            self.pref_active_download = None

            if percentage == 100.0:
                print(f"Model '{model_name}' downloaded successfully.")
            elif percentage == -1.0:
                print(f"Error downloading model '{model_name}': {error_message}")

            elif percentage == -2.0:
                 print(f"Download for model '{model_name}' was cancelled.")

            return GLib.SOURCE_REMOVE

        return GLib.SOURCE_REMOVE
