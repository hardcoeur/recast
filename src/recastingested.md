Directory structure:
└── src/
    ├── main.py
    └── gnomerecast/
        ├── __init__.py
        ├── application.py
        ├── window.py
        ├── __pycache__/
        ├── audio/
        │   ├── __init__.py
        │   ├── capture.py
        │   ├── device_utils.py
        │   ├── wp_default_tracker.py
        │   └── __pycache__/
        ├── models/
        │   ├── __init__.py
        │   ├── transcript_item.py
        │   └── __pycache__/
        ├── transcription/
        │   ├── __init__.py
        │   ├── transcriber.py
        │   └── __pycache__/
        ├── ui/
        │   ├── toast.py
        │   └── __pycache__/
        ├── utils/
        │   ├── __init__.py
        │   ├── download.py
        │   ├── export.py
        │   ├── io.py
        │   ├── models.py
        │   └── __pycache__/
        └── views/
            ├── app_selection_dialog.py
            ├── dictation_overlay.py
            ├── history_view.py
            ├── initial_view.py
            ├── model_management_dialog.py
            ├── podcast_episode_dialog.py
            ├── podcast_url_dialog.py
            ├── preferences_window.py
            ├── progress_dialog.py
            ├── segments_view.py
            ├── transcript_view.py
            └── __pycache__/

================================================
File: main.py
================================================
#!/usr/bin/env python3

import sys
import gi

gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
gi.require_version('Gst', '1.0')

from gi.repository import Gtk, Adw, Gst
from gnomerecast.application import GnomeRecastApplication

if __name__ == "__main__":
    Gst.init(None)
    app = GnomeRecastApplication()
    exit_status = app.run(sys.argv)
    sys.exit(exit_status)


================================================
File: gnomerecast/__init__.py
================================================
# This file marks the gnomerecast directory as a Python package.


================================================
File: gnomerecast/application.py
================================================
import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Gtk, Adw, Gio, Gdk
import concurrent.futures # Added for I/O thread pool
import importlib.resources # Added for package-relative paths
import pathlib # Added for path manipulation

from .window import GnomeRecastWindow
from .views.dictation_overlay import DictationOverlay
from .views.preferences_window import PreferencesWindow

# Define the base path for data files within the gnomerecast package
_GNOMERECAST_DATA_ROOT = importlib.resources.files('gnomerecast') / 'data'

class GnomeRecastApplication(Adw.Application):
    """The main application class for GnomeRecast."""

    def __init__(self, **kwargs):
        super().__init__(application_id="org.hardcoeur.Recast", **kwargs)

        self.dictation_overlay = None
        self.preferences_window = None
        self.io_pool = concurrent.futures.ThreadPoolExecutor(max_workers=1) # For I/O operations

        self.style_manager = Adw.StyleManager.get_default()

        self._perform_settings_migration()


    def do_startup(self):
        """Called once when the application first starts."""
        Adw.Application.do_startup(self)
        
        # Note: Settings migration moved to __init__ to run even earlier,
        # but can also be here if preferred, as long as it's before settings are heavily used.
        # self._perform_settings_migration() # Ensure it runs if not in __init__

        self.css_provider = Gtk.CssProvider()
        css_path = _GNOMERECAST_DATA_ROOT / 'css' / 'style.css'
        self.css_provider.load_from_path(str(css_path))

        display = Gdk.Display.get_default()
        if display:
            Gtk.StyleContext.add_provider_for_display(
                display, self.css_provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
            )
        else:
            print("Warning: Could not get default Gdk.Display to apply CSS.")


        quit_action = Gio.SimpleAction.new("quit", None)
        quit_action.connect("activate", self.quit)
        self.add_action(quit_action)

        about_action = Gio.SimpleAction.new("about", None)
        about_action.connect("activate", self._on_about_action)
        self.add_action(about_action)

        preferences_action = Gio.SimpleAction.new("preferences", None)
        preferences_action.connect("activate", self._on_preferences_action)
        self.add_action(preferences_action)

        toggle_dictation_action = Gio.SimpleAction.new("toggle-dictation", None)
        toggle_dictation_action.connect("activate", self.toggle_dictation_overlay)
        self.add_action(toggle_dictation_action)
        self.set_accels_for_action("app.toggle-dictation", ["<Control><Alt>D"])

        builder = Gtk.Builder()
        ui_path = _GNOMERECAST_DATA_ROOT / 'ui' / 'app-menu.ui'
        builder.add_from_file(str(ui_path))

        app_menu = builder.get_object("app-menu")
        if not isinstance(app_menu, Gio.MenuModel):
            print(f"Warning: Object 'app-menu' in 'data/ui/app-menu.ui' is not a GMenuModel.")
            app_menu = None

        self.app_menu = app_menu

    @staticmethod
    def _migrate_key(settings: Gio.Settings, old_key_name: str, new_key_name: str, value_mapping: dict, new_key_type: str = "s"):
        """
        Helper to migrate a GSettings key.
        Assumes old key is a string type that needs mapping.
        New key type can be 's' (string) or other GVariant compatible types.
        """
        if settings.is_writable(old_key_name):
            try:
                # Try to get the old value. If the key doesn't exist or isn't set,
                # settings.get_string() will raise GLib.Error if the key is not in the schema.
                old_value_str = settings.get_string(old_key_name)

                if old_value_str and old_value_str in value_mapping:
                    new_value = value_mapping[old_value_str]
                    current_new_value = settings.get_string(new_key_name)
                    default_new_value = settings.get_default_value(new_key_name).get_string()

                    if current_new_value == default_new_value:
                        print(f"Migrating GSettings key '{old_key_name}' ('{old_value_str}') to '{new_key_name}' with value '{new_value}'.")
                        if new_key_type == "s":
                            settings.set_string(new_key_name, new_value)
                        # Add other types if needed
                        
                        print(f"Consider removing or resetting old key '{old_key_name}' if it's no longer used and not in current schema.")
                        # Example: try resetting, but be cautious as it might error if not in schema
                        # try:
                        #     if settings.get_user_value(old_key_name) is not None: # Check if user explicitly set it
                        #          settings.reset_key(old_key_name)
                        # except gi.repository.GLib.Error:
                        #     pass # Key not in schema, cannot reset
                    elif current_new_value == new_value:
                        print(f"Old key '{old_key_name}' maps to current value of '{new_key_name}'. No migration needed.")
                    else:
                        print(f"New key '{new_key_name}' already has a user-set value ('{current_new_value}'). Skipping migration for '{old_key_name}'.")
                elif old_value_str: # Old value exists but not in mapping
                    print(f"Old key '{old_key_name}' has value '{old_value_str}' not in mapping. Skipping migration.")
                # else: old_value_str is empty (default or not set, and readable)
                    # print(f"Old key '{old_key_name}' is empty or default. No migration needed.")

            except gi.repository.GLib.Error as e:
                # This error occurs if get_string fails even if is_writable was true
                print(f"Error reading GSettings key '{old_key_name}' even though it was writable, skipping migration: {e}")
            except Exception as e: # Catch any other unexpected errors during migration logic
                print(f"Unexpected error migrating GSettings key '{old_key_name}': {e}")
        else:
            print(f"Old GSettings key '{old_key_name}' not found (is_writable is False), skipping migration.")


    def _perform_settings_migration(self):
        """Performs one-time settings migrations if needed."""
        settings = Gio.Settings.new("org.hardcoeur.Recast")
        
        # --- Microphone settings migration (existing) ---
        new_mic_id_key = "mic-input-device-id"
        new_follow_default_key = "follow-system-default"
        old_mic_key = "mic-input-device"

        if settings.is_writable(old_mic_key):
            try:
                old_mic_value = settings.get_string(old_mic_key) # Try to read the old key's value

                # If successful, proceed with migration checks
                # Check if new keys are at their default values
                new_mic_id_is_default = (settings.get_string(new_mic_id_key) == settings.get_default_value(new_mic_id_key).get_string())
                new_follow_is_default = (settings.get_boolean(new_follow_default_key) == settings.get_default_value(new_follow_default_key).get_boolean())

                if new_mic_id_is_default and new_follow_is_default:
                    # New keys are default. Now check if the old key had a meaningful, non-empty value.
                    if old_mic_value != "":
                        print(f"Migrating old microphone setting: '{old_mic_key}' ('{old_mic_value}') to '{new_mic_id_key}' and '{new_follow_default_key}'.")
                        settings.set_string(new_mic_id_key, old_mic_value)
                        settings.set_boolean(new_follow_default_key, False)
                        
                        print(f"Attempting to clear old microphone setting key '{old_mic_key}'.")
                        try:
                            # This reset_key is important if the old key is still in the schema but deprecated.
                            # If not in schema, it might error, but that's fine, we tried.
                            settings.reset_key(old_mic_key)
                            print(f"Successfully reset old key '{old_mic_key}'.")
                        except gi.repository.GLib.Error as reset_e:
                            print(f"Could not reset old key '{old_mic_key}' (it might not be in the current schema or already reset): {reset_e}")
                        
                        print(f"Microphone migration complete: '{new_mic_id_key}' set to '{old_mic_value}', '{new_follow_default_key}' to False.")
                    else:
                        # Old key was readable but empty.
                        print(f"No microphone setting migration needed for '{old_mic_key}' (old value was empty).")
                else:
                    # New keys are not at their default values, so migration is not appropriate.
                    print(f"No microphone setting migration needed for '{old_mic_key}' (new keys '{new_mic_id_key}' or '{new_follow_default_key}' already have user-set values).")

            except gi.repository.GLib.Error as e:
                # This error occurs if get_string fails even if is_writable was true
                print(f"Error reading GSettings key '{old_mic_key}' even though it was writable, skipping migration: {e}")
            except Exception as e: # Catch any other unexpected errors during this specific migration
                print(f"Unexpected error during microphone setting migration for '{old_mic_key}': {e}")
        else:
            print(f"Old GSettings key '{old_mic_key}' not found (is_writable is False), skipping migration.")

        # --- Whisper Device Mode Migration ---
        # Hypothetical old key: "whisper-device" (e.g., an integer enum)
        # New key: "whisper-device-mode" (string: "auto", "cpu", "cuda")
        device_mode_mapping = {'0': 'auto', '1': 'cpu', '2': 'cuda'}
        # Assuming the old key was also a string type for get_string to work,
        # or it would need a different getter if it was, e.g., an integer.
        # For this example, we'll assume it was a string '0', '1', '2'.
        GnomeRecastApplication._migrate_key(settings,
                                            "whisper-device",
                                            "whisper-device-mode",
                                            device_mode_mapping)

        # --- Whisper Compute Type Migration ---
        # Hypothetical old key: "whisper-compute-precision" (e.g., an integer enum)
        # New key: "whisper-compute-type" (string: "auto", "int8", "float16")
        # Note: Schema includes "float32", spec mentions "float32", mapping only has up to float16.
        # Adding float32 to mapping for completeness if an old key '3' existed.
        compute_type_mapping = {'0': 'auto', '1': 'int8', '2': 'float16', '3': 'float32'}
        GnomeRecastApplication._migrate_key(settings,
                                            "whisper-compute-precision",
                                            "whisper-compute-type",
                                            compute_type_mapping)
        
        print("Settings migration check complete.")


    def _on_theme_mode_changed(self, settings, key):
        """Handles changes to the 'theme-mode' GSetting."""
        theme_mode_str = settings.get_string(key)

        if theme_mode_str == "Light":
            mapped_scheme = Adw.ColorScheme.FORCE_LIGHT
        elif theme_mode_str == "Dark":
            mapped_scheme = Adw.ColorScheme.FORCE_DARK
        else:
            mapped_scheme = Adw.ColorScheme.DEFAULT

        self.style_manager.set_color_scheme(mapped_scheme)

    def _on_font_size_changed(self, settings, key):
        """Handles changes to the 'font-size' GSetting and updates CSS."""
        font_size = settings.get_int(key)
        css = f"""
        window, label, textview, button {{
            font-size: {font_size}pt;
        }}
        """
        self.css_provider.load_from_string(css)


    def do_activate(self):
        """Called when the application is activated."""
        win = self.props.active_window
        if not win:
            win = GnomeRecastWindow(application=self, app_menu=self.app_menu)
        win.present()

    def do_shutdown(self):
        """Called when the application is shutting down."""
        Adw.Application.do_shutdown(self)
        if self.io_pool:
            print("Shutting down I/O thread pool...")
            self.io_pool.shutdown(wait=True)
            self.io_pool = None
            print("I/O thread pool shut down.")
        # Any other application-specific shutdown tasks can go here

    def toggle_dictation_overlay(self):
        """Shows or hides the dictation overlay window."""
        if self.dictation_overlay is None:
            self.dictation_overlay = DictationOverlay(application=self)

        if self.dictation_overlay.is_visible():
            self.dictation_overlay.hide()
        else:
            self.dictation_overlay.present()

    def _on_about_action(self, action, param):
        """Handles the 'about' action."""
        about_window = Adw.AboutWindow(
            application_name="Recast",
            developer_name="Robert Renling",
            version="0.2.0",
            application_icon="org.hardcoeur.GnomeRecast",
            website="https://github.com/hardcoeur/recast",
            comments="A simple app to transcribe audio.",
            license_type=Gtk.License.GPL_3_0_ONLY,
        )
        active_window = self.get_active_window()
        if active_window:
            about_window.set_transient_for(active_window)
            about_window.set_modal(True)
        about_window.present()

    def _on_preferences_action(self, action, param):
        """Handles the 'preferences' action, ensuring only one instance is created."""
        active_window = self.get_active_window()
        if self.preferences_window is None:
            self.preferences_window = PreferencesWindow()
        self.preferences_window.present(active_window)


================================================
File: gnomerecast/window.py
================================================
import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Gtk, Adw, GLib, Gio, Gdk, Pango
import wave
import tempfile
import os
import re
import json # Added for JSON export
from datetime import datetime # Added for default filenames
import importlib.resources # Added for package-relative paths
import pathlib # Added for path manipulation

from typing import Optional, Any
from .audio.capture import AudioCapturer
from .views.transcript_view import TranscriptionView
from .views.initial_view import InitialView
from .transcription.transcriber import Transcriber
from .views.history_view import HistoryView
from .models.transcript_item import TranscriptItem, SegmentItem
from .utils import export as export_utils # Added
from .utils.io import atomic_write_json # Added
from .ui.toast import ToastPresenter # Added for toast framework

# Define the base path for data files within the gnomerecast package
_GNOMERECAST_DATA_ROOT = importlib.resources.files('gnomerecast') / 'data'

LANGUAGE_MAP = {"auto": "Auto Detect", "en": "English", "es": "Spanish"}
REVERSE_LANGUAGE_MAP = {v: k for k, v in LANGUAGE_MAP.items()}

MODE_MAP = {"fast": "Fast", "balanced": "Balanced", "accurate": "Accurate"}
MODE_TO_MODEL = {"fast": "tiny", "balanced": "base", "accurate": "small"}
MODEL_TO_MODE = {v: k for k, v in MODE_TO_MODEL.items()}

