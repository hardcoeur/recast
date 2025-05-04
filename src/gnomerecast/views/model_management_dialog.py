import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Adw, Gio, GObject, GLib
from typing import Optional
import functools
import threading
import pathlib
import os

from ..utils.models import (
    get_available_models,
    list_local_models,
    download_model,
    APP_MODEL_DIR
)

class ModelItem(GObject.Object):
    """Simple GObject to hold model information for the ListStore."""
    __gtype_name__ = 'ModelItem'

    name = GObject.Property(type=str)
    size = GObject.Property(type=str)
    status = GObject.Property(type=str)
    download_url = GObject.Property(type=str)
    is_downloading = GObject.Property(type=bool, default=False)
    download_progress = GObject.Property(type=float, default=0.0)
    error_message = GObject.Property(type=str, default=None)
    signal_handlers = GObject.Property(type=object)
    cancel_event = GObject.Property(type=object)


    def __init__(self, name, size, status, download_url=None):
        super().__init__()
        self.name = name
        self.size = size
        self.status = status
        self.download_url = download_url
        self.signal_handlers = {}
        self.cancel_event = None
        self.is_downloading = False
        self.download_progress = 0.0
        self.error_message = None


class ModelManagementDialog(Gtk.Dialog):
    """Dialog for managing Whisper transcription models."""

    def __init__(self, parent, **kwargs):
        super().__init__(transient_for=parent, **kwargs)

        self.active_downloads = {}

        self.set_title("Manage Transcription Models")
        self.set_modal(True)
        self.set_default_size(450, 350)
        self.add_button("_Close", Gtk.ResponseType.CLOSE)

        self.connect("close-request", self._on_close_request)

        content_area = self.get_content_area()

        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, margin_top=12, margin_bottom=12, margin_start=12, margin_end=12)
        content_area.append(main_box)

        scrolled_window = Gtk.ScrolledWindow()
        scrolled_window.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scrolled_window.set_vexpand(True)
        main_box.append(scrolled_window)

        self.model_store = Gio.ListStore(item_type=ModelItem)
        selection_model = Gtk.SingleSelection(model=self.model_store)
        self.model_list_view = Gtk.ListView(model=selection_model)
        self.model_list_view.set_show_separators(True)
        scrolled_window.set_child(self.model_list_view)

        factory = Gtk.SignalListItemFactory()
        factory.connect("setup", self._on_factory_setup)
        factory.connect("bind", self._on_factory_bind)
        factory.connect("unbind", self._on_factory_unbind)

        self.model_list_view.set_factory(factory)

        self._populate_model_list()

    def _populate_model_list(self):
        """Loads available and local models and populates the list store."""
        print("Populating model list...")
        available_models = get_available_models()
        local_models_list = list_local_models()
        local_models_dict = {model['name']: model for model in local_models_list}

        self.model_store.remove_all()

        added_model_names = set()

        for name, details in available_models.items():
            status = "Not Downloaded"
            size = details.get("size", "N/A")
            download_url = details.get("url")

            if name in local_models_dict:
                status = "Downloaded"
                size = local_models_dict[name].get("size", "N/A")

            item = ModelItem(
                name=name,
                size=size,
                status=status,
                download_url=download_url
            )
            self.model_store.append(item)
            added_model_names.add(name)

        for local_model in local_models_list:
            name = local_model.get("name")
            if name and name not in added_model_names:
                 print(f"Found local-only model: {name}")
                 item = ModelItem(
                     name=name,
                     size=local_model.get("size", "N/A"),
                     status="Downloaded (Local Only)",
                     download_url=None
                 )
                 self.model_store.append(item)


        print(f"Loaded {self.model_store.get_n_items()} models into list store.")

    def _on_factory_setup(self, factory, list_item):
        """Setup the widget for a list item using Adw.ActionRow."""
        action_row = Adw.ActionRow()
        action_row.set_activatable(False)

        suffix_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6, valign=Gtk.Align.CENTER)

        size_label = Gtk.Label()
        progress_bar = Gtk.ProgressBar(visible=False, show_text=False, hexpand=True, width_request=100)
        download_button = Gtk.Button(icon_name="folder-download-symbolic", tooltip_text="Download Model")
        cancel_button = Gtk.Button(icon_name="edit-delete-symbolic", tooltip_text="Cancel Download", visible=False)
        remove_button = Gtk.Button(icon_name="user-trash-symbolic", tooltip_text="Remove Model")

        suffix_box.append(size_label)
        suffix_box.append(progress_bar)
        suffix_box.append(download_button)
        suffix_box.append(cancel_button)
        suffix_box.append(remove_button)

        action_row.add_suffix(suffix_box)

        list_item.widgets = {
            "action_row": action_row,
            "size_label": size_label,
            "progress_bar": progress_bar,
            "download_button": download_button,
            "cancel_button": cancel_button,
            "remove_button": remove_button,
        }

        list_item.set_child(action_row)


    def _on_factory_bind(self, factory, list_item):
        """Bind the data from the ModelItem to the list item's widgets."""
        model_item = list_item.get_item()
        setattr(list_item, '_bound_item', model_item)

        widgets = list_item.widgets
        action_row = widgets["action_row"]
        size_label = widgets["size_label"]
        progress_bar = widgets["progress_bar"]
        download_button = widgets["download_button"]
        cancel_button = widgets["cancel_button"]
        remove_button = widgets["remove_button"]

        action_row.set_title(model_item.name)
        size_label.set_label(f"({model_item.size})")

        is_downloaded = model_item.status == "Downloaded" or model_item.status == "Downloaded (Local Only)"
        is_downloading = model_item.is_downloading
        is_error = model_item.status == "Error"
        can_download = bool(model_item.download_url) and not is_downloaded and not is_downloading

        action_row.set_subtitle(model_item.error_message if is_error else model_item.status)
        action_row.set_sensitive(not is_downloading)

        size_label.set_visible(not is_downloading)
        progress_bar.set_visible(is_downloading)
        progress_bar.set_fraction(model_item.download_progress if is_downloading else 0)

        download_button.set_visible(can_download or is_error)
        download_button.set_sensitive(can_download or is_error)
        cancel_button.set_visible(is_downloading)
        cancel_button.set_sensitive(is_downloading)
        remove_button.set_visible(is_downloaded)
        remove_button.set_sensitive(is_downloaded)

        if "download" not in model_item.signal_handlers:
            dl_handler_id = download_button.connect("clicked", functools.partial(self._on_download_clicked, item=model_item))
            model_item.signal_handlers["download"] = (download_button, dl_handler_id)

        if "remove" not in model_item.signal_handlers:
            rm_handler_id = remove_button.connect("clicked", functools.partial(self._on_remove_clicked, item=model_item))
            model_item.signal_handlers["remove"] = (remove_button, rm_handler_id)

        if "cancel" not in model_item.signal_handlers:
            cancel_handler_id = cancel_button.connect("clicked", functools.partial(self._on_cancel_clicked, item=model_item))
            model_item.signal_handlers["cancel"] = (cancel_button, cancel_handler_id)


    def _on_factory_unbind(self, factory, list_item):
        """Disconnect signal handlers when the item is unbound."""
        model_item = getattr(list_item, '_bound_item', None)

        if model_item and hasattr(model_item, 'signal_handlers'):
            for key, handler_info in list(model_item.signal_handlers.items()):
                widget, handler_id = handler_info
                try:
                    if widget.is_connected(handler_id):
                         widget.disconnect(handler_id)
                except TypeError:
                    print(f"Warning: Could not disconnect signal for {key} on {model_item.name}, widget might be destroyed.")
                del model_item.signal_handlers[key]

        if hasattr(list_item, '_bound_item'):
            delattr(list_item, '_bound_item')


    def _on_download_clicked(self, button, item):
        """Handler for download button click."""
        if item.is_downloading or not item.download_url:
            print(f"Download request ignored for {item.name} (already downloading or no URL)")
            return

        print(f"Starting download for {item.name} from {item.download_url}")
        model_name = item.name

        item.is_downloading = True
        item.status = "Downloading"
        item.download_progress = 0.0
        item.error_message = None
        item.cancel_event = threading.Event()

        position = self.model_store.find(item)[1]
        if position != Gtk.INVALID_LIST_POSITION:
            self.model_store.items_changed(position, 1, 1)
        else:
            print(f"Warning: Could not find item {item.name} in store to update UI for download start.")


        download_thread = threading.Thread(
            target=download_model,
            args=(
                model_name,
                item.download_url,
                APP_MODEL_DIR,
                self._update_download_progress,
                item.cancel_event
            ),
            daemon=True
        )

        self.active_downloads[model_name] = {
            "thread": download_thread,
            "cancel_event": item.cancel_event
        }

        download_thread.start()

    def _update_download_progress(self, model_name: str, percentage: float, error_message: Optional[str] = None):
        """Callback executed via GLib.idle_add from the download thread."""
        print(f"Progress update for {model_name}: {percentage}%, Error: {error_message}")

        item_to_update = None
        position = Gtk.INVALID_LIST_POSITION
        for i in range(self.model_store.get_n_items()):
            item = self.model_store.get_item(i)
            if item.name == model_name:
                item_to_update = item
                position = i
                break

        if not item_to_update:
            print(f"Error: Could not find ModelItem '{model_name}' in store to update progress.")
            if model_name in self.active_downloads:
                del self.active_downloads[model_name]
            return

        final_state = False
        if percentage == 100.0:
            item_to_update.is_downloading = False
            item_to_update.status = "Downloaded"
            item_to_update.download_progress = 1.0
            item_to_update.error_message = None
            item_to_update.cancel_event = None
            final_state = True
            print(f"Download completed for {model_name}. Refreshing list.")
            self._populate_model_list()
            if model_name in self.active_downloads:
                del self.active_downloads[model_name]
            return

        elif percentage == -1.0:
            item_to_update.is_downloading = False
            item_to_update.status = "Error"
            item_to_update.download_progress = 0.0
            item_to_update.error_message = error_message or "Unknown download error"
            item_to_update.cancel_event = None
            final_state = True
            print(f"Download error for {model_name}: {item_to_update.error_message}")

        elif percentage == -2.0:
            item_to_update.is_downloading = False
            item_to_update.status = "Not Downloaded"
            item_to_update.download_progress = 0.0
            item_to_update.error_message = None
            item_to_update.cancel_event = None
            final_state = True
            print(f"Download cancelled for {model_name}")

        elif 0 <= percentage < 100:
            item_to_update.is_downloading = True
            item_to_update.status = "Downloading"
            item_to_update.download_progress = percentage / 100.0
            item_to_update.error_message = None

        else:
             print(f"Warning: Received unexpected progress value for {model_name}: {percentage}")
             return


        if final_state and model_name in self.active_downloads:
            del self.active_downloads[model_name]
            print(f"Removed {model_name} from active downloads.")

        if position != Gtk.INVALID_LIST_POSITION:
            self.model_store.items_changed(position, 1, 1)
        else:
             print(f"Warning: Could not find position for updated item {model_name} after processing.")


    def _on_cancel_clicked(self, button, item):
        """Handler for cancel button click."""
        if not item.is_downloading or not item.cancel_event:
            print(f"Cancel request ignored for {item.name} (not downloading or no event)")
            return

        print(f"Cancel requested for {item.name}")
        item.cancel_event.set()
        button.set_sensitive(False)


    def _on_remove_clicked(self, button, item):
        """Handler for remove button click."""
        print(f"Remove clicked for {item.name}")
        expected_filename = f"ggml-{item.name}.bin"
        file_path = APP_MODEL_DIR / expected_filename

        if file_path.exists() and file_path.is_file():
            try:
                print(f"Attempting to delete {file_path}")
                file_path.unlink()
                print(f"Successfully deleted {file_path}")
                self._populate_model_list()
            except OSError as e:
                print(f"Error deleting model file {file_path}: {e}")
                error_dialog = Gtk.MessageDialog(
                    transient_for=self,
                    modal=True,
                    message_type=Gtk.MessageType.ERROR,
                    buttons=Gtk.ButtonsType.CLOSE,
                    text=f"Failed to remove model '{item.name}'",
                    secondary_text=str(e)
                )
                error_dialog.connect("response", lambda d, r: d.destroy())
                error_dialog.show()
        else:
            print(f"Model file not found for removal: {file_path}")
            self._populate_model_list()

    def _on_close_request(self, dialog):
        """Handle dialog close: cancel any active downloads."""
        print("Close requested. Cancelling active downloads...")
        active_names = list(self.active_downloads.keys())
        if not active_names:
            print("No active downloads to cancel.")
            return False

        for model_name in active_names:
            if model_name in self.active_downloads:
                print(f"Signalling cancel for {model_name}")
                cancel_event = self.active_downloads[model_name].get("cancel_event")
                if cancel_event:
                    cancel_event.set()

        print("Cancellation signals sent.")
        return False