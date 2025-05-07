import gi
import os
from gi.repository import Gtk, Adw, Gio, Pango, GObject, GLib, Gdk

import threading
# Updated import for AudioCapturer, removed old list_audio_input_devices
from ..audio.capture import AudioCapturer 
from ..audio.device_utils import get_input_devices, AudioInputDevice # New import
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
        self.settings = Gio.Settings.new("org.hardcoeur.Recast")

        self.set_search_enabled(False)
        self.set_title("Preferences")


        self.is_testing = False
        self.test_capturer: Optional[AudioCapturer] = None # Type hint
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
        microphone_page.set_icon_name("audio-input-microphone-symbolic") # Standard icon
        self.add(microphone_page)

        input_device_group = Adw.PreferencesGroup()
        input_device_group.set_title("Input Device")
        microphone_page.add(input_device_group)

        # --- Microphone Input Device Row Refactor ---
        self.mic_input_device_row = Adw.ComboRow()
        self.mic_input_device_row.set_title("Input device")
        
        # Populate with AudioInputDevice objects (or their string representations)
        self.audio_devices_list: list[AudioInputDevice] = get_input_devices()
        
        # Create a Gtk.StringList for the ComboRow model, storing device names
        device_display_names = [dev.name for dev in self.audio_devices_list]
        device_list_model = Gtk.StringList.new(device_display_names)

        if not self.audio_devices_list:
            # This case should ideally be handled by get_input_devices returning a default "No devices" entry
            device_list_model.append("No Input Devices Found") 
            self.mic_input_device_row.set_sensitive(False)

        self.mic_input_device_row.set_model(device_list_model)
        input_device_group.add(self.mic_input_device_row)
        
        # Custom binding logic for mic input device
        self._bind_mic_input_device_combo_row(self.mic_input_device_row)
        # --- End Microphone Input Device Row Refactor ---

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
        model_list = ["tiny", "base", "small", "medium", "large"] # These are keys for available_models
        model_list_model = Gtk.StringList.new(model_list)
        self.model_row.set_model(model_list_model)
        transcription_group.add(self.model_row)
        self._bind_combo_row_string_setting(
            self.model_row, "default-model"
        )

        device_row = Adw.ComboRow()
        device_row.set_title("Transcription Device")
        device_values = list(PreferencesWindow.DEVICE_DISPLAY_TO_VALUE.keys()) # "Auto", "CPU", "CUDA"
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

        self.model_row.connect("notify::selected", self._on_selected_model_changed) # Use 'selected' not 'selected-item' for index
        self._on_selected_model_changed(self.model_row, None) # Initial check


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
        language_list_codes = ["en", "es", "fr", "de", "ja", "ko", "zh"] 
        language_display_map = {"en": "English", "es": "Spanish", "fr": "French", "de": "German", "ja": "Japanese", "ko": "Korean", "zh": "Chinese"}
        
        language_display_list = [language_display_map.get(code, code.upper()) for code in language_list_codes]
        language_list_model = Gtk.StringList.new(language_display_list)
        target_language_row.set_model(language_list_model)
        translation_group.add(target_language_row)
        
        self._bind_combo_row_string_setting_with_map(
            target_language_row, "target-language", language_display_map, language_list_codes[0] 
        )


        enable_translation_row.bind_property(
            "active", target_language_row, "sensitive", GObject.BindingFlags.DEFAULT
        )

        output_format_row = Adw.ComboRow()
        output_format_row.set_title("Default output format")
        format_list = ["txt", "md", "srt"] 
        format_list_model = Gtk.StringList.new(format_list) 
        output_format_row.set_model(format_list_model)
        translation_group.add(output_format_row)
        self._bind_combo_row_string_setting( 
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
        self._bind_combo_row_string_setting( 
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

    def _on_choose_autosave_folder_clicked(self, button):
        dialog = Gtk.FileDialog(modal=True)
        dialog.set_title("Select Autosave Folder")
        parent_window = self.get_native()
        dialog.select_folder(parent_window, None, self._on_folder_selected)

    def _on_folder_selected(self, dialog, result):
        try:
            folder_file = dialog.select_folder_finish(result)
            if folder_file:
                folder_path = folder_file.get_path()
                self.settings.set_string("autosave-location", folder_path)
                self.autosave_path_label.set_text(folder_path)
        except GLib.Error as e:
            print(f"Error selecting folder: {e.message}")
        except Exception as e:
            print(f"Unexpected error during folder selection: {e}")

    def _find_string_in_model(self, model: Gtk.StringList, text: str) -> int:
        if not text: return Gtk.INVALID_LIST_POSITION
        n_items = model.get_n_items()
        for i in range(n_items):
            item = model.get_string(i)
            if item == text:
                return i
        return Gtk.INVALID_LIST_POSITION

    def _bind_combo_row_string_setting(self, combo_row: Adw.ComboRow, key: str):
        saved_value = self.settings.get_string(key)
        model = combo_row.get_model() # Should be Gtk.StringList
        
        if isinstance(model, Gtk.StringList): # Ensure model is Gtk.StringList
            idx = self._find_string_in_model(model, saved_value)
            if idx != Gtk.INVALID_LIST_POSITION:
                combo_row.set_selected(idx)
            elif model.get_n_items() > 0: # Default to first if not found
                combo_row.set_selected(0) 
                # Optionally update GSettings if we defaulted
                # self.settings.set_string(key, model.get_string(0))


        def on_notify_selected(combobox, _param):
            selected_idx = combobox.get_selected()
            if selected_idx != Gtk.INVALID_LIST_POSITION and isinstance(model, Gtk.StringList):
                value_to_save = model.get_string(selected_idx)
                if self.settings.get_string(key) != value_to_save:
                    self.settings.set_string(key, value_to_save)
        
        combo_row.connect("notify::selected", on_notify_selected)

        def on_gsettings_changed(settings_obj, changed_key):
            if changed_key == key and isinstance(model, Gtk.StringList):
                new_value = settings_obj.get_string(key)
                current_combo_idx = combo_row.get_selected()
                current_combo_val = model.get_string(current_combo_idx) if current_combo_idx != Gtk.INVALID_LIST_POSITION else None
                if new_value != current_combo_val:
                    idx = self._find_string_in_model(model, new_value)
                    if idx != Gtk.INVALID_LIST_POSITION:
                        combo_row.set_selected(idx)
        
        self.settings.connect(f"changed::{key}", on_gsettings_changed)


    def _bind_mic_input_device_combo_row(self, combo_row: Adw.ComboRow):
        current_device_id = self.settings.get_string("mic-input-device-id")
        follow_default = self.settings.get_boolean("follow-system-default")
        
        selected_idx = Gtk.INVALID_LIST_POSITION
        target_device_name_for_selection = None

        if follow_default:
            # Find "System Default" entry by its properties
            for dev in self.audio_devices_list:
                if dev.id == "" and dev.api == "default": # Our definition of System Default
                    target_device_name_for_selection = dev.name
                    break
        else:
            # Find specific device by ID
            for dev in self.audio_devices_list:
                if dev.id == current_device_id:
                    target_device_name_for_selection = dev.name
                    break
        
        model = combo_row.get_model() # Should be Gtk.StringList of names
        if isinstance(model, Gtk.StringList) and target_device_name_for_selection:
            selected_idx = self._find_string_in_model(model, target_device_name_for_selection)

        if selected_idx != Gtk.INVALID_LIST_POSITION:
            combo_row.set_selected(selected_idx)
        elif model and model.get_n_items() > 0: # Default to first item if not found
            combo_row.set_selected(0)
            # Update GSettings to reflect this default selection (if first item maps cleanly)
            if self.audio_devices_list:
                first_dev = self.audio_devices_list[0]
                if first_dev.id == "" and first_dev.api == "default":
                    if not self.settings.get_boolean("follow-system-default") or self.settings.get_string("mic-input-device-id") != "":
                        self.settings.set_string("mic-input-device-id", "")
                        self.settings.set_boolean("follow-system-default", True)
                else:
                    if self.settings.get_boolean("follow-system-default") or self.settings.get_string("mic-input-device-id") != first_dev.id:
                        self.settings.set_string("mic-input-device-id", first_dev.id or "")
                        self.settings.set_boolean("follow-system-default", False)

        def on_mic_selection_changed(combobox, _param):
            selected_idx = combobox.get_selected()
            if selected_idx == Gtk.INVALID_LIST_POSITION or selected_idx >= len(self.audio_devices_list):
                return

            selected_audio_device = self.audio_devices_list[selected_idx]
            
            if selected_audio_device.id == "" and selected_audio_device.api == "default": # "System Default"
                if self.settings.get_string("mic-input-device-id") != "" or \
                   not self.settings.get_boolean("follow-system-default"):
                    self.settings.set_string("mic-input-device-id", "")
                    self.settings.set_boolean("follow-system-default", True)
            else: # Specific device
                if self.settings.get_string("mic-input-device-id") != selected_audio_device.id or \
                   self.settings.get_boolean("follow-system-default"):
                    self.settings.set_string("mic-input-device-id", selected_audio_device.id or "")
                    self.settings.set_boolean("follow-system-default", False)

        combo_row.connect("notify::selected", on_mic_selection_changed)

        def on_mic_gsettings_changed(settings_obj, key):
            new_device_id = settings_obj.get_string("mic-input-device-id")
            new_follow_default = settings_obj.get_boolean("follow-system-default")
            
            current_combo_idx = combo_row.get_selected()
            
            # Determine what the ComboRow *should* select based on new GSettings
            target_idx_to_select = Gtk.INVALID_LIST_POSITION
            if new_follow_default:
                for i, dev_iter in enumerate(self.audio_devices_list):
                    if dev_iter.id == "" and dev_iter.api == "default":
                        target_idx_to_select = i; break
            else:
                for i, dev_iter in enumerate(self.audio_devices_list):
                    if dev_iter.id == new_device_id:
                        target_idx_to_select = i; break
            
            if target_idx_to_select != Gtk.INVALID_LIST_POSITION and target_idx_to_select != current_combo_idx:
                combo_row.set_selected(target_idx_to_select)

        self.settings.connect("changed::mic-input-device-id", on_mic_gsettings_changed)
        self.settings.connect("changed::follow-system-default", on_mic_gsettings_changed)


    def _bind_device_combo_row(self, combo_row: Adw.ComboRow, key: str):
        saved_value = self.settings.get_string(key) 
        display_value = PreferencesWindow.DEVICE_VALUE_TO_DISPLAY.get(saved_value, "Auto")

        model = combo_row.get_model()
        if isinstance(model, Gtk.StringList):
            idx = self._find_string_in_model(model, display_value)
            if idx != Gtk.INVALID_LIST_POSITION:
                combo_row.set_selected(idx)
            else:
                auto_idx = self._find_string_in_model(model, "Auto")
                if auto_idx != Gtk.INVALID_LIST_POSITION: combo_row.set_selected(auto_idx)
        
        def on_notify_selected(combobox, _param):
            selected_idx = combobox.get_selected()
            if selected_idx != Gtk.INVALID_LIST_POSITION and isinstance(model, Gtk.StringList):
                selected_display = model.get_string(selected_idx)
                value_to_save = PreferencesWindow.DEVICE_DISPLAY_TO_VALUE.get(selected_display)
                if value_to_save and self.settings.get_string(key) != value_to_save:
                    self.settings.set_string(key, value_to_save)
        
        combo_row.connect("notify::selected", on_notify_selected)

        def on_gsettings_changed(settings_obj, changed_key):
            if changed_key == key and isinstance(model, Gtk.StringList):
                new_setting_val = settings_obj.get_string(key)
                new_display_val = PreferencesWindow.DEVICE_VALUE_TO_DISPLAY.get(new_setting_val, "Auto")
                
                current_combo_idx = combo_row.get_selected()
                current_display_combo_val = model.get_string(current_combo_idx) if current_combo_idx != Gtk.INVALID_LIST_POSITION else None

                if new_display_val != current_display_combo_val:
                    idx = self._find_string_in_model(model, new_display_val)
                    if idx != Gtk.INVALID_LIST_POSITION:
                        combo_row.set_selected(idx)
        self.settings.connect(f"changed::{key}", on_gsettings_changed)
        
    def _bind_combo_row_string_setting_with_map(self, combo_row: Adw.ComboRow, key: str, display_to_value_map: dict, default_value_code: str):
        value_to_display_map = {v: k for k, v in display_to_value_map.items()} # code: display
        
        saved_value_code = self.settings.get_string(key) 
        display_name_to_select = value_to_display_map.get(saved_value_code, value_to_display_map.get(default_value_code))

        model = combo_row.get_model() # Gtk.StringList of display names
        if isinstance(model, Gtk.StringList):
            idx = self._find_string_in_model(model, display_name_to_select)
            if idx != Gtk.INVALID_LIST_POSITION:
                combo_row.set_selected(idx)
            else: # Fallback to default if current saved not in map or display list
                default_display_name = value_to_display_map.get(default_value_code)
                default_idx = self._find_string_in_model(model, default_display_name)
                if default_idx != Gtk.INVALID_LIST_POSITION: combo_row.set_selected(default_idx)

        def on_notify_selected(combobox, _param):
            selected_idx = combobox.get_selected()
            if selected_idx != Gtk.INVALID_LIST_POSITION and isinstance(model, Gtk.StringList):
                selected_display_name = model.get_string(selected_idx)
                # Find the code corresponding to the selected display name
                value_code_to_save = default_value_code # Default if not found in map
                for code, display in value_to_display_map.items():
                    if display == selected_display_name:
                        value_code_to_save = code
                        break
                if self.settings.get_string(key) != value_code_to_save:
                    self.settings.set_string(key, value_code_to_save)
        
        combo_row.connect("notify::selected", on_notify_selected)

        def on_gsettings_changed(settings_obj, changed_key):
            if changed_key == key and isinstance(model, Gtk.StringList):
                new_value_code = settings_obj.get_string(key)
                new_display_name = value_to_display_map.get(new_value_code, value_to_display_map.get(default_value_code))
                
                current_combo_idx = combo_row.get_selected()
                current_display_val = model.get_string(current_combo_idx) if current_combo_idx != Gtk.INVALID_LIST_POSITION else None

                if new_display_name != current_display_val:
                    idx = self._find_string_in_model(model, new_display_name)
                    if idx != Gtk.INVALID_LIST_POSITION:
                        combo_row.set_selected(idx)
        self.settings.connect(f"changed::{key}", on_gsettings_changed)


    def _on_autolaunch_changed(self, switch_row, _param):
        is_active = switch_row.get_active()
        autostart_dir = os.path.join(GLib.get_user_config_dir(), "autostart")
        desktop_file_name = "org.hardcoeur.Recast.desktop" 
        desktop_file_path = os.path.join(autostart_dir, desktop_file_name)
        desktop_content = f"""[Desktop Entry]
Type=Application
Name=GnomeRecast
Comment=Record and Transcribe Audio
Exec=gnomerecast
Icon=org.hardcoeur.Recast
Terminal=false
Categories=GNOME;GTK;AudioVideo;Audio;
X-GNOME-Autostart-enabled=true
"""
        if is_active:
            try:
                os.makedirs(autostart_dir, exist_ok=True)
                with open(desktop_file_path, "w") as f: f.write(desktop_content)
            except Exception as e: print(f"Error creating autostart file: {e}")
        elif os.path.exists(desktop_file_path):
            try: os.remove(desktop_file_path)
            except Exception as e: print(f"Error removing autostart file: {e}")


    def _on_test_button_clicked(self, button):
        if not self.is_testing:
            self.is_testing = True
            self.test_button.set_label("Stop Test")
            self.test_audio_level = 0.0
            self.input_level_bar.set_value(0.0)
            try:
                self.test_capturer = AudioCapturer(settings=self.settings, data_callback=self._on_test_audio_data)
                self.test_capturer.start()
                self.level_update_timer_id = GLib.timeout_add(100, self._update_level_bar)
            except Exception as e:
                print(f"Error starting audio capture for test: {e}")
                self.is_testing = False; self.test_button.set_label("Start Test")
                if self.test_capturer: self.test_capturer.cleanup_on_destroy()
                self.test_capturer = None
        else:
            self._stop_audio_test()

    def _stop_audio_test(self):
        if not self.is_testing: return
        self.is_testing = False
        self.test_button.set_label("Start Test")
        if self.level_update_timer_id: GLib.source_remove(self.level_update_timer_id); self.level_update_timer_id = None
        if self.test_capturer:
            self.test_capturer.stop()
            GLib.idle_add(self.test_capturer.cleanup_on_destroy) # Ensure cleanup is on main thread
            self.test_capturer = None
        self.input_level_bar.set_value(0.0); self.test_audio_level = 0.0


    def _on_test_audio_data(self, audio_data: bytes):
        if not audio_data or not self.is_testing: return
        try:
            width = 2 
            if len(audio_data) % width != 0:
                 audio_data = audio_data[:len(audio_data) - (len(audio_data) % width)]
                 if not audio_data: return
            peak = 0
            for i in range(0, len(audio_data), width):
                sample = int.from_bytes(audio_data[i:i+width], byteorder='little', signed=True)
                peak = max(peak, abs(sample))
            max_amplitude = 32767 
            self.test_audio_level = min(peak / max_amplitude, 1.0) if max_amplitude > 0 else 0.0
        except Exception as e: print(f"Error processing audio data for level: {e}")


    def _update_level_bar(self):
        if not self.is_testing: return GLib.SOURCE_REMOVE
        self.input_level_bar.set_value(self.test_audio_level)
        return GLib.SOURCE_CONTINUE


    def _on_destroy(self, window, *args):
        if self.is_testing: self._stop_audio_test()
        
        # Model download logic (simplified for brevity, original logic assumed correct)
        selected_idx = self.model_row.get_selected()
        if selected_idx != Gtk.INVALID_LIST_POSITION:
            model_name = self.model_row.get_model().get_string(selected_idx)
            if model_name:
                self.local_model_names = {m['name'] for m in list_local_models()}
                is_available = model_name in self.available_models
                is_local = model_name in self.local_model_names
                if is_available and not is_local and self.pref_active_download is None:
                    self._start_model_download(model_name)
        
        # Disconnect GSettings handlers - important for manually connected signals
        # This would require storing handler IDs for each `self.settings.connect` call
        # For simplicity, this explicit disconnection is omitted here but is good practice.
        # Example: if self.mic_settings_handler_id: self.settings.disconnect(self.mic_settings_handler_id)
        
        return Gdk.EVENT_PROPAGATE


    def _on_selected_model_changed(self, combo_row, _param):
        selected_idx = combo_row.get_selected()
        if selected_idx != Gtk.INVALID_LIST_POSITION:
            model = combo_row.get_model() # Should be Gtk.StringList
            if isinstance(model, Gtk.StringList):
                model_name = model.get_string(selected_idx)
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
        selected_idx = self.model_row.get_selected()
        if selected_idx != Gtk.INVALID_LIST_POSITION:
            model = self.model_row.get_model() # Gtk.StringList
            if isinstance(model, Gtk.StringList):
                model_name = model.get_string(selected_idx)
                if model_name:
                    is_available = model_name in self.available_models
                    is_local = model_name in self.local_model_names 
                    if is_available and not is_local:
                        self._start_model_download(model_name)


    def _start_model_download(self, model_name: str):
        if self.pref_active_download is not None: return
        model_info = self.available_models.get(model_name)
        if not model_info or 'url' not in model_info: return

        self.model_row.set_sensitive(False) 
        self.download_model_button.set_visible(False) 
        self.download_spinner.set_visible(True); self.download_spinner.start()
        cancel_event = threading.Event()
        self.pref_active_download = {'name': model_name, 'cancel_event': cancel_event}
        threading.Thread(
            target=download_model,
            args=(model_name, model_info['url'], APP_MODEL_DIR, self._update_pref_download_progress, cancel_event),
            daemon=True
        ).start()


    def _update_pref_download_progress(self, model_name: str, percentage: float, error_message: str | None):
        GLib.idle_add(self._update_pref_download_ui, model_name, percentage, error_message)


    def _update_pref_download_ui(self, model_name: str, percentage: float, error_message: str | None):
        if not self.pref_active_download or self.pref_active_download['name'] != model_name:
            return GLib.SOURCE_REMOVE 
        is_finished = percentage >= 100.0 or percentage < 0
        if is_finished:
            self.download_spinner.stop(); self.download_spinner.set_visible(False)
            self.model_row.set_sensitive(True)
            self.local_model_names = {m['name'] for m in list_local_models()}
            self._on_selected_model_changed(self.model_row, None) 
            self.pref_active_download = None 
            # print(f"Download finished for {model_name}. Percentage: {percentage}, Error: {error_message}")
            return GLib.SOURCE_REMOVE 
        return GLib.SOURCE_CONTINUE # If we had a progress bar to update continuously