class GnomeRecastWindow(Adw.ApplicationWindow):
    """The main application window for GnomeRecast."""


    def __init__(self, app_menu: Optional[Gio.MenuModel] = None, **kwargs):
        super().__init__(**kwargs)

        self.settings = Gio.Settings.new("org.hardcoeur.Recast")

        self.set_title("")
        self.set_default_size(800, 600)

        self.recording_audio_capturer = None
        self.recording_audio_buffer = bytearray()

        self.transcriber = Transcriber()
        self._selected_history_transcript: Optional[TranscriptItem] = None
        self.last_export_filter_name: Optional[str] = None # Added to store last export filter

        self.header_bar = Adw.HeaderBar()
        self.header_bar.add_css_class("window-header-bar")
        self.window_title_widget = Adw.WindowTitle(title="")
        self.window_title_widget.add_css_class("window-title")

        self.main_menu_button = Gtk.MenuButton()
        self.main_menu_button.add_css_class("main-menu-button")
        self.main_menu_button.set_icon_name("open-menu-symbolic")
        self.main_menu_button.set_tooltip_text("Main Menu")
        if app_menu:
             self.main_menu_button.set_menu_model(app_menu)
        else:
             self.main_menu_button.set_sensitive(False)
             print("Warning: No app_menu model received by window, disabling menu button.")
        self.header_bar.pack_end(self.main_menu_button)

        self.reader_button = Gtk.Button(label="Reader")
        self.reader_button.set_tooltip_text("Show cleaned transcript text")
        self.reader_button.set_visible(False)
        self.reader_button.set_sensitive(False)
        self.reader_button.connect("clicked", self._on_reader_button_clicked)
        self.header_bar.pack_end(self.reader_button)

        mode_menu = Gio.Menu()
        mode_menu.append_item(Gio.MenuItem.new(MODE_MAP['accurate'], 'win.select-mode::accurate'))
        mode_menu.append_item(Gio.MenuItem.new(MODE_MAP['balanced'], 'win.select-mode::balanced'))
        mode_menu.append_item(Gio.MenuItem.new(MODE_MAP['fast'], 'win.select-mode::fast'))
        self.mode_button = Gtk.MenuButton(
            menu_model=mode_menu,
            tooltip_text="Choose transcription accuracy mode"
        )
        self.header_bar.pack_end(self.mode_button)

        language_menu = Gio.Menu()
        language_menu.append_item(Gio.MenuItem.new(LANGUAGE_MAP['auto'], 'win.select-language::auto'))
        language_menu.append_item(Gio.MenuItem.new(LANGUAGE_MAP['en'], 'win.select-language::en'))
        language_menu.append_item(Gio.MenuItem.new(LANGUAGE_MAP['es'], 'win.select-language::es'))
        self.language_button = Gtk.MenuButton(
            menu_model=language_menu,
            tooltip_text="Choose transcription language"
        )
        self.header_bar.pack_end(self.language_button)


        self.is_recording = False
        self.recording_timer_id = None
        self.recording_start_time = None

        self.recording_controls_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        rec_icon = Gtk.Image(icon_name="media-record-symbolic")
        self.recording_timer_label = Gtk.Label(label="00:00")
        self.stop_recording_button = Gtk.Button(label="Stop Recording")
        self.stop_recording_button.connect("clicked", self._on_stop_recording_clicked)

        self.recording_controls_box.append(rec_icon)
        self.recording_controls_box.append(self.recording_timer_label)
        self.recording_controls_box.append(self.stop_recording_button)
        self.recording_controls_box.set_visible(False)

        self.header_bar.set_title_widget(self.window_title_widget)


        self.initial_view = InitialView()
        self.transcript_view = TranscriptionView()
        # Pass the application instance to HistoryView
        app_instance = self.get_application()
        self.history_view = HistoryView(application=app_instance, on_transcript_selected=self._load_transcript_from_history)
        self.history_view.connect("transcript-selected", self._on_history_item_selected)


        self.initial_view.connect("start-recording", self.start_recording_ui)
        self.initial_view.connect("stop-recording", self._on_stop_recording_clicked)

        self.leaflet = Adw.Leaflet()
        self.leaflet.set_hexpand(True)
        self.leaflet.set_vexpand(True)
        self.leaflet.set_can_unfold(False)
        self.leaflet.set_can_navigate_back(False)
        self.leaflet.set_can_navigate_forward(False)

        self.leaflet.append(self.initial_view)
        initial_page = self.leaflet.get_page(self.initial_view)
        initial_page.set_property("name", "initial")

        self.leaflet.append(self.transcript_view)
        transcript_page = self.leaflet.get_page(self.transcript_view)
        transcript_page.set_property("name", "transcript")

        self.leaflet.append(self.history_view)
        history_page = self.leaflet.get_page(self.history_view)
        history_page.set_property("name", "history")

        self._set_active_view("initial")

        drop_target = Gtk.DropTarget.new(Gio.File, Gdk.DragAction.COPY)
        drop_target.connect("drop", self._on_file_drop)
        self.leaflet.add_controller(drop_target)

        toolbar_view = Adw.ToolbarView()
        toolbar_view.add_top_bar(self.header_bar)

        # Initialize ToastOverlay and wrap the leaflet
        self.toast_overlay = Adw.ToastOverlay()
        self.toast_overlay.set_child(self.leaflet) # Leaflet is the content over which toasts appear
        toolbar_view.set_content(self.toast_overlay) # ToolbarView now manages the ToastOverlay
        ToastPresenter.attach(self.toast_overlay) # Register with singleton presenter

        main_hbox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)

        self.sidebar_vbox = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=6,
            margin_top=12,
            margin_bottom=12,
            margin_start=6,
            margin_end=6,
            width_request=32,
            height_request=32
        )
        main_hbox.append(self.sidebar_vbox)


        main_hbox.append(toolbar_view)
        toolbar_view.set_hexpand(True)
        toolbar_view.set_vexpand(True)

        self.set_content(main_hbox)

        # Diagnostic: Try loading 'compass' as a themed icon
        home_button = Gtk.Button()
        home_button.set_icon_name("compass-symbolic") # Assuming 'compass-symbolic' is the installed name for compass-symbolic.svg
        home_button.set_tooltip_text("Home (Themed Icon Test)")
        home_button.connect("clicked", self.show_initial_view)
        self.sidebar_vbox.append(home_button)
        headset_icon_path = _GNOMERECAST_DATA_ROOT / 'icons' / 'headset.png'
        history_icon_path = _GNOMERECAST_DATA_ROOT / 'icons' / 'history.png'
        self._add_sidebar_button(str(headset_icon_path), self.show_transcript_view, "Transcribe")
        self._add_sidebar_button(str(history_icon_path), self.show_history_view, "History")


        self._create_language_action()
        self._create_mode_action()
        self._create_export_action()
        self._create_save_action()
        self._create_open_action() # Added

        self._update_language_button_label()
        self._update_mode_button_label()

        self.settings.connect("changed::target-language", lambda s, k: self._update_language_button_label())
        self.settings.connect("changed::auto-detect-language", lambda s, k: self._update_language_button_label())
        self.settings.connect("changed::default-model", lambda s, k: self._update_mode_button_label())


    def _add_sidebar_button(self, icon_path, callback, tooltip_text):
        """Creates a Gtk.Button with an icon, connects it, and adds it to the sidebar."""
        icon = Gtk.Picture.new_for_filename(icon_path)
        icon.set_content_fit(Gtk.ContentFit.COVER)
        icon.set_can_shrink(False)
        icon.set_size_request(32, 32)
        button = Gtk.Button()
        button.set_child(icon)
        button.set_tooltip_text(tooltip_text)
        button.connect("clicked", callback)
        self.sidebar_vbox.append(button)

    def _set_active_view(self, view_name: str):
        """
        Centralized method to switch the visible child in the leaflet
        and update the state of related actions (e.g., export).
        """
        if hasattr(self, 'leaflet') and self.leaflet:
            self.leaflet.set_visible_child_name(view_name)
            is_transcript_view_active = (view_name == "transcript")
            
            export_action = self.lookup_action("export-transcript")
            if export_action:
                # Enable export if transcript view is active AND has content
                has_content_for_export = hasattr(self.transcript_view, 'has_content') and self.transcript_view.has_content()
                export_action.set_enabled(is_transcript_view_active and has_content_for_export)

            save_action = self.lookup_action("save-transcript")
            if save_action:
                 # Enable save if transcript view is active AND has content
                has_content_for_save = hasattr(self.transcript_view, 'has_content') and self.transcript_view.has_content()
                save_action.set_enabled(is_transcript_view_active and has_content_for_save)


            if hasattr(self, "reader_button"):
               is_history_view = (view_name == "history")
               self.reader_button.set_visible(is_history_view)
               if not is_history_view:
                    self.reader_button.set_sensitive(False)
                    self._selected_history_transcript = None

            print(f"GnomeRecastWindow: Switched active view to '{view_name}'.")
        else:
            print(f"GnomeRecastWindow: Error - Leaflet not found when trying to set active view to '{view_name}'.")


    def _on_recording_audio_data(self, audio_data):
        """Callback function to receive audio data chunks during recording."""
        if self.is_recording and self.recording_audio_buffer is not None:
            self.recording_audio_buffer.extend(audio_data)

    def show_transcript_view(self, sender, transcript_item=None):
        """
        Handles the 'history-item-activated' signal or direct calls to show a transcript.
        If called from sidebar (no transcript_item), it just navigates to the view.
        Switches the main view to the transcript view and loads the selected item if provided.
        """
        from .models.transcript_item import TranscriptItem

        if transcript_item:
            if not isinstance(transcript_item, TranscriptItem):
                print(f"Error in show_transcript_view: Expected TranscriptItem, got {type(transcript_item)}")
                return
            print(f"GnomeRecastWindow: Received history-item-activated for {transcript_item.uuid}")
        else:
            if isinstance(sender, Gtk.Button):
                 print("GnomeRecastWindow: Sidebar 'Transcribe' button clicked. Navigating to transcript view.")
            else:
                 print("GnomeRecastWindow: show_transcript_view called without item. Navigating to transcript view.")
            self._set_active_view("transcript")
            return

        if hasattr(self, 'transcript_view') and self.transcript_view:
            print(f"GnomeRecastWindow: Loading transcript {transcript_item.uuid} into view.")
            self.transcript_view.load_transcript(transcript_item)
            print(f"GnomeRecastWindow: Setting visible child to transcript_view.")
            self._set_active_view("transcript")
        else:
            print("Error in show_transcript_view: TranscriptView not initialized or accessible.")


    def show_initial_view(self, button=None):
            """
            Switches the main view back to the initial view and resets relevant state.
            """
            print("GnomeRecastWindow: Switching back to initial view.")
            if hasattr(self, 'transcript_view') and self.transcript_view:
                if hasattr(self.transcript_view, 'player_controls') and self.transcript_view.player_controls:
                    if hasattr(self.transcript_view.player_controls, 'player') and self.transcript_view.player_controls.player:
                        print("GnomeRecastWindow: Stopping media player in transcript view.")
                        self.transcript_view.player_controls.player.stop()
                else:
                    print("GnomeRecastWindow: TranscriptView has no player_controls attribute.")
            else:
                print("GnomeRecastWindow: TranscriptView not found, cannot stop player.")


            self._set_active_view("initial")

    def show_history_view(self, button=None):
        """Switches the main view to the history view."""
        print("GnomeRecastWindow: Switching to history view.")
        self._set_active_view("history")
        if hasattr(self, 'reader_button'):
            self.reader_button.set_sensitive(False)
        self._selected_history_transcript = None


    def start_recording_ui(self, *args):
        """Configures the UI to show recording controls."""
        if self.is_recording:
            return

        print("GnomeRecastWindow: Starting recording UI.")
        self.is_recording = True

        print("GnomeRecastWindow: Starting audio capture.")
        self.recording_audio_buffer.clear()
        try:
            self.recording_audio_capturer = AudioCapturer(
                settings=self.settings,
                data_callback=self._on_recording_audio_data
            )
            self.recording_audio_capturer.start()
            print("GnomeRecastWindow: AudioCapturer started.")
        except Exception as e:
            print(f"GnomeRecastWindow: Error starting AudioCapturer: {e}")
            self.stop_recording_ui()
            return

        self.window_title_widget.set_visible(False)
        self.header_bar.set_title_widget(self.recording_controls_box)
        self.recording_controls_box.set_visible(True)

        self.recording_timer_label.set_text("00:00")
        self.recording_start_time = GLib.get_monotonic_time()
        if self.recording_timer_id:
                GLib.source_remove(self.recording_timer_id)
        self.recording_timer_id = GLib.timeout_add_seconds(1, self._update_recording_timer)
        print("GnomeRecastWindow: Recording UI started.")


    def stop_recording_ui(self):
        """Configures the UI back to the default state after recording stops."""
        if not self.is_recording:
            return

        print("GnomeRecastWindow: Stopping recording UI.")
        self.is_recording = False

        if self.recording_timer_id:
            GLib.source_remove(self.recording_timer_id)
            self.recording_timer_id = None
            print("GnomeRecastWindow: Recording timer stopped.")

        self.recording_controls_box.set_visible(False)
        self.header_bar.set_title_widget(self.window_title_widget)
        self.window_title_widget.set_visible(True)
        print("GnomeRecastWindow: Recording UI stopped.")
        if hasattr(self, 'initial_view') and self.initial_view:
             self.initial_view.reset_button_state()


    def _update_recording_timer(self):
        """Updates the recording timer label every second."""
        if not self.is_recording or self.recording_start_time is None:
            print("GnomeRecastWindow: Timer update called but not recording. Stopping timer.")
            self.recording_timer_id = None
            return GLib.SOURCE_REMOVE

        now = GLib.get_monotonic_time()
        elapsed_us = now - self.recording_start_time
        elapsed_s = int(elapsed_us // 1_000_000)

        minutes = elapsed_s // 60
        seconds = elapsed_s % 60
        time_str = f"{str(minutes).zfill(2)}:{str(seconds).zfill(2)}"
        self.recording_timer_label.set_text(time_str)

        return GLib.SOURCE_CONTINUE


    def _on_stop_recording_clicked(self, *args):
        """Handles the stop-recording signal or button click."""
        print("GnomeRecastWindow: Stop recording button clicked.")

        if self.recording_audio_capturer:
            print("GnomeRecastWindow: Stopping audio capture.")
            self.recording_audio_capturer.stop()
            # Ensure cleanup is called, potentially on idle_add if it involves GLib operations
            GLib.idle_add(self.recording_audio_capturer.cleanup_on_destroy)
            self.recording_audio_capturer = None
            print("GnomeRecastWindow: AudioCapturer stopped and cleanup scheduled.")
        else:
            print("GnomeRecastWindow: No active audio capturer found to stop.")

        self.stop_recording_ui()

        if self.recording_audio_buffer:
            print(f"GnomeRecastWindow: Saving recorded audio buffer ({len(self.recording_audio_buffer)} bytes).")
            try:
                with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as temp_file:
                    temp_wav_path = temp_file.name

                print(f"GnomeRecastWindow: Writing to temporary WAV file: {temp_wav_path}")
                with wave.open(temp_wav_path, 'wb') as wf:
                    wf.setnchannels(1)
                    wf.setsampwidth(2)
                    wf.setframerate(16000)
                    wf.writeframes(self.recording_audio_buffer)

                self._start_transcription_process([temp_wav_path])
            except Exception as e:
                print(f"GnomeRecastWindow: Error saving recording to WAV file: {e}")

            finally:
                self.recording_audio_buffer.clear()
                print("GnomeRecastWindow: Audio buffer cleared.")
        else:
            print("GnomeRecastWindow: No audio recorded.")

    def on_segment_generated(self, segment_dict: dict):
        """Handles a single segment generated by the transcriber."""
        print(f"Window: Received segment [{segment_dict.get('start', '?'):.2f}s->{segment_dict.get('end', '?'):.2f}s], scheduling UI update.")
        if 'start' in segment_dict and 'start_ms' not in segment_dict:
            segment_dict["start_ms"] = int(float(segment_dict["start"]) * 1000)
        if 'end' in segment_dict and 'end_ms' not in segment_dict:
            segment_dict["end_ms"] = int(float(segment_dict["end"]) * 1000)

        GLib.idle_add(self._idle_add_segment_callback, segment_dict)

    def _idle_add_segment_callback(self, segment_dict):
        """Helper function called by GLib.idle_add to add a segment with debugging."""
        print(f"Window (idle_add): Calling add_segment for [{segment_dict.get('start', '?'):.2f}s->{segment_dict.get('end', '?'):.2f}s].")
        if hasattr(self, 'transcript_view') and self.transcript_view:
            self.transcript_view.add_segment(segment_dict)
        else:
            print("Window (idle_add): Error - TranscriptView not found when trying to add segment.")
        return GLib.SOURCE_REMOVE

    def _start_transcription_process(self, file_paths: list, cleanup_paths: list | None = None):
        """
        Starts the transcription process for the given file paths, integrating progress
        and results directly into TranscriptionView. Optionally cleans up specified
        temporary files upon successful completion.

        Args:
            file_paths: A list of absolute paths to audio/video files.
            cleanup_paths: An optional list of absolute paths to files that should be
                            deleted after successful transcription.
        """
        if not file_paths:
            print("GnomeRecastWindow: No file paths provided for transcription.")
            return

        self.transcript_view.reset_view()

        GLib.idle_add(self._set_active_view, "transcript")

        def on_progress(fraction: float, total_segments: int = 0, completed_segments: int = 0):
            """Callback for transcription progress updates."""
            GLib.idle_add(self.transcript_view.update_progress, fraction, total_segments, completed_segments)

        # Updated on_completion to handle new parameters from transcriber
        def on_completion(status: str, transcript_segments: list, saved_json_path: Optional[str], save_error_message: Optional[str]):
            """Handles transcription completion, cleanup, and final state, including save status."""
            print(f"GnomeRecastWindow: Transcription process finished. Status: {status}, Saved JSON: {saved_json_path}, Save Error: {save_error_message}")

            # Determine primary success based on transcription itself
            transcription_successful = status == 'completed' or status == 'completed_save_failed'

            if cleanup_paths and transcription_successful: # Cleanup if transcription part was okay
                print(f"GnomeRecastWindow: Transcription part successful. Attempting cleanup for: {cleanup_paths}")
                for path in cleanup_paths:
                    try:
                        if os.path.exists(path):
                            os.remove(path)
                            print(f"GnomeRecastWindow: Successfully removed temporary file: {path}")
                        else:
                            print(f"GnomeRecastWindow: Temporary file not found for cleanup: {path}")
                    except OSError as e:
                        print(f"GnomeRecastWindow: Error removing temporary file {path}: {e}")
            elif cleanup_paths:
                print(f"GnomeRecastWindow: Transcription status was '{status}'. Skipping cleanup for: {cleanup_paths}")

            if status == 'completed': # Transcription and save successful
                toast_message = f"Saved ✓ {os.path.basename(saved_json_path)}" if saved_json_path else "Transcription complete, save path unknown."
                ToastPresenter.show(self, toast_message)
                GLib.idle_add(self.history_view.refresh_list)
                print(f"GnomeRecastWindow: Transcription and save successful. Segments added in real-time. History refreshed.")
            elif status == 'completed_save_failed':
                base_filename = os.path.basename(cleanup_paths[0]) if cleanup_paths else "transcript" # Get a filename for the toast
                toast_message = f"❌ Could not save {base_filename}: {save_error_message or 'Unknown error'}"
                ToastPresenter.show(self, toast_message)
                # Transcription itself was okay, segments might be in view, but not persisted.
                # Decide if history should be refreshed if a .tmp file might exist or if it's an overwrite fail.
                # For now, let's not refresh history if save failed, to avoid showing a non-existent item.
                print(f"GnomeRecastWindow: Transcription successful, but save failed. Segments might be in view.")
            elif status == 'error':
                toast_message = f"❌ Transcription failed: {save_error_message or 'Unknown error'}"
                ToastPresenter.show(self, toast_message)
                print(f"GnomeRecastWindow: Transcription failed. Error: {save_error_message}")
                if hasattr(self, 'initial_view') and self.initial_view:
                    GLib.idle_add(self.initial_view.reset_button_state)
                GLib.idle_add(self.show_initial_view)
            elif status == 'cancelled':
                ToastPresenter.show(self, "Transcription cancelled.")
                print(f"GnomeRecastWindow: Transcription cancelled by user.")
                # Optionally, revert to initial view or leave as is
                if hasattr(self, 'initial_view') and self.initial_view:
                    GLib.idle_add(self.initial_view.reset_button_state)
                GLib.idle_add(self.show_initial_view) # Or stay on transcript view if partially filled
            elif status == 'no_files':
                ToastPresenter.show(self, "No files selected for transcription.")
            else: # Other unexpected statuses
                ToastPresenter.show(self, f"Transcription finished with status: {status}")
                if hasattr(self, 'initial_view') and self.initial_view:
                    GLib.idle_add(self.initial_view.reset_button_state)
                GLib.idle_add(self.show_initial_view)


        self.transcriber.start_transcription(
            file_paths=file_paths,
            progress_callback=on_progress,
            segment_callback=self.on_segment_generated,
            completion_callback=on_completion
        )
        print(f"GnomeRecastWindow: Transcription started for {file_paths}")


    def _on_file_drop(self, drop_target, value, x, y):
        """Handles the 'drop' signal from the main view stack's drop target."""
        print(f"GnomeRecastWindow: Drop detected. Value type: {type(value)}")
        if isinstance(value, Gio.File):
            file_path = value.get_path()
            if file_path:
                print(f"GnomeRecastWindow: File dropped: {file_path}")
                if os.path.exists(file_path) and os.path.isfile(file_path):
                    if file_path.lower().endswith(".json"):
                        print(f"Attempting to import (drag & drop) JSON transcript: {file_path}")
                        self._import_transcript_file(file_path) # Use the new import handler
                    else:
                        # Assume it's an audio/video file for transcription
                        print(f"Attempting to transcribe (drag & drop) media file: {file_path}")
                        self.transcript_view.reset_view()
                        self._set_active_view("transcript")
                        self._start_transcription_process([file_path], cleanup_paths=[])
                    return True
                else:
                    print(f"GnomeRecastWindow: Dropped path is not a valid file: {file_path}")
                    return False
            else:
                print("GnomeRecastWindow: Dropped Gio.File has no path.")
                return False
        elif isinstance(value, Gtk.StringObject):
                text = value.get_string()
                print(f"GnomeRecastWindow: Text dropped (ignored): {text[:50]}...")
                return False
        else:
            print(f"GnomeRecastWindow: Unsupported drop value type: {type(value)}")
            return False

    def _create_mode_action(self):
        """Creates and adds a stateful action for mode selection."""
        action = Gio.SimpleAction.new_stateful(
            "select-mode", GLib.VariantType.new('s'), GLib.Variant.new_string(self._get_current_mode_key())
        )
        action.connect("change-state", self._on_select_mode)
        self.add_action(action)
        print("Action 'win.select-mode' created.")

    def _create_language_action(self):
        """Creates and adds a stateful action for language selection."""
        action = Gio.SimpleAction.new_stateful(
            "select-language", GLib.VariantType.new('s'), GLib.Variant.new_string(self._get_current_language_key())
        )
        action.connect("change-state", self._on_select_language)
        self.add_action(action)
        print("Action 'win.select-language' created.")

    def _create_export_action(self):
        """Creates and adds a simple action for exporting the transcript."""
        action = Gio.SimpleAction.new("export-transcript", None)
        action.connect("activate", self._on_export_transcript)
        action.set_enabled(False) # Initially disabled, enabled when transcript view is active
        self.add_action(action)
        print("Action 'win.export-transcript' created.")

    def _create_save_action(self):
        """Creates and adds a simple action for saving the current transcript."""
        action = Gio.SimpleAction.new("save-transcript", None)
        action.connect("activate", self._on_save_transcript)
        # Sensitivity will be managed based on transcript_view content
        # For now, let's assume it's enabled if transcript_view has content.
        # This will be checked in _on_save_transcript or by a separate update method.
        action.set_enabled(False) # Start disabled, enable when content is available
        self.add_action(action)
        # Accelerators for window actions are set on the application
        app = self.get_application()
        if app:
            app.set_accels_for_action("win.save-transcript", ["<Control>s"])
        print("Action 'win.save-transcript' (Ctrl+S) created.")

    def _create_open_action(self):
        """Creates and adds a simple action for opening a transcript or media file."""
        action = Gio.SimpleAction.new("open-file", None)
        action.connect("activate", self._on_open_file_activate)
        self.add_action(action)
        app = self.get_application()
        if app:
            # Using "win.open-file" to be consistent with other window actions if it's window-specific.
            # If it's a global app action that could be triggered without the window, "app.open-file" is fine.
            # Let's assume it's tied to this window's context for now.
            app.set_accels_for_action("win.open-file", ["<Control>o"])
        print("Action 'win.open-file' (Ctrl+O) created.")


    def _on_history_item_selected(self, history_view, transcript_item):
        """Updates UI when a transcript item is selected in history view."""
        print(f"Transcript selected: {transcript_item.output_filename}")
        self._selected_history_transcript = transcript_item
        if hasattr(self, 'reader_button'):
            # Enable reader button only if the selected item has segments
            self.reader_button.set_sensitive(bool(transcript_item and transcript_item.segments))

    def _on_select_mode(self, action, value):
        """Handles state change for the mode selection action."""
        new_mode_key = value.get_string()
        print(f"Changing mode to: {new_mode_key}")

        if new_mode_key in MODE_TO_MODEL:
            new_model_size = MODE_TO_MODEL[new_mode_key]
            self.settings.set_string("default-model", new_model_size)
            action.set_state(value)
        else:
            print(f"Warning: Unknown mode key selected: {new_mode_key}")

    def _on_select_language(self, action, value):
        """Handles state change for the language selection action."""
        new_lang_key = value.get_string()
        print(f"Changing language to: {new_lang_key}")

        if new_lang_key == "auto":
            self.settings.set_boolean("auto-detect-language", True)
        elif new_lang_key in LANGUAGE_MAP:
            self.settings.set_boolean("auto-detect-language", False)
            self.settings.set_string("target-language", new_lang_key)
        else:
            print(f"Warning: Unknown language key selected: {new_lang_key}")
            return

        action.set_state(value)


    def _get_current_mode_key(self) -> str:
        """Gets the current mode key based on GSettings."""
        current_model = self.settings.get_string("default-model")
        return MODEL_TO_MODE.get(current_model, "balanced")

    def _get_current_language_key(self) -> str:
        """Gets the current language key based on GSettings."""
        if self.settings.get_boolean("auto-detect-language"):
            return "auto"
        else:
            return self.settings.get_string("target-language")

    def _update_mode_button_label(self):
        """Updates the mode button label based on the current GSettings."""
        current_mode_key = self._get_current_mode_key()
        label = MODE_MAP.get(current_mode_key, "Unknown Mode")
        self.mode_button.set_label(label)
        mode_action = self.lookup_action("select-mode")
        if mode_action and mode_action.get_state().get_string() != current_mode_key:
                mode_action.set_state(GLib.Variant.new_string(current_mode_key))
        print(f"Mode button label updated to: {label}")

    def _update_language_button_label(self):
        """Updates the language button label based on the current GSettings."""
        current_lang_key = self._get_current_language_key()
        label = LANGUAGE_MAP.get(current_lang_key, "Unknown Lang")
        self.language_button.set_label(label)
        lang_action = self.lookup_action("select-language")
        if lang_action and lang_action.get_state().get_string() != current_lang_key:
                lang_action.set_state(GLib.Variant.new_string(current_lang_key))
        print(f"Language button label updated to: {label}")


    def _on_export_transcript(self, action, param):
        """Handles the 'activate' signal for the 'export-transcript' action."""
        print("Export Transcript action activated.")

        if not (hasattr(self, 'transcript_view') and self.transcript_view and
                hasattr(self.transcript_view, 'has_content') and self.transcript_view.has_content()):
            ToastPresenter.show(self, "Nothing to export.")
            print("Export action: No active transcript content to export.")
            return

        current_item = self.transcript_view.get_current_item()
        if not current_item:
            # Fallback: try to construct a temporary item from view data if no item is formally loaded
            # This case should be less common if transcription/load always sets current_item.
            # For now, we require a current_item to get metadata like output_filename_base.
             view_data = self.transcript_view.get_transcript_data_for_saving()
             if not view_data or not view_data.get("segments"):
                ToastPresenter.show(self, "No transcript data available to export.")
                return
            # Create a temporary TranscriptItem for export if one isn't set.
            # This is a simplified approach.
             current_item = TranscriptItem(
                source_path="", # No source path for an unsaved item
                transcript_text=view_data.get("text", ""),
                segments=[SegmentItem(**s) for s in view_data.get("segments", [])], # Reconstruct SegmentItem objects
                language=view_data.get("language", "en")
            )
             current_item.output_filename = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_export"


        dialog = Gtk.FileDialog.new()
        dialog.set_title("Export Transcript As...")

        # Define file filters
        filters = Gio.ListStore.new(Gtk.FileFilter)
        
        txt_filter = Gtk.FileFilter(); txt_filter.set_name("Plain Text (*.txt)"); txt_filter.add_pattern("*.txt")
        filters.append(txt_filter)
        
        md_filter = Gtk.FileFilter(); md_filter.set_name("Markdown (*.md)"); md_filter.add_pattern("*.md")
        filters.append(md_filter)
        
        srt_filter = Gtk.FileFilter(); srt_filter.set_name("SubRip Subtitle (*.srt)"); srt_filter.add_pattern("*.srt")
        filters.append(srt_filter)
        
        json_filter = Gtk.FileFilter(); json_filter.set_name("JSON Transcript (*.json)"); json_filter.add_pattern("*.json")
        filters.append(json_filter)
        
        dialog.set_filters(filters)

        # Pre-select last used filter
        if self.last_export_filter_name:
            for i in range(filters.get_n_items()):
                f = filters.get_item(i)
                if f.get_name() == self.last_export_filter_name:
                    dialog.set_default_filter(f)
                    break
        else:
            dialog.set_default_filter(txt_filter) # Default to TXT if no previous

        # Default filename
        base_name = os.path.splitext(current_item.output_filename)[0] if current_item.output_filename else "transcript"
        # Initial extension will be set by the dialog based on the selected filter if possible,
        # but Gtk.FileDialog does not directly use the filter for the initial name's extension.
        # We'll adjust it in the callback. For now, just set a base name.
        dialog.set_initial_name(base_name) # e.g., "YYYYMMDD_HHMMSS_new" or "transcript_export"

        print("Showing file export dialog...")
        dialog.save(self, None, self._on_export_dialog_finish, current_item)


    def _on_export_dialog_finish(self, dialog, result, transcript_item: TranscriptItem):
        """Callback executed after the user selects a file in the export dialog."""
        try:
            gfile: Optional[Gio.File] = dialog.save_finish(result)
            if gfile:
                target_path = gfile.get_path()
                if not target_path:
                    ToastPresenter.show(self, "❌ Invalid export path selected.")
                    return

                selected_filter = dialog.get_filter()
                if selected_filter:
                    self.last_export_filter_name = selected_filter.get_name()
                
                # Determine export format based on filename extension or selected filter
                # Gtk.FileDialog doesn't always enforce the extension from the filter on the Gio.File,
                # so checking the path is more reliable.
                file_ext = os.path.splitext(target_path)[1].lower()
                
                export_format = None
                if file_ext == ".txt":
                    export_format = "txt"
                elif file_ext == ".md":
                    export_format = "md"
                elif file_ext == ".srt":
                    export_format = "srt"
                elif file_ext == ".json":
                    export_format = "json"
                else:
                    # Fallback if extension is missing or unknown, try to infer from filter name
                    if self.last_export_filter_name:
                        if "Plain Text" in self.last_export_filter_name: export_format = "txt"; target_path += ".txt"
                        elif "Markdown" in self.last_export_filter_name: export_format = "md"; target_path += ".md"
                        elif "SubRip" in self.last_export_filter_name: export_format = "srt"; target_path += ".srt"
                        elif "JSON" in self.last_export_filter_name: export_format = "json"; target_path += ".json"
                
                if not export_format:
                    ToastPresenter.show(self, "❌ Unknown export format. Please select a filter or use a known extension.")
                    return

                print(f"Attempting to export transcript to: {target_path} as {export_format}")

                app = self.get_application()
                if not app or not hasattr(app, 'io_pool') or not app.io_pool:
                    ToastPresenter.show(self, "❌ Export failed: Thread pool error.")
                    return

                def export_io_operation():
                    try:
                        content_to_write: Any = ""
                        is_binary_write = False

                        if export_format == "txt":
                            content_to_write = export_utils.export_to_txt(transcript_item)
                        elif export_format == "md":
                            content_to_write = export_utils.export_to_md(transcript_item)
                        elif export_format == "srt":
                            content_to_write = export_utils.export_to_srt(transcript_item)
                        elif export_format == "json":
                            # Use the TranscriptItem's to_dict method for spec-compliant JSON
                            content_to_write = transcript_item.to_dict()
                            # atomic_write_json handles json.dump internally
                            atomic_write_json(content_to_write, target_path)
                            ToastPresenter.show(self, f"Exported ✓ {os.path.basename(target_path)}")
                            return # atomic_write_json handles writing

                        # For text-based formats
                        with open(target_path, "w", encoding='utf-8') as f:
                            f.write(content_to_write)
                        
                        ToastPresenter.show(self, f"Exported ✓ {os.path.basename(target_path)}")

                    except Exception as e_io:
                        print(f"Error during export I/O to {target_path}: {e_io}")
                        ToastPresenter.show(self, f"❌ Export failed: {e_io}")
                
                app.io_pool.submit(export_io_operation)

            else: # User cancelled
                print("Export operation cancelled by user.")
                # No toast for cancellation typically
        except GLib.Error as e:
            if e.matches(Gio.io_error_quark(), Gio.IOErrorEnum.CANCELLED):
                print("Export operation cancelled by user (GLib.Error).")
            else:
                print(f"GLib error during export dialog: {e}")
                ToastPresenter.show(self, f"❌ Export error: {e.code.value_nick}")
        except Exception as e_main:
            print(f"Unexpected error during export dialog callback: {e_main}")
            ToastPresenter.show(self, f"❌ Unexpected export error.")


    def _load_transcript_from_history(self, transcript_item: TranscriptItem):
        """
        Loads a TranscriptItem (selected from history) into the transcript view.
        Uses TranscriptView.load_transcript() directly.
        """
        if not transcript_item:
            print("Error: _load_transcript_from_history (double-click handler) called with None item.")
            if hasattr(self, 'reader_button'):
                self.reader_button.set_sensitive(False)
            self._selected_history_transcript = None
            return
        
        print(f"GnomeRecastWindow: _load_transcript_from_history called for item: {transcript_item.uuid if transcript_item else 'None'}")

        self._selected_history_transcript = transcript_item # Keep track of selected item for Reader button etc.
        if hasattr(self, 'reader_button'):
            self.reader_button.set_sensitive(bool(transcript_item.segments)) # Enable reader if segments exist
            print(f"Reader button sensitivity set for item {transcript_item.uuid}")

        if not hasattr(self, 'transcript_view') or not self.transcript_view:
            print("Error: TranscriptView not available to load history.")
            return

        print(f"GnomeRecastWindow: Queuing transcript_view.load_transcript for history item {transcript_item.uuid}")
        # The load_transcript method in TranscriptView now handles resetting and adding segments.
        GLib.idle_add(self.transcript_view.load_transcript, transcript_item)
        # Ensure _set_active_view is also called via idle_add to run on the main thread after load_transcript might have started
        GLib.idle_add(self._set_active_view, "transcript")
        print(f"GnomeRecastWindow: _load_transcript_from_history completed for {transcript_item.uuid}")

    def _on_open_file_activate(self, action, param):
        """Handles activation of the 'open-file' action (e.g., Ctrl+O or menu)."""
        print("Open File action activated.")
        dialog = Gtk.FileDialog.new()
        dialog.set_title("Open Transcript or Media File")
        # dialog.set_accept_label("Open") # Already default

        # Create filters
        json_filter = Gtk.FileFilter()
        json_filter.set_name("Transcript Files (*.json)")
        json_filter.add_mime_type("application/json")
        json_filter.add_pattern("*.json")

        # Common audio formats (extend as needed)
        audio_video_filter = Gtk.FileFilter()
        audio_video_filter.set_name("Audio/Video Files")
        # General types
        audio_video_filter.add_mime_type("audio/*")
        audio_video_filter.add_mime_type("video/*")
        # Specific common patterns (examples)
        audio_video_filter.add_pattern("*.mp3")
        audio_video_filter.add_pattern("*.wav")
        audio_video_filter.add_pattern("*.ogg")
        audio_video_filter.add_pattern("*.flac")
        audio_video_filter.add_pattern("*.mp4")
        audio_video_filter.add_pattern("*.mkv")
        audio_video_filter.add_pattern("*.mov")
        audio_video_filter.add_pattern("*.webm")


        all_supported_filter = Gtk.FileFilter()
        all_supported_filter.set_name("All Supported Files")
        all_supported_filter.add_filter(json_filter)
        all_supported_filter.add_filter(audio_video_filter)


        filters = Gio.ListStore.new(Gtk.FileFilter)
        filters.append(all_supported_filter) # Add combined filter first
        filters.append(json_filter)
        filters.append(audio_video_filter)
        
        dialog.set_filters(filters)
        dialog.set_default_filter(all_supported_filter) # Default to showing all supported

        # Set initial folder (optional, e.g., user's documents or last used)
        # For now, let it default or use a standard location like home or documents
        # default_folder = Gio.File.new_for_path(os.path.expanduser("~"))
        # dialog.set_initial_folder(default_folder)

        dialog.open(self, None, self._on_open_file_dialog_finish)

    def _on_open_file_dialog_finish(self, dialog, result):
        """Callback for Gtk.FileDialog.open()."""
        try:
            file: Optional[Gio.File] = dialog.open_finish(result)
            if file:
                file_path = file.get_path()
                if not file_path or not os.path.isfile(file_path):
                    ToastPresenter.show(self, f"❌ Invalid file selected.")
                    print(f"Open dialog: Invalid file path received: {file_path}")
                    return

                print(f"File selected for opening: {file_path}")
                
                # Check file extension to decide action
                if file_path.lower().endswith(".json"):
                    print(f"Attempting to import JSON transcript: {file_path}")
                    # This will call the import pipeline defined in Phase 4
                    self._import_transcript_file(file_path) # This method needs to be created
                else:
                    # Assume it's an audio/video file for transcription
                    print(f"Attempting to transcribe media file: {file_path}")
                    self.transcript_view.reset_view() # Reset view before starting new transcription
                    self._set_active_view("transcript")
                    # The _start_transcription_process method handles its own threading for transcription
                    self._start_transcription_process([file_path], cleanup_paths=[]) # No cleanup for user-opened files
            else:
                print("Open file operation cancelled by user.")
                # No toast needed for cancellation usually
        except GLib.Error as e:
            if e.matches(Gio.io_error_quark(), Gio.IOErrorEnum.CANCELLED):
                print("Open file operation cancelled by user (GLib.Error).")
            else:
                print(f"GLib error during file open dialog: {e}")
                ToastPresenter.show(self, f"❌ Error opening file: {e.code.value_nick}")
        except Exception as e:
            print(f"Unexpected error during file open dialog callback: {e}")
            ToastPresenter.show(self, f"❌ Unexpected error opening file.")


    def _import_transcript_file(self, json_file_path: str):
        """
        Handles the import of an external JSON transcript file.
        This implements Phase 4 of the plan.
        """
        app = self.get_application()
        if not app or not hasattr(app, 'io_pool') or not app.io_pool:
            ToastPresenter.show(self, "❌ Import failed: Thread pool error.")
            return

        def import_operation():
            try:
                # 1. Validation (using TranscriptItem.load_from_json which now does strict validation)
                print(f"Import operation: Validating {json_file_path}")
                loaded_item = TranscriptItem.load_from_json(json_file_path)
                
                transcripts_dir = os.path.join(GLib.get_user_data_dir(), 'GnomeRecast', 'transcripts')
                os.makedirs(transcripts_dir, exist_ok=True)
                
                original_basename = os.path.splitext(os.path.basename(json_file_path))[0]
                new_timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
                
                uuid_collision = False
                colliding_file_path = None
                # Basic UUID collision check (can be improved for performance on many files)
                for entry in os.scandir(transcripts_dir):
                    if entry.is_file() and entry.name.lower().endswith(".json"):
                        try:
                            temp_existing_item = TranscriptItem.load_from_json(os.path.join(transcripts_dir, entry.name))
                            if temp_existing_item.uuid == loaded_item.uuid:
                                uuid_collision = True
                                colliding_file_path = os.path.join(transcripts_dir, entry.name)
                                break
                        except Exception: # Ignore errors in existing files for this check
                            continue
                
                action_taken = "copy" # Default action
                if uuid_collision:
                    # Simplified: default to "keep_both" to avoid complex synchronous dialog from worker thread
                    print(f"UUID {loaded_item.uuid} collision with {colliding_file_path}. Defaulting to 'Keep Both'.")
                    action_taken = "keep_both"

                data_to_write = loaded_item.to_dict()

                if action_taken == "keep_both":
                    data_to_write['uuid'] = str(uuid.uuid4())
                    data_to_write['timestamp'] = new_timestamp_str
                    target_filename = f"{new_timestamp_str}_{original_basename}.json"
                    data_to_write['output_filename'] = target_filename
                elif action_taken == "replace" and colliding_file_path: # This case is less likely with current simplified logic
                    target_filename = os.path.basename(colliding_file_path)
                    data_to_write['output_filename'] = target_filename
                else: # Default "copy" behavior
                    target_filename = f"{new_timestamp_str}_{original_basename}.json"
                    # If not a collision, or if collision but we're not replacing,
                    # we might still want to update timestamp if it's a "copy new"
                    # For simplicity now, if it's a plain copy (no collision), use original item's timestamp for filename
                    # if not uuid_collision:
                    #    target_filename = f"{loaded_item.timestamp}_{original_basename}.json" # Needs YYYYMMDD_HHMMSS
                    # else (it's a non-colliding copy, or "copy" was chosen for some other reason)
                    data_to_write['timestamp'] = new_timestamp_str # Ensure new timestamp for new file name
                    data_to_write['output_filename'] = target_filename


                target_path = os.path.join(transcripts_dir, target_filename)
                atomic_write_json(data_to_write, target_path)
                
                ToastPresenter.show(self, f"Imported ✓ {os.path.basename(target_path)}")
                GLib.idle_add(self.history_view.refresh_list)
                
                final_item_to_load = TranscriptItem.load_from_json(target_path)
                GLib.idle_add(self.transcript_view.load_transcript, final_item_to_load)
                GLib.idle_add(self._set_active_view, "transcript")

            except Exception as e: # Catch-all for the import operation
                if isinstance(e, ValueError):
                    print(f"Import failed: Validation error - {e}")
                    GLib.idle_add(self._show_modal_message, "Invalid Transcript File", f"The file '{os.path.basename(json_file_path)}' is not a valid transcript file or is malformed.\n\nDetails: {e}")
                elif isinstance(e, FileNotFoundError):
                    print(f"Import failed: File not found - {e}")
                    GLib.idle_add(self._show_modal_message, "Import Error", f"File not found: {json_file_path}")
                elif isinstance(e, json.JSONDecodeError):
                    print(f"Import failed: JSON decode error - {e}")
                    GLib.idle_add(self._show_modal_message, "Import Error", f"Could not decode JSON from: {os.path.basename(json_file_path)}")
                else:
                    print(f"Import failed: Unexpected error - {e}", exc_info=True)
                    GLib.idle_add(self._show_modal_message, "Import Error", f"An unexpected error occurred while importing '{os.path.basename(json_file_path)}'.\nDetails: {str(e)[:100]}")
        # End of import_operation function definition

        # This call should be part of _import_transcript_file, after import_operation is defined.
        # Corrected indentation to 8 spaces (relative to class indent of 4).
        app.io_pool.submit(import_operation)

    def _show_modal_message(self, title: str, message: str, secondary_text: Optional[str] = None, msg_type: Gtk.MessageType = Gtk.MessageType.ERROR):
        """Displays a modal Gtk.MessageDialog."""
        dialog = Gtk.MessageDialog(
            transient_for=self,
            modal=True,
            message_type=msg_type,
            buttons=Gtk.ButtonsType.CLOSE,
            text=title,
        )
        if secondary_text:
            dialog.props.secondary_text = secondary_text
        dialog.connect("response", lambda d, r: d.destroy())
        dialog.present()


    def _on_save_transcript(self, action, param):
        """Handles the 'activate' signal for the 'save-transcript' action."""
        print("Save Transcript action activated (Ctrl+S).")
        # Check if transcript_view is active and has content
        if not (self.leaflet.get_visible_child_name() == "transcript" and
                hasattr(self.transcript_view, 'has_content') and
                self.transcript_view.has_content()):
            ToastPresenter.show(self, "Nothing to save.")
            print("Save action: No active transcript content to save.")
            return

        current_transcript_data = self.transcript_view.get_transcript_data_for_saving()
        if not current_transcript_data:
            ToastPresenter.show(self, "Could not retrieve transcript data to save.")
            return

        # If the current transcript came from history (_selected_history_transcript is set AND its source_path exists)
        # and it's currently loaded in the view (e.g. check if transcript_view's current item matches)
        # This logic needs to be robust: how do we know if transcript_view is displaying _selected_history_transcript?
        # For now, let's assume if _selected_history_transcript exists and its source_path is valid, we try to overwrite.
        # A more robust way would be for transcript_view to hold the TranscriptItem it's displaying.
        
        # Simplification: if self.transcript_view.current_item is not None and self.transcript_view.current_item.source_path:
        # This assumes transcript_view has a 'current_item' property that holds the loaded TranscriptItem.
        # This needs to be implemented in TranscriptView.load_transcript().
        
        target_item_for_save = self.transcript_view.get_current_item() # Needs implementation in TranscriptView

        if target_item_for_save and target_item_for_save.source_path and os.path.exists(target_item_for_save.source_path):
            # Overwrite existing file
            print(f"Attempting to overwrite existing transcript: {target_item_for_save.source_path}")
            try:
                # Update the target_item_for_save with data from current_transcript_data if necessary,
                # then call target_item_for_save.save() or directly use atomic_write_json.
                # For now, let's re-create the dict to ensure it's current.
                # This assumes current_transcript_data is a full dict matching TranscriptItem.to_dict()
                # This part needs careful handling of what current_transcript_data provides.
                # Ideally, we get a full TranscriptItem-like dict from the view.
                
                # Let's assume current_transcript_data is a dict ready for atomic_write_json
                # and contains all necessary fields (uuid, timestamp, segments, etc.)
                # If it's a new transcript that was loaded from an old one, it should retain original UUID and timestamp unless explicitly changed.
                
                # The TranscriptItem.save() method is better here if the view holds a full TranscriptItem.
                # For now, directly using atomic_write_json with data from view.
                
                # Construct the full dictionary to save, ensuring all fields from spec §1.1 are present.
                # This might involve merging view data with existing item data if it's an overwrite.
                
                # Simplest path for now: assume current_transcript_data IS the complete data to save.
                # This requires transcript_view.get_transcript_data_for_saving() to be comprehensive.
                
                # Get the application's I/O pool
                app = self.get_application()
                if not app or not hasattr(app, 'io_pool') or not app.io_pool:
                    print("Error: I/O thread pool not available on application object.")
                    ToastPresenter.show(self, "❌ Save failed: Thread pool error.")
                    return

                def save_operation():
                    try:
                        # Ensure all required fields are in current_transcript_data
                        # This is crucial for meeting the spec.
                        # Example: ensure 'language', 'source_path' (media), 'audio_source_path' (media) are there.
                        # If current_transcript_data doesn't have them, fetch from target_item_for_save.
                        data_to_save = {
                            "uuid": target_item_for_save.uuid,
                            "timestamp": datetime.strptime(target_item_for_save.timestamp, "%Y-%m-%d %H:%M:%S").strftime("%Y%m%d_%H%M%S"), # Convert to JSON format
                            "text": current_transcript_data.get("text", target_item_for_save.transcript_text),
                            "segments": current_transcript_data.get("segments", target_item_for_save.to_segment_dicts()),
                            "language": current_transcript_data.get("language", target_item_for_save.language),
                            "source_path": target_item_for_save.audio_source_path, # Media path
                            "audio_source_path": target_item_for_save.audio_source_path, # Media path
                            "output_filename": target_item_for_save.output_filename
                        }

                        atomic_write_json(data_to_save, target_item_for_save.source_path)
                        ToastPresenter.show(self, f"Saved ✓ {os.path.basename(target_item_for_save.source_path)}")
                        GLib.idle_add(self.history_view.refresh_list) # Refresh history as content changed
                    except Exception as e:
                        print(f"Error saving (overwrite) to {target_item_for_save.source_path}: {e}")
                        ToastPresenter.show(self, f"❌ Could not save {os.path.basename(target_item_for_save.source_path)}: {e}")

                app.io_pool.submit(save_operation)

            except Exception as e: # Catch errors before submitting to thread pool
                print(f"Error preparing to save (overwrite) {target_item_for_save.source_path}: {e}")
                ToastPresenter.show(self, f"❌ Save error: {e}")

        else:
            # New, unsaved session: Prompt with Gtk.FileDialog.save()
            print("New transcript session. Prompting for save location.")
            dialog = Gtk.FileDialog.new()
            dialog.set_title("Save Transcript As...")
            
            # Default directory and filename
            default_folder_path = os.path.join(GLib.get_user_data_dir(), 'GnomeRecast', 'transcripts')
            os.makedirs(default_folder_path, exist_ok=True)
            default_folder = Gio.File.new_for_path(default_folder_path)
            dialog.set_initial_folder(default_folder)
            
            default_filename = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_new.json"
            dialog.set_initial_name(default_filename)

            # File filter for JSON
            json_filter = Gtk.FileFilter()
            json_filter.set_name("JSON Transcript Files (*.json)")
            json_filter.add_mime_type("application/json")
            json_filter.add_pattern("*.json")
            
            filters = Gio.ListStore.new(Gtk.FileFilter)
            filters.append(json_filter)
            dialog.set_filters(filters)
            dialog.set_default_filter(json_filter)

            dialog.save(self, None, self._on_new_transcript_file_selected_for_save, current_transcript_data)

    def _on_new_transcript_file_selected_for_save(self, dialog, result, transcript_data_to_save):
        """Callback for Gtk.FileDialog.save() for new transcripts."""
        try:
            file = dialog.save_finish(result)
            if file:
                target_path = file.get_path()
                print(f"New transcript save path selected: {target_path}")

                # Ensure the data to save has all required fields from spec §1.1
                # This is a new save, so some fields need to be generated.
                final_data_to_save = {
                    "uuid": str(uuid.uuid4()), # New UUID
                    "timestamp": datetime.now().strftime("%Y%m%d_%H%M%S"), # New timestamp
                    "text": transcript_data_to_save.get("text", ""),
                    "segments": transcript_data_to_save.get("segments", []),
                    "language": transcript_data_to_save.get("language", self.settings.get_string("target-language") if not self.settings.get_boolean("auto-detect-language") else "en"), # Best guess for language
                    "source_path": "",  # No original media source for a brand new, unsaved transcript unless explicitly set
                    "audio_source_path": "", # ditto
                    "output_filename": os.path.basename(target_path)
                }
                
                app = self.get_application()
                if not app or not hasattr(app, 'io_pool') or not app.io_pool:
                    print("Error: I/O thread pool not available on application object.")
                    ToastPresenter.show(self, "❌ Save failed: Thread pool error.")
                    return

                def save_operation():
                    try:
                        atomic_write_json(final_data_to_save, target_path)
                        ToastPresenter.show(self, f"Saved ✓ {os.path.basename(target_path)}")
                        GLib.idle_add(self.history_view.refresh_list)
                        # After a successful new save, update the transcript_view's current item
                        # This requires TranscriptItem to be created and loaded back or updated in view
                        # For now, this part is deferred until TranscriptView has better state management.
                        # Ideally:
                        # new_item = TranscriptItem.load_from_json(target_path)
                        # if new_item:
                        # GLib.idle_add(self.transcript_view.set_current_item, new_item) # Method to be created
                    except Exception as e:
                        print(f"Error saving new transcript to {target_path}: {e}")
                        ToastPresenter.show(self, f"❌ Could not save {os.path.basename(target_path)}: {e}")
                
                app.io_pool.submit(save_operation)

            else:
                print("Save operation cancelled by user.")
                ToastPresenter.show(self, "Save cancelled.")
        except GLib.Error as e:
            if e.matches(Gio.io_error_quark(), Gio.IOErrorEnum.CANCELLED):
                 print("File save operation cancelled by user (GLib.Error).")
                 ToastPresenter.show(self, "Save cancelled.")
            else:
                 print(f"GLib error during file save dialog: {e}")
                 ToastPresenter.show(self, f"❌ Save error: {e}")
        except Exception as e:
            print(f"Unexpected error during file save dialog callback: {e}")
            ToastPresenter.show(self, f"❌ Unexpected save error: {e}")


    def _on_reader_button_clicked(self, button):
        """Handles the click event for the Reader button."""
        print("Reader button clicked.")
        if not self._selected_history_transcript:
            print("Error: Reader button clicked but no history item selected.")
            return

        full_text_parts = []
        if self._selected_history_transcript.segments:
            for segment in self._selected_history_transcript.segments:
                    # isinstance check removed as TranscriptItem.load_from_json ensures SegmentItem instances
                    start_m, start_s = divmod(int(segment.start), 60)
                    end_m, end_s = divmod(int(segment.end), 60)
                    timestamp = f"[{start_m:02d}:{start_s:02d} → {end_m:02d}:{end_s:02d}]"
                    full_text_parts.append(f"{timestamp}\n{segment.text}\n")
        full_text = "".join(full_text_parts)

        if not full_text:
            print("Warning: Selected history item generated no text for Reader mode.")
            return

        cleaned_text = re.sub(r"^\[\d{2}:\d{2}\s*→\s*\d{2}:\d{2}\]\n?", "", full_text, flags=re.MULTILINE)
        cleaned_text = cleaned_text.strip()

        reader_window = Adw.ApplicationWindow(application=self.get_application())
        reader_window.set_title("Reader Mode - Transcript")
        reader_window.set_resizable(True)
        reader_window.set_default_size(400, 600)
        reader_window.set_modal(True)
        reader_window.add_css_class("reader-popup-window")

        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        main_box.set_margin_top(6)
        main_box.set_margin_end(6)
        main_box.set_margin_start(6)
        main_box.set_margin_bottom(6)

        top_bar_overlay = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        top_bar_overlay.add_css_class("topbar")
        top_bar_overlay.set_valign(Gtk.Align.START)
        top_bar_overlay.set_halign(Gtk.Align.END)
        top_bar_overlay.set_margin_top(12)
        top_bar_overlay.set_margin_end(12)

        close_button = Gtk.Button(label="✕")
        close_button.connect("clicked", lambda btn: reader_window.close())
        top_bar_overlay.append(close_button)

        buffer = Gtk.TextBuffer()
        buffer.set_text(cleaned_text)

        text_view = Gtk.TextView(buffer=buffer)
        text_view.add_css_class("reader-text-view")
        text_view.set_editable(False)
        text_view.set_wrap_mode(Gtk.WrapMode.WORD)

        scroller = Gtk.ScrolledWindow()
        scroller.add_css_class("reader-scrolled-window")
        scroller.set_child(text_view)
        scroller.set_vexpand(True)
        scroller.set_hexpand(True)

        overlay = Gtk.Overlay()
        overlay.set_child(scroller)
        overlay.add_overlay(top_bar_overlay)

        reader_window.set_content(overlay)
        reader_window.present()

        print("Reader mode window displayed.")





================================================
File: gnomerecast/audio/__init__.py
================================================
# This file makes the audio directory a Python package.


================================================
File: gnomerecast/audio/capture.py
================================================
import gi
gi.require_version('Gst', '1.0')
gi.require_version('GObject', '2.0')
gi.require_version('Gio', '2.0') # For Gio.Settings

from gi.repository import Gst, GLib, GObject, Gio
from typing import Optional, Callable

# Import new utilities
from ..audio.device_utils import get_input_devices, AudioInputDevice
from ..audio.wp_default_tracker import DefaultSourceTracker


class AudioCapturer(GObject.Object):
    """
    Captures audio using GStreamer, provides raw audio data via a callback or signal,
    and supports dynamic device selection and default device tracking.
    """
    __gsignals__ = {
        'source-changed': (GObject.SignalFlags.RUN_FIRST, None, (str,)), # Emits new source description
        'error': (GObject.SignalFlags.RUN_FIRST, None, (str,)), # Emits error message
        # PyGObject ≥ 3.50 no longer maps the builtin `bytes` type;
        # use the generic Python‑object GType instead.
        'data-ready': (GObject.SignalFlags.RUN_FIRST, None, (object,)),
    }

    def __init__(self, settings: Gio.Settings, data_callback: Optional[Callable[[bytes], None]] = None):
        super().__init__()
        Gst.init_check(None)

        self._settings = settings
        self._data_callback = data_callback

        self.pipeline: Optional[Gst.Pipeline] = None
        self.appsink: Optional[Gst.Element] = None
        
        self._current_gst_id: Optional[str] = None # Actual ID used by the current pipeline source
        self._current_pw_serial: Optional[int] = None # PW serial if applicable to current source
        self._is_following_system_default: bool = False # Reflects if tracker is active and being followed
        self._tracker_instance: Optional[DefaultSourceTracker] = None
        self._tracker_signal_handler_id: int = 0
        
        # Read initial settings
        self._target_device_id: Optional[str] = self._settings.get_string("mic-input-device-id")
        self._follow_system_default_setting: bool = self._settings.get_boolean("follow-system-default")

        # Connect to GSettings changes
        self._settings_changed_handler_id_id = self._settings.connect(f"changed::mic-input-device-id", self._on_settings_changed)
        self._settings_changed_handler_follow = self._settings.connect(f"changed::follow-system-default", self._on_settings_changed)
        
        # Initial pipeline setup and tracker management, scheduled on main loop
        GLib.idle_add(self._update_tracker_and_pipeline_from_settings)


    def _on_settings_changed(self, settings, key):
        print(f"AudioCapturer: Setting '{key}' changed in GSettings. Re-evaluating pipeline and tracker.")
        self._target_device_id = self._settings.get_string("mic-input-device-id")
        self._follow_system_default_setting = self._settings.get_boolean("follow-system-default")
        GLib.idle_add(self._update_tracker_and_pipeline_from_settings)

    def _manage_tracker_subscription(self):
        """Connects or disconnects from DefaultSourceTracker based on settings."""
        if self._follow_system_default_setting:
            if not self._tracker_instance:
                self._tracker_instance = DefaultSourceTracker.get_instance()
                if self._tracker_instance._core and self._tracker_instance._core.is_connected(): # Check if tracker initialized correctly
                    print("AudioCapturer: Subscribing to DefaultSourceTracker.")
                    self._tracker_signal_handler_id = self._tracker_instance.connect(
                        "default-changed", self._on_tracker_default_changed
                    )
                    # Trigger an initial check/move with current tracker default
                    if self._tracker_instance._default_node_props.get("gst_id") is not None:
                         GLib.idle_add(self.move_to,
                                       self._tracker_instance._default_node_props["gst_id"],
                                       self._tracker_instance._default_node_props.get("pw_serial"))
                    else: # If tracker has no default yet, ensure pipeline reflects this state
                        GLib.idle_add(self._rebuild_pipeline_from_settings, True) # Pass True to indicate tracker context

                else:
                    print("AudioCapturer: DefaultSourceTracker instance obtained but not connected to WirePlumber. Cannot track defaults.")
                    self._tracker_instance = None # Don't hold a non-functional instance
            # else: already subscribed
        else: # Not following system default
            if self._tracker_instance and self._tracker_signal_handler_id > 0:
                print("AudioCapturer: Unsubscribing from DefaultSourceTracker.")
                self._tracker_instance.disconnect(self._tracker_signal_handler_id)
                self._tracker_signal_handler_id = 0
                # self._tracker_instance.stop() # Singleton should manage its own lifecycle or be stopped globally
                self._tracker_instance = None # Release our reference
            self._is_following_system_default = False # Ensure this flag is reset

    def _on_tracker_default_changed(self, tracker, gst_id: str, pw_serial: int):
        print(f"AudioCapturer: Received 'default-changed' from tracker. GST ID: {gst_id}, PW Serial: {pw_serial}")
        if self._follow_system_default_setting: # Double check setting before acting
            GLib.idle_add(self.move_to, gst_id, pw_serial)
        else:
            print("AudioCapturer: Ignored 'default-changed' as 'follow-system-default' GSetting is false.")


    def _cleanup_pipeline_sync(self):
        """Synchronously stops and nulls the pipeline. Call from main thread."""
        if self.pipeline:
            print("AudioCapturer: Cleaning up existing pipeline...")
            self.pipeline.set_state(Gst.State.NULL)
            self.pipeline = None
            self.appsink = None
            print("AudioCapturer: Pipeline cleaned up.")

    def _build_pipeline(self, target_gst_id_from_setting: Optional[str], 
                        follow_default_from_setting: bool, 
                        tracker_gst_id: Optional[str] = None, 
                        tracker_pw_serial: Optional[int] = None) -> bool:
        """
        Builds the GStreamer pipeline. Must be called on the main GLib thread.
        Uses tracker_gst_id if follow_default_from_setting is true and tracker_gst_id is valid.
        Otherwise, uses target_gst_id_from_setting.
        """
        self._cleanup_pipeline_sync() # Ensure any old pipeline is gone

        source_element_name: Optional[str] = None
        source_properties = {}
        effective_gst_id_used: Optional[str] = None # For logging/status

        # Determine the source element and its properties
        if follow_default_from_setting:
            self._is_following_system_default = True # Mark that we are in this mode
            if tracker_gst_id and tracker_gst_id != "error": # Prioritize tracker's info
                print(f"AudioCapturer: Following system default via tracker. GST ID: {tracker_gst_id}, PW Serial: {tracker_pw_serial}")
                source_element_name = "pipewiresrc" # Assume tracker provides PipeWire compatible ID
                source_properties["path"] = tracker_gst_id
                # If pipewiresrc needs serial: source_properties["serial"] = tracker_pw_serial (or similar)
                effective_gst_id_used = tracker_gst_id
                self._current_gst_id = tracker_gst_id # Store what tracker gave us
                self._current_pw_serial = tracker_pw_serial
            elif target_gst_id_from_setting == "pipewire-default": # User chose "Default PipeWire Source"
                 source_element_name = "pipewiresrc"
                 effective_gst_id_used = "pipewire-default (selected)"
                 print(f"AudioCapturer: Following system default, selected 'Default PipeWire Source'. Using pipewiresrc.")
                 self._current_gst_id = "pipewire-default"
            else: # General system default, use autoaudiosrc
                source_element_name = "autoaudiosrc"
                effective_gst_id_used = "autoaudiosrc (system default)"
                print(f"AudioCapturer: Following system default. Using autoaudiosrc.")
                self._current_gst_id = "" # Represents auto
        elif target_gst_id_from_setting: # Specific device selected, not following default
            self._is_following_system_default = False
            effective_gst_id_used = target_gst_id_from_setting
            print(f"AudioCapturer: Using specific device ID: {target_gst_id_from_setting}")
            
            # Find device details from device_utils
            # Caching this list could be an optimization if it's slow
            available_devices = get_input_devices() 
            selected_audio_device: Optional[AudioInputDevice] = None
            for dev in available_devices:
                if dev.id == target_gst_id_from_setting:
                    selected_audio_device = dev
                    break
            
            if selected_audio_device and selected_audio_device.gst_plugin_name:
                source_element_name = selected_audio_device.gst_plugin_name
                if source_element_name == "pipewiresrc":
                    source_properties["path"] = selected_audio_device.id
                elif source_element_name == "pulsesrc":
                    source_properties["device"] = selected_audio_device.id
                elif source_element_name == "alsasrc": # Basic ALSA handling
                    source_properties["device"] = selected_audio_device.id 
                print(f"AudioCapturer: Found device '{selected_audio_device.name}', using plugin '{source_element_name}' with ID '{selected_audio_device.id}'")
            else:
                print(f"AudioCapturer: Device ID '{target_gst_id_from_setting}' not found or no plugin info. Falling back to autoaudiosrc.")
                source_element_name = "autoaudiosrc"
                effective_gst_id_used = f"{target_gst_id_from_setting} (not found, using autoaudiosrc)"
            self._current_gst_id = target_gst_id_from_setting # Store the user's selection
        else: # No specific device, not following default (e.g. initial empty settings)
            self._is_following_system_default = False
            source_element_name = "autoaudiosrc"
            effective_gst_id_used = "autoaudiosrc (no selection)"
            print("AudioCapturer: No specific device and not following default. Using autoaudiosrc.")
            self._current_gst_id = ""

        if not source_element_name:
            self.emit("error", "Fatal: Could not determine audio source element name.")
            return False

        print(f"AudioCapturer: Attempting to build with source: {source_element_name}, props: {source_properties}")

        try:
            self.pipeline = Gst.Pipeline.new("capture-pipeline")
            source = Gst.ElementFactory.make(source_element_name, "audio-source")
            if not source:
                self.emit("error", f"Failed to create source element: {source_element_name}")
                return False
            for key, value in source_properties.items():
                source.set_property(key, value)

            queue = Gst.ElementFactory.make("queue", "audio-queue")
            audioconvert = Gst.ElementFactory.make("audioconvert", "audio-convert")
            audioresample = Gst.ElementFactory.make("audioresample", "audio-resample")
            capsfilter = Gst.ElementFactory.make("capsfilter", "audio-caps")
            self.appsink = Gst.ElementFactory.make("appsink", "audio-sink")

            if not all([self.pipeline, source, queue, audioconvert, audioresample, capsfilter, self.appsink]):
                self.emit("error", "Failed to create one or more GStreamer elements.")
                return False

            caps = Gst.Caps.from_string("audio/x-raw,format=S16LE,rate=16000,channels=1")
            capsfilter.set_property("caps", caps)
            self.appsink.set_property("emit-signals", True)
            self.appsink.set_property("max-buffers", 2) # Slightly larger queue for appsink
            self.appsink.set_property("drop", True)
            self.appsink.connect("new-sample", self._on_new_sample)

            self.pipeline.add_many(source, queue, audioconvert, audioresample, capsfilter, self.appsink)
            if not Gst.Element.link_many(source, queue, audioconvert, audioresample, capsfilter, self.appsink):
                self.emit("error", "Failed to link GStreamer elements.")
                self._cleanup_pipeline_sync()
                return False
            
            print(f"AudioCapturer: Pipeline built successfully with {source_element_name} (Effective ID: {effective_gst_id_used}).")
            self.emit("source-changed", f"Using: {source_element_name} (ID: {effective_gst_id_used or 'default'})")
            return True

        except Exception as e:
            self.emit("error", f"Exception during pipeline construction: {e}")
            self._cleanup_pipeline_sync()
            return False
        
    def _rebuild_pipeline_from_settings(self, is_tracker_context: bool = False) -> bool:
        """
        Helper to rebuild pipeline based on current GSettings.
        is_tracker_context indicates if the rebuild is due to "follow default" mode,
        affecting which ID (user-selected or tracker-provided) is prioritized.
        """
        print(f"AudioCapturer: Rebuilding pipeline. Target ID from GSetting: '{self._target_device_id}', Follow Default GSetting: {self._follow_system_default_setting}, IsTrackerContext: {is_tracker_context}")
        
        is_playing = False
        if self.pipeline and self.pipeline.get_state(0)[1] == Gst.State.PLAYING:
            is_playing = True
        
        # Determine which IDs to use based on context
        id_from_gsettings = self._target_device_id
        follow_gsetting = self._follow_system_default_setting
        
        tracker_id_to_use = None
        tracker_serial_to_use = None

        if is_tracker_context and self._tracker_instance and self._tracker_instance._default_node_props:
            # If in tracker context, use the tracker's current known default if available.
            # This means self._current_gst_id and self._current_pw_serial should reflect tracker state.
            tracker_id_to_use = self._current_gst_id
            tracker_serial_to_use = self._current_pw_serial
            print(f"AudioCapturer: Rebuild in tracker context. Using tracker ID: {tracker_id_to_use}, Serial: {tracker_serial_to_use}")
        
        # _build_pipeline decides based on follow_gsetting and availability of tracker_id_to_use
        if self._build_pipeline(target_gst_id_from_setting=id_from_gsettings,
                                follow_default_from_setting=follow_gsetting,
                                tracker_gst_id=tracker_id_to_use, # Pass current tracker info
                                tracker_pw_serial=tracker_serial_to_use):
            if is_playing:
                self.start()
        else:
            print("AudioCapturer: Failed to rebuild pipeline from settings.")
            # Error signal should have been emitted by _build_pipeline
            
        return GLib.SOURCE_REMOVE # For GLib.idle_add

    def _on_new_sample(self, appsink):
        sample = appsink.emit("pull-sample")
        if sample:
            buffer = sample.get_buffer()
            if buffer:
                success, map_info = buffer.map(Gst.MapFlags.READ)
                if success:
                    data = bytes(map_info.data)
                    if self._data_callback: self._data_callback(data)
                    self.emit("data-ready", data)
                    buffer.unmap(map_info)
                    return Gst.FlowReturn.OK
        return Gst.FlowReturn.ERROR

    def start(self):
        def _do_start():
            if self.pipeline:
                current_state = self.pipeline.get_state(0)[1]
                if current_state == Gst.State.PLAYING:
                    print("AudioCapturer: Pipeline already playing.")
                    return GLib.SOURCE_REMOVE
                if current_state == Gst.State.NULL or current_state == Gst.State.READY:
                    print("AudioCapturer: Starting pipeline...")
                    ret = self.pipeline.set_state(Gst.State.PLAYING)
                    if ret == Gst.StateChangeReturn.FAILURE:
                        self.emit("error", "Unable to set the pipeline to the playing state.")
                    # ASYNC and SUCCESS are fine.
                else: # PAUSED etc.
                     print(f"AudioCapturer: Pipeline in state {current_state}, attempting to set to PLAYING.")
                     self.pipeline.set_state(Gst.State.PLAYING) # Try anyway
            else:
                self.emit("error", "Cannot start, pipeline not built.")
            return GLib.SOURCE_REMOVE
        GLib.idle_add(_do_start)

    def stop(self):
        def _do_stop():
            if self.pipeline:
                print("AudioCapturer: Stopping pipeline...")
                self.pipeline.set_state(Gst.State.NULL)
                print("AudioCapturer: Pipeline stopped (set to NULL).")
            return GLib.SOURCE_REMOVE
        GLib.idle_add(_do_stop)

    def move_to(self, new_gst_id: str, new_pw_serial: Optional[int] = None):
        """
        Runtime reconfiguration, typically called by DefaultSourceTracker if following system default.
        """
        def _do_move():
            print(f"AudioCapturer: move_to called. New GST ID: {new_gst_id}, New PW Serial: {new_pw_serial}")
            if not self._follow_system_default_setting: # Check GSetting, not just internal state
                print("AudioCapturer: move_to ignored, GSetting 'follow-system-default' is false.")
                return GLib.SOURCE_REMOVE

            # Update current tracked identifiers
            self._current_gst_id = new_gst_id
            self._current_pw_serial = new_pw_serial
            self._is_following_system_default = True # Explicitly affirm we are acting on tracker info
            
            is_playing = False
            if self.pipeline and self.pipeline.get_state(0)[1] == Gst.State.PLAYING:
                is_playing = True
            
            # Rebuild pipeline with the new default device info from tracker
            if self._build_pipeline(target_gst_id_from_setting=self._target_device_id, # Keep user's choice as fallback
                                    follow_default_from_setting=True, # We are in follow mode
                                    tracker_gst_id=new_gst_id,
                                    tracker_pw_serial=new_pw_serial):
                if is_playing:
                    self.start()
            else:
                print(f"AudioCapturer: Failed to move to new source {new_gst_id}")
                self.emit("error", f"Failed to switch to new default source: {new_gst_id}")
            return GLib.SOURCE_REMOVE
            
        GLib.idle_add(_do_move)

    def set_data_callback(self, callback: Optional[Callable[[bytes], None]]):
        self._data_callback = callback

    def cleanup_on_destroy(self):
        """Call this when the capturer is no longer needed to release resources."""
        print("AudioCapturer: Cleaning up on destroy...")
        if self._settings: # Disconnect GSettings handlers
            if hasattr(self, '_settings_changed_handler_id_id') and self._settings_changed_handler_id_id > 0:
                self._settings.disconnect(self._settings_changed_handler_id_id)
                self._settings_changed_handler_id_id = 0
            if hasattr(self, '_settings_changed_handler_follow') and self._settings_changed_handler_follow > 0:
                self._settings.disconnect(self._settings_changed_handler_follow)
                self._settings_changed_handler_follow = 0
        self._settings = None # Release settings object reference

        # Disconnect from DefaultSourceTracker
        if self._tracker_instance and self._tracker_signal_handler_id > 0:
            print("AudioCapturer: Disconnecting from DefaultSourceTracker during cleanup.")
            self._tracker_instance.disconnect(self._tracker_signal_handler_id)
            self._tracker_signal_handler_id = 0
        # Decided not to call self._tracker_instance.stop() here as it's a singleton.
        # It should be stopped globally when the application exits if necessary.
        self._tracker_instance = None
        
        # Ensure pipeline is stopped and cleaned on the main thread
        # Use a list of idle_adds to ensure order if needed, or rely on separate calls
        if self.pipeline:
            # Schedule stop and then cleanup. These are already idle_add internally.
            self.stop()
            # _cleanup_pipeline_sync needs to be explicitly on idle_add if called from here
            GLib.idle_add(self._cleanup_pipeline_sync)
        
        print("AudioCapturer: Cleanup process initiated and mostly complete.")


================================================
File: gnomerecast/audio/device_utils.py
================================================
import gi
gi.require_version('Gst', '1.0')
gi.require_version('GObject', '2.0')
from gi.repository import Gst, GObject

from dataclasses import dataclass
from typing import List, Optional

@dataclass
class AudioInputDevice:
    id: Optional[str]  # GStreamer device.id or special "default"
    name: str          # User-friendly name
    api: str           # e.g., "pipewire", "pulse", "alsa"
    device_type: str   # "physical", "monitor", "default"
    pw_serial: Optional[int] = None # PipeWire serial, if applicable
    gst_plugin_name: Optional[str] = None # e.g. pipewiresrc, pulsesrc

    def __str__(self):
        return self.name

    def __eq__(self, other):
        if not isinstance(other, AudioInputDevice):
            return NotImplemented
        return self.id == other.id and self.api == other.api and self.device_type == other.device_type

    def __hash__(self):
        return hash((self.id, self.api, self.device_type))

def get_input_devices() -> List[AudioInputDevice]:
    """
    Lists available audio input devices (microphones and monitors).
    Includes a special "Default PipeWire Source" if PipeWire is likely available.
    """
    devices = []
    Gst.init_check(None)

    # Add a "System Default" option. This will be handled by GSettings `follow-system-default`
    devices.append(AudioInputDevice(
        id="", # Special ID for system default
        name="System Default",
        api="default",
        device_type="default",
        gst_plugin_name="autoaudiosrc" # Fallback, actual determined by settings
    ))

    monitor = Gst.DeviceMonitor.new()
    monitor.add_filter("Audio/Source", None) # GstCaps.new_empty_simple("audio/source"))
    
    # It seems PipeWire is becoming standard, so we can try to add a default PW source.
    # The actual default tracking will be done by WpDefaultTracker.
    # This entry is more for user selection if they prefer PW explicitly.
    # We don't have PW serial here, it's a generic "use default pipewire"
    devices.append(AudioInputDevice(
        id="pipewire-default", # A special identifier for this choice
        name="Default PipeWire Source",
        api="pipewire",
        device_type="default",
        gst_plugin_name="pipewiresrc"
    ))

    if not monitor.start():
        print("Failed to start device monitor")
        # Fallback: at least provide ALSA default if monitor fails
        devices.append(AudioInputDevice(id="alsa-default", name="Default ALSA Source (Fallback)", api="alsa", device_type="default", gst_plugin_name="alsasrc"))
        return devices

    gst_devices = monitor.get_devices()
    if gst_devices:
        for device in gst_devices:
            name = device.get_display_name()
            api = "unknown"
            device_id = device.get_properties().get_string("device.id")
            gst_plugin_name = None
            
            # Determine API and device type
            # This is a heuristic. A more robust way might involve checking device.classes
            # or specific properties if GstDevice provides them.
            # For now, we rely on names and common GStreamer elements.
            if "alsa" in name.lower() or (device_id and "alsa" in device_id.lower()):
                api = "alsa"
                gst_plugin_name = "alsasrc"
            elif "pulse" in name.lower() or (device_id and "pulse" in device_id.lower()):
                api = "pulse"
                gst_plugin_name = "pulsesrc"
            elif "pipewire" in name.lower() or (device_id and ("pipewire" in device_id.lower() or "pw" in device_id.lower())):
                api = "pipewire"
                gst_plugin_name = "pipewiresrc"
            
            # Try to get device.api if available from GstDevice properties
            device_api_prop = device.get_properties().get_string("device.api")
            if device_api_prop:
                api = device_api_prop
                if api == "pipewire":
                    gst_plugin_name = "pipewiresrc"
                elif api == "alsa":
                    gst_plugin_name = "alsasrc"
                elif api == "pulse":
                    gst_plugin_name = "pulsesrc"


            device_type = "physical"
            if "monitor" in name.lower():
                device_type = "monitor"

            # For PipeWire, try to get the serial if available (though GstDevice might not expose it directly)
            # This might be more relevant when a specific device is chosen, not during general listing.
            # The pw_serial will be more reliably obtained via WirePlumber for the *default* device.
            pw_serial = None
            if api == "pipewire":
                # GstDevice might have 'object.serial' or similar for PW, needs checking Gst docs/PW integration
                # For now, we assume Gst.Device.get_properties() gives us what GStreamer knows.
                # If 'device.id' for pipewiresrc is the node ID (integer), that's useful.
                # If it's a string path, that's also fine for 'path' property of pipewiresrc.
                # The 'id' here is the GStreamer device.id, which pipewiresrc can use for its 'path' property
                # if it's a string, or potentially 'node-id' if it's an int.
                # The `micrefactor.md` implies `gst_id` is the device.id from GstDevice.
                pass


            devices.append(AudioInputDevice(
                id=device_id, 
                name=name, 
                api=api, 
                device_type=device_type,
                pw_serial=pw_serial, # Likely None here, to be filled by tracker for default
                gst_plugin_name=gst_plugin_name
            ))
    
    monitor.stop()
    
    # Remove duplicates that might arise from different ways of identifying defaults
    # For example, if GstDeviceMonitor lists a "Default" that is also our "Default PipeWire Source"
    # A more robust deduplication might be needed based on actual IDs if they overlap.
    # Using a set of tuples for properties that define uniqueness
    unique_devices = []
    seen_ids = set()
    for dev in devices:
        # For "System Default" and "Default PipeWire Source", name is unique enough.
        # For others, use the GStreamer device ID.
        lookup_key = dev.name if dev.device_type == "default" else dev.id
        if lookup_key not in seen_ids:
            unique_devices.append(dev)
            seen_ids.add(lookup_key)
            
    return unique_devices

if __name__ == '__main__':
    # Example usage:
    Gst.init(None)
    available_devices = get_input_devices()
    print("Available Audio Input Devices:")
    for dev in available_devices:
        print(f"- Name: {dev.name}")
        print(f"  ID: {dev.id}")
        print(f"  API: {dev.api}")
        print(f"  Type: {dev.device_type}")
        print(f"  GStreamer Plugin: {dev.gst_plugin_name}")
        if dev.pw_serial is not None:
            print(f"  PipeWire Serial: {dev.pw_serial}")


================================================
File: gnomerecast/audio/wp_default_tracker.py
================================================
import gi
gi.require_version('GObject', '2.0')
gi.require_version('Wp', '0.5') # Or 0.4 depending on available version
from gi.repository import GObject, Wp, GLib

class DefaultSourceTracker(GObject.Object):
    """
    A GObject singleton that monitors the system's default audio input source
    using WirePlumber and emits a signal when it changes.
    """
    __gsignals__ = {
        'default-changed': (GObject.SignalFlags.RUN_FIRST, None, (str, int)),
        # gst_id: str, pw_serial: int
    }

    _instance = None
    _core = None
    _om = None
    _default_nodes_api = None # Technically, we monitor Wp.Metadata for default changes
    _default_node_props = {} # Stores properties of the current default node {gst_id, pw_serial}

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if hasattr(self, '_initialized') and self._initialized:
            return
        super().__init__()
        self._initialized = True
        
        try:
            Wp.init(Wp.InitFlags.ALL)
            # Use a new main context for WirePlumber core if running in a separate thread,
            # or None if integrating into an existing GLib.MainLoop on the main thread.
            # For a singleton GObject usually integrated with GTK, None (default context) is fine.
            self._core = Wp.Core.new(None, None) 
            
            if not self._core.connect():
                print("DefaultSourceTracker: Failed to connect to WirePlumber core")
                self._core = None 
                return

            self._om = Wp.ObjectManager.new()
            # We are interested in Wp.Metadata for default nodes.
            self._om.add_interest_full(Wp.Metadata, Wp.Constraint.new_full(
                Wp.PW_KEY_METADATA_NAME, "default", Wp.ConstraintVerb.EQUALS, # Default settings are stored in "default" metadata
            ))
            # Also need Wp.Node to resolve the default node name to its properties (like serial and path)
            self._om.add_interest_full(Wp.Node, Wp.Constraint.new_full(
                 Wp.PW_KEY_MEDIA_CLASS, "Audio/Source", Wp.ConstraintVerb.EQUALS, # Interested in Audio Sources
            ))
            
            self._om.connect("objects-changed", self._on_objects_changed_initial_setup)
            self._core.install_object_manager(self._om)
            print("DefaultSourceTracker: WirePlumber core connected and object manager installed.")

        except Exception as e:
            print(f"DefaultSourceTracker: Error initializing WirePlumber: {e}")
            if self._core and self._core.is_connected():
                self._core.disconnect()
            self._core = None

    def _on_objects_changed_initial_setup(self, om):
        # This callback is primarily for the initial setup of the metadata listener.
        # Once the "default" Wp.Metadata object is found, we connect to its "changed" signal.
        # print("DefaultSourceTracker: Objects changed (initial setup)")
        metadata = om.lookup_object(Wp.Constraint.new_full(
            Wp.PW_KEY_METADATA_NAME, "default", Wp.ConstraintVerb.EQUALS,
        ))
        if metadata and isinstance(metadata, Wp.Metadata):
            # print(f"DefaultSourceTracker: Found 'default' Wp.Metadata object: {metadata}")
            # Disconnect this handler as we only need to set up the listener once.
            om.disconnect_by_func(self._on_objects_changed_initial_setup)
            metadata.connect("changed", self._on_default_metadata_changed)
            # Perform an initial check for the default node
            GLib.idle_add(self._check_and_emit_default_node)


    def _on_default_metadata_changed(self, metadata, subject, key, value_type, value):
        # print(f"DefaultSourceTracker: Default metadata changed: subject={subject}, key={key}, value='{value}'")
        # We are interested in changes to the default audio source.
        # In WirePlumber, this is typically "default.audio.source" for ALSA node name,
        # or "default.bluez.source" for Bluetooth. The value is the node *name*.
        if key and ("default.audio.source" in key or "default.bluez.source" in key):
            # print(f"DefaultSourceTracker: Relevant metadata key '{key}' changed to '{value}'. Re-checking default node.")
            GLib.idle_add(self._check_and_emit_default_node)


    def _check_and_emit_default_node(self):
        if not self._core or not self._core.is_connected() or not self._om:
            # print("DefaultSourceTracker: Core not connected or ObjectManager not available.")
            return False # Important for GLib.idle_add to remove if it returns False

        try:
            # Find the "default" Wp.Metadata object again (could be cached)
            metadata_obj = self._om.lookup_object(Wp.Constraint.new_full(
                Wp.PW_KEY_METADATA_NAME, "default", Wp.ConstraintVerb.EQUALS,
            ))

            if not metadata_obj or not isinstance(metadata_obj, Wp.Metadata):
                # print("DefaultSourceTracker: 'default' Wp.Metadata object not found.")
                return False 

            # Try to get the default audio source node NAME first
            default_node_name = metadata_obj.get_property_value_for_subject(0, "default.audio.source") # Global subject (0)
            if not default_node_name: # Fallback for some systems or BT devices
                 default_node_name = metadata_obj.get_property_value_for_subject(0, "default.bluez.source")

            if not default_node_name:
                # print("DefaultSourceTracker: Could not determine default audio source node name from metadata.")
                if self._default_node_props: # If there was a previous default, signal it's gone
                    self._default_node_props = {}
                    self.emit("default-changed", "", -1)
                return False

            # Now, find the Wp.Node that corresponds to this default_node_name
            node = self._om.lookup_object(Wp.Constraint.new_full(
                Wp.PW_KEY_NODE_NAME, default_node_name, Wp.ConstraintVerb.EQUALS,
            ))

            if node and isinstance(node, Wp.Node):
                props = node.get_properties()
                if props:
                    # The GStreamer ID for pipewiresrc is usually the object path.
                    gst_id_for_pipewiresrc = props.get_string(Wp.PW_KEY_OBJECT_PATH)
                    if not gst_id_for_pipewiresrc: # Fallback if path isn't there for some reason
                        gst_id_for_pipewiresrc = props.get_string(Wp.PW_KEY_NODE_NAME)

                    pw_serial_obj = props.get_value(Wp.PW_KEY_OBJECT_SERIAL)
                    pw_serial = int(pw_serial_obj) if pw_serial_obj is not None else -1
                    
                    # Check if it actually changed from the last known default
                    if (self._default_node_props.get("gst_id") != gst_id_for_pipewiresrc or
                        self._default_node_props.get("pw_serial") != pw_serial):
                        # print(f"DefaultSourceTracker: Default audio source changed.")
                        # print(f"  New GST ID (for pipewiresrc): {gst_id_for_pipewiresrc}, PW Serial: {pw_serial}, Node Name: {default_node_name}")
                        self._default_node_props = {"gst_id": gst_id_for_pipewiresrc, "pw_serial": pw_serial, "name": default_node_name}
                        self.emit("default-changed", gst_id_for_pipewiresrc, pw_serial)
            else:
                # print(f"DefaultSourceTracker: Node with name '{default_node_name}' not found via ObjectManager.")
                if self._default_node_props: # If there was a previous default, signal it's gone
                    self._default_node_props = {}
                    self.emit("default-changed", "", -1)
        
        except Exception as e:
            print(f"DefaultSourceTracker: Error in _check_and_emit_default_node: {e}")
            if self._default_node_props: # If there was a previous default
                self._default_node_props = {}
                self.emit("default-changed", "", -1) # Signal error/loss of tracking
        
        return False # Remove from idle_add

    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = DefaultSourceTracker()
        return cls._instance

    def stop(self):
        print("DefaultSourceTracker: Stopping...")
        if self._core and self._core.is_connected():
            # print("DefaultSourceTracker: Disconnecting WirePlumber core.")
            self._core.disconnect()
        self._core = None
        self._om = None # Object manager is owned by core or needs explicit unref if not
        DefaultSourceTracker._instance = None 
        # print("DefaultSourceTracker: Stopped.")


if __name__ == '__main__':
    loop = GLib.MainLoop()

    def on_default_changed_cb(tracker, gst_id, pw_serial):
        print(f"\nCALLBACK: Default changed! GST ID (for pipewiresrc): '{gst_id}', PW Serial: {pw_serial}\n")

    tracker = DefaultSourceTracker.get_instance()
    
    if tracker._core and tracker._core.is_connected():
        tracker.connect("default-changed", on_default_changed_cb)
        print("DefaultSourceTracker initialized. Monitoring for default audio source changes.")
        print("Try changing your system's default microphone in sound/audio settings.")
    else:
        print("Failed to initialize DefaultSourceTracker. WirePlumber might not be running or accessible.")
        print("Exiting example.")
        exit()

    try:
        loop.run()
    except KeyboardInterrupt:
        print("\nExiting...")
    finally:
        if tracker:
            tracker.stop()
        if loop.is_running():
            loop.quit()



================================================
File: gnomerecast/models/__init__.py
================================================
# src/gnomerecast/models/__init__.py


================================================
File: gnomerecast/models/transcript_item.py
================================================
import gi
gi.require_version('GObject', '2.0')
from gi.repository import GObject
import uuid
import os
import json
from datetime import datetime
import pathlib
import logging # Added
from ..utils.io import atomic_write_json # Added

logger = logging.getLogger(__name__) # Added

class SegmentItem(GObject.Object):
    """
    Represents a single segment of a transcript.
    """
    __gtype_name__ = 'SegmentItem'

    start = GObject.Property(type=float, nick='Start Time', blurb='Segment start time (seconds)')
    end = GObject.Property(type=float, nick='End Time', blurb='Segment end time (seconds)')
    text = GObject.Property(type=str, nick='Text', blurb='Segment text content')
    speaker = GObject.Property(type=str, nick='Speaker', blurb='Identified speaker (placeholder)', default='')

    def __init__(self, start: float, end: float, text: str, speaker: str = ''):
        """
        Initializes a SegmentItem.

        Args:
            start: Start time in seconds.
            end: End time in seconds.
            text: Text content of the segment.
            speaker: Speaker identifier (optional, defaults to empty).
        """
        super().__init__()
        self.set_property('start', start)
        self.set_property('end', end)
        self.set_property('text', text)
        self.set_property('speaker', speaker)

    def __repr__(self):
        return f"<SegmentItem(start={self.start:.2f}, end={self.end:.2f}, text='{self.text[:20]}...')>"


class TranscriptItem(GObject.Object):
    """
    Represents a single completed transcription result.
    """
    __gtype_name__ = 'TranscriptItem'

    uuid = GObject.Property(type=str, nick='UUID', blurb='Unique identifier')
    source_path = GObject.Property(type=str, nick='JSON File Path', blurb='Path to the .json transcript file itself')
    transcript_text = GObject.Property(type=str, nick='Transcript Text', blurb='Full text content')
    timestamp = GObject.Property(type=str, nick='Timestamp', blurb='Creation timestamp (YYYYMMDD_HHMMSS in JSON, YYYY-MM-DD HH:MM:SS internally)')
    output_filename = GObject.Property(type=str, nick='Output Filename', blurb='Filename of the JSON transcript file (basename of source_path)')
    segments = GObject.Property(type=GObject.TYPE_PYOBJECT, nick='Segments', blurb='List of SegmentItem objects')
    audio_source_path = GObject.Property(type=str, default="", nick='Media Source Path', blurb='Path to the original audio/video file that was transcribed')
    language = GObject.Property(type=str, default="en", nick='Language', blurb='Detected language code (e.g., "en", "es")')


    @classmethod
    def load_from_json(cls, json_file_path: str):
        """
        Loads transcript data from a JSON file according to docs/refactordevspec.txt.

        Args:
            json_file_path: The full path to the .json transcript file.

        Returns:
            A TranscriptItem instance populated with data.
        Raises:
            FileNotFoundError: If the json_file_path does not exist.
            json.JSONDecodeError: If the file content is not valid JSON.
            ValueError: If the JSON content is malformed or missing mandatory keys
                        as per docs/refactordevspec.txt §1.1.
        """
        try:
            path_obj = pathlib.Path(json_file_path)
            if not path_obj.is_file():
                raise FileNotFoundError(f"Transcript JSON file not found: {json_file_path}")

            with path_obj.open('r', encoding='utf-8') as f:
                data = json.load(f)

            # Validate mandatory keys as per docs/refactordevspec.txt §1.1
            # Mandatory keys in JSON: uuid, timestamp, text, segments, language, source_path (media), audio_source_path (media), output_filename (JSON filename)
            # Note: The spec lists 'source_path' and 'audio_source_path' for media. We'll prioritize 'audio_source_path' if both exist.
            # The 'output_filename' in JSON should match the actual JSON filename.
            # The 'source_path' for the TranscriptItem object itself will be json_file_path.

            spec_mandatory_keys = ['uuid', 'timestamp', 'text', 'segments', 'language', 'output_filename']
            # 'source_path' (media) and 'audio_source_path' (media) are also in spec, handle them carefully
            
            missing_keys = [key for key in spec_mandatory_keys if key not in data]
            if missing_keys:
                raise ValueError(f"JSON file {json_file_path} is missing mandatory keys: {', '.join(missing_keys)}")

            # Check for media path keys
            if 'audio_source_path' not in data and 'source_path' not in data:
                raise ValueError(f"JSON file {json_file_path} must contain either 'audio_source_path' or 'source_path' for the media file.")

            item_uuid = data['uuid']
            json_timestamp_str = data['timestamp'] # Expected YYYYMMDD_HHMMSS from spec
            transcript_text = data['text']
            segments_data = data['segments']
            language_code = data['language']
            output_filename_from_json = data['output_filename']

            # Media path: prioritize 'audio_source_path', then 'source_path' from JSON for the media file
            media_path = data.get('audio_source_path', data.get('source_path'))

            if not isinstance(item_uuid, str) or not item_uuid:
                raise ValueError(f"Invalid or missing 'uuid' (must be non-empty string) in {json_file_path}")
            if not isinstance(json_timestamp_str, str) or not json_timestamp_str: # TODO: Add more specific format validation for YYYYMMDD_HHMMSS
                raise ValueError(f"Invalid or missing 'timestamp' (must be non-empty string) in {json_file_path}")
            try: # Validate timestamp format
                datetime.strptime(json_timestamp_str, "%Y%m%d_%H%M%S")
            except ValueError as e:
                raise ValueError(f"Invalid 'timestamp' format in {json_file_path}. Expected YYYYMMDD_HHMMSS. Error: {e}") from e
            if not isinstance(transcript_text, str): # Allow empty string for text
                 raise ValueError(f"Invalid 'text' (must be string) in {json_file_path}")
            if not isinstance(language_code, str) or not language_code :
                raise ValueError(f"Invalid or missing 'language' (must be non-empty string) in {json_file_path}")
            if not isinstance(output_filename_from_json, str) or not output_filename_from_json:
                raise ValueError(f"Invalid or missing 'output_filename' (must be non-empty string) in {json_file_path}")
            if output_filename_from_json != path_obj.name:
                logger.warning(f"Output filename in JSON ('{output_filename_from_json}') does not match actual filename ('{path_obj.name}') for {json_file_path}. Using actual filename as definitive.")


            segments = []
            if not isinstance(segments_data, list):
                raise ValueError(f"'segments' field must be a list in {json_file_path}")

            for i, seg_dict in enumerate(segments_data):
                if not isinstance(seg_dict, dict):
                    logger.warning(f"Segment at index {i} is not a dictionary in {json_file_path}. Skipping.")
                    continue

                try:
                    # Try to get 'text' first, as it's essential.
                    text = seg_dict.get('text')
                    if text is None: # Explicitly check for None, as empty string is valid
                        logger.warning(f"Segment at index {i} in {json_file_path} is missing 'text'. Skipping.")
                        continue
                    text = str(text).strip()

                    # Handle 'start' and 'end' times, preferring direct float values
                    # then 'start_ms'/'end_ms', then falling back if neither.
                    start_time_s: float | None = None
                    end_time_s: float | None = None

                    if 'start' in seg_dict and isinstance(seg_dict['start'], (float, int)):
                        start_time_s = float(seg_dict['start'])
                    elif 'start_ms' in seg_dict and isinstance(seg_dict['start_ms'], (float, int)):
                        start_time_s = float(seg_dict['start_ms']) / 1000.0
                    
                    if 'end' in seg_dict and isinstance(seg_dict['end'], (float, int)):
                        end_time_s = float(seg_dict['end'])
                    elif 'end_ms' in seg_dict and isinstance(seg_dict['end_ms'], (float, int)):
                        end_time_s = float(seg_dict['end_ms']) / 1000.0

                    if start_time_s is None or end_time_s is None:
                        logger.warning(f"Segment at index {i} in {json_file_path} is missing valid 'start'/'end' times or 'start_ms'/'end_ms'. Skipping.")
                        continue
                    
                    # Speaker is optional as per spec, defaults to ""
                    speaker = str(seg_dict.get('speaker', ''))

                    segments.append(SegmentItem(start=start_time_s, end=end_time_s, text=text, speaker=speaker))
                
                except (ValueError, TypeError) as e:
                    logger.warning(f"Malformed segment data at index {i} in {json_file_path} (type error or value error: {e}). Skipping.")
                    continue
                except Exception as e_seg: # Catch any other unexpected error within segment processing
                    logger.error(f"Unexpected error processing segment at index {i} in {json_file_path}: {e_seg}", exc_info=True)
                    continue # Skip this segment and try the next

            # The 'source_path' for the TranscriptItem constructor is the path to the JSON file itself.
            # The 'output_filename' for constructor is derived from this json_file_path.
            return cls(
                source_path=str(path_obj),      # Path to this JSON file
                audio_source_path=media_path,   # Path to the original media
                transcript_text=transcript_text,
                item_uuid=item_uuid,
                timestamp_str=json_timestamp_str, # Pass YYYYMMDD_HHMMSS to constructor
                segments=segments,
                language=language_code
            )

        except (FileNotFoundError, json.JSONDecodeError, ValueError) as e: # Re-raise specific, handled exceptions
            logger.error(f"Failed to load transcript from {json_file_path}: {e}", exc_info=True)
            raise
        except Exception as e: # Catch any other unexpected error
            logger.error(f"Unexpected error loading transcript from {json_file_path}: {e}", exc_info=True)
            # Wrap unexpected errors in ValueError for consistent error type from this method
            raise ValueError(f"An unexpected error occurred while loading {json_file_path}") from e


    def __init__(self, source_path: str, transcript_text: str,
                 audio_source_path: str | None = "", # Default to empty string as per GObject prop
                 item_uuid: str | None = None,
                 timestamp_str: str | None = None, # Expects YYYYMMDD_HHMMSS from load_from_json, or None
                 segments: list | None = None,
                 language: str | None = "en"): # Default to "en" as per GObject prop
        """
        Initializes a TranscriptItem.

        Args:
            source_path: Path to the .json metadata file for this transcript.
            transcript_text: The transcribed text content.
            audio_source_path: Path to the original audio/video file (optional).
            item_uuid: Optional existing UUID. If None, a new one is generated.
            timestamp_str: Optional existing timestamp string.
                           If from JSON, expected format YYYYMMDD_HHMMSS.
                           If None, current time is used and formatted to YYYY-MM-DD HH:MM:SS for internal use.
            segments: Optional list of SegmentItem objects. Defaults to an empty list.
            language: Language code (e.g., "en"). Defaults to "en".
        """
        super().__init__()

        self.set_property('uuid', item_uuid if item_uuid else str(uuid.uuid4()))
        self.set_property('source_path', source_path) # Path to this JSON file
        self.set_property('transcript_text', transcript_text)

        if timestamp_str:
            try:
                # Convert YYYYMMDD_HHMMSS from JSON to YYYY-MM-DD HH:MM:SS for internal storage
                dt_obj = datetime.strptime(timestamp_str, "%Y%m%d_%H%M%S")
                internal_timestamp = dt_obj.strftime("%Y-%m-%d %H:%M:%S")
            except ValueError:
                logger.warning(f"Invalid timestamp format '{timestamp_str}' for UUID {self.uuid}. Using current time. Expected YYYYMMDD_HHMMSS.")
                internal_timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        else:
            internal_timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.set_property('timestamp', internal_timestamp)

        # output_filename is the basename of the JSON file path (source_path)
        self.set_property('output_filename', pathlib.Path(source_path).name if source_path else f"{self.uuid}.json")
        
        parsed_segments = segments if segments is not None else []
        if not all(isinstance(s, SegmentItem) for s in parsed_segments):
             logger.warning(f"Invalid segment data passed to TranscriptItem constructor for {self.uuid}. Segments cleared.")
             parsed_segments = []
        self.set_property('segments', parsed_segments)
        self.set_property('audio_source_path', audio_source_path if audio_source_path is not None else "")
        self.set_property('language', language if language is not None else "en")


    def to_dict(self) -> dict:
        """
        Serializes the TranscriptItem to a dictionary suitable for JSON storage,
        adhering to the spec in docs/refactordevspec.txt §1.1.
        Keys: uuid, timestamp (YYYYMMDD_HHMMSS), text, segments, language,
              source_path (media), audio_source_path (media), output_filename (JSON filename)
        """
        # Convert internal timestamp (YYYY-MM-DD HH:MM:SS) to JSON format (YYYYMMDD_HHMMSS)
        try:
            dt_obj = datetime.strptime(self.timestamp, "%Y-%m-%d %H:%M:%S")
            json_timestamp = dt_obj.strftime("%Y%m%d_%H%M%S")
        except ValueError:
            logger.warning(f"Could not parse internal timestamp '{self.timestamp}' for UUID {self.uuid} during to_dict. Using as is for JSON.")
            # Fallback: try to convert if it's already in YYYYMMDD_HHMMSS due to direct setting or error
            try:
                datetime.strptime(self.timestamp, "%Y%m%d_%H%M%S") # just validate
                json_timestamp = self.timestamp
            except ValueError: # if truly unparseable by either format
                 logger.error(f"Unparseable internal timestamp '{self.timestamp}' for UUID {self.uuid}. Defaulting timestamp in JSON.")
                 json_timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")


        return {
            'uuid': self.uuid,
            'timestamp': json_timestamp,
            'text': self.transcript_text, # Full transcript text
            'segments': [ # List of segment objects
                {
                    'start': round(seg.start, 3), # float seconds, rounded
                    'end': round(seg.end, 3),     # float seconds, rounded
                    'text': seg.text,             # string, trimmed (SegmentItem __init__ should handle trim if needed)
                    'speaker': seg.speaker        # string, may be empty
                } for seg in self.segments
            ],
            'language': self.language, # string
            'source_path': self.audio_source_path, # Path to original media file (as per spec example for this key)
            'audio_source_path': self.audio_source_path, # Path to original media file (explicitly named)
            'output_filename': self.output_filename # Basename of the JSON file itself (e.g., "YYYYMMDD_HHMMSS_basename.json")
        }

    def to_segment_dicts(self) -> list[dict]:
        """
        Returns the list of segment data as dictionaries.
        New method as per spec §7.
        """
        return [
            {
                'start': round(seg.start, 3),
                'end': round(seg.end, 3),
                'text': seg.text,
                'speaker': seg.speaker
            } for seg in self.segments
        ]

    def save(self):
        """
        Saves the current transcript item to its `source_path` (which is the JSON file path)
        using `atomic_write_json`.
        New method as per spec §7.
        This method itself does not handle threading; the caller should use a thread pool.
        """
        if not self.source_path:
            # This should ideally not happen if object is constructed correctly via load_from_json or with a valid path.
            raise ValueError("Cannot save TranscriptItem: source_path (JSON file path) is not set.")
        
        data_to_save = self.to_dict()
        try:
            # The self.source_path property should point to the target JSON file.
            atomic_write_json(data_to_save, self.source_path)
            logger.info(f"TranscriptItem {self.uuid} saved to {self.source_path}")
        except Exception as e:
            logger.error(f"Failed to save TranscriptItem {self.uuid} to {self.source_path}: {e}", exc_info=True)
            raise # Re-raise to allow caller to handle (e.g., show toast in UI)


    def __repr__(self):
        return (f"<TranscriptItem(uuid='{self.uuid}', json_file='{self.source_path}', "
                f"media_file='{self.audio_source_path}', lang='{self.language}', "
                f"timestamp='{self.timestamp}')>")



================================================
File: gnomerecast/transcription/__init__.py
================================================
# This file makes Python treat the directory as a package.


================================================
File: gnomerecast/transcription/transcriber.py
================================================
import threading
import typing as t
import os
import json
import uuid
import weakref # Added
from datetime import datetime
from faster_whisper import WhisperModel
from faster_whisper.transcribe import TranscriptionOptions

from gi.repository import GLib, Gio

from ..utils.models import ModelNotAvailableError, ensure_cached # Updated import
from ..utils.io import atomic_write_json # Added



ProgressCallback = t.Callable[[float, int, int], None]
SegmentCallback = t.Callable[[dict], None]
# CompletionCallback will now also indicate save status and path
CompletionCallback = t.Callable[[str, t.List[dict], t.Optional[str], t.Optional[str]], None]
# status, segments, saved_json_path, save_error_message


class Transcriber:
    """
    Handles the transcription process in a separate thread using faster-whisper.
    """
    _MODEL_POOL: t.Dict[t.Tuple[str, str, str], WhisperModel] = weakref.WeakValueDictionary()

    def _run_transcription_thread(
        self,
        file_paths: t.List[str],
        progress_callback: ProgressCallback,
        segment_callback: SegmentCallback,
        completion_callback: CompletionCallback,
        cancellation_token: threading.Event,
    ):
        """
        The actual worker function that runs in a separate thread.
        Uses faster-whisper for in-process transcription.
        """
        total_files = len(file_paths)
        status = "completed" # Default status
        all_files_segments: t.List[dict] = []
        saved_json_path: t.Optional[str] = None
        save_error_message: t.Optional[str] = None
        current_overall_transcription_pct: float = 0.0
        current_segments_done: int = 0

        permanent_storage_dir = os.path.join(GLib.get_user_data_dir(), 'GnomeRecast', 'transcripts')
        os.makedirs(permanent_storage_dir, exist_ok=True)
        print(f"Ensured permanent storage directory exists: {permanent_storage_dir}")

        print("Transcription thread started.")
        model = None

        try:
            try:
                settings = Gio.Settings.new("org.hardcoeur.Recast")
                selected_model_name = settings.get_string("default-model")
                auto_detect = settings.get_boolean("auto-detect-language")
                lang_to_use = None if auto_detect else settings.get_string("target-language")
                enable_translation = settings.get_boolean("enable-translation")
                device_mode = settings.get_string("whisper-device-mode")
                compute_type_setting = settings.get_string("whisper-compute-type")
                print(f"Thread using settings: model_name={selected_model_name}, lang={lang_to_use or 'auto'}, translate={enable_translation}, device_mode={device_mode}, compute_type={compute_type_setting}")
            except Exception as e:
                print(f"Error reading GSettings in thread: {e}. Using default transcription parameters.")
                selected_model_name = "base"
                lang_to_use = None
                enable_translation = False
                device_mode = "cpu"
                compute_type_setting = "auto"

            # Ensure model is cached before loading
            try:
                # Adapt progress_cb for ensure_cached.
                # ensure_cached progress_cb is Callable[[float, str], None]
                # - percent: 0.0 for start, 100.0 for done, -1.0 for error
                # - message: string description
                # Main progress_callback is Callable[[float (overall_pct), int (segments_done), float (model_download_pct)], None]
                def _ensure_cached_progress_adapter(model_dl_pct_raw: float, message: str):
                    print(f"ensure_cached progress: {model_dl_pct_raw}%, message: {message}")
                    if progress_callback:
                        model_download_progress = model_dl_pct_raw / 100.0 if model_dl_pct_raw >= 0 else model_dl_pct_raw
                        # During model download/prep, overall transcription pct and segments_done are 0 or last known.
                        # Here, we assume they are 0 as this happens before main transcription loop.
                        GLib.idle_add(progress_callback,
                                      current_overall_transcription_pct, # Use current/last known overall %
                                      current_segments_done,             # Use current/last known segments
                                      model_download_progress)           # Actual model download/prep %
                    if model_dl_pct_raw == -1.0 and "Error:" in message: # Error from ensure_cached
                        # This error will be raised as ModelNotAvailableError, so just log here.
                        print(f"ensure_cached reported error: {message}")


                model_dir_path = ensure_cached(
                    model_name=selected_model_name,
                    device=device_mode,
                    compute_type=compute_type_setting,
                    progress_cb=_ensure_cached_progress_adapter if progress_callback else None
                )
                print(f"Model directory ensured at: {model_dir_path}")
                # Signal model download/preparation is complete by sending 100% for model_download_pct,
                # or -1.0 if it was already cached and ensure_cached sent 100 immediately.
                # The last call from _ensure_cached_progress_adapter should handle the 100% state.
                # If transcription starts, model_download_pct becomes -1.0.

            except ModelNotAvailableError as e:
                print(f"[ERROR] Model not available: {e.details}")
                status = "error"
                # Error already sent via _ensure_cached_progress_adapter with -1.0
                # completion_callback will be called in finally block.
                save_error_message = f"model-unavailable:{e.details}"
                GLib.idle_add(completion_callback, status, [], None, save_error_message)
                return
            except Exception as cache_err:
                print(f"[ERROR] Failed to ensure model is cached: {cache_err}")
                status = "error"
                save_error_message = f"Caching error: {str(cache_err)}"
                if progress_callback: # Send a generic model error if specific adapter didn't catch it.
                    GLib.idle_add(progress_callback, current_overall_transcription_pct, current_segments_done, -1.0)
                GLib.idle_add(completion_callback, status, [], None, save_error_message)
                return

            # Model is ready, set model_download_pct to -1 for subsequent transcription progress
            if progress_callback:
                GLib.idle_add(progress_callback, current_overall_transcription_pct, current_segments_done, -1.0)


            if device_mode == "cuda":
                device = "cuda"
                compute_type = "float16"
            elif device_mode == "cpu":
                device = "cpu"
                compute_type = "int8"
            else:  # 'auto'
                device = "auto"
                compute_type = "auto" # faster-whisper will pick the best for the auto-selected device
            print(f"User preferred device mode: {device_mode}, Effective device for WhisperModel: {device}, Compute type: {compute_type}")

            try:
                model_key = (selected_model_name, device, compute_type)
                if model_key in Transcriber._MODEL_POOL:
                    model = Transcriber._MODEL_POOL[model_key]
                    print(f"Reusing cached WhisperModel instance for {model_key}")
                else:
                    print(f"Initializing WhisperModel with directory: {model_dir_path}, device={device}, compute_type={compute_type}")
                    # model_dir_path is from the new ensure_cached
                    model = WhisperModel(model_size_or_path=str(model_dir_path), device=device, compute_type=compute_type)
                    Transcriber._MODEL_POOL[model_key] = model
                    print(f"Cached new WhisperModel instance for {model_key}")
                print("Faster-whisper model ready.")
            except Exception as model_load_err:
                print(f"[ERROR] Failed to load faster-whisper model: {model_load_err}")
                status = "error"
                # Provide more context if model_dir_path was involved
                err_detail_msg = f"Failed to load model from {model_dir_path if 'model_dir_path' in locals() else selected_model_name}: {model_load_err}"
                GLib.idle_add(completion_callback, status, [], None, err_detail_msg)
                return

            for index, file_path in enumerate(file_paths):
                if cancellation_token.is_set():
                    print(f"Cancellation requested. Stopping transcription.")
                    status = "cancelled"
                    break

                print(f"\n--- Starting processing for file {index + 1}/{total_files}: {file_path} ---")

                current_file_segments: t.List[dict] = []
                current_full_text: str = ""
                total_duration: float = 0.0
                info = None

                try:
                    language_arg = None if lang_to_use == "auto" or not lang_to_use else lang_to_use
                    task_arg = "translate" if enable_translation else "transcribe"


                    print(f"Starting faster-whisper transcription for: {file_path}")
                    print(f"  Task: {task_arg}, Language: {language_arg or 'auto detect'}")
                    segments_generator, info = model.transcribe(
                        file_path,
                        beam_size=5,
                        task=task_arg,
                        language=language_arg,
                        word_timestamps=False,
                        vad_filter=False,

                    )
                    total_duration = info.duration
                    print(f"Transcription initiated. Detected language: {info.language}, Probability: {info.language_probability:.2f}, Duration: {total_duration:.2f}s")

                    print("Iterating over segments generator...")
                    last_segment_index = -1

                    for i, segment in enumerate(segments_generator):
                        if cancellation_token.is_set():
                            print(f"Cancellation requested during segment processing.")
                            status = "cancelled"
                            break

                        last_segment_index = i

                        current_segments_done = i + 1
                        if progress_callback:
                            if total_duration > 0:
                                current_overall_transcription_pct = min(segment.end / total_duration, 1.0)
                                GLib.idle_add(progress_callback, current_overall_transcription_pct, current_segments_done, -1.0)
                            else:
                                current_overall_transcription_pct = 0.0 # Or some other appropriate value
                                GLib.idle_add(progress_callback, current_overall_transcription_pct, current_segments_done, -1.0)

                        segment_dict = {
                            "id": i,
                            "text": segment.text.strip(),
                            "start": segment.start,
                            "end": segment.end,
                            "start_ms": int(segment.start * 1000),
                            "end_ms": int(segment.end * 1000),
                        }
                        current_file_segments.append(segment_dict)
                        current_full_text += segment.text

                        if segment_callback:
                            print(f"Transcriber: Generated segment [{segment_dict['start']:.2f}s->{segment_dict['end']:.2f}s], calling callback.")
                            GLib.idle_add(segment_callback, segment_dict)


                    if status == "cancelled":
                         break

                    if status == "completed" and progress_callback:
                        current_overall_transcription_pct = 1.0
                        # current_segments_done is already updated
                        final_completed_count = last_segment_index + 1 if last_segment_index >=0 else current_segments_done
                        GLib.idle_add(progress_callback, current_overall_transcription_pct, final_completed_count, -1.0)

                    print(f"Finished processing segments for {file_path}.")

                    if status == "completed":
                        unique_id = str(uuid.uuid4())
                        timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
                        base_name = os.path.splitext(os.path.basename(file_path))[0]
                        destination_filename = f"{timestamp_str}_{base_name}.json"
                        destination_path = os.path.join(permanent_storage_dir, destination_filename)
                        print(f"Generated metadata: UUID={unique_id}, Timestamp={timestamp_str}, DestFile={destination_filename}")

                        # Prepare segments for JSON file storage as per spec (start, end, text, speaker)
                        segments_for_file = []
                        for seg_data in current_file_segments: # current_file_segments contains richer dicts
                            segments_for_file.append({
                                "start": round(seg_data['start'], 3),
                                "end": round(seg_data['end'], 3),
                                "text": seg_data['text'], # Already stripped
                                "speaker": ""  # Default speaker, as not directly provided by whisper segments
                            })

                        # final_json_data must match the structure defined in docs/refactordevspec.txt §1.1
                        # and expected by TranscriptItem.load_from_json
                        final_json_data = {
                            "uuid": unique_id,
                            "timestamp": timestamp_str,  # Format: YYYYMMDD_HHMMSS
                            "text": current_full_text.strip(),
                            "segments": segments_for_file,
                            "language": info.language if info else "unknown", # Ensure info is not None
                            "source_path": file_path,  # Path to the original media file
                            "audio_source_path": file_path, # Path to the original media file (spec has both)
                            "output_filename": destination_filename # Basename of the JSON file
                        }

                        try:
                            print(f"Attempting to save final transcript JSON to: {destination_path} using atomic_write_json")
                            # This is a blocking call but we are in a worker thread.
                            atomic_write_json(final_json_data, destination_path)
                            print(f"JSON saved successfully to {destination_path} via atomic_write_json.")
                            saved_json_path = destination_path # Store for completion callback
                            # status remains "completed"
                            all_files_segments.extend(current_file_segments) # Keep using richer segments for callback
                        except Exception as save_err:
                            print(f"[ERROR] Failed to save transcript JSON to {destination_path} using atomic_write_json: {save_err}")
                            status = "completed_save_failed" # Indicate transcription was ok, but save failed
                            save_error_message = str(save_err)


                except Exception as transcribe_err:
                    print(f"[ERROR] faster-whisper transcribe failed for {file_path}: {transcribe_err}")
                    status = "error" # Transcription error itself
                    save_error_message = str(transcribe_err) # Use this field for the primary error
                    break # Stop processing further files on transcription error


        finally:
            print(f"Transcription thread finishing with overall status: {status}")
            # Pass segments if transcription itself completed, regardless of save status for this specific callback argument
            final_segments_to_pass = all_files_segments if (status.startswith("completed") or status == "cancelled") else []
            GLib.idle_add(completion_callback, status, final_segments_to_pass, saved_json_path, save_error_message)
            print("Completion callback scheduled with save status.")


    def start_transcription(
        self,
        file_paths: t.List[str],
        progress_callback: ProgressCallback,
        segment_callback: SegmentCallback,
        completion_callback: CompletionCallback,
    ) -> threading.Event:
        """
        Starts the transcription process in a background thread using faster-whisper.
        """
        if not file_paths:
            print("No files selected for transcription.")
            GLib.idle_add(completion_callback, "no_files", [], None, "No files provided.")
            return threading.Event()

        cancellation_token = threading.Event()

        def transcription_worker():
            self._run_transcription_thread(
                file_paths=file_paths,
                progress_callback=progress_callback,
                segment_callback=segment_callback,
                completion_callback=completion_callback,
                cancellation_token=cancellation_token
            )

        thread = threading.Thread(
            target=transcription_worker,
            daemon=True
        )
        thread.start()
        print(f"[Transcriber] Started transcription for {len(file_paths)} file(s).")
        return cancellation_token




================================================
File: gnomerecast/ui/toast.py
================================================
import gi
import time
import weakref
from weakref import ReferenceType # Added import

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, GLib, Adw

class ToastPresenter:
    """Singleton presenter for managing toast notifications across the application."""
    
    _instance = None
    _registry: weakref.WeakKeyDictionary[Adw.ToastOverlay, ReferenceType[Gtk.Window] | None] = weakref.WeakKeyDictionary()
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._last_toast = {}  # Tracks last shown toast per (message, title) pair
        return cls._instance
    
    @classmethod
    def attach(cls, overlay: Adw.ToastOverlay) -> None:
        """Register a toast overlay with the presenter and its root window."""
        if overlay not in cls._registry:
            root_window = overlay.get_root()
            if isinstance(root_window, Gtk.Window):
                cls._registry[overlay] = weakref.ref(root_window)
            else:
                # Log a warning if the root is not a Gtk.Window or not found
                print(f"Warning: Could not find a Gtk.Window root for overlay {overlay}. Storing with None.")
                cls._registry[overlay] = None
    
    @classmethod
    def show(cls, parent: Gtk.Widget, message: str, timeout: int = 3) -> None:
        """Show a toast message attached to the nearest registered overlay."""
        
        # This inner function will be scheduled by GLib.idle_add
        def _actual_add_toast():
            overlay = None
            widget = parent
            while widget:
                if isinstance(widget, Adw.ToastOverlay) and widget in cls._registry:
                    overlay = widget
                    break
                widget = widget.get_parent()

            if not overlay:
                # Try to find any registered overlay if parent-based search fails
                if cls._registry:
                    # Attempt to get the first available overlay from the registry
                    # This is a fallback, ideally parent should lead to an overlay
                    try:
                        overlay = next(iter(cls._registry.keys()))
                        print(f"ToastPresenter.show: Overlay not found for parent {parent}. Using first registered overlay: {overlay}")
                    except StopIteration:
                        pass # _registry is empty
                
            if not overlay:
                print(f"Toast fallback (no overlay for parent {parent}): {message}")
                return

            # Coalesce duplicate toasts within 1 second
            current_time = time.time()
            # Use overlay's root window for title, if available
            root_for_title = overlay.get_root()
            window_title = root_for_title.get_title() if root_for_title and hasattr(root_for_title, 'get_title') else "Unknown Window"
            toast_key = (message, window_title)
            
            # print(f"DEBUG: ToastPresenter:show_toast - message='{message}', window_title='{window_title}', toast_key={toast_key}")
            
            if toast_key in cls._last_toast:
                last_time = cls._last_toast[toast_key]
                if current_time - last_time < 1.0:  # Within 1 second window
                    return
            
            cls._last_toast[toast_key] = current_time
            toast = Adw.Toast.new(message)
            toast.set_timeout(timeout)
            overlay.add_toast(toast)
        
        GLib.idle_add(_actual_add_toast)

    @classmethod
    def show_global(cls, message: str, timeout: int = 3) -> None:
        """
        Display a toast on the first registered overlay (main window if identifiable)
        when the caller has no widget context (e.g. worker threads).
        """
        
        # This inner function will be scheduled by GLib.idle_add
        def _actual_add_global_toast():
            target_overlay: Adw.ToastOverlay | None = None
            
            # Attempt to find the "main" window overlay first.
            # This is a heuristic: assumes main window might have a specific title
            # or is simply the first one that has a valid Gtk.Window root.
            # A more robust way might involve a specific registration for the main window.
            main_window_title_candidates = ["GnomeRecast", "Recast"] # Adjust as needed
            
            for overlay, window_ref in cls._registry.items():
                if window_ref:
                    window = window_ref()
                    if window and hasattr(window, 'get_title'):
                        title = window.get_title()
                        if title in main_window_title_candidates:
                            target_overlay = overlay
                            break # Found a candidate for main window
            
            # If no "main" window overlay found, use the first valid one
            if not target_overlay:
                for overlay, window_ref in cls._registry.items():
                    if window_ref and window_ref(): # Check if window still exists
                        target_overlay = overlay
                        break # Found any valid overlay
            
            if not target_overlay:
                 # As a last resort, try any overlay even if its window_ref is None (less ideal)
                if not target_overlay and cls._registry:
                    try:
                        target_overlay = next(iter(cls._registry.keys()))
                    except StopIteration:
                        pass # Registry is empty

            if not target_overlay:
                print(f"Toast fallback (show_global, no registered overlays): {message}")
                return

            # Coalesce duplicate toasts within 1 second
            current_time = time.time()
            # Use overlay's root window for title, if available
            root_for_title = target_overlay.get_root()
            window_title = root_for_title.get_title() if root_for_title and hasattr(root_for_title, 'get_title') else "Global Toast"
            toast_key = (message, window_title)

            # print(f"DEBUG: ToastPresenter:show_global - message='{message}', window_title='{window_title}', toast_key={toast_key}")

            if toast_key in cls._last_toast:
                last_time = cls._last_toast[toast_key]
                if current_time - last_time < 1.0: # Within 1 second window
                    return
            
            cls._last_toast[toast_key] = current_time
            toast = Adw.Toast.new(message)
            toast.set_timeout(timeout)
            target_overlay.add_toast(toast)

        GLib.idle_add(_actual_add_global_toast)



================================================
File: gnomerecast/utils/__init__.py
================================================
# This file makes the 'utils' directory a Python package.


================================================
File: gnomerecast/utils/download.py
================================================
import requests
import threading
import os
import pathlib
from typing import Optional, Callable, Tuple
from gi.repository import GLib

ProgressCallback = Callable[[int, int, Optional[str]], None]

def download_file(
    url: str,
    target_path: pathlib.Path,
    progress_callback: Optional[ProgressCallback] = None,
    cancel_event: Optional[threading.Event] = None
) -> Tuple[str, Optional[str]]:
    """
    Downloads a file from a URL to a target path, reporting progress and allowing cancellation.

    Args:
        url: The URL to download the file from.
        target_path: The pathlib.Path object representing the destination file path.
        progress_callback: A function to call with (current_bytes, total_bytes, error_message) updates.
                           It's the caller's responsibility to ensure this callback is thread-safe
                           or marshalled to the correct thread (e.g., using GLib.idle_add).
        cancel_event: A threading.Event object to signal cancellation.

    Returns:
        A tuple containing:
        - status string: 'completed', 'cancelled', or 'error'.
        - error message string (if status is 'error'), otherwise None.
    """
    temp_path = target_path.with_suffix(target_path.suffix + ".part")
    status = "error"
    error_message = None
    downloaded_size = 0
    total_size = -1

    try:
        target_path.parent.mkdir(parents=True, exist_ok=True)

        print(f"Starting download: {url} to {target_path}")

        response = requests.get(url, stream=True, timeout=60)
        response.raise_for_status()

        total_size = int(response.headers.get('content-length', 0))
        chunk_size = 8192

        if progress_callback:
            progress_callback(0, total_size, None)

        with open(temp_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=chunk_size):
                if cancel_event and cancel_event.is_set():
                    print(f"Download cancellation requested: {url}")
                    status = "cancelled"


                    f.close()
                    temp_path.unlink(missing_ok=True)
                    print(f"Partial download file deleted: {temp_path}")
                    return status, None

                if chunk:
                    f.write(chunk)
                    downloaded_size += len(chunk)
                    if progress_callback:
                        progress_callback(downloaded_size, total_size, None)

        temp_path.rename(target_path)
        print(f"Download completed: {url}")
        status = "completed"
        if progress_callback:
            progress_callback(downloaded_size, total_size, None)

    except requests.exceptions.Timeout:
        error_message = "Connection timed out."
        print(f"Error downloading file {url}: {error_message}")
        if temp_path.exists():
            temp_path.unlink(missing_ok=True)
        if progress_callback:
            progress_callback(downloaded_size, total_size, error_message)
    except requests.exceptions.RequestException as e:
        error_message = f"Network error: {e}"
        print(f"Error downloading file {url}: {error_message}")
        if temp_path.exists():
            temp_path.unlink(missing_ok=True)
        if progress_callback:
            progress_callback(downloaded_size, total_size, error_message)
    except OSError as e:
        error_message = f"File system error: {e}"
        print(f"Error saving file {url} to {target_path}: {error_message}")
        if temp_path.exists():
            temp_path.unlink(missing_ok=True)
        if progress_callback:
            progress_callback(downloaded_size, total_size, error_message)
    except Exception as e:
        error_message = f"Unexpected error: {e}"
        print(f"Unexpected error during download of {url}: {error_message}")
        if 'temp_path' in locals() and temp_path.exists():
             temp_path.unlink(missing_ok=True)
        if progress_callback:
            progress_callback(downloaded_size, total_size, error_message)

    return status, error_message


================================================
File: gnomerecast/utils/export.py
================================================
import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    # Ensure this matches the actual SegmentItem class if used, or just TranscriptItem
    from ..models.transcript_item import TranscriptItem, SegmentItem

def _format_timestamp_srt(seconds: float) -> str:
    """Formats seconds into SRT timestamp HH:MM:SS,ms."""
    delta = datetime.timedelta(seconds=seconds)
    hours, remainder = divmod(delta.total_seconds(), 3600)
    minutes, seconds = divmod(remainder, 60)
    milliseconds = int((seconds - int(seconds)) * 1000)
    return f"{int(hours):02}:{int(minutes):02}:{int(seconds):02},{milliseconds:03}"

def _format_timestamp_md(seconds: float) -> str:
    """Formats seconds into MD timestamp HH:MM:SS."""
    delta = datetime.timedelta(seconds=seconds)
    hours, remainder = divmod(delta.total_seconds(), 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{int(hours):02}:{int(minutes):02}:{int(seconds):02}"

def export_to_txt(transcript_item: 'TranscriptItem') -> str:
    """Exports the transcript item to plain text with double newlines between segments."""
    if not transcript_item or not transcript_item.segments:
        return ""

    # Assuming transcript_item.segments is a list of SegmentItem objects
    return "\n\n".join(segment.text.strip() for segment in transcript_item.segments if hasattr(segment, 'text') and segment.text)

def export_to_md(transcript_item: 'TranscriptItem') -> str:
    """Exports the transcript item to Markdown format."""
    if not transcript_item.segments:
        return ""

    md_content = []
    for segment in transcript_item.segments:
        start_time_str = _format_timestamp_md(segment.start)
        segment_text = segment.text.strip() if segment.text else ""
        md_content.append(f"**[{start_time_str}]** {segment_text}")

    return "\n\n".join(md_content)

def export_to_srt(transcript_item: 'TranscriptItem') -> str:
    """Exports the transcript item to SRT format."""
    if not transcript_item.segments:
        return ""

    srt_content = []
    for i, segment in enumerate(transcript_item.segments):
        start_time_str = _format_timestamp_srt(segment.start)
        end_time_str = _format_timestamp_srt(segment.end)
        segment_text = segment.text.strip() if segment.text else ""

        srt_content.append(str(i + 1))
        srt_content.append(f"{start_time_str} --> {end_time_str}")
        srt_content.append(segment_text)
        srt_content.append("")

    return "\n".join(srt_content)


================================================
File: gnomerecast/utils/io.py
================================================
import json
import logging
import os
import tempfile
from pathlib import Path

# Initialize logger for this module
logger = logging.getLogger(__name__)

def atomic_write_json(data: dict, file_path_str: str) -> None:
    """
    Atomically writes a dictionary to a JSON file.

    It first writes to a temporary file in the same directory, then renames it
    to the final destination, ensuring that the destination file is either
    the old version or the new version, never a partially written one.

    Args:
        data: The dictionary to write to JSON.
        file_path_str: The absolute path to the target JSON file.

    Raises:
        OSError: If file operations fail (e.g., permission issues).
        TypeError: If the data is not JSON serializable.
        ValueError: If JSON encoding fails for other reasons.
    """
    try:
        path_obj = Path(file_path_str)
        # Ensure the parent directory exists
        path_obj.parent.mkdir(parents=True, exist_ok=True)

        # Use NamedTemporaryFile in the same directory as the target file
        # to ensure os.replace works (it might fail across different filesystems).
        # delete=False is crucial as we handle the deletion/renaming manually.
        with tempfile.NamedTemporaryFile(
            mode='w',
            encoding='utf-8',
            dir=path_obj.parent,
            prefix=path_obj.name + '.',
            suffix='.tmp',
            delete=False
        ) as tmp_file:
            temp_file_path = tmp_file.name
            json.dump(data, tmp_file, indent=4, ensure_ascii=False)
            # Ensure data is written to disk before renaming
            tmp_file.flush()
            os.fsync(tmp_file.fileno())

        # Atomically replace the target file with the temporary file
        os.replace(temp_file_path, path_obj)
        logger.info(f"Successfully wrote JSON data to {path_obj}")

    except (OSError, IOError) as e:
        logger.error(f"Error writing JSON to {file_path_str}: {e}", exc_info=True)
        # Clean up the temporary file if it still exists and an error occurred
        if 'temp_file_path' in locals() and Path(temp_file_path).exists():
            try:
                os.remove(temp_file_path)
            except OSError as remove_err:
                logger.error(f"Error removing temporary file {temp_file_path}: {remove_err}", exc_info=True)
        raise  # Re-raise the original exception
    except (TypeError, ValueError) as e:
        logger.error(f"Error serializing data to JSON for {file_path_str}: {e}", exc_info=True)
        # Clean up the temporary file
        if 'temp_file_path' in locals() and Path(temp_file_path).exists():
            try:
                os.remove(temp_file_path)
            except OSError as remove_err:
                logger.error(f"Error removing temporary file {temp_file_path}: {remove_err}", exc_info=True)
        raise # Re-raise the original exception
    except Exception as e:
        logger.error(f"An unexpected error occurred during atomic_write_json for {file_path_str}: {e}", exc_info=True)
        if 'temp_file_path' in locals() and Path(temp_file_path).exists():
            try:
                os.remove(temp_file_path)
            except OSError as remove_err:
                logger.error(f"Error removing temporary file {temp_file_path}: {remove_err}", exc_info=True)
        raise

if __name__ == '__main__':
    # Example usage (for testing purposes)
    logging.basicConfig(level=logging.INFO)
    test_data_dir = Path(__file__).parent.parent.parent / "test_data" # Assuming a test_data directory at project root
    test_data_dir.mkdir(exist_ok=True)
    test_file = test_data_dir / "test_atomic_write.json"

    sample_data = {
        "name": "Test Recast",
        "version": "1.0",
        "items": [1, 2, 3],
        "settings": {"theme": "dark", "notifications": True}
    }

    print(f"Attempting to write to: {test_file}")
    try:
        atomic_write_json(sample_data, str(test_file))
        print(f"Successfully wrote to {test_file}")

        # Verify content
        with open(test_file, 'r', encoding='utf-8') as f:
            read_data = json.load(f)
        assert read_data == sample_data
        print("File content verified.")

    except Exception as e:
        print(f"An error occurred during example usage: {e}")

    finally:
        # Clean up the test file
        if test_file.exists():
            # os.remove(test_file)
            print(f"Test file {test_file} can be manually inspected or removed.")


================================================
File: gnomerecast/utils/models.py
================================================
import pathlib
import threading
from typing import Dict, Callable, Optional, Tuple

# Attempt to import WhisperModel, as it's crucial.
try:
    from faster_whisper import WhisperModel
    FASTER_WHISPER_AVAILABLE = True
except ImportError:
    WhisperModel = None # type: ignore # Make linters happy if not installed
    FASTER_WHISPER_AVAILABLE = False

APP_MODEL_DIR: pathlib.Path = pathlib.Path.home() / '.local' / 'share' / 'GnomeRecast' / 'models'

AVAILABLE_MODELS: Dict[str, str] = {
    'tiny': '39 MB',
    'base': '74 MB',
    'small': '244 MB',
    'medium': '769 MB',
    'large': '1.5 GB',
    # As per spec: ".en variants can be added if they should still be distinct"
    # e.g., 'tiny.en': '39 MB', if faster-whisper supports these names directly
    # and corresponding URLs are considered (though URLs are not directly used by this ensure_cached)
}

# URLs for the simplified model names (assuming ggml-v3 for 'large')
# These are as per the spec, though not directly used by ensure_cached if
# faster-whisper handles downloads by model name.
_MODEL_URLS: Dict[str, str] = {
    'tiny': "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-tiny.bin?download=true",
    'base': "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-base.bin?download=true",
    'small': "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-small.bin?download=true",
    'medium': "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-medium.bin?download=true",
    'large': "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-large-v3.bin?download=true",
}

class ModelNotAvailableError(RuntimeError):
    def __init__(self, model: str, details: str):
        self.model = model
        self.details = details
        super().__init__(f"Model {model} not available: {details}")

# Global cache for model directory paths once successfully "ensured".
# Key: model_name (str), Value: model_directory_path (pathlib.Path)
_model_cache_paths: Dict[str, pathlib.Path] = {}
_model_cache_lock = threading.Lock() # To protect access to _model_cache_paths

def ensure_cached(
    model_name: str,
    *,
    device: str, # "cpu" | "cuda" | "auto"
    compute_type: str, # "int8" | "float16" | "auto"
    progress_cb: Callable[[float, str], None] | None = None
) -> pathlib.Path:
    """
    Ensures the specified model is available in faster-whisper's cache
    and returns the local directory path to the model.
    Downloads the model via faster-whisper if not already cached.
    Raises ModelNotAvailableError if the model_name is invalid or download/load fails.
    """
    if not FASTER_WHISPER_AVAILABLE:
        err_msg = "The 'faster-whisper' library is not installed or could not be imported."
        if progress_cb:
            progress_cb(-1.0, f"Error: {err_msg}")
        raise ModelNotAvailableError(model_name, err_msg)

    if model_name not in AVAILABLE_MODELS:
        err_msg = f"Model name '{model_name}' is not in the list of recognized available models."
        if progress_cb:
            progress_cb(-1.0, f"Error: {err_msg}")
        raise ModelNotAvailableError(model_name, err_msg)

    # Check cache first (thread-safe)
    with _model_cache_lock:
        if model_name in _model_cache_paths:
            cached_path = _model_cache_paths[model_name]
            if progress_cb:
                progress_cb(0.0, "Starting model preparation (found in cache)")
                progress_cb(100.0, f"Model preparation complete (from cache: {cached_path})")
            return cached_path

    if progress_cb:
        progress_cb(0.0, "Starting model preparation")

    try:
        # Instantiate WhisperModel to trigger its download and cache mechanism.
        # faster-whisper does not provide fine-grained download progress for this call.
        # The progress_cb here signals the start and end of this preparation phase.
        
        temp_model = WhisperModel(model_name, device=device, compute_type=compute_type)
        
        model_dir_path = pathlib.Path(temp_model.model_path)
        
        del temp_model # Release the model instance and its resources.

        # Cache the successfully obtained path (thread-safe)
        with _model_cache_lock:
            _model_cache_paths[model_name] = model_dir_path
        
        if progress_cb:
            progress_cb(100.0, f"Model preparation complete (model '{model_name}' cached at: {model_dir_path})")
        
        return model_dir_path

    except Exception as e:
        details = f"Failed to ensure model '{model_name}' (device: {device}, compute: {compute_type}). Error: {type(e).__name__} - {str(e)}"
        
        if "out of memory" in str(e).lower():
            details += f". The model may be too large for the available '{device}' memory. Try a smaller model or check resources."
        elif "CUDA" in str(e).upper() or "CUBLAS" in str(e).upper() or "NVIDIA" in str(e).upper() :
            details += f". There might be an issue with your CUDA setup or GPU compatibility for device '{device}'."
        elif "No such file or directory" in str(e) and ".cache/huggingface/hub" in str(e):
             details += f". This could indicate a problem with model file download or cache integrity for '{model_name}'."

        if progress_cb:
            progress_cb(-1.0, f"Error: {details}")
        raise ModelNotAvailableError(model_name, details) from e



================================================
File: gnomerecast/views/app_selection_dialog.py
================================================
import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Gio, GObject, Adw

import logging

log = logging.getLogger(__name__)

class AppItem(GObject.Object):
    __gtype_name__ = 'AppItem'

    name = GObject.Property(type=str)
    icon = GObject.Property(type=Gio.Icon)
    app_info = GObject.Property(type=Gio.AppInfo)

    def __init__(self, name, icon, app_info):
        super().__init__()
        self.props.name = name
        self.props.icon = icon
        self.props.app_info = app_info


class AppSelectionDialog(Gtk.Dialog):
    """
    A dialog window to select an installed application.
    """
    def __init__(self, parent):
        super().__init__(transient_for=parent, modal=True)

        self.set_title("Select Application to Record")
        self.set_default_size(400, 300)

        self.add_button("_Cancel", Gtk.ResponseType.CANCEL)
        record_button = self.add_button("_Record", Gtk.ResponseType.ACCEPT)
        record_button.set_sensitive(False)

        content_area = self.get_content_area()
        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin_top=10, margin_bottom=10, margin_start=10, margin_end=10)
        content_area.append(main_box)

        scrolled_window = Gtk.ScrolledWindow()
        scrolled_window.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scrolled_window.set_vexpand(True)
        main_box.append(scrolled_window)

        self.list_store = Gio.ListStore(item_type=AppItem)
        self.selection_model = Gtk.SingleSelection(model=self.list_store)
        self.app_list_view = Gtk.ListView(model=self.selection_model)
        self.app_list_view.set_show_separators(True)
        scrolled_window.set_child(self.app_list_view)

        factory = Gtk.SignalListItemFactory()
        factory.connect("setup", self._on_factory_setup)
        factory.connect("bind", self._on_factory_bind)
        self.app_list_view.set_factory(factory)

        self._populate_app_list()

        self.selection_model.connect("notify::selected-item", self._on_app_selection_changed)

    def _on_factory_setup(self, factory, list_item):
        """Sets up the widget structure for a list item."""
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12, margin_top=6, margin_bottom=6, margin_start=6, margin_end=6)
        icon_image = Gtk.Image(icon_size=Gtk.IconSize.LARGE)
        label = Gtk.Label(halign=Gtk.Align.START, hexpand=True)
        box.append(icon_image)
        box.append(label)
        list_item.set_child(box)

    def _on_factory_bind(self, factory, list_item):
        """Binds the data from an AppItem to the list item's widgets."""
        box = list_item.get_child()
        icon_image = box.get_first_child()
        label = box.get_last_child()
        app_item = list_item.get_item()

        if app_item:
            icon_image.set_from_gicon(app_item.props.icon)
            label.set_text(app_item.props.name)
        else:
            icon_image.set_from_gicon(None)
            label.set_text("")


    def _populate_app_list(self):
        """Fetches installed applications and populates the list store."""
        log.info("Populating application list...")
        self.list_store.remove_all()
        try:
            app_infos = Gio.AppInfo.get_all()
            count = 0
            for app_info in app_infos:
                if app_info.get_name() and app_info.get_icon():
                    if app_info.should_show():
                        name = app_info.get_name()
                        icon = app_info.get_icon()
                        app_item = AppItem(name=name, icon=icon, app_info=app_info)
                        self.list_store.append(app_item)
                        count += 1
            log.info(f"Found {count} suitable applications.")
        except Exception as e:
            log.error(f"Error fetching application list: {e}", exc_info=True)


    def _on_app_selection_changed(self, selection_model, param):
        """Enables/disables the Record button based on selection."""
        selected_item = selection_model.get_selected_item()
        record_button = self.get_widget_for_response(Gtk.ResponseType.ACCEPT)
        if record_button:
            record_button.set_sensitive(selected_item is not None)

    def get_selected_app_info(self) -> Gio.AppInfo | None:
        """
        Returns the Gio.AppInfo of the selected application.

        Returns:
            Gio.AppInfo | None: The selected app's info, or None if no selection.
        """
        selected_item_gobj = self.selection_model.get_selected_item()
        if isinstance(selected_item_gobj, AppItem):
            return selected_item_gobj.props.app_info
        return None


