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