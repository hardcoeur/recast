import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Gtk, Adw, Gio, Gdk
from .window import GnomeRecastWindow
from .views.dictation_overlay import DictationOverlay
from .views.preferences_window import PreferencesWindow

class GnomeRecastApplication(Adw.Application):
    """The main application class for GnomeRecast."""

    def __init__(self, **kwargs):
        super().__init__(application_id="org.hardcoeur.Recast", **kwargs)

        self.dictation_overlay = None
        self.preferences_window = None

        self.style_manager = Adw.StyleManager.get_default()

        self._perform_settings_migration()


    def do_startup(self):
        """Called once when the application first starts."""
        Adw.Application.do_startup(self)
        
        # Note: Settings migration moved to __init__ to run even earlier,
        # but can also be here if preferred, as long as it's before settings are heavily used.
        # self._perform_settings_migration() # Ensure it runs if not in __init__

        self.css_provider = Gtk.CssProvider()
        self.css_provider.load_from_path("/app/share/gnomerecast/css/style.css")

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
        builder.add_from_file("/app/share/gnomerecast/ui/app-menu.ui")

        app_menu = builder.get_object("app-menu")
        if not isinstance(app_menu, Gio.MenuModel):
            print(f"Warning: Object 'app-menu' in 'data/ui/app-menu.ui' is not a GMenuModel.")
            app_menu = None

        self.app_menu = app_menu

    def _perform_settings_migration(self):
        """Performs one-time migration for microphone settings if needed."""
        settings = Gio.Settings.new("org.hardcoeur.Recast")
        
        new_mic_id_key = "mic-input-device-id"
        new_follow_default_key = "follow-system-default"
        old_mic_key = "mic-input-device" # The old key to migrate from

        current_new_mic_id = settings.get_string(new_mic_id_key)
        current_follow_default = settings.get_boolean(new_follow_default_key)
        old_mic_value = settings.get_string(old_mic_key)

        # Check if new keys are at their default values and old key has a value
        # Default for mic-input-device-id is ""
        # Default for follow-system-default is false
        if current_new_mic_id == "" and not current_follow_default and old_mic_value != "":
            print(f"Migrating old microphone setting: '{old_mic_value}'")
            # If old value was "System Default" or similar, map to new logic
            # For now, assume old_mic_value was a device ID or a placeholder that implies specific device
            # If old_mic_value was meant to be a system default, this logic might need refinement.
            # Based on micrefactor.md, the old key was likely a device string.
            
            settings.set_string(new_mic_id_key, old_mic_value)
            settings.set_boolean(new_follow_default_key, False) # Explicitly not following default
            
            # Clear the old key to prevent re-migration
            print(f"Clearing old microphone setting key '{old_mic_key}'.")
            settings.set_string(old_mic_key, "") # Or settings.reset_key(old_mic_key) if that's preferred
            
            print(f"Migration complete: '{new_mic_id_key}' set to '{old_mic_value}', '{new_follow_default_key}' to False.")
        else:
            print("No microphone setting migration needed or already migrated.")


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