================================================
File: gnomerecast/views/dictation_overlay.py
================================================
import gi
gi.require_version('Gtk', '4.0')
from gi.repository import Gtk, Gio, GLib
import wave
import tempfile
import os
import concurrent.futures
from ..audio.capture import AudioCapturer
from faster_whisper import WhisperModel


class DictationOverlay(Gtk.Window):
    """
    A floating, always-on-top window for live dictation transcription.
    """
    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        self.add_css_class("dictation-overlay-window")
        self.settings = Gio.Settings.new("org.hardcoeur.Recast")

        self.set_title("GnomeRecast Dictation")
        self.set_decorated(False)
        self.set_keep_above(True)
        self.set_default_size(400, 250)
        self.set_resizable(False)

        self.audio_capturer = AudioCapturer(settings=self.settings, data_callback=self._on_audio_data_received)
        self.audio_buffer = bytearray()

        self.sample_rate = 16000
        self.channels = 1
        self.bytes_per_sample = 2

        self.chunk_duration_seconds = 5
        self.chunk_size_bytes = int(
            self.sample_rate * self.channels * self.bytes_per_sample * self.chunk_duration_seconds
        )

        self.thread_pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)

        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5)
        main_box.add_css_class("dictation-main-box")
        main_box.set_margin_top(5)
        main_box.set_margin_bottom(5)
        main_box.set_margin_start(5)
        main_box.set_margin_end(5)
        self.set_child(main_box)

        scrolled_window = Gtk.ScrolledWindow()
        scrolled_window.add_css_class("dictation-scrolled-window")
        scrolled_window.set_hexpand(True)
        scrolled_window.set_vexpand(True)
        scrolled_window.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        main_box.append(scrolled_window)

        self.transcript_view = Gtk.TextView()
        self.transcript_view.add_css_class("dictation-transcript-view")
        self.transcript_view.set_editable(False)
        self.transcript_view.set_cursor_visible(False)
        self.transcript_view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self.transcript_buffer = self.transcript_view.get_buffer()
        self.transcript_buffer.set_text("Start speaking...")
        scrolled_window.set_child(self.transcript_view)

        status_bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        status_bar.add_css_class("dictation-status-bar")
        main_box.append(status_bar)


        self.word_count_label = Gtk.Label(label="Words: 0 / 250")
        self.word_count_label.add_css_class("dictation-word-count-label")
        self.word_count_label.set_halign(Gtk.Align.START)
        status_bar.append(self.word_count_label)


        spacer = Gtk.Box()
        spacer.add_css_class("dictation-spacer")
        spacer.set_hexpand(True)
        status_bar.append(spacer)


        self.copy_button = Gtk.Button(icon_name="edit-copy-symbolic")
        self.copy_button.add_css_class("dictation-copy-button")
        self.copy_button.set_tooltip_text("Copy Transcript")

        status_bar.append(self.copy_button)
        self.copy_button.connect("clicked", self._on_copy_clicked)


    def _on_audio_data_received(self, audio_data: bytes):
        """Callback function for receiving audio data."""
        self.audio_buffer.extend(audio_data)

        while len(self.audio_buffer) >= self.chunk_size_bytes:
            chunk_to_process = self.audio_buffer[:self.chunk_size_bytes]
            self.audio_buffer = self.audio_buffer[self.chunk_size_bytes:]
            self._process_audio_chunk(bytes(chunk_to_process))

    def _process_audio_chunk(self, audio_chunk: bytes):
        """
        Submits an audio chunk to the thread pool for asynchronous transcription.
        """
        print(f"Submitting audio chunk of size: {len(audio_chunk)} for transcription.")
        self.thread_pool.submit(self._transcribe_chunk_task, audio_chunk)

    def _transcribe_chunk_task(self, audio_chunk: bytes):
        """
        Task executed in the thread pool to transcribe an audio chunk.
        Saves chunk to WAV, transcribes, cleans up, and schedules UI update.
        """
        temp_wav_path = None
        transcribed_text = None
        try:
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as temp_wav_file:
                temp_wav_path = temp_wav_file.name

            with wave.open(temp_wav_path, 'wb') as wf:
                wf.setnchannels(self.channels)
                wf.setsampwidth(self.bytes_per_sample)
                wf.setframerate(self.sample_rate)
                wf.writeframes(audio_chunk)


            model_to_use = self.settings.get_string("default-model")
            auto_detect = self.settings.get_boolean("auto-detect-language")
            lang_to_use = self.settings.get_string("target-language")
            enable_translation = self.settings.get_boolean("enable-translation")
            device_mode = self.settings.get_string("whisper-device-mode")

            model = None
            try:
                if device_mode == "cuda":
                    device = "cuda"
                    compute_type = "float16"
                elif device_mode == "cpu":
                    device = "cpu"
                    compute_type = "int8"
                else:  # 'auto'
                    device = "auto"
                    compute_type = "auto"
                print(f"BG Task: User preferred device mode: {device_mode}, Effective device for WhisperModel: {device}, Compute type: {compute_type}")

                model = WhisperModel(model_to_use, device=device, compute_type=compute_type)
            except Exception as model_load_err:
                print(f"BG Task: Failed to load faster-whisper model '{model_to_use}' with device '{device}' and compute_type '{compute_type}': {model_load_err}")
                return

            try:
                language_arg = None if auto_detect else lang_to_use
                task_arg = "translate" if enable_translation else "transcribe"
                print(f"BG Task: Transcribing chunk {temp_wav_path} (lang={language_arg}, task={task_arg})")

                segments_generator, info = model.transcribe(
                    temp_wav_path,
                    beam_size=5,
                    task=task_arg,
                    language=language_arg

                )

                chunk_text = ""
                for segment in segments_generator:
                    chunk_text += segment.text

                transcribed_text = chunk_text.strip()

            except Exception as transcribe_err:
                print(f"BG Task: faster-whisper transcribe failed for chunk {temp_wav_path}: {transcribe_err}")
                transcribed_text = None

            if transcribed_text:
                print(f"BG Task: Transcription successful: '{transcribed_text}'")
                GLib.idle_add(self._append_actual_text, transcribed_text + " ")
            else:
                print("BG Task: Transcription returned no text or failed for this chunk.")


        except Exception as e:
            print(f"BG Task: Unexpected error processing audio chunk: {e}")
        finally:
            if temp_wav_path and os.path.exists(temp_wav_path):
                try:
                    os.remove(temp_wav_path)
                except OSError as e:
                    print(f"BG Task: Error removing temporary WAV file {temp_wav_path}: {e}")


    def _append_actual_text(self, text_to_append: str):
        """Appends transcribed text to the transcript view and updates word count."""
        end_iter = self.transcript_buffer.get_end_iter()
        self.transcript_buffer.insert(end_iter, text_to_append)

        start_iter = self.transcript_buffer.get_start_iter()
        end_iter = self.transcript_buffer.get_end_iter()
        full_text = self.transcript_buffer.get_text(start_iter, end_iter, False)
        word_count = len(full_text.split())
        self.word_count_label.set_text(f"Words: {word_count} / 250")
        return False

    def _on_copy_clicked(self, button):
        """Handles the copy button click event."""
        clipboard = Gtk.Display.get_default().get_clipboard()
        buffer = self.transcript_buffer
        start_iter = buffer.get_start_iter()
        end_iter = buffer.get_end_iter()
        text_content = buffer.get_text(start_iter, end_iter, False)
        clipboard.set(text_content)
        print("Dictation text copied to clipboard.")

    def do_show(self):
        """Override show signal to start audio capture."""
        self.audio_buffer.clear()
        self.transcript_buffer.set_text("")
        self.word_count_label.set_text("Words: 0 / 250")

        print("DictationOverlay: Starting audio capture...")
        try:
            self.audio_capturer.start()
        except Exception as e:
            print(f"DictationOverlay: Error starting audio capture: {e}")
        super().do_show()
    def do_close(self):
        """Override close signal to stop audio capture and shut down thread pool."""
        print("DictationOverlay: Stopping audio capture and shutting down thread pool...")
        try:
            self.audio_capturer.stop()
        except Exception as e:
            print(f"DictationOverlay: Error stopping audio capture: {e}")

        self.thread_pool.shutdown(wait=False, cancel_futures=True)
        print("DictationOverlay: Thread pool shutdown initiated.")

        super().do_close()


