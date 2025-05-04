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
        super().__init__(application_id="org.gnome.GnomeRecast", **kwargs)

        self.dictation_overlay = None
        self.preferences_window = None

        self.style_manager = Adw.StyleManager.get_default()


    def do_startup(self):
        """Called once when the application first starts."""
        Adw.Application.do_startup(self)

        self.css_provider = Gtk.CssProvider()
        self.css_provider.load_from_path("data/css/style.css")

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
        builder.add_from_file("data/ui/app-menu.ui")

        app_menu = builder.get_object("app-menu")
        if not isinstance(app_menu, Gio.MenuModel):
            print(f"Warning: Object 'app-menu' in 'data/ui/app-menu.ui' is not a GMenuModel.")
            app_menu = None

        self.app_menu = app_menu


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
            application_name="GnomeRecast",
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