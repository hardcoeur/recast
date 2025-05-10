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