================================================
File: gnomerecast/views/history_view.py
================================================
import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Adw, GLib, Gio
from gi.repository import GObject


import os
import json
import typing as t
from datetime import datetime
from pathlib import Path
import logging # Added

from ..models.transcript_item import TranscriptItem, SegmentItem

logger = logging.getLogger(__name__) # Added

TRANSCRIPT_DIR = Path(GLib.get_user_data_dir()) / "GnomeRecast" / "transcripts"

class HistoryView(Gtk.Box):
    """
    View to display and interact with saved transcription history.
    Loads transcript JSON files from a predefined directory.
    """
    __gtype_name__ = 'HistoryView'
    __gsignals__ = {
    'transcript-selected': (GObject.SignalFlags.RUN_FIRST, None, (object,))
    }

    def __init__(self, application: Adw.Application, on_transcript_selected: t.Callable[[TranscriptItem], None], **kwargs):
        """
        Initializes the HistoryView.

        Args:
            application: The main application instance (for accessing io_pool).
            on_transcript_selected: Callback function executed when a transcript
                                     is selected from the list.
            **kwargs: Additional keyword arguments for Gtk.Box.
        """
        super().__init__(**kwargs)
        self.app = application # Store the application instance
        self.add_css_class("history-view-box")
        self._on_transcript_selected_callback = on_transcript_selected

        TRANSCRIPT_DIR.mkdir(parents=True, exist_ok=True)

        scrolled_window = Gtk.ScrolledWindow()
        scrolled_window.set_hexpand(True)
        scrolled_window.set_vexpand(True)
        scrolled_window.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.append(scrolled_window)

        self.list_box = Gtk.ListBox()
        self.list_box.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.list_box.set_css_classes(["boxed-list"])
        self.list_box.connect("selected-rows-changed", self._on_row_selected)
        scrolled_window.set_child(self.list_box)

        self.refresh_list()

    def refresh_list(self):
        """
        Clears and repopulates the list box with transcript items
        found in the TRANSCRIPT_DIR.
        """
        while row := self.list_box.get_row_at_index(0):
            self.list_box.remove(row)

        # Show a temporary loading indicator or keep existing items until new ones are loaded
        # For simplicity, clear and then repopulate. A spinner could be added.
        loading_label = Gtk.Label(label="Loading history...")
        loading_label.set_vexpand(True)
        loading_label.set_halign(Gtk.Align.CENTER)
        loading_label.set_valign(Gtk.Align.CENTER)
        self.list_box.append(loading_label) # Temporarily add loading label

        # app = self.get_application() # This was the error source
        if not self.app or not hasattr(self.app, 'io_pool') or not self.app.io_pool:
            logger.error("HistoryView: I/O thread pool not available on application object (self.app). Loading synchronously.")
            self._load_and_populate_sync() # Fallback to synchronous loading
            if self.list_box.get_first_child() == loading_label: # Remove loading if it's still there
                 self.list_box.remove(loading_label)
            return

        self.app.io_pool.submit(self._background_load_transcripts, loading_label)

    def _background_load_transcripts(self, loading_label_widget: Gtk.Label):
        """Loads transcript items in a background thread."""
        loaded_items = []
        try:
            if TRANSCRIPT_DIR.exists():
                for entry in TRANSCRIPT_DIR.iterdir():
                    if entry.is_file() and entry.suffix == ".json":
                        try:
                            item = TranscriptItem.load_from_json(str(entry))
                            if item:
                                loaded_items.append(item)
                        except (FileNotFoundError, json.JSONDecodeError, ValueError) as e:
                            logger.error(f"Skipping malformed or unreadable transcript {entry.name}: {e}", exc_info=True)
                        except Exception as e:
                            logger.error(f"Unexpected error loading transcript {entry.name}: {e}", exc_info=True)
            
            loaded_items.sort(key=lambda x: x.timestamp, reverse=True)
            GLib.idle_add(self._populate_list_from_items, loaded_items, loading_label_widget)
        except Exception as e:
            logger.error(f"Error in background transcript loading thread: {e}", exc_info=True)
            GLib.idle_add(self._populate_list_from_items, [], loading_label_widget) # Populate with empty on error


    def _load_and_populate_sync(self):
        """Synchronous version of loading and populating for fallback."""
        items = []
        if TRANSCRIPT_DIR.exists():
            for entry in TRANSCRIPT_DIR.iterdir():
                if entry.is_file() and entry.suffix == ".json":
                    try:
                        item = TranscriptItem.load_from_json(str(entry))
                        if item:
                            items.append(item)
                    except (FileNotFoundError, json.JSONDecodeError, ValueError) as e:
                        logger.error(f"Skipping malformed or unreadable transcript {entry.name}: {e}", exc_info=True)
                    except Exception as e:
                        logger.error(f"Unexpected error loading transcript {entry.name}: {e}", exc_info=True)
        items.sort(key=lambda x: x.timestamp, reverse=True)
        self._populate_list_from_items(items, None)


    def _populate_list_from_items(self, items: t.List[TranscriptItem], loading_label_to_remove: t.Optional[Gtk.Widget]):
        """Populates the list_box with items. Called from GLib.idle_add."""
        if loading_label_to_remove and self.list_box.get_first_child() == loading_label_to_remove:
            self.list_box.remove(loading_label_to_remove)
        
        # Clear again just in case something was added between initial clear and this idle_add
        while row := self.list_box.get_row_at_index(0):
            self.list_box.remove(row)

        if not items:
            if not TRANSCRIPT_DIR.exists() or not any(f.is_file() and f.suffix == ".json" for f in TRANSCRIPT_DIR.iterdir() if f.exists()): # Re-check if dir is truly empty
                placeholder_label = Gtk.Label(label="No saved transcripts found.")
                placeholder_label.set_vexpand(True)
                placeholder_label.set_halign(Gtk.Align.CENTER)
                placeholder_label.set_valign(Gtk.Align.CENTER)
                self.list_box.append(placeholder_label)
                logger.info("Transcript directory is empty or does not exist after load attempt.")
            return

        for item in items:
            row = Gtk.ListBoxRow()

            setattr(row, "_transcript_item", item)

            gesture = Gtk.GestureClick.new()
            gesture.set_button(0)
            gesture.connect("released", self._on_row_clicked)
            row.add_controller(gesture)

            row_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
            row_box.set_margin_top(6)
            row_box.set_margin_bottom(6)
            row_box.set_margin_start(12)
            row_box.set_margin_end(12)

            filename_label = Gtk.Label(label=item.output_filename or "Untitled Transcript")
            filename_label.set_halign(Gtk.Align.START)
            filename_label.set_hexpand(True)

            try:
                dt_object = datetime.fromisoformat(item.timestamp)
                timestamp_str = dt_object.strftime("%Y-%m-%d %H:%M:%S")
            except (ValueError, TypeError):
                timestamp_str = item.timestamp

            timestamp_label = Gtk.Label(label=timestamp_str)
            timestamp_label.set_halign(Gtk.Align.END)
            timestamp_label.set_css_classes(["dim-label"])

            row_box.append(filename_label)
            row_box.append(timestamp_label)

            row.set_child(row_box)
            self.list_box.append(row)


    def _on_row_clicked(self, gesture: Gtk.GestureClick, n_press: int, x: float, y: float):
        """
        Handles clicks on a list box row. Triggers the transcript selection
        callback on a double-click (n_press == 2).
        """
        if n_press == 2:
            widget = gesture.get_widget()
            if isinstance(widget, Gtk.ListBoxRow):
                item = getattr(widget, "_transcript_item", None)
                if item and isinstance(item, TranscriptItem) and self._on_transcript_selected_callback:
                    print(f"History item double-clicked: {item.output_filename}")
                    # Allow opening even if segments are empty, TranscriptView will handle displaying it.
                    # if not item.segments:
                    #      print("Selected transcript has no segments, not calling callback.")
                    #      return
                    self._on_transcript_selected_callback(item)

    def _on_row_selected(self, listbox: Gtk.ListBox):
        row = listbox.get_selected_row()
        if not row:
            return
        item = getattr(row, "_transcript_item", None)
        if item and isinstance(item, TranscriptItem):
            self.emit("transcript-selected", item)


