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
        css_resource_ref = _GNOMERECAST_DATA_ROOT / 'css' / 'style.css'
        with importlib.resources.as_file(css_resource_ref) as css_file_path:
            self.css_provider.load_from_path(str(css_file_path))

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
        ui_resource_ref = _GNOMERECAST_DATA_ROOT / 'ui' / 'app-menu.ui'
        with importlib.resources.as_file(ui_resource_ref) as ui_file_path:
            builder.add_from_file(str(ui_file_path))

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
        if not settings.get_property("settings-schema").has_key(old_key_name):
            print(f"Old GSettings key '{old_key_name}' not in current schema – skipping migration for this key.")
            return
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
            # This means has_key was true, but is_writable was false.
            print(f"Old GSettings key '{old_key_name}' exists in schema but is not writable, skipping migration.")


    def _perform_settings_migration(self):
        """Performs one-time settings migrations if needed."""
        settings = Gio.Settings.new("org.hardcoeur.Recast")
        
        # --- Microphone settings migration (existing) ---
        new_mic_id_key = "mic-input-device-id"
        new_follow_default_key = "follow-system-default"
        old_mic_key = "mic-input-device"

        if settings.get_property("settings-schema").has_key(old_mic_key):
            # Key exists in schema. Now check if writable and then try to process.
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
                    # Or if other GSettings operations fail on an existing, writable key.
                    print(f"Error processing old GSettings key '{old_mic_key}' even though it's in schema, skipping migration: {e}")
                except Exception as e: # Catch any other unexpected errors during this specific migration
                    print(f"Unexpected error during microphone setting migration for '{old_mic_key}': {e}")
            else:
                # Key exists in schema but is not writable
                print(f"Old GSettings key '{old_mic_key}' exists in schema but is not writable, skipping migration.")
        else:
            # Key does not exist in schema
            print(f"Old GSettings key '{old_mic_key}' not found in current schema, skipping migration for this key.")

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