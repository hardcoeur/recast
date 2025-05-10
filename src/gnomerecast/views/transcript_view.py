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