================================================
File: gnomerecast/views/initial_view.py
================================================
import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import GObject, Gtk, Adw, Pango

class InitialView(Gtk.Box):
    """
    A view displayed when no transcript is active, prompting the user
    to load a file or record audio. Also handles the record button state.
    """
    __gsignals__ = {
        'start-recording': (GObject.SignalFlags.RUN_FIRST, None, ()),
        'stop-recording': (GObject.SignalFlags.RUN_FIRST, None, ())
    }
    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        self.add_css_class("initial-view-box")
        self._is_recording = False

        self.set_orientation(Gtk.Orientation.VERTICAL)
        self.set_spacing(24)
        self.set_halign(Gtk.Align.CENTER)
        self.set_valign(Gtk.Align.CENTER)
        self.set_hexpand(True)
        self.set_vexpand(True)

        icon = Gtk.Image.new_from_icon_name("document-save-symbolic")
        icon.set_pixel_size(64)
        icon.set_halign(Gtk.Align.CENTER)
        icon.set_margin_bottom(24)
        self.append(icon)

        formats_label = Gtk.Label()
        formats_label.set_markup("<b>MP3   WAV   M4A   MP4</b>")
        formats_label.set_halign(Gtk.Align.CENTER)
        formats_label.set_margin_bottom(4)
        self.append(formats_label)

        drop_label = Gtk.Label()
        drop_label.set_markup("<span size='large'>Drop an audio file here to transcribe it.</span>")
        drop_label.set_halign(Gtk.Align.CENTER)
        self.append(drop_label)

        self.record_button = Gtk.Button()
        self.record_button.set_tooltip_text("Start recording from your default microphone")

        button_content = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        button_content.set_halign(Gtk.Align.CENTER)

        self.record_icon = Gtk.Image.new_from_icon_name("media-record-symbolic")
        button_content.append(self.record_icon)

        self.record_label = Gtk.Label.new("Record Microphone")
        button_content.append(self.record_label)

        self.record_button.set_child(button_content)
        self.record_button.add_css_class("recordit-action")
        self.record_button.add_css_class("pill")
        self.record_button.set_size_request(220, 42)
        self.record_button.set_margin_top(24)

        self.record_button.connect("clicked", self._on_record_button_clicked)

        self.append(self.record_button)

    def _on_record_button_clicked(self, button):
        """Handles the record button click event."""
        if not self._is_recording:
            self.emit("start-recording")
            self.record_label.set_text("Recording...")
            self.record_icon.set_from_icon_name("media-playback-stop-symbolic")
            self.record_button.set_tooltip_text("Stop recording")
            self._is_recording = True
        else:
            self.emit("stop-recording")
            self.record_label.set_text("Record Microphone")
            self.record_icon.set_from_icon_name("media-record-symbolic")
            self.record_button.set_tooltip_text("Start recording from your default microphone")
            self._is_recording = False

    def reset_button_state(self):
        """Resets the button to its initial state."""
        if self._is_recording:
            self.record_label.set_text("Record Microphone")
            self.record_icon.set_from_icon_name("media-record-symbolic")
            self.record_button.set_tooltip_text("Start recording from your default microphone")
            self._is_recording = False


