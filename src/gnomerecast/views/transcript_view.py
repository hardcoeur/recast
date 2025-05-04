import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Adw, Gdk, GLib, Pango, GObject

import logging
from typing import Dict, Any

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

        self._segments_data = []

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


    def update_progress(self, fraction: float, total_segments: int = 0, completed_segments: int = 0):
        """Update progress bar and label directly (should be called via GLib.idle_add)."""
        try:
            fraction_value = float(fraction)
        except (ValueError, TypeError):
            fraction_value = 0.0

        clamped_fraction = max(0.0, min(1.0, fraction_value))
        percentage = int(clamped_fraction * 100)
        label = f"Transcribing... {percentage}%"

        try:
            total = int(total_segments)
            completed = int(completed_segments)
        except (ValueError, TypeError):
            total = 0
            completed = 0

        if total > 0:
            label += f" ({min(completed, total)}/{total})"
        elif completed > 0:
            label += f" (Segment {completed})"

        # Need to add a progress_bar attribute first
        # self.progress_bar.set_fraction(clamped_fraction)
        self.progress_label.set_label(label)
        # self.progress_bar.set_tooltip_text(label)



    def reset_view(self):
        """Clears all segments and resets progress."""
        log.info("Resetting TranscriptionView")
        child = self.list_box.get_first_child()
        while child:
            next_child = child.get_next_sibling()
            self.list_box.remove(child)
            child = next_child

        self._segments_data.clear()
        # Need to add a progress_bar attribute first
        # self.update_progress(0.0)
        self.progress_label.set_label("Transcribing... 0%")
        # self.progress_bar.set_tooltip_text("Transcribing... 0%")
        adjustment = self.scrolled_window.get_vadjustment()
        if adjustment:
            adjustment.set_value(0)

    def get_full_text(self) -> str:
        """
        Retrieves the full transcript text by concatenating all segments.
        """
        full_text = ""
        if hasattr(self, '_segments_data') and self._segments_data:
            for segment_dict in self._segments_data:
                segment_text = segment_dict.get("text", "").strip()
                start = segment_dict.get("start", 0.0)
                end = segment_dict.get("end", 0.0)

                if isinstance(segment_text, str):
                    start_ts = self._format_timestamp_plain(start)
                    end_ts = self._format_timestamp_plain(end)
                    full_text += f"[{start_ts} → {end_ts}]\n{segment_text}\n\n"
                else:
                    log.warning(f"Segment data 'text' is not a string: {segment_text}. Skipping.")

        return full_text.strip()

    def _format_timestamp_plain(self, seconds: float) -> str:
        minutes = int(seconds) // 60
        seconds = int(seconds) % 60
        return f"{minutes:02}:{seconds:02}"