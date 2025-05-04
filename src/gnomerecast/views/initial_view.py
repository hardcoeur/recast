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