================================================
File: gnomerecast/views/model_management_dialog.py
================================================
import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Adw, Gio, GObject, GLib
from typing import Optional, Dict
import functools
from ..ui.toast import ToastPresenter
import threading
import pathlib
import os

from faster_whisper import WhisperModel

from ..utils.models import (
    AVAILABLE_MODELS, # Changed: Use AVAILABLE_MODELS
    # get_available_models, # Removed
    # list_local_models, # Removed
    APP_MODEL_DIR, # Keep if used by _on_remove_clicked for path construction
)

class ModelItem(GObject.Object):
    """Simple GObject to hold model information for the ListStore."""
    __gtype_name__ = 'ModelItem'

    name = GObject.Property(type=str)
    size = GObject.Property(type=str)
    status = GObject.Property(type=str)
    download_url = GObject.Property(type=str)
    is_downloading = GObject.Property(type=bool, default=False)
    download_progress = GObject.Property(type=float, default=0.0)
    error_message = GObject.Property(type=str, default=None)
    signal_handlers = GObject.Property(type=object)
    cancel_event = GObject.Property(type=object)


    def __init__(self, name, size, status, download_url=None):
        super().__init__()
        self.name = name
        self.size = size
        self.status = status
        self.download_url = download_url
        self.signal_handlers = {}
        self.cancel_event = None
        self.is_downloading = False
        self.download_progress = 0.0
        self.error_message = None


