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

from ..models.transcript_item import TranscriptItem, SegmentItem

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

    def __init__(self, on_transcript_selected: t.Callable[[TranscriptItem], None], **kwargs):
        """
        Initializes the HistoryView.

        Args:
            on_transcript_selected: Callback function executed when a transcript
                                     is selected from the list. It receives a list
                                     of segment dictionaries.
            **kwargs: Additional keyword arguments for Gtk.Box.
        """
        super().__init__(**kwargs)
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

        if not TRANSCRIPT_DIR.exists() or not any(TRANSCRIPT_DIR.iterdir()):
            placeholder_label = Gtk.Label(label="No saved transcripts found.")
            placeholder_label.set_vexpand(True)
            placeholder_label.set_halign(Gtk.Align.CENTER)
            placeholder_label.set_valign(Gtk.Align.CENTER)
            print("Transcript directory is empty or does not exist.")
            return

        items = []
        for entry in TRANSCRIPT_DIR.iterdir():
            if entry.is_file() and entry.suffix == ".json":
                try:
                    item = TranscriptItem.load_from_json(str(entry))
                    if item:
                        items.append(item)
                except Exception as e:
                    print(f"Error loading transcript {entry.name}: {e}")

        items.sort(key=lambda x: x.timestamp, reverse=True)

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
                    if not item.segments:
                         print("Selected transcript has no segments.")
                         return
                    self._on_transcript_selected_callback(item)

    def _on_row_selected(self, listbox: Gtk.ListBox):
        row = listbox.get_selected_row()
        if not row:
            return
        item = getattr(row, "_transcript_item", None)
        if item and isinstance(item, TranscriptItem):
            self.emit("transcript-selected", item)