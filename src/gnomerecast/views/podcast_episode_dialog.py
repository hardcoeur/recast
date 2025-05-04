import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Adw, Gio, GLib, GObject

import threading
import feedparser
import logging
from datetime import datetime

log = logging.getLogger(__name__)

class EpisodeItem(GObject.Object):
    __gtype_name__ = 'EpisodeItem'

    title = GObject.Property(type=str)
    published_date = GObject.Property(type=str)
    audio_url = GObject.Property(type=str)
    description = GObject.Property(type=str)

    def __init__(self, title, published_date, audio_url, description):
        super().__init__()
        self._title = title
        self._published_date = published_date
        self._audio_url = audio_url
        self._description = description

    @GObject.Property(type=str)
    def title(self):
        return self._title

    @GObject.Property(type=str)
    def published_date(self):
        if self._published_date:
            try:
                dt = datetime(*self._published_date[:6])
                return dt.strftime("%Y-%m-%d")
            except Exception:
                return str(self._published_date)
        return "Unknown Date"

    @GObject.Property(type=str)
    def audio_url(self):
        return self._audio_url

    @GObject.Property(type=str)
    def description(self):
        desc = self._description or ""
        import re
        desc = re.sub('<[^<]+?>', '', desc)
        return desc


class PodcastEpisodeDialog(Gtk.Dialog):
    """Dialog to display podcast episodes from a feed URL and allow selection."""

    def __init__(self, feed_url, parent, **kwargs):
        super().__init__(transient_for=parent, modal=True, **kwargs)
        self.feed_url = feed_url
        self._episodes_data = []

        self.set_title("Select Podcast Episode")
        self.set_default_size(600, 400)
        self.set_resizable(True)

        self.add_button("Cancel", Gtk.ResponseType.CANCEL)
        self.transcribe_button = self.add_button("Transcribe Selected", Gtk.ResponseType.OK)
        self.transcribe_button.set_sensitive(False)

        content_area = self.get_content_area()
        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin_top=10, margin_bottom=10, margin_start=10, margin_end=10)
        content_area.append(main_box)

        self.status_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6, halign=Gtk.Align.CENTER)
        self.spinner = Gtk.Spinner(spinning=True)
        self.status_label = Gtk.Label(label="Fetching feed...")
        self.status_box.append(self.spinner)
        self.status_box.append(self.status_label)
        main_box.append(self.status_box)

        scrolled_window = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER,
                                              vscrollbar_policy=Gtk.PolicyType.AUTOMATIC,
                                              vexpand=True)
        main_box.append(scrolled_window)

        self.list_store = Gio.ListStore(item_type=EpisodeItem)
        self.selection_model = Gtk.SingleSelection(model=self.list_store)
        self.list_view = Gtk.ListView(model=self.selection_model)
        self.list_view.set_css_classes(["boxed-list"])

        factory = Gtk.SignalListItemFactory()
        factory.connect("setup", self._on_factory_setup)
        factory.connect("bind", self._on_factory_bind)

        self.list_view.set_factory(factory)
        scrolled_window.set_child(self.list_view)

        self.selection_model.connect("notify::selected-item", self._on_episode_selected)

        self.fetch_thread = threading.Thread(target=self._fetch_and_parse_feed, daemon=True)
        self.fetch_thread.start()

    def _on_factory_setup(self, factory, list_item):
        """Setup the list item widget."""
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3, margin_top=5, margin_bottom=5, margin_start=5, margin_end=5)
        title_label = Gtk.Label(halign=Gtk.Align.START, xalign=0)
        title_label.set_css_classes(["title-4"])
        date_label = Gtk.Label(halign=Gtk.Align.START, xalign=0)
        date_label.set_css_classes(["caption"])
        box.append(title_label)
        box.append(date_label)
        list_item.set_child(box)

    def _on_factory_bind(self, factory, list_item):
        """Bind data from the EpisodeItem to the list item widget."""
        box = list_item.get_child()
        labels = [widget for widget in self._get_all_children(box) if isinstance(widget, Gtk.Label)]
        episode_item = list_item.get_item()

        if len(labels) == 2 and episode_item:
            labels[0].set_text(episode_item.title or "No Title")
            labels[1].set_text(episode_item.published_date or "No Date")

    def _get_all_children(self, widget):
        """Recursively get all children of a widget."""
        children = []
        if hasattr(widget, 'get_first_child'):
            child = widget.get_first_child()
            while child:
                children.append(child)
                children.extend(self._get_all_children(child))
                child = child.get_next_sibling()
        return children

    def _fetch_and_parse_feed(self):
        """Fetches and parses the podcast feed in a background thread."""
        log.info(f"Fetching podcast feed: {self.feed_url}")
        try:
            headers = {'User-Agent': 'GnomeRecast/1.0'}
            feed_data = feedparser.parse(self.feed_url, agent=headers.get('User-Agent'))

            if feed_data.bozo:
                exception = feed_data.get("bozo_exception")
                if isinstance(exception, feedparser.NonXMLContentType):
                     raise ValueError(f"Feed is not XML: {exception}")
                elif isinstance(exception, feedparser.CharacterEncodingOverride):
                     log.warning(f"Character encoding override: {exception}")
                elif exception:
                     raise ValueError(f"Feed parsing error: {exception}")


            if feed_data.entries:
                episodes = []
                for entry in feed_data.entries:
                    title = entry.get("title", "Untitled Episode")
                    published = entry.get("published_parsed")
                    description = entry.get("summary", entry.get("description", ""))

                    audio_url = None
                    if "enclosures" in entry:
                        for enclosure in entry.enclosures:
                            if enclosure.get("type", "").startswith("audio/"):
                                audio_url = enclosure.get("href")
                                break

                    if audio_url:
                        episodes.append({
                            "title": title,
                            "published_date": published,
                            "audio_url": audio_url,
                            "description": description
                        })
                    else:
                        log.warning(f"Skipping episode '{title}' - no audio enclosure found.")

                log.info(f"Found {len(episodes)} episodes with audio.")
                if episodes:
                    GLib.idle_add(self._populate_episode_list, episodes)
                else:
                    GLib.idle_add(self._show_fetch_error, "No episodes with audio found in the feed.")

            else:
                log.warning("Feed parsed successfully, but no entries found.")
                GLib.idle_add(self._show_fetch_error, "No episodes found in the feed.")

        except Exception as e:
            log.error(f"Failed to fetch or parse feed {self.feed_url}: {e}", exc_info=True)
            GLib.idle_add(self._show_fetch_error, f"Error fetching feed: {e}")

    def _populate_episode_list(self, episodes_data):
        """Populates the list store with episode data on the main thread."""
        log.debug("Populating episode list UI.")
        self.status_box.set_visible(False)
        self.list_store.remove_all()
        self._episodes_data = episodes_data

        for data in episodes_data:
            item = EpisodeItem(
                title=data["title"],
                published_date=data["published_date"],
                audio_url=data["audio_url"],
                description=data["description"]
            )
            self.list_store.append(item)
        log.debug(f"Added {self.list_store.get_n_items()} items to the list store.")
        return GLib.SOURCE_REMOVE

    def _show_fetch_error(self, error_message):
        """Displays an error message on the main thread."""
        log.debug(f"Showing fetch error: {error_message}")
        self.spinner.stop()
        self.spinner.set_visible(False)
        self.status_label.set_text(f"Error: {error_message}")
        self.status_label.set_tooltip_text(error_message)
        return GLib.SOURCE_REMOVE

    def _on_episode_selected(self, selection_model, _param):
        """Enables the 'Transcribe Selected' button when an episode is selected."""
        selected_item = selection_model.get_selected_item()
        self.transcribe_button.set_sensitive(selected_item is not None)
        log.debug(f"Episode selected: {selected_item.title if selected_item else 'None'}")

    def get_selected_episode_data(self):
        """Returns the data of the selected episode."""
        selected_pos = self.selection_model.get_selected()
        if selected_pos != Gtk.INVALID_LIST_POSITION:
            item = self.list_store.get_item(selected_pos)
            if item:
                log.debug(f"Retrieving data for selected episode: {item.title}")
                return {
                    "title": item.title,
                    "audio_url": item.audio_url,
                    "published_date": item.published_date,
                    "description": item.description
                }
        log.debug("No episode selected or item not found.")
        return None