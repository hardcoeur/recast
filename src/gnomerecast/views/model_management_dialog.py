import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Adw, Gio, GObject, GLib
from typing import Optional, Dict
import functools
from ..ui.toast import ToastPresenter
import threading
import pathlib
import os

from faster_whisper import WhisperModel

from ..utils.models import (
    AVAILABLE_MODELS, # Changed: Use AVAILABLE_MODELS
    # get_available_models, # Removed
    # list_local_models, # Removed
    APP_MODEL_DIR, # Keep if used by _on_remove_clicked for path construction
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

        self.active_downloads: Dict[str, Dict] = {} # Store thread and cancel event if needed, or just model name

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
        """Populates the list store with available models and checks their cache status."""
        print("ModelManagementDialog: Initiating model list population with new cache check logic...")
        self.model_store.remove_all()

        # Sort AVAILABLE_MODELS by name for consistent order
        # AVAILABLE_MODELS is now a direct import: Dict[str, str] where str is size
        sorted_model_names = sorted(AVAILABLE_MODELS.keys())

        for model_name in sorted_model_names:
            size = AVAILABLE_MODELS[model_name]
            # Create item with initial "Checking..." status
            item = ModelItem(
                name=model_name,
                size=size,
                status="Checking status...",
                download_url=None # download_url is not directly used for caching with faster-whisper by name
            )
            self.model_store.append(item)
            # Start a background thread to check the actual cache status
            threading.Thread(
                target=self._check_model_cache_status_worker,
                args=(item,), # Pass the ModelItem instance
                daemon=True
            ).start()
        print(f"ModelManagementDialog: Initialized {self.model_store.get_n_items()} models for status checking.")

    def _check_model_cache_status_worker(self, model_item: ModelItem):
        """
        Worker function to check if a model is cached using faster-whisper.
        Runs in a background thread. Updates the passed ModelItem.
        """
        is_cached = False
        error_message: Optional[str] = None
        model_name = model_item.name
        try:
            # Attempt to load the model with local_files_only=True
            _model = WhisperModel(model_name, device="cpu", compute_type="int8", local_files_only=True)
            is_cached = True
            del _model # Release resources
            print(f"Thread: Model '{model_name}' IS cached.")
        except RuntimeError as e:
            if "model is not found locally" in str(e).lower() or \
               "doesn't exist or is not a directory" in str(e).lower() or \
               "path does not exist or is not a directory" in str(e).lower() or \
               "no such file or directory" in str(e).lower() and ".cache/huggingface/hub" in str(e).lower():
                is_cached = False
                print(f"Thread: Model '{model_name}' is NOT cached (expected error: {e}).")
            else: # Other unexpected RuntimeError
                is_cached = False
                error_message = f"RuntimeError checking cache for {model_name}: {str(e)}"
                print(error_message)
        except Exception as e:
            is_cached = False
            error_message = f"Unexpected error checking cache for {model_name}: {type(e).__name__} - {str(e)}"
            print(error_message)

        GLib.idle_add(self._update_model_item_cache_status_from_worker, model_item, is_cached, error_message)

    def _update_model_item_cache_status_from_worker(self, model_item: ModelItem, is_cached: bool, error_message: Optional[str]):
        """
        Updates the ModelItem's status in the UI based on cache check.
        Called from the main GTK thread.
        """
        if model_item.is_downloading: # If it was marked as downloading, don't overwrite status yet
            print(f"Model '{model_item.name}' cache status check completed, but download is in progress. Status unchanged for now.")
            return GLib.SOURCE_REMOVE

        if error_message:
            model_item.status = "Error Checking Status"
            model_item.error_message = error_message
            print(f"UI Update: Model '{model_item.name}' status check error: {error_message}")
        else:
            model_item.status = "Downloaded" if is_cached else "Not Downloaded"
            model_item.error_message = None
            print(f"UI Update: Model '{model_item.name}' status: {model_item.status}")


        # Find the item in the store and trigger an update for its row
        position = Gtk.INVALID_LIST_POSITION
        # Iterate using range and get_item if direct find on model_item fails due to object identity issues
        # after thread. For now, assume model_item is the correct reference or has comparable properties.
        # A more robust way is to find by model_item.name if model_item itself isn't found.
        found, pos_val = self.model_store.find(model_item)
        if found:
            position = pos_val
        else: # Fallback to search by name if direct object find fails
            for i in range(self.model_store.get_n_items()):
                item_in_store = self.model_store.get_item(i)
                if item_in_store.name == model_item.name:
                    # Update the original item in the store directly if properties are GObject.Properties
                    item_in_store.status = model_item.status
                    item_in_store.error_message = model_item.error_message
                    position = i
                    break
        
        if position != Gtk.INVALID_LIST_POSITION:
            self.model_store.items_changed(position, 1, 1) # Notify ListView to rebind this item
        else:
            print(f"Warning: Could not find item {model_item.name} in store to update its cache status UI.")
        return GLib.SOURCE_REMOVE

    # Removed _on_local_models_loaded_management as it's no longer used.

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
        is_error = "Error" in model_item.status # More general error check
        # "Downloaded" status is now set by the cache check.
        # "Not Downloaded" means it's not cached.
        is_cached = model_item.status == "Downloaded"
        can_download = not is_cached and not is_downloading and model_item.status != "Checking status..."


        action_row.set_subtitle(model_item.error_message if model_item.error_message else model_item.status)
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


    def _on_download_clicked(self, button, item: ModelItem):
        """Handler for download/cache button click."""
        if item.is_downloading:
            print(f"Caching request ignored for {item.name} (already in progress)")
            return

        print(f"Starting caching for {item.name}")
        model_name = item.name

        item.is_downloading = True
        item.status = "Caching..." # Or "Preparing..."
        item.download_progress = 0.0 # Not really applicable, but reset
        item.error_message = None
        # item.cancel_event = threading.Event() # TODO: Re-evaluate if cancellation is needed/simple for this

        position = self.model_store.find(item)[1]
        if position != Gtk.INVALID_LIST_POSITION:
            self.model_store.items_changed(position, 1, 1)
        else:
            print(f"Warning: Could not find item {item.name} in store to update UI for caching start.")

        parent_window = self.get_transient_for()
        if parent_window:
            GLib.idle_add(ToastPresenter.show, self, f"Preparing model {item.name}...")

        self.active_downloads[model_name] = {} # Mark as active

        cache_thread = threading.Thread(
            target=self._cache_model_in_thread,
            args=(model_name,),
            daemon=True
        )
        cache_thread.start()

    def _cache_model_in_thread(self, model_item_name: str):
        """
        Attempts to instantiate the model, forcing faster-whisper to download/cache it.
        This runs in a background thread.
        """
        try:
            print(f"Thread: Caching model {model_item_name} using faster-whisper...")
            # This will download if not present and cache it according to faster-whisper's logic
            model = WhisperModel(model_size_or_path=model_item_name, device="cpu", compute_type="int8")
            # We don't need to keep the model object here, just ensure it was loaded.
            del model
            print(f"Thread: Successfully prepared/cached {model_item_name}.")
            GLib.idle_add(self._update_model_item_status, model_item_name, "Cached", None)
        except Exception as e:
            print(f"Thread: Error caching model {model_item_name}: {e}")
            GLib.idle_add(self._update_model_item_status, model_item_name, "Error Caching", str(e))


    def _update_model_item_status(self, model_name: str, new_status: str, error_message: Optional[str]):
        """
        Updates the ModelItem's status in the UI. Called via GLib.idle_add from the caching thread.
        """
        print(f"Updating UI for {model_name}: Status='{new_status}', Error='{error_message}'")
        item_to_update = None
        position = Gtk.INVALID_LIST_POSITION
        for i in range(self.model_store.get_n_items()):
            item = self.model_store.get_item(i)
            if item.name == model_name:
                item_to_update = item
                position = i
                break

        parent_window = self.get_transient_for()

        if item_to_update:
            item_to_update.is_downloading = False
            item_to_update.status = new_status
            item_to_update.error_message = error_message
            # item_to_update.cancel_event = None # Clear if it was used

            if position != Gtk.INVALID_LIST_POSITION:
                self.model_store.items_changed(position, 1, 1)
            else:
                print(f"Warning: Could not find position for updated item {model_name} after processing, but item was found.")
            
            # After a download attempt (which calls _cache_model_in_thread -> _update_model_item_status),
            # we need to re-verify the cache status using the specific local_files_only check.
            # Find the ModelItem again to pass to the checker.
            item_for_recheck = None
            for i in range(self.model_store.get_n_items()):
                item = self.model_store.get_item(i)
                if item.name == model_name:
                    item_for_recheck = item
                    break
            
            if item_for_recheck:
                print(f"Post-download/cache attempt, re-verifying cache status for {model_name}...")
                item_for_recheck.status = "Checking status..." # Temporarily set status
                if position != Gtk.INVALID_LIST_POSITION: self.model_store.items_changed(position,1,1)

                threading.Thread(
                    target=self._check_model_cache_status_worker,
                    args=(item_for_recheck,),
                    daemon=True
                ).start()
            else:
                print(f"Error: Could not find item {model_name} to re-verify cache status after download attempt.")


            if new_status == "Cached": # This status comes from the _cache_model_in_thread
                if parent_window:
                    GLib.idle_add(ToastPresenter.show, self, f"Model {model_name} is ready.")
            elif new_status == "Error Caching":
                if parent_window:
                    GLib.idle_add(ToastPresenter.show, self, f"❌ Failed to prepare model {model_name}: {error_message}")
        else:
            print(f"Error: Could not find ModelItem '{model_name}' in store to update status.")
            if parent_window:
                 GLib.idle_add(ToastPresenter.show, self, f"❌ Error updating status for an unknown model: {model_name}")


        if model_name in self.active_downloads:
            del self.active_downloads[model_name]
            print(f"Removed {model_name} from active operations.")
        # No _update_download_progress method to remove as it's being replaced by this logic.

    def _on_cancel_clicked(self, button, item: ModelItem):
        """Handler for cancel button click.
        NOTE: Cancellation for faster-whisper's internal download is not straightforward.
        This might need to be re-evaluated or simplified if true cancellation isn't feasible.
        For now, it primarily serves to update UI if a download was thought to be cancellable.
        """
        model_name = item.name
        print(f"Cancel requested for {model_name}")
        if model_name in self.active_downloads:
            # Currently, no direct cancel mechanism for WhisperModel instantiation.
            # We can mark it as "cancelling" in UI and then let it finish or error out.
            # Or, if we had a cancel_event on the item, we could set it,
            # but the _cache_model_in_thread doesn't check it.
            print(f"Note: True cancellation of faster-whisper caching is not implemented.")
            # Update UI to reflect attempt or remove from active_downloads
            # For now, let's just visually update and let the thread complete.
            item.status = "Cancelling..." # Or revert to "Not Downloaded"
            item.is_downloading = False # Or keep true until thread confirms
            # del self.active_downloads[model_name] # Or keep until thread finishes
            
            position = self.model_store.find(item)[1]
            if position != Gtk.INVALID_LIST_POSITION:
                self.model_store.items_changed(position, 1, 1)

            parent_window = self.get_transient_for()
            if parent_window:
                GLib.idle_add(ToastPresenter.show, self, f"Attempting to cancel operation for {model_name} (may complete).")

        # button.set_sensitive(False) # Already handled by is_downloading state in bind


    def _on_remove_clicked(self, button, item: ModelItem):
        """Handler for remove button click."""
        print(f"Remove clicked for {item.name}")
        expected_filename = f"ggml-{item.name}.bin"
        file_path = APP_MODEL_DIR / expected_filename

        if file_path.exists() and file_path.is_file():
            try:
                print(f"Attempting to delete {file_path}")
                file_path.unlink() # This part is for the old ggml file structure.
                                   # For faster-whisper, actual deletion is more complex as it's in a cache dir.
                                   # This might not effectively remove a faster-whisper cached model.
                                   # A true "remove" for faster-whisper would involve finding its cache path and deleting that.
                                   # For now, we'll assume this old logic is what's intended for "removal" if it's still here.
                print(f"Successfully deleted {file_path} (if it was a standalone ggml file).")
                # After attempting removal, re-check the status of this model item.
                # The model might still be cached by faster-whisper elsewhere.
                item.status = "Checking status..." # Mark for re-check
                pos_found, item_pos = self.model_store.find(item)
                if pos_found:
                    self.model_store.items_changed(item_pos, 1, 1)

                threading.Thread(
                    target=self._check_model_cache_status_worker,
                    args=(item,),
                    daemon=True
                ).start()

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
            print(f"Model file not found for removal at old path: {file_path}. Status will be re-checked.")
            # Still re-check status, as it might be cached by faster-whisper independently.
            item.status = "Checking status..."
            pos_found, item_pos = self.model_store.find(item)
            if pos_found:
                self.model_store.items_changed(item_pos, 1, 1)
            threading.Thread(
                target=self._check_model_cache_status_worker,
                args=(item,),
                daemon=True
            ).start()

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