class ModelManagementDialog(Gtk.Dialog):
    """Dialog for managing Whisper transcription models."""

    def __init__(self, parent, **kwargs):
        super().__init__(transient_for=parent, **kwargs)

        self.active_downloads: Dict[str, Dict] = {} # Store thread and cancel event if needed, or just model name

        self.set_title("Manage Transcription Models")
        self.set_modal(True)
        self.set_default_size(450, 350)
        self.add_button("_Close", Gtk.ResponseType.CLOSE)

        self.connect("close-request", self._on_close_request)

        content_area = self.get_content_area()

        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, margin_top=12, margin_bottom=12, margin_start=12, margin_end=12)
        content_area.append(main_box)

        scrolled_window = Gtk.ScrolledWindow()
        scrolled_window.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scrolled_window.set_vexpand(True)
        main_box.append(scrolled_window)

        self.model_store = Gio.ListStore(item_type=ModelItem)
        selection_model = Gtk.SingleSelection(model=self.model_store)
        self.model_list_view = Gtk.ListView(model=selection_model)
        self.model_list_view.set_show_separators(True)
        scrolled_window.set_child(self.model_list_view)

        factory = Gtk.SignalListItemFactory()
        factory.connect("setup", self._on_factory_setup)
        factory.connect("bind", self._on_factory_bind)
        factory.connect("unbind", self._on_factory_unbind)

        self.model_list_view.set_factory(factory)

        self._populate_model_list()

    def _populate_model_list(self):
        """Populates the list store with available models and checks their cache status."""
        print("ModelManagementDialog: Initiating model list population with new cache check logic...")
        self.model_store.remove_all()

        # Sort AVAILABLE_MODELS by name for consistent order
        # AVAILABLE_MODELS is now a direct import: Dict[str, str] where str is size
        sorted_model_names = sorted(AVAILABLE_MODELS.keys())

        for model_name in sorted_model_names:
            size = AVAILABLE_MODELS[model_name]
            # Create item with initial "Checking..." status
            item = ModelItem(
                name=model_name,
                size=size,
                status="Checking status...",
                download_url=None # download_url is not directly used for caching with faster-whisper by name
            )
            self.model_store.append(item)
            # Start a background thread to check the actual cache status
            threading.Thread(
                target=self._check_model_cache_status_worker,
                args=(item,), # Pass the ModelItem instance
                daemon=True
            ).start()
        print(f"ModelManagementDialog: Initialized {self.model_store.get_n_items()} models for status checking.")

    def _check_model_cache_status_worker(self, model_item: ModelItem):
        """
        Worker function to check if a model is cached using faster-whisper.
        Runs in a background thread. Updates the passed ModelItem.
        """
        is_cached = False
        error_message: Optional[str] = None
        model_name = model_item.name
        try:
            # Attempt to load the model with local_files_only=True
            _model = WhisperModel(model_name, device="cpu", compute_type="int8", local_files_only=True)
            is_cached = True
            del _model # Release resources
            print(f"Thread: Model '{model_name}' IS cached.")
        except RuntimeError as e:
            if "model is not found locally" in str(e).lower() or \
               "doesn't exist or is not a directory" in str(e).lower() or \
               "path does not exist or is not a directory" in str(e).lower() or \
               "no such file or directory" in str(e).lower() and ".cache/huggingface/hub" in str(e).lower():
                is_cached = False
                print(f"Thread: Model '{model_name}' is NOT cached (expected error: {e}).")
            else: # Other unexpected RuntimeError
                is_cached = False
                error_message = f"RuntimeError checking cache for {model_name}: {str(e)}"
                print(error_message)
        except Exception as e:
            is_cached = False
            error_message = f"Unexpected error checking cache for {model_name}: {type(e).__name__} - {str(e)}"
            print(error_message)

        GLib.idle_add(self._update_model_item_cache_status_from_worker, model_item, is_cached, error_message)

    def _update_model_item_cache_status_from_worker(self, model_item: ModelItem, is_cached: bool, error_message: Optional[str]):
        """
        Updates the ModelItem's status in the UI based on cache check.
        Called from the main GTK thread.
        """
        if model_item.is_downloading: # If it was marked as downloading, don't overwrite status yet
            print(f"Model '{model_item.name}' cache status check completed, but download is in progress. Status unchanged for now.")
            return GLib.SOURCE_REMOVE

        if error_message:
            model_item.status = "Error Checking Status"
            model_item.error_message = error_message
            print(f"UI Update: Model '{model_item.name}' status check error: {error_message}")
        else:
            model_item.status = "Downloaded" if is_cached else "Not Downloaded"
            model_item.error_message = None
            print(f"UI Update: Model '{model_item.name}' status: {model_item.status}")


        # Find the item in the store and trigger an update for its row
        position = Gtk.INVALID_LIST_POSITION
        # Iterate using range and get_item if direct find on model_item fails due to object identity issues
        # after thread. For now, assume model_item is the correct reference or has comparable properties.
        # A more robust way is to find by model_item.name if model_item itself isn't found.
        found, pos_val = self.model_store.find(model_item)
        if found:
            position = pos_val
        else: # Fallback to search by name if direct object find fails
            for i in range(self.model_store.get_n_items()):
                item_in_store = self.model_store.get_item(i)
                if item_in_store.name == model_item.name:
                    # Update the original item in the store directly if properties are GObject.Properties
                    item_in_store.status = model_item.status
                    item_in_store.error_message = model_item.error_message
                    position = i
                    break
        
        if position != Gtk.INVALID_LIST_POSITION:
            self.model_store.items_changed(position, 1, 1) # Notify ListView to rebind this item
        else:
            print(f"Warning: Could not find item {model_item.name} in store to update its cache status UI.")
        return GLib.SOURCE_REMOVE

    # Removed _on_local_models_loaded_management as it's no longer used.

    def _on_factory_setup(self, factory, list_item):
        """Setup the widget for a list item using Adw.ActionRow."""
        action_row = Adw.ActionRow()
        action_row.set_activatable(False)

        suffix_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6, valign=Gtk.Align.CENTER)

        size_label = Gtk.Label()
        progress_bar = Gtk.ProgressBar(visible=False, show_text=False, hexpand=True, width_request=100)
        download_button = Gtk.Button(icon_name="folder-download-symbolic", tooltip_text="Download Model")
        cancel_button = Gtk.Button(icon_name="edit-delete-symbolic", tooltip_text="Cancel Download", visible=False)
        remove_button = Gtk.Button(icon_name="user-trash-symbolic", tooltip_text="Remove Model")

        suffix_box.append(size_label)
        suffix_box.append(progress_bar)
        suffix_box.append(download_button)
        suffix_box.append(cancel_button)
        suffix_box.append(remove_button)

        action_row.add_suffix(suffix_box)

        list_item.widgets = {
            "action_row": action_row,
            "size_label": size_label,
            "progress_bar": progress_bar,
            "download_button": download_button,
            "cancel_button": cancel_button,
            "remove_button": remove_button,
        }

        list_item.set_child(action_row)


    def _on_factory_bind(self, factory, list_item):
        """Bind the data from the ModelItem to the list item's widgets."""
        model_item = list_item.get_item()
        setattr(list_item, '_bound_item', model_item)

        widgets = list_item.widgets
        action_row = widgets["action_row"]
        size_label = widgets["size_label"]
        progress_bar = widgets["progress_bar"]
        download_button = widgets["download_button"]
        cancel_button = widgets["cancel_button"]
        remove_button = widgets["remove_button"]

        action_row.set_title(model_item.name)
        size_label.set_label(f"({model_item.size})")

        is_downloaded = model_item.status == "Downloaded" or model_item.status == "Downloaded (Local Only)"
        is_downloading = model_item.is_downloading
        is_error = "Error" in model_item.status # More general error check
        # "Downloaded" status is now set by the cache check.
        # "Not Downloaded" means it's not cached.
        is_cached = model_item.status == "Downloaded"
        can_download = not is_cached and not is_downloading and model_item.status != "Checking status..."


        action_row.set_subtitle(model_item.error_message if model_item.error_message else model_item.status)
        action_row.set_sensitive(not is_downloading)

        size_label.set_visible(not is_downloading)
        progress_bar.set_visible(is_downloading)
        progress_bar.set_fraction(model_item.download_progress if is_downloading else 0)

        download_button.set_visible(can_download or is_error)
        download_button.set_sensitive(can_download or is_error)
        cancel_button.set_visible(is_downloading)
        cancel_button.set_sensitive(is_downloading)
        remove_button.set_visible(is_downloaded)
        remove_button.set_sensitive(is_downloaded)

        if "download" not in model_item.signal_handlers:
            dl_handler_id = download_button.connect("clicked", functools.partial(self._on_download_clicked, item=model_item))
            model_item.signal_handlers["download"] = (download_button, dl_handler_id)

        if "remove" not in model_item.signal_handlers:
            rm_handler_id = remove_button.connect("clicked", functools.partial(self._on_remove_clicked, item=model_item))
            model_item.signal_handlers["remove"] = (remove_button, rm_handler_id)

        if "cancel" not in model_item.signal_handlers:
            cancel_handler_id = cancel_button.connect("clicked", functools.partial(self._on_cancel_clicked, item=model_item))
            model_item.signal_handlers["cancel"] = (cancel_button, cancel_handler_id)


    def _on_factory_unbind(self, factory, list_item):
        """Disconnect signal handlers when the item is unbound."""
        model_item = getattr(list_item, '_bound_item', None)

        if model_item and hasattr(model_item, 'signal_handlers'):
            for key, handler_info in list(model_item.signal_handlers.items()):
                widget, handler_id = handler_info
                try:
                    if widget.is_connected(handler_id):
                         widget.disconnect(handler_id)
                except TypeError:
                    print(f"Warning: Could not disconnect signal for {key} on {model_item.name}, widget might be destroyed.")
                del model_item.signal_handlers[key]

        if hasattr(list_item, '_bound_item'):
            delattr(list_item, '_bound_item')


    def _on_download_clicked(self, button, item: ModelItem):
        """Handler for download/cache button click."""
        if item.is_downloading:
            print(f"Caching request ignored for {item.name} (already in progress)")
            return

        print(f"Starting caching for {item.name}")
        model_name = item.name

        item.is_downloading = True
        item.status = "Caching..." # Or "Preparing..."
        item.download_progress = 0.0 # Not really applicable, but reset
        item.error_message = None
        # item.cancel_event = threading.Event() # TODO: Re-evaluate if cancellation is needed/simple for this

        position = self.model_store.find(item)[1]
        if position != Gtk.INVALID_LIST_POSITION:
            self.model_store.items_changed(position, 1, 1)
        else:
            print(f"Warning: Could not find item {item.name} in store to update UI for caching start.")

        parent_window = self.get_transient_for()
        if parent_window:
            GLib.idle_add(ToastPresenter.show, self, f"Preparing model {item.name}...")

        self.active_downloads[model_name] = {} # Mark as active

        cache_thread = threading.Thread(
            target=self._cache_model_in_thread,
            args=(model_name,),
            daemon=True
        )
        cache_thread.start()

    def _cache_model_in_thread(self, model_item_name: str):
        """
        Attempts to instantiate the model, forcing faster-whisper to download/cache it.
        This runs in a background thread.
        """
        try:
            print(f"Thread: Caching model {model_item_name} using faster-whisper...")
            # This will download if not present and cache it according to faster-whisper's logic
            model = WhisperModel(model_size_or_path=model_item_name, device="cpu", compute_type="int8")
            # We don't need to keep the model object here, just ensure it was loaded.
            del model
            print(f"Thread: Successfully prepared/cached {model_item_name}.")
            GLib.idle_add(self._update_model_item_status, model_item_name, "Cached", None)
        except Exception as e:
            print(f"Thread: Error caching model {model_item_name}: {e}")
            GLib.idle_add(self._update_model_item_status, model_item_name, "Error Caching", str(e))


    def _update_model_item_status(self, model_name: str, new_status: str, error_message: Optional[str]):
        """
        Updates the ModelItem's status in the UI. Called via GLib.idle_add from the caching thread.
        """
        print(f"Updating UI for {model_name}: Status='{new_status}', Error='{error_message}'")
        item_to_update = None
        position = Gtk.INVALID_LIST_POSITION
        for i in range(self.model_store.get_n_items()):
            item = self.model_store.get_item(i)
            if item.name == model_name:
                item_to_update = item
                position = i
                break

        parent_window = self.get_transient_for()

        if item_to_update:
            item_to_update.is_downloading = False
            item_to_update.status = new_status
            item_to_update.error_message = error_message
            # item_to_update.cancel_event = None # Clear if it was used

            if position != Gtk.INVALID_LIST_POSITION:
                self.model_store.items_changed(position, 1, 1)
            else:
                print(f"Warning: Could not find position for updated item {model_name} after processing, but item was found.")
            
            # After a download attempt (which calls _cache_model_in_thread -> _update_model_item_status),
            # we need to re-verify the cache status using the specific local_files_only check.
            # Find the ModelItem again to pass to the checker.
            item_for_recheck = None
            for i in range(self.model_store.get_n_items()):
                item = self.model_store.get_item(i)
                if item.name == model_name:
                    item_for_recheck = item
                    break
            
            if item_for_recheck:
                print(f"Post-download/cache attempt, re-verifying cache status for {model_name}...")
                item_for_recheck.status = "Checking status..." # Temporarily set status
                if position != Gtk.INVALID_LIST_POSITION: self.model_store.items_changed(position,1,1)

                threading.Thread(
                    target=self._check_model_cache_status_worker,
                    args=(item_for_recheck,),
                    daemon=True
                ).start()
            else:
                print(f"Error: Could not find item {model_name} to re-verify cache status after download attempt.")


            if new_status == "Cached": # This status comes from the _cache_model_in_thread
                if parent_window:
                    GLib.idle_add(ToastPresenter.show, self, f"Model {model_name} is ready.")
            elif new_status == "Error Caching":
                if parent_window:
                    GLib.idle_add(ToastPresenter.show, self, f"❌ Failed to prepare model {model_name}: {error_message}")
        else:
            print(f"Error: Could not find ModelItem '{model_name}' in store to update status.")
            if parent_window:
                 GLib.idle_add(ToastPresenter.show, self, f"❌ Error updating status for an unknown model: {model_name}")


        if model_name in self.active_downloads:
            del self.active_downloads[model_name]
            print(f"Removed {model_name} from active operations.")
        # No _update_download_progress method to remove as it's being replaced by this logic.

    def _on_cancel_clicked(self, button, item: ModelItem):
        """Handler for cancel button click.
        NOTE: Cancellation for faster-whisper's internal download is not straightforward.
        This might need to be re-evaluated or simplified if true cancellation isn't feasible.
        For now, it primarily serves to update UI if a download was thought to be cancellable.
        """
        model_name = item.name
        print(f"Cancel requested for {model_name}")
        if model_name in self.active_downloads:
            # Currently, no direct cancel mechanism for WhisperModel instantiation.
            # We can mark it as "cancelling" in UI and then let it finish or error out.
            # Or, if we had a cancel_event on the item, we could set it,
            # but the _cache_model_in_thread doesn't check it.
            print(f"Note: True cancellation of faster-whisper caching is not implemented.")
            # Update UI to reflect attempt or remove from active_downloads
            # For now, let's just visually update and let the thread complete.
            item.status = "Cancelling..." # Or revert to "Not Downloaded"
            item.is_downloading = False # Or keep true until thread confirms
            # del self.active_downloads[model_name] # Or keep until thread finishes
            
            position = self.model_store.find(item)[1]
            if position != Gtk.INVALID_LIST_POSITION:
                self.model_store.items_changed(position, 1, 1)

            parent_window = self.get_transient_for()
            if parent_window:
                GLib.idle_add(ToastPresenter.show, self, f"Attempting to cancel operation for {model_name} (may complete).")

        # button.set_sensitive(False) # Already handled by is_downloading state in bind


    def _on_remove_clicked(self, button, item: ModelItem):
        """Handler for remove button click."""
        print(f"Remove clicked for {item.name}")
        expected_filename = f"ggml-{item.name}.bin"
        file_path = APP_MODEL_DIR / expected_filename

        if file_path.exists() and file_path.is_file():
            try:
                print(f"Attempting to delete {file_path}")
                file_path.unlink() # This part is for the old ggml file structure.
                                   # For faster-whisper, actual deletion is more complex as it's in a cache dir.
                                   # This might not effectively remove a faster-whisper cached model.
                                   # A true "remove" for faster-whisper would involve finding its cache path and deleting that.
                                   # For now, we'll assume this old logic is what's intended for "removal" if it's still here.
                print(f"Successfully deleted {file_path} (if it was a standalone ggml file).")
                # After attempting removal, re-check the status of this model item.
                # The model might still be cached by faster-whisper elsewhere.
                item.status = "Checking status..." # Mark for re-check
                pos_found, item_pos = self.model_store.find(item)
                if pos_found:
                    self.model_store.items_changed(item_pos, 1, 1)

                threading.Thread(
                    target=self._check_model_cache_status_worker,
                    args=(item,),
                    daemon=True
                ).start()

            except OSError as e:
                print(f"Error deleting model file {file_path}: {e}")
                error_dialog = Gtk.MessageDialog(
                    transient_for=self,
                    modal=True,
                    message_type=Gtk.MessageType.ERROR,
                    buttons=Gtk.ButtonsType.CLOSE,
                    text=f"Failed to remove model '{item.name}'",
                    secondary_text=str(e)
                )
                error_dialog.connect("response", lambda d, r: d.destroy())
                error_dialog.show()
        else:
            print(f"Model file not found for removal at old path: {file_path}. Status will be re-checked.")
            # Still re-check status, as it might be cached by faster-whisper independently.
            item.status = "Checking status..."
            pos_found, item_pos = self.model_store.find(item)
            if pos_found:
                self.model_store.items_changed(item_pos, 1, 1)
            threading.Thread(
                target=self._check_model_cache_status_worker,
                args=(item,),
                daemon=True
            ).start()

    def _on_close_request(self, dialog):
        """Handle dialog close: cancel any active downloads."""
        print("Close requested. Cancelling active downloads...")
        active_names = list(self.active_downloads.keys())
        if not active_names:
            print("No active downloads to cancel.")
            return False

        for model_name in active_names:
            if model_name in self.active_downloads:
                print(f"Signalling cancel for {model_name}")
                cancel_event = self.active_downloads[model_name].get("cancel_event")
                if cancel_event:
                    cancel_event.set()

        print("Cancellation signals sent.")
        return False


================================================
File: gnomerecast/views/podcast_episode_dialog.py
================================================
import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Adw, Gio, GLib, GObject

import threading
import feedparser
import logging
from datetime import datetime

log = logging.getLogger(__name__)

class EpisodeItem(GObject.Object):
    __gtype_name__ = 'EpisodeItem'

    title = GObject.Property(type=str)
    published_date = GObject.Property(type=str)
    audio_url = GObject.Property(type=str)
    description = GObject.Property(type=str)

    def __init__(self, title, published_date, audio_url, description):
        super().__init__()
        self._title = title
        self._published_date = published_date
        self._audio_url = audio_url
        self._description = description

    @GObject.Property(type=str)
    def title(self):
        return self._title

    @GObject.Property(type=str)
    def published_date(self):
        if self._published_date:
            try:
                dt = datetime(*self._published_date[:6])
                return dt.strftime("%Y-%m-%d")
            except Exception:
                return str(self._published_date)
        return "Unknown Date"

    @GObject.Property(type=str)
    def audio_url(self):
        return self._audio_url

    @GObject.Property(type=str)
    def description(self):
        desc = self._description or ""
        import re
        desc = re.sub('<[^<]+?>', '', desc)
        return desc


class PodcastEpisodeDialog(Gtk.Dialog):
    """Dialog to display podcast episodes from a feed URL and allow selection."""

    def __init__(self, feed_url, parent, **kwargs):
        super().__init__(transient_for=parent, modal=True, **kwargs)
        self.feed_url = feed_url
        self._episodes_data = []

        self.set_title("Select Podcast Episode")
        self.set_default_size(600, 400)
        self.set_resizable(True)

        self.add_button("Cancel", Gtk.ResponseType.CANCEL)
        self.transcribe_button = self.add_button("Transcribe Selected", Gtk.ResponseType.OK)
        self.transcribe_button.set_sensitive(False)

        content_area = self.get_content_area()
        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin_top=10, margin_bottom=10, margin_start=10, margin_end=10)
        content_area.append(main_box)

        self.status_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6, halign=Gtk.Align.CENTER)
        self.spinner = Gtk.Spinner(spinning=True)
        self.status_label = Gtk.Label(label="Fetching feed...")
        self.status_box.append(self.spinner)
        self.status_box.append(self.status_label)
        main_box.append(self.status_box)

        scrolled_window = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER,
                                              vscrollbar_policy=Gtk.PolicyType.AUTOMATIC,
                                              vexpand=True)
        main_box.append(scrolled_window)

        self.list_store = Gio.ListStore(item_type=EpisodeItem)
        self.selection_model = Gtk.SingleSelection(model=self.list_store)
        self.list_view = Gtk.ListView(model=self.selection_model)
        self.list_view.set_css_classes(["boxed-list"])

        factory = Gtk.SignalListItemFactory()
        factory.connect("setup", self._on_factory_setup)
        factory.connect("bind", self._on_factory_bind)

        self.list_view.set_factory(factory)
        scrolled_window.set_child(self.list_view)

        self.selection_model.connect("notify::selected-item", self._on_episode_selected)

        self.fetch_thread = threading.Thread(target=self._fetch_and_parse_feed, daemon=True)
        self.fetch_thread.start()

    def _on_factory_setup(self, factory, list_item):
        """Setup the list item widget."""
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3, margin_top=5, margin_bottom=5, margin_start=5, margin_end=5)
        title_label = Gtk.Label(halign=Gtk.Align.START, xalign=0)
        title_label.set_css_classes(["title-4"])
        date_label = Gtk.Label(halign=Gtk.Align.START, xalign=0)
        date_label.set_css_classes(["caption"])
        box.append(title_label)
        box.append(date_label)
        list_item.set_child(box)

    def _on_factory_bind(self, factory, list_item):
        """Bind data from the EpisodeItem to the list item widget."""
        box = list_item.get_child()
        labels = [widget for widget in self._get_all_children(box) if isinstance(widget, Gtk.Label)]
        episode_item = list_item.get_item()

        if len(labels) == 2 and episode_item:
            labels[0].set_text(episode_item.title or "No Title")
            labels[1].set_text(episode_item.published_date or "No Date")

    def _get_all_children(self, widget):
        """Recursively get all children of a widget."""
        children = []
        if hasattr(widget, 'get_first_child'):
            child = widget.get_first_child()
            while child:
                children.append(child)
                children.extend(self._get_all_children(child))
                child = child.get_next_sibling()
        return children

    def _fetch_and_parse_feed(self):
        """Fetches and parses the podcast feed in a background thread."""
        log.info(f"Fetching podcast feed: {self.feed_url}")
        try:
            headers = {'User-Agent': 'GnomeRecast/1.0'}
            feed_data = feedparser.parse(self.feed_url, agent=headers.get('User-Agent'))

            if feed_data.bozo:
                exception = feed_data.get("bozo_exception")
                if isinstance(exception, feedparser.NonXMLContentType):
                     raise ValueError(f"Feed is not XML: {exception}")
                elif isinstance(exception, feedparser.CharacterEncodingOverride):
                     log.warning(f"Character encoding override: {exception}")
                elif exception:
                     raise ValueError(f"Feed parsing error: {exception}")


            if feed_data.entries:
                episodes = []
                for entry in feed_data.entries:
                    title = entry.get("title", "Untitled Episode")
                    published = entry.get("published_parsed")
                    description = entry.get("summary", entry.get("description", ""))

                    audio_url = None
                    if "enclosures" in entry:
                        for enclosure in entry.enclosures:
                            if enclosure.get("type", "").startswith("audio/"):
                                audio_url = enclosure.get("href")
                                break

                    if audio_url:
                        episodes.append({
                            "title": title,
                            "published_date": published,
                            "audio_url": audio_url,
                            "description": description
                        })
                    else:
                        log.warning(f"Skipping episode '{title}' - no audio enclosure found.")

                log.info(f"Found {len(episodes)} episodes with audio.")
                if episodes:
                    GLib.idle_add(self._populate_episode_list, episodes)
                else:
                    GLib.idle_add(self._show_fetch_error, "No episodes with audio found in the feed.")

            else:
                log.warning("Feed parsed successfully, but no entries found.")
                GLib.idle_add(self._show_fetch_error, "No episodes found in the feed.")

        except Exception as e:
            log.error(f"Failed to fetch or parse feed {self.feed_url}: {e}", exc_info=True)
            GLib.idle_add(self._show_fetch_error, f"Error fetching feed: {e}")

    def _populate_episode_list(self, episodes_data):
        """Populates the list store with episode data on the main thread."""
        log.debug("Populating episode list UI.")
        self.status_box.set_visible(False)
        self.list_store.remove_all()
        self._episodes_data = episodes_data

        for data in episodes_data:
            item = EpisodeItem(
                title=data["title"],
                published_date=data["published_date"],
                audio_url=data["audio_url"],
                description=data["description"]
            )
            self.list_store.append(item)
        log.debug(f"Added {self.list_store.get_n_items()} items to the list store.")
        return GLib.SOURCE_REMOVE

    def _show_fetch_error(self, error_message):
        """Displays an error message on the main thread."""
        log.debug(f"Showing fetch error: {error_message}")
        self.spinner.stop()
        self.spinner.set_visible(False)
        self.status_label.set_text(f"Error: {error_message}")
        self.status_label.set_tooltip_text(error_message)
        return GLib.SOURCE_REMOVE

    def _on_episode_selected(self, selection_model, _param):
        """Enables the 'Transcribe Selected' button when an episode is selected."""
        selected_item = selection_model.get_selected_item()
        self.transcribe_button.set_sensitive(selected_item is not None)
        log.debug(f"Episode selected: {selected_item.title if selected_item else 'None'}")

    def get_selected_episode_data(self):
        """Returns the data of the selected episode."""
        selected_pos = self.selection_model.get_selected()
        if selected_pos != Gtk.INVALID_LIST_POSITION:
            item = self.list_store.get_item(selected_pos)
            if item:
                log.debug(f"Retrieving data for selected episode: {item.title}")
                return {
                    "title": item.title,
                    "audio_url": item.audio_url,
                    "published_date": item.published_date,
                    "description": item.description
                }
        log.debug("No episode selected or item not found.")
        return None


================================================
File: gnomerecast/views/podcast_url_dialog.py
================================================
import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gtk, Gio, GLib


class PodcastUrlDialog(Gtk.Dialog):
    """A dialog to prompt the user for a podcast feed URL."""

    def __init__(self, parent: Gtk.Window):
        super().__init__(
            transient_for=parent,
            modal=True,
            title="Transcribe Podcast Feed",
        )

        self.set_default_size(400, -1)

        content_area = self.get_content_area()
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, margin_top=12, margin_bottom=12, margin_start=12, margin_end=12)
        content_area.append(box)

        preferences_group = Adw.PreferencesGroup()
        box.append(preferences_group)

        self._url_entry_row = Adw.EntryRow(title="Feed URL")
        preferences_group.add(self._url_entry_row)

        self.add_button("_Cancel", Gtk.ResponseType.CANCEL)
        fetch_button = self.add_button("_Fetch Feed", Gtk.ResponseType.OK)
        fetch_button.get_style_context().add_class("suggested-action")
        fetch_button.set_sensitive(False)

        self._url_entry_row.get_delegate().connect("notify::text", self._on_entry_text_changed)


    def _on_entry_text_changed(self, entry: Gtk.Entry, _param):
        """Enable/disable the Fetch button based on entry content."""
        text = entry.get_text().strip()
        self.get_widget_for_response(Gtk.ResponseType.OK).set_sensitive(bool(text))

    def get_url(self) -> str:
        """Return the entered URL."""
        return self._url_entry_row.get_text().strip()


================================================
File: gnomerecast/views/preferences_window.py
================================================
import gi
import os
from gi.repository import Gtk, Adw, Gio, Pango, GObject, GLib, Gdk

import threading
from typing import Optional # Added for type hinting
# Updated import for AudioCapturer, removed old list_audio_input_devices
from ..audio.capture import AudioCapturer
from ..audio.device_utils import get_input_devices, AudioInputDevice # New import
from ..utils.models import AVAILABLE_MODELS # Changed: Import AVAILABLE_MODELS
from faster_whisper import WhisperModel # Added for model caching
from ..ui.toast import ToastPresenter

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
        self.test_capturer: Optional[AudioCapturer] = None
        self.test_audio_level = 0.0
        self.level_update_timer_id = None

        self.connect("destroy", self._on_destroy)

        self.available_models = AVAILABLE_MODELS # Changed: Use imported AVAILABLE_MODELS
        self.local_model_names = set() # Initialize as empty
        self.pref_active_download = None
        # Removed: list_local_models(self._on_local_models_loaded_preferences)
        # Model status will be checked by _initiate_model_status_checks() called later in __init__

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
        # Use the actual keys from available_models for the dropdown
        # self.available_models is populated in __init__
        model_names_for_dropdown = sorted(list(self.available_models.keys()))
        model_list_model = Gtk.StringList.new(model_names_for_dropdown)
        self.model_row.set_model(model_list_model)
        transcription_group.add(self.model_row)
        self._bind_combo_row_string_setting(
            self.model_row, "default-model" # This gsetting stores the selected model name key
        )

        device_row = Adw.ComboRow()
        device_row.set_title("Transcription Device")
        device_values = list(PreferencesWindow.DEVICE_DISPLAY_TO_VALUE.keys()) # "Auto", "CPU", "CUDA"
        device_list_model = Gtk.StringList.new(device_values)
        device_row.set_model(device_list_model)
        transcription_group.add(device_row)
        self._bind_device_combo_row(device_row, "whisper-device-mode")

        compute_type_row = Adw.ComboRow()
        compute_type_row.set_title("Compute Type")
        compute_types = ["auto", "int8", "float16", "float32"]
        compute_type_model = Gtk.StringList.new(compute_types)
        compute_type_row.set_model(compute_type_model)
        transcription_group.add(compute_type_row)
        self._bind_combo_row_string_setting(compute_type_row, "whisper-compute-type")


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

        self._initiate_model_status_checks() # New: Start checking model statuses

    def _initiate_model_status_checks(self):
        """
        Starts background checks for the cache status of each available model.
        This should be called after the model_row UI is set up.
        """
        for model_name in self.available_models.keys(): # self.available_models is already set
            threading.Thread(
                target=self._check_model_cache_status_thread_worker,
                args=(model_name,),
                daemon=True
            ).start()

    def _check_model_cache_status_thread_worker(self, model_name: str):
        """
        Worker function to check if a model is cached using faster-whisper.
        Runs in a background thread.
        """
        is_cached = False
        error_message: Optional[str] = None
        try:
            # Attempt to load the model with local_files_only=True
            _model = WhisperModel(model_name, device="cpu", compute_type="int8", local_files_only=True)
            is_cached = True
            del _model # Release resources
        except RuntimeError as e: # faster-whisper often raises RuntimeError for missing models with local_files_only
            # Check for specific messages indicating the model is not found locally
            if "model is not found locally" in str(e).lower() or \
               "doesn't exist or is not a directory" in str(e).lower() or \
               "path does not exist or is not a directory" in str(e).lower() or \
               "no such file or directory" in str(e).lower() and ".cache/huggingface/hub" in str(e).lower(): # More specific for HF cache
                is_cached = False
                # This is an expected "error" when the model is not cached, so no error_message for console.
            else: # Other unexpected RuntimeError
                is_cached = False
                error_message = f"RuntimeError checking cache for {model_name}: {str(e)}"
                print(error_message) # Log unexpected errors
        except Exception as e:
            is_cached = False
            error_message = f"Unexpected error checking cache for {model_name}: {type(e).__name__} - {str(e)}"
            print(error_message) # Log unexpected errors

        GLib.idle_add(self._update_model_status_ui, model_name, is_cached, error_message)

    def _update_model_status_ui(self, model_name: str, is_cached: bool, error: Optional[str]):
        """
        Updates the UI and internal state based on the model's cache status.
        Called from the main GTK thread via GLib.idle_add.
        """
        if error:
            # Log to console, a toast might be too noisy for "not found" during initial scan.
            # print(f"PreferencesWindow: Info checking cache for {model_name}: {error}")
            pass # Error already printed in worker for unexpected ones.

        if is_cached:
            self.local_model_names.add(model_name)
        else:
            if model_name in self.local_model_names:
                self.local_model_names.remove(model_name)

        # If the currently selected model in the dropdown is the one we just checked,
        # refresh its UI elements (like the download button).
        selected_idx = self.model_row.get_selected()
        model_in_combo = self.model_row.get_model()
        if isinstance(model_in_combo, Gtk.StringList) and selected_idx != Gtk.INVALID_LIST_POSITION:
            current_selected_model_name = model_in_combo.get_string(selected_idx)
            if current_selected_model_name == model_name:
                self._on_selected_model_changed(self.model_row, None) # Trigger UI update for current selection

        return GLib.SOURCE_REMOVE # One-shot callback

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
        
        # Model download logic is now triggered by user action, not on destroy.
        # The old logic here is removed.
        
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
                    # self.local_model_names is now updated by _update_model_status_ui
                    # as background checks complete.
                    is_available = model_name in self.available_models # self.available_models is from AVAILABLE_MODELS
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
                    # self.local_model_names will be updated by _update_pref_download_ui or _on_selected_model_changed
                    is_local = model_name in self.local_model_names
                    if is_available and not is_local:
                        self._start_model_download(model_name)


    def _cache_model_thread_worker(self, model_name_to_cache: str):
        """
        Worker function for the background thread to cache the model using faster-whisper.
        """
        # Ensure WhisperModel is imported in the thread if not globally accessible in this context
        # from faster_whisper import WhisperModel # Already imported at the top of the file
        try:
            # This will download and cache the model if not already present in faster-whisper's cache
            # Using basic device/compute_type as the goal is just caching.
            _model = WhisperModel(model_size_or_path=model_name_to_cache, device="cpu", compute_type="int8")
            # Optionally, you might want to del _model here if memory is a concern immediately after caching
            # del _model
            GLib.idle_add(self._update_pref_download_ui, model_name_to_cache, True, None)
        except Exception as e:
            GLib.idle_add(self._update_pref_download_ui, model_name_to_cache, False, str(e))


    def _start_model_download(self, model_name: str):
        if self.pref_active_download is not None:
            # Already a download in progress, or this is a stale call.
            # Potentially log or show a toast if trying to start another.
            return

        parent_window = self.get_native()
        if parent_window:
            GLib.idle_add(ToastPresenter.show, self, f"Preparing model {model_name}...")

        self.model_row.set_sensitive(False)
        self.download_model_button.set_visible(False)
        self.download_spinner.set_visible(True)
        self.download_spinner.start()
        
        self.pref_active_download = {'name': model_name} # Removed 'cancel_event'

        threading.Thread(
            target=self._cache_model_thread_worker,
            args=(model_name,), # Pass model_name directly
            daemon=True
        ).start()

    # _update_pref_download_progress method is removed as per instructions.

    def _update_pref_download_ui(self, model_name: str, success: bool, error_message: Optional[str]):
        """
        Callback executed in the main GTK thread after model caching attempt.
        Handles UI updates based on success or failure.
        """
        # It's possible this callback fires after the window is closed or download was "cancelled"
        # by user navigating away or selecting another model.
        # Check if the download it refers to is still the active one.
        if not self.pref_active_download or self.pref_active_download['name'] != model_name:
            # If a new download started for a different model, or no download is active,
            # this callback is stale. Stop spinner if it's for this model, but don't reset UI globally.
            if self.download_spinner.is_spinning() and (not self.pref_active_download or self.pref_active_download.get('name') == model_name):
                 self.download_spinner.stop()
                 self.download_spinner.set_visible(False)
            return GLib.SOURCE_REMOVE # Stale or irrelevant callback

        self.download_spinner.stop()
        self.download_spinner.set_visible(False)
        self.model_row.set_sensitive(True)

        # Re-check the cache status for the model that was attempted to be downloaded/cached.
        # This will update self.local_model_names and the UI via _update_model_status_ui.
        threading.Thread(
            target=self._check_model_cache_status_thread_worker,
            args=(model_name,), # model_name is the one from the download attempt
            daemon=True
        ).start()
        
        self.pref_active_download = None # Reset active download state

        parent_window = self.get_native()
        if parent_window:
            if success:
                GLib.idle_add(ToastPresenter.show, self, f"Model {model_name} is ready.")
            else:
                error_msg_display = error_message if error_message else "Unknown error"
                GLib.idle_add(ToastPresenter.show, self, f"❌ Failed to prepare model {model_name}: {error_msg_display}")
        
        return GLib.SOURCE_REMOVE # Callback is one-shot and has completed its work

    # Removed _on_local_models_loaded_preferences as it's no longer needed.
    # Model status is now checked individually by _check_model_cache_status_thread_worker
    # and UI updated by _update_model_status_ui.

    # Removed _on_local_models_loaded_after_download for the same reasons.



