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