================================================
File: gnomerecast/views/progress_dialog.py
================================================
import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Gtk, Adw, Gio, GLib
import typing
from typing import Optional
import threading
import wave
import tempfile
import os

if typing.TYPE_CHECKING:
    from ..window import GnomeRecastWindow
    from ..audio.capture import AudioCapturer, AudioBuffer

class ProgressDialog(Gtk.Dialog):
    """
    A modal dialog to indicate transcription progress and allow cancellation.
    """
    def __init__(self, transient_for: 'GnomeRecastWindow', transcriber, show_stop_button=False, **kwargs):
        super().__init__(transient_for=transient_for, **kwargs)

        self.capturer: typing.Optional['AudioCapturer'] = None
        self.audio_buffer: typing.Optional['AudioBuffer'] = None
        self.is_monitor_recording = show_stop_button
        self._temp_wav_path: typing.Optional[str] = None

        self.transcriber = transcriber
        self._transcriber_cancellation_token: Optional[object] = None
        self._download_cancel_event: Optional[threading.Event] = None

        if self.is_monitor_recording:
            self.set_title("Recording App Audio…")
            initial_label = "Recording system audio output..."
        else:
            self.set_title("Transcribing…")
            initial_label = "Preparing..."

        self.set_modal(True)
        self.set_deletable(False)

        content_area = self.get_content_area()
        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, margin_top=12, margin_bottom=12, margin_start=12, margin_end=12)
        content_area.append(main_box)

        self.spinner = Gtk.Spinner(spinning=True, halign=Gtk.Align.CENTER)
        main_box.append(self.spinner)

        self.label = Gtk.Label(label=initial_label, halign=Gtk.Align.CENTER, hexpand=True)
        main_box.append(self.label)

        button_label = "Stop Recording" if self.is_monitor_recording else "Cancel"
        self.add_button(button_label, Gtk.ResponseType.CANCEL)
        self.connect("response", self._on_response)

    def set_transcriber_cancellation_token(self, token):
        """Stores the cancellation token provided by the Transcriber."""
        self._transcriber_cancellation_token = token

    def set_download_cancel_event(self, event: threading.Event):
        """Stores the threading.Event used to signal download cancellation."""
        self._download_cancel_event = event

    def set_capturer(self, capturer: 'AudioCapturer', audio_buffer: 'AudioBuffer'):
        """Stores the AudioCapturer instance and buffer."""
        self.capturer = capturer
        self.audio_buffer = audio_buffer

    def update_transcription_progress(self, filename, percentage):
        """Updates the progress label specifically for transcription."""
        if self.get_visible():
            self.label.set_text(f"Processing: {filename} ({percentage:.0f}%)")

    def update_progress(self, title: Optional[str] = None, percentage: Optional[float] = None, text: Optional[str] = None):
        """
        Updates the dialog's title, progress bar fraction, and label text.
        Use negative percentage for indeterminate (-1) or special states (-2 cancelled).
        """
        if not self.get_visible():
            return

        if title:
            self.set_title(title)

        if percentage is not None:
            if percentage < 0:
                pass
            else:
                 pass

        if text:
            self.label.set_text(text)

    def set_progress_text(self, text: str):
         """Sets the text of the progress label."""
         if self.get_visible():
              self.label.set_text(text)


    def on_completion(self, status, transcript_items=None):
        """
        Handles the completion signal from the Transcriber.

        Args:
            status (str): The final status ('completed', 'cancelled', 'error', 'no_files').
            transcript_items (list | None): A list of TranscriptItem objects if completed, else None or [].
        """
        print(f"\nTranscription finished with status: {status}")

        if status == 'completed' and transcript_items:
            print("--- Transcription Results ---")
            if transcript_items:
                for item in transcript_items:
                    text_preview = (item.transcript_text[:100] + '...') if len(item.transcript_text) > 100 else item.transcript_text
                    print(f"- Source: {item.source_path}\n"
                          f"  UUID: {item.uuid}\n"
                          f"  Timestamp: {item.timestamp}\n"
                          f"  Output: {item.output_filename}\n"
                          f"  Text: {text_preview}\n"
                          f"  Segments: {len(item.segments) if item.segments else 0}")
            else:
                print("  (No transcripts generated)")
            print("-----------------------------")

            main_window = self.get_transient_for()
            if main_window and hasattr(main_window, 'show_transcript_view') and transcript_items:
                print("Requesting main window to switch to transcript view...")
                GLib.idle_add(main_window.show_transcript_view, None, transcript_items[0])
            elif not main_window:
                 print("Could not get transient_for window to switch view.")
            elif not hasattr(main_window, 'show_transcript_view'):
                 print(f"Transient window does not have show_transcript_view method.")

        elif status == 'error':
            print("  An error occurred during transcription. Check logs above.")
            main_window = self.get_transient_for()
            if main_window and hasattr(main_window, 'show_initial_view'):
                print("Requesting main window to switch back to initial view (error)...")
                GLib.idle_add(main_window.show_initial_view)
        elif status == 'cancelled':
            print("  Transcription was cancelled by the user.")
            main_window = self.get_transient_for()
            if main_window and hasattr(main_window, 'show_initial_view'):
                print("Requesting main window to switch back to initial view (cancelled)...")
                GLib.idle_add(main_window.show_initial_view)
        elif status == 'no_files':
             print("  No files were provided for transcription.")
             main_window = self.get_transient_for()
             if main_window and hasattr(main_window, 'show_initial_view'):
                 print("Requesting main window to switch back to initial view (no files)...")
                 GLib.idle_add(main_window.show_initial_view)


        if self._temp_wav_path and os.path.exists(self._temp_wav_path):
            try:
                os.remove(self._temp_wav_path)
                print(f"Cleaned up temporary file: {self._temp_wav_path}")
                self._temp_wav_path = None
            except OSError as e:
                print(f"Error removing temporary file {self._temp_wav_path}: {e}")

        if not self.is_visible():
             print("Progress dialog already closed.")
             return
        print("Closing progress dialog.")
        self.close()

    def _on_response(self, dialog, response_id):
        """Handles dialog response signals."""
        if response_id == Gtk.ResponseType.CANCEL:
            cancel_button = self.get_widget_for_response(Gtk.ResponseType.CANCEL)

            if hasattr(self, '_download_cancel_event') and self._download_cancel_event:
                print("Cancel button clicked (Download Phase). Setting event.")
                self._download_cancel_event.set()
                if cancel_button:
                    cancel_button.set_sensitive(False)
                    cancel_button.set_label("Cancelling...")

            elif self.is_monitor_recording:
                print("Stop Recording button clicked.")
                if cancel_button:
                    cancel_button.set_sensitive(False)
                    cancel_button.set_label("Stopping...")
                self._stop_monitor_recording_flow()

            else:
                print("Cancel button clicked (Transcription Phase).")
                if self.transcriber and self._transcriber_cancellation_token:
                    print("Attempting to cancel transcription...")
                    if cancel_button:
                        cancel_button.set_sensitive(False)
                        cancel_button.set_label("Cancelling...")
                    self.transcriber.cancel_transcription(self._transcriber_cancellation_token)
                else:
                    print("Transcriber or cancellation token not set. Closing dialog.")
                    self.close()

    def _stop_monitor_recording_flow(self):
        """Stops monitor recording, saves audio, and starts transcription."""
        print("Stopping monitor recording flow...")

        if self.capturer:
            print("Stopping AudioCapturer...")
            self.capturer.stop()
        else:
            print("Error: AudioCapturer instance not found.")
            self.on_completion("error")
            return

        if not self.audio_buffer or not self.audio_buffer.get_data():
            print("Error: Audio buffer is empty or not found.")
            self.on_completion("error")
            return

        stop_button = self.get_widget_for_response(Gtk.ResponseType.CANCEL)
        if stop_button:
            stop_button.set_sensitive(False)
            stop_button.set_label("Processing...")
        self.label.set_text("Saving recorded audio...")
        self.spinner.start()

        try:
            print("Saving audio buffer to temporary WAV file...")
            rate = self.audio_buffer.get_rate()
            channels = self.audio_buffer.get_channels()
            width = self.audio_buffer.get_width()
            data = self.audio_buffer.get_data()

            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as temp_f:
                self._temp_wav_path = temp_f.name
                print(f"Temporary WAV file path: {self._temp_wav_path}")

                with wave.open(temp_f, 'wb') as wf:
                    wf.setnchannels(channels)
                    wf.setsampwidth(width)
                    wf.setframerate(rate)
                    wf.writeframes(data)
            print("Temporary WAV file saved successfully.")

        except Exception as e:
            print(f"Error saving temporary WAV file: {e}")
            self.on_completion("error")
            return

        if self._temp_wav_path:
            self.label.set_text("Processing recorded audio...")
            print(f"Starting transcription for {self._temp_wav_path}...")

            def cleanup_temp_file():
                if self._temp_wav_path and os.path.exists(self._temp_wav_path):
                    try:
                        os.remove(self._temp_wav_path)
                        print(f"Transcriber callback cleaned up temp file: {self._temp_wav_path}")
                        self._temp_wav_path = None
                    except OSError as e:
                        print(f"Error in transcriber cleanup removing temp file {self._temp_wav_path}: {e}")
                else:
                    print("Transcriber cleanup: Temp file already removed or path not set.")


            new_token = self.transcriber.start_transcription(
                [self._temp_wav_path],
                progress_callback=self.update_transcription_progress,
                completion_callback=self.on_completion,
                cleanup_callback=cleanup_temp_file
            )
            self.set_transcriber_cancellation_token(new_token)

            if stop_button:
                 stop_button.set_sensitive(True)
                 stop_button.set_label("Cancel")
            self.is_monitor_recording = False

        else:
            print("Error: Temporary WAV path not set after saving.")
            self.on_completion("error")


================================================
File: gnomerecast/views/segments_view.py
================================================
import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Gio, GObject, Adw, Gst
from ..models.transcript_item import SegmentItem
import math

def format_timestamp(seconds: float) -> str:
    """Formats seconds into HH:MM:SS string."""
    if not isinstance(seconds, (int, float)) or seconds < 0:
        return "00:00:00"
    hours = math.floor(seconds / 3600)
    minutes = math.floor((seconds % 3600) / 60)
    secs = math.floor(seconds % 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"

class SegmentsView(Gtk.ScrolledWindow):
    """
    A view to display transcript segments in a list.
    """
    __gtype_name__ = 'SegmentsView'


    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.add_css_class("segments-view-scrolled-window")

        self.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.set_vexpand(True)
        self.set_halign(Gtk.Align.FILL)
        self.set_valign(Gtk.Align.FILL)

        self._model = Gio.ListStore(item_type=SegmentItem)

        factory = Gtk.SignalListItemFactory()
        factory.connect("setup", self._on_factory_setup)
        factory.connect("bind", self._on_factory_bind)

        selection_model = Gtk.SingleSelection(model=self._model)

        self._list_view = Gtk.ListView(model=selection_model, factory=factory)
        self._list_view.add_css_class("segments-list-view")
        self._list_view.set_css_classes(["boxed-list"])
        self._list_view.connect("activate", self._on_list_activate)

        self.set_child(self._list_view)

    def _on_factory_setup(self, factory, list_item):
        """Setup the widget structure for a list item."""
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        box.add_css_class("segment-row-box")
        box.set_margin_top(6)
        box.set_margin_bottom(6)
        box.set_margin_start(12)
        box.set_margin_end(12)

        timestamp_label = Gtk.Label(halign=Gtk.Align.START, hexpand=False)
        timestamp_label.add_css_class("segment-timestamp-label")
        timestamp_label.set_width_chars(18)

        speaker_label = Gtk.Label(halign=Gtk.Align.START, hexpand=False)
        speaker_label.add_css_class("segment-speaker-label")
        speaker_label.set_valign(Gtk.Align.CENTER)
        speaker_label.add_css_class("pill")

        text_label = Gtk.Label(halign=Gtk.Align.START, hexpand=True, wrap=True, xalign=0)
        text_label.add_css_class("segment-text-label")

        box.append(timestamp_label)
        box.append(speaker_label)
        box.append(text_label)

        list_item.set_child(box)

    def _on_factory_bind(self, factory, list_item):
        """Bind data from a SegmentItem to the list item's widgets."""
        box = list_item.get_child()
        item = list_item.get_item()

        if not isinstance(box, Gtk.Box) or not isinstance(item, SegmentItem):
            return

        timestamp_label = box.get_first_child()
        speaker_label = timestamp_label.get_next_sibling()
        text_label = speaker_label.get_next_sibling()

        if isinstance(timestamp_label, Gtk.Label):
            start_str = format_timestamp(item.start)
            end_str = format_timestamp(item.end)
            timestamp_label.set_text(f"{start_str} - {end_str}")

        if isinstance(speaker_label, Gtk.Label):
            if item.speaker:
                speaker_label.set_text(f"Speaker: {item.speaker}")
                speaker_label.set_visible(True)
            else:
                speaker_label.set_text("")
                speaker_label.set_visible(False)

        if isinstance(text_label, Gtk.Label):
            text_label.set_text(item.text)


    def load_segments(self, segments_data: list | None):
        """
        Clears the current list and loads new segments.

        Args:
            segments_data: A list of dictionaries, where each dict
                           represents a segment (must have 'start', 'end', 'text').
                           Can be None or empty.
        """
        self._model.remove_all()

        if not segments_data or not isinstance(segments_data, list):
            print("SegmentsView: No valid segment data provided.")
            return

        print(f"SegmentsView: Loading {len(segments_data)} segments.")
        for segment_item in segments_data:
            if isinstance(segment_item, SegmentItem):
                self._model.append(segment_item)
            else:
                print(f"SegmentsView: Skipping invalid item in segments_data: {type(segment_item)}")

    def _on_list_activate(self, list_view, position):
        """Handle activation (e.g., double-click) of a list item."""
        selection_model = list_view.get_model()
        if not selection_model:
            return

        item = selection_model.get_item(position)

        if isinstance(item, SegmentItem):
            start_time_ns = int(item.start * Gst.SECOND)
            print(f"SegmentsView: Emitting segment-activated for {item.start}s ({start_time_ns}ns)")
            self.emit("segment-activated", start_time_ns)

GObject.signal_new(
    "segment-activated",
    SegmentsView,
    GObject.SignalFlags.RUN_FIRST,
    None,
    (GObject.TYPE_UINT64,)
)


================================================
File: gnomerecast/views/transcript_view.py
================================================
import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Adw, Gdk, GLib, Pango, GObject

import logging
from typing import Dict, Any, Optional # Added Optional
from ..models.transcript_item import TranscriptItem # Added

log = logging.getLogger(__name__)

class TranscriptionView(Gtk.Box):
    """
    Live transcription view displaying progress, segments, and controls.
    Uses composition to include an Adw.ToolbarView.
    Activated immediately after transcription starts.
    """
    __gtype_name__ = 'TranscriptionView'

    __gsignals__ = {
        'stop-transcription': (GObject.SignalFlags.RUN_FIRST, None, ()),
        'segment-removed': (GObject.SignalFlags.RUN_FIRST, None, (int,)),
    }

    def __init__(self, **kwargs):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, **kwargs)
        self.set_vexpand(True)
        self.add_css_class("transcript-view-box")

        self.toolbar_view = Adw.ToolbarView()
        self.toolbar_view.set_vexpand(True)
        self.append(self.toolbar_view)

        self._segments_data = [] # Holds dicts for UI display
        self.current_item: Optional[TranscriptItem] = None # Holds the loaded TranscriptItem, if any

        self._build_ui()

    def _format_timestamp(self, ms: int) -> str:
        """Formats milliseconds into mm:ss,SSS"""
        minutes = ms // 60000
        seconds = (ms % 60000) // 1000
        milliseconds = ms % 1000
        return f"{minutes}:{seconds:02d},{milliseconds:03d}"

    def _build_ui(self):
        header_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        header_box.set_margin_top(6)
        header_box.set_margin_bottom(6)
        header_box.set_margin_start(12)
        header_box.set_margin_end(12)

        header_box.append(Gtk.Label(label=""))
        self.toolbar_view.add_top_bar(header_box)

        self.search_entry = Gtk.SearchEntry(
            placeholder_text="Search Transcripts",
            hexpand=True,
            visible=True
        )


        self.progress_label = Gtk.Label(
            label="Transcribing... 0%",
            halign=Gtk.Align.END,
            css_classes=["monospace"]
        )
        header_box.append(self.progress_label)

        self.stop_button = Gtk.Button(
            label="Stop",
            css_classes=["destructive-action"],
        )
        header_box.append(self.stop_button)

        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, vexpand=True)
        self.toolbar_view.set_content(main_box)

        self.scrolled_window = Gtk.ScrolledWindow(
            hscrollbar_policy=Gtk.PolicyType.NEVER,
            vscrollbar_policy=Gtk.PolicyType.AUTOMATIC,
            vexpand=True
        )
        main_box.append(self.scrolled_window)

        self.list_box = Gtk.ListBox(
            selection_mode=Gtk.SelectionMode.NONE,
            vexpand=True,
            css_classes=["transcript-list"],
        )
        self.scrolled_window.set_child(self.list_box)

    def _on_stop_clicked(self, button):
        log.info("Stop button clicked")
        self.emit("stop-transcription")

    def _on_remove_segment_clicked(self, button, row, segment_index):
        log.info(f"Remove button clicked for segment index: {segment_index}")
        self.list_box.remove(row)
        self.emit("segment-removed", segment_index)

    def _on_copy_segment_clicked(self, button, segment_text):
        log.info(f"Copy button clicked for segment: '{segment_text[:50]}...'")
        clipboard = Gdk.Display.get_default().get_clipboard()
        if clipboard:
            clipboard.set(segment_text)
            log.info("Segment text copied to clipboard.")

        else:
            log.warning("Could not get the default clipboard from Gdk.Display.")

    def _scroll_to_bottom(self):
        GLib.idle_add(self._do_scroll)

    def _do_scroll(self):
        adjustment = self.scrolled_window.get_vadjustment()
        if adjustment:
            target_value = adjustment.get_upper() - adjustment.get_page_size()
            adjustment.set_value(target_value)
        return GLib.SOURCE_REMOVE


    def add_segment(self, segment_data: Dict[str, Any]):
        """Adds a new transcript segment to the list."""
        print(f"TranscriptView: Adding segment [{segment_data.get('start', '?'):.2f}s->{segment_data.get('end', '?'):.2f}s] to UI.")
        try:
            text = segment_data['text'].strip()
            start_ms = segment_data['start_ms']
            end_ms = segment_data['end_ms']
            segment_index = len(self._segments_data)
            self._segments_data.append(segment_data)

            timestamp_str = f"{self._format_timestamp(start_ms)} → {self._format_timestamp(end_ms)}"

            row = Gtk.ListBoxRow(
                selectable=False,
                activatable=False,
            )
            row.add_css_class("transcript-segment-row")

            row_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4, margin_top=6, margin_bottom=6, margin_start=12, margin_end=12)
            row_box.add_css_class("transcript-segment-content-box")
            row.set_child(row_box)

            text_label = Gtk.Label(
                label=text,
                wrap=True,
                wrap_mode=Pango.WrapMode.WORD_CHAR,
                justify=Gtk.Justification.LEFT,
                xalign=0,
                selectable=False,
            )
            text_label.add_css_class("transcript-segment-text-label")
            row_box.append(text_label)

            timestamp_label = Gtk.Label(
                label=timestamp_str,
                xalign=0,
                css_classes=["timestamp-label", "monospace"],
            )
            attrs = Pango.AttrList.new()
            attrs.insert(Pango.attr_family_new("monospace"))
            grey_color = Gdk.RGBA()
            grey_color.parse("#888")
            attrs.insert(Pango.attr_foreground_new(int(grey_color.red * 65535), int(grey_color.green * 65535), int(grey_color.blue * 65535)))
            timestamp_label.set_attributes(attrs)

            row_box.append(timestamp_label)

            button_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8, halign=Gtk.Align.END)
            button_box.add_css_class("transcript-segment-button-box")
            row_box.append(button_box)

            remove_button = Gtk.Button(
                label="Remove",
                css_classes=["destructive-action"],
            )
            remove_button.connect("clicked", self._on_remove_segment_clicked, row, segment_index)
            remove_button.add_css_class("transcript-segment-remove-button")
            button_box.append(remove_button)

            copy_button = Gtk.Button(
                label="Copy",
                css_classes=["suggested-action"],
            )
            copy_button.connect("clicked", self._on_copy_segment_clicked, text)
            copy_button.add_css_class("transcript-segment-copy-button")
            button_box.append(copy_button)

            self.list_box.append(row)
            self._scroll_to_bottom()

        except KeyError as e:
            log.error(f"Missing key in segment data: {e}. Data: {segment_data}")
        except Exception as e:
            log.exception(f"Error adding segment: {e}")


    def update_progress(self, overall_pct: float, segments_done: int = 0, model_download_pct: float = -1.0):
        """
        Update progress label based on transcription and model download status.
        Should be called via GLib.idle_add.
        overall_pct: Overall transcription progress (0.0 to 1.0).
        segments_done: Number of segments transcribed.
        model_download_pct: Model download/preparation progress (0.0 to 1.0, or -1.0 if not applicable/done).
        """
        label = ""

        if model_download_pct >= 0 and model_download_pct <= 1.0: # model_download_pct is 0.0-1.0
            percentage = int(model_download_pct * 100)
            if model_download_pct == 0.0:
                 label = "Starting model preparation..."
            elif model_download_pct < 1.0:
                label = f"Preparing model: {percentage}%"
            else: # model_download_pct == 1.0
                label = "Model ready. Starting transcription..."
        else: # model_download_pct is -1.0 (or other negative, indicating not applicable)
            try:
                overall_fraction_value = float(overall_pct)
            except (ValueError, TypeError):
                overall_fraction_value = 0.0
            
            clamped_overall_fraction = max(0.0, min(1.0, overall_fraction_value))
            overall_percentage = int(clamped_overall_fraction * 100)
            label = f"Transcribing... {overall_percentage}%"

            try:
                segments = int(segments_done)
            except (ValueError, TypeError):
                segments = 0
            
            if segments > 0 : # Show segment count if available
                label += f" (Segment {segments})"
            elif overall_percentage == 100 and segments == 0 : # Transcription complete but maybe no segments (e.g. empty audio)
                 label = "Transcription complete."


        self.progress_label.set_label(label)


    def reset_view(self):
        """Clears all segments and resets progress."""
        log.info("Resetting TranscriptionView")
        child = self.list_box.get_first_child()
        while child:
            next_child = child.get_next_sibling()
            self.list_box.remove(child)
            child = next_child

        self._segments_data.clear()
        self.current_item = None # Clear the loaded item
        # Need to add a progress_bar attribute first
        # self.update_progress(0.0)
        self.progress_label.set_label("Transcribing... 0%")
        # self.progress_bar.set_tooltip_text("Transcribing... 0%")
        adjustment = self.scrolled_window.get_vadjustment()
        if adjustment:
            adjustment.set_value(0)
        
        # Update save/export action sensitivity via a signal or direct call if window is accessible
        # This assumes the parent window might listen for a signal or this view is part of a larger controller.
        # For now, this is a placeholder for how the window's save/export actions get updated.
        parent_window = self.get_ancestor(Adw.ApplicationWindow) # noqa: F841, E501 (keep for now if other uses, but remove the GLib.idle_add below)
        # if parent_window and hasattr(parent_window, '_set_active_view') and hasattr(parent_window, 'leaflet'):
        #      # This call is problematic and might be causing the view to flip back.
        #      # The window._set_active_view should handle sensitivity when it switches to this view.
        #      # GLib.idle_add(parent_window._set_active_view, parent_window.leaflet.get_visible_child_name())
        #      pass # Window._set_active_view will handle sensitivity
        # The main window is responsible for setting action sensitivity when it activates this view.


    def load_transcript(self, transcript_item: TranscriptItem):
        """
        Loads a full TranscriptItem into the view, replacing current content.
        """
        self.reset_view() # Clear existing content
        self.current_item = transcript_item
        log.info(f"Loading TranscriptItem {transcript_item.uuid} into view.")

        if transcript_item.segments:
            for seg_item_obj in transcript_item.segments:
                # Convert SegmentItem object to the dict format add_segment expects
                segment_data_for_ui = {
                    'text': seg_item_obj.text,
                    'start': seg_item_obj.start, # add_segment expects start_ms, end_ms
                    'end': seg_item_obj.end,
                    'start_ms': int(seg_item_obj.start * 1000),
                    'end_ms': int(seg_item_obj.end * 1000),
                    'speaker': seg_item_obj.speaker
                    # 'id' will be assigned by add_segment based on current _segments_data length
                }
                self.add_segment(segment_data_for_ui)
        
        # Update save/export action sensitivity
        parent_window = self.get_ancestor(Adw.ApplicationWindow) # noqa: F841, E501 (keep for now if other uses, but remove the GLib.idle_add below)
        # if parent_window and hasattr(parent_window, '_set_active_view') and hasattr(parent_window, 'leaflet'):
        #      # This call is problematic and might be causing the view to flip back.
        #      # The window._set_active_view should handle sensitivity when it switches to this view.
        #      # GLib.idle_add(parent_window._set_active_view, parent_window.leaflet.get_visible_child_name())
        #      pass # Window._set_active_view will handle sensitivity
        # The main window is responsible for setting action sensitivity when it activates this view.


    def has_content(self) -> bool:
        """
        Checks if the transcript view has any content (segments).
        """
        return bool(self._segments_data)

    def get_current_item(self) -> Optional[TranscriptItem]:
        """
        Returns the TranscriptItem currently loaded in the view, if any.
        """
        return self.current_item

    def get_transcript_data_for_saving(self) -> Optional[Dict[str, Any]]:
        """
        Constructs a dictionary representing the current transcript state for saving.
        This should be compatible with what TranscriptItem.to_dict() would produce
        or what atomic_write_json expects.
        """
        if not self.has_content():
            return None

        # Consolidate text from segments
        full_text = " ".join(seg.get('text', '') for seg in self._segments_data).strip()
        
        # Prepare segments in the format expected by TranscriptItem.to_dict()
        # (start, end, text, speaker)
        segments_for_json = []
        for seg_ui_data in self._segments_data:
            segments_for_json.append({
                "start": round(seg_ui_data.get('start', 0.0), 3),
                "end": round(seg_ui_data.get('end', 0.0), 3),
                "text": seg_ui_data.get('text', "").strip(),
                "speaker": seg_ui_data.get('speaker', "") # Assuming speaker might be edited in UI later
            })

        # If there's a current_item, use its metadata as a base
        if self.current_item:
            data = {
                "uuid": self.current_item.uuid,
                # timestamp should be in YYYYMMDD_HHMMSS for JSON
                "timestamp": GLib.DateTime.new_from_iso8601(self.current_item.timestamp + "Z", None).format("%Y%m%d_%H%M%S") if self.current_item.timestamp else GLib.DateTime.new_now_local().format("%Y%m%d_%H%M%S"),
                "text": full_text,
                "segments": segments_for_json,
                "language": self.current_item.language,
                "source_path": self.current_item.audio_source_path, # Media path
                "audio_source_path": self.current_item.audio_source_path, # Media path
                "output_filename": self.current_item.output_filename # JSON filename
            }
        else:
            # This is a new, unsaved transcript (e.g., from live recording not yet auto-saved)
            # Some fields will be generated fresh by the save logic in window.py
            data = {
                "text": full_text,
                "segments": segments_for_json,
                # language might be inferred or use a default in window.py's save logic
            }
        return data


    def get_full_text(self) -> str:
        """
        Retrieves the clean, concatenated transcript text from all segments.
        This is primarily for exports like .txt where only the speech content is desired.
        """
        if not hasattr(self, '_segments_data') or not self._segments_data:
            return ""
        
        # Concatenate text from all segments, separated by a space or newline.
        # The spec for export_to_txt uses "\n\n" between segments.
        # For a generic get_full_text, a single space might be more universally useful,
        # or let the export functions handle specific formatting.
        # Let's go with newline separation for now, as it's often useful.
        
        text_parts = []
        for segment_dict in self._segments_data:
            segment_text = segment_dict.get("text", "")
            if isinstance(segment_text, str):
                text_parts.append(segment_text.strip())
            else:
                log.warning(f"Segment data 'text' is not a string: {segment_text}. Skipping.")
        
        return "\n".join(text_parts) # Or " ".join(text_parts) if single line is preferred

    def _format_timestamp_plain(self, seconds: float) -> str:
        minutes = int(seconds) // 60
        seconds = int(seconds) % 60
        return f"{minutes:02}:{seconds:02}"


