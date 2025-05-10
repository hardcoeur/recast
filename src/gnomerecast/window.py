import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Gtk, Adw, GLib, Gio, Gdk, Pango
import wave
import tempfile
import os
import re
import json # Added for JSON export
from datetime import datetime # Added for default filenames
import importlib.resources # Added for package-relative paths
import pathlib # Added for path manipulation

from typing import Optional, Any
from .audio.capture import AudioCapturer
from .views.transcript_view import TranscriptionView
from .views.initial_view import InitialView
from .transcription.transcriber import Transcriber
from .views.history_view import HistoryView
from .models.transcript_item import TranscriptItem, SegmentItem
from .utils import export as export_utils # Added
from .utils.io import atomic_write_json # Added
from .ui.toast import ToastPresenter # Added for toast framework

# Define the base path for data files within the gnomerecast package
_GNOMERECAST_DATA_ROOT = importlib.resources.files('gnomerecast') / 'data'

LANGUAGE_MAP = {"auto": "Auto Detect", "en": "English", "es": "Spanish"}
REVERSE_LANGUAGE_MAP = {v: k for k, v in LANGUAGE_MAP.items()}

MODE_MAP = {"fast": "Fast", "balanced": "Balanced", "accurate": "Accurate"}
MODE_TO_MODEL = {"fast": "tiny", "balanced": "base", "accurate": "small"}
MODEL_TO_MODE = {v: k for k, v in MODE_TO_MODEL.items()}

class GnomeRecastWindow(Adw.ApplicationWindow):
    """The main application window for GnomeRecast."""


    def __init__(self, app_menu: Optional[Gio.MenuModel] = None, **kwargs):
        super().__init__(**kwargs)

        self.settings = Gio.Settings.new("org.hardcoeur.Recast")

        self.set_title("")
        self.set_default_size(800, 600)

        self.recording_audio_capturer = None
        self.recording_audio_buffer = bytearray()

        self.transcriber = Transcriber()
        self._selected_history_transcript: Optional[TranscriptItem] = None
        self.last_export_filter_name: Optional[str] = None # Added to store last export filter

        self.header_bar = Adw.HeaderBar()
        self.header_bar.add_css_class("window-header-bar")
        self.window_title_widget = Adw.WindowTitle(title="")
        self.window_title_widget.add_css_class("window-title")

        self.main_menu_button = Gtk.MenuButton()
        self.main_menu_button.add_css_class("main-menu-button")
        self.main_menu_button.set_icon_name("open-menu-symbolic")
        self.main_menu_button.set_tooltip_text("Main Menu")
        if app_menu:
             self.main_menu_button.set_menu_model(app_menu)
        else:
             self.main_menu_button.set_sensitive(False)
             print("Warning: No app_menu model received by window, disabling menu button.")
        self.header_bar.pack_end(self.main_menu_button)

        self.reader_button = Gtk.Button(label="Reader")
        self.reader_button.set_tooltip_text("Show cleaned transcript text")
        self.reader_button.set_visible(False)
        self.reader_button.set_sensitive(False)
        self.reader_button.connect("clicked", self._on_reader_button_clicked)
        self.header_bar.pack_end(self.reader_button)

        mode_menu = Gio.Menu()
        mode_menu.append_item(Gio.MenuItem.new(MODE_MAP['accurate'], 'win.select-mode::accurate'))
        mode_menu.append_item(Gio.MenuItem.new(MODE_MAP['balanced'], 'win.select-mode::balanced'))
        mode_menu.append_item(Gio.MenuItem.new(MODE_MAP['fast'], 'win.select-mode::fast'))
        self.mode_button = Gtk.MenuButton(
            menu_model=mode_menu,
            tooltip_text="Choose transcription accuracy mode"
        )
        self.header_bar.pack_end(self.mode_button)

        language_menu = Gio.Menu()
        language_menu.append_item(Gio.MenuItem.new(LANGUAGE_MAP['auto'], 'win.select-language::auto'))
        language_menu.append_item(Gio.MenuItem.new(LANGUAGE_MAP['en'], 'win.select-language::en'))
        language_menu.append_item(Gio.MenuItem.new(LANGUAGE_MAP['es'], 'win.select-language::es'))
        self.language_button = Gtk.MenuButton(
            menu_model=language_menu,
            tooltip_text="Choose transcription language"
        )
        self.header_bar.pack_end(self.language_button)


        self.is_recording = False
        self.recording_timer_id = None
        self.recording_start_time = None

        self.recording_controls_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        rec_icon = Gtk.Image(icon_name="media-record-symbolic")
        self.recording_timer_label = Gtk.Label(label="00:00")
        self.stop_recording_button = Gtk.Button(label="Stop Recording")
        self.stop_recording_button.connect("clicked", self._on_stop_recording_clicked)

        self.recording_controls_box.append(rec_icon)
        self.recording_controls_box.append(self.recording_timer_label)
        self.recording_controls_box.append(self.stop_recording_button)
        self.recording_controls_box.set_visible(False)

        self.header_bar.set_title_widget(self.window_title_widget)


        self.initial_view = InitialView()
        self.transcript_view = TranscriptionView()
        # Pass the application instance to HistoryView
        app_instance = self.get_application()
        self.history_view = HistoryView(application=app_instance, on_transcript_selected=self._load_transcript_from_history)
        self.history_view.connect("transcript-selected", self._on_history_item_selected)


        self.initial_view.connect("start-recording", self.start_recording_ui)
        self.initial_view.connect("stop-recording", self._on_stop_recording_clicked)

        self.leaflet = Adw.Leaflet()
        self.leaflet.set_hexpand(True)
        self.leaflet.set_vexpand(True)
        self.leaflet.set_can_unfold(False)
        self.leaflet.set_can_navigate_back(False)
        self.leaflet.set_can_navigate_forward(False)

        self.leaflet.append(self.initial_view)
        initial_page = self.leaflet.get_page(self.initial_view)
        initial_page.set_property("name", "initial")

        self.leaflet.append(self.transcript_view)
        transcript_page = self.leaflet.get_page(self.transcript_view)
        transcript_page.set_property("name", "transcript")

        self.leaflet.append(self.history_view)
        history_page = self.leaflet.get_page(self.history_view)
        history_page.set_property("name", "history")

        self._set_active_view("initial")

        drop_target = Gtk.DropTarget.new(Gio.File, Gdk.DragAction.COPY)
        drop_target.connect("drop", self._on_file_drop)
        self.leaflet.add_controller(drop_target)

        toolbar_view = Adw.ToolbarView()
        toolbar_view.add_top_bar(self.header_bar)

        # Initialize ToastOverlay and wrap the leaflet
        self.toast_overlay = Adw.ToastOverlay()
        self.toast_overlay.set_child(self.leaflet) # Leaflet is the content over which toasts appear
        toolbar_view.set_content(self.toast_overlay) # ToolbarView now manages the ToastOverlay
        ToastPresenter.attach(self.toast_overlay) # Register with singleton presenter

        main_hbox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)

        self.sidebar_vbox = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=6,
            margin_top=12,
            margin_bottom=12,
            margin_start=6,
            margin_end=6,
            width_request=32,
            height_request=32
        )
        main_hbox.append(self.sidebar_vbox)


        main_hbox.append(toolbar_view)
        toolbar_view.set_hexpand(True)
        toolbar_view.set_vexpand(True)

        self.set_content(main_hbox)

        # Diagnostic: Try loading 'compass' as a themed icon
        home_button = Gtk.Button()
        home_button.set_icon_name("compass-symbolic") # Assuming 'compass-symbolic' is the installed name for compass-symbolic.svg
        home_button.set_tooltip_text("Home (Themed Icon Test)")
        home_button.connect("clicked", self.show_initial_view)
        self.sidebar_vbox.append(home_button)
        self._add_sidebar_button("icons/headset.png", self.show_transcript_view, "Transcribe")
        self._add_sidebar_button("icons/history.png", self.show_history_view, "History")


        self._create_language_action()
        self._create_mode_action()
        self._create_export_action()
        self._create_save_action()
        self._create_open_action() # Added

        self._update_language_button_label()
        self._update_mode_button_label()

        self.settings.connect("changed::target-language", lambda s, k: self._update_language_button_label())
        self.settings.connect("changed::auto-detect-language", lambda s, k: self._update_language_button_label())
        self.settings.connect("changed::default-model", lambda s, k: self._update_mode_button_label())


    def _add_sidebar_button(self, icon_path_str: str, callback, tooltip_text):
        """Creates a Gtk.Button with an icon, connects it, and adds it to the sidebar.
        icon_path_str should be relative to _GNOMERECAST_DATA_ROOT (e.g., 'icons/headset.png')
        """
        icon_resource_ref = _GNOMERECAST_DATA_ROOT / icon_path_str
        with importlib.resources.as_file(icon_resource_ref) as icon_file_path:
            icon = Gtk.Picture.new_for_filename(str(icon_file_path))
        icon.set_content_fit(Gtk.ContentFit.COVER)
        icon.set_can_shrink(False)
        icon.set_size_request(32, 32)
        button = Gtk.Button()
        button.set_child(icon)
        button.set_tooltip_text(tooltip_text)
        button.connect("clicked", callback)
        self.sidebar_vbox.append(button)

    def _set_active_view(self, view_name: str):
        """
        Centralized method to switch the visible child in the leaflet
        and update the state of related actions (e.g., export).
        """
        if hasattr(self, 'leaflet') and self.leaflet:
            self.leaflet.set_visible_child_name(view_name)
            is_transcript_view_active = (view_name == "transcript")
            
            export_action = self.lookup_action("export-transcript")
            if export_action:
                # Enable export if transcript view is active AND has content
                has_content_for_export = hasattr(self.transcript_view, 'has_content') and self.transcript_view.has_content()
                export_action.set_enabled(is_transcript_view_active and has_content_for_export)

            save_action = self.lookup_action("save-transcript")
            if save_action:
                 # Enable save if transcript view is active AND has content
                has_content_for_save = hasattr(self.transcript_view, 'has_content') and self.transcript_view.has_content()
                save_action.set_enabled(is_transcript_view_active and has_content_for_save)


            if hasattr(self, "reader_button"):
               is_history_view = (view_name == "history")
               self.reader_button.set_visible(is_history_view)
               if not is_history_view:
                    self.reader_button.set_sensitive(False)
                    self._selected_history_transcript = None

            print(f"GnomeRecastWindow: Switched active view to '{view_name}'.")
        else:
            print(f"GnomeRecastWindow: Error - Leaflet not found when trying to set active view to '{view_name}'.")


    def _on_recording_audio_data(self, audio_data):
        """Callback function to receive audio data chunks during recording."""
        if self.is_recording and self.recording_audio_buffer is not None:
            self.recording_audio_buffer.extend(audio_data)

    def show_transcript_view(self, sender, transcript_item=None):
        """
        Handles the 'history-item-activated' signal or direct calls to show a transcript.
        If called from sidebar (no transcript_item), it just navigates to the view.
        Switches the main view to the transcript view and loads the selected item if provided.
        """
        from .models.transcript_item import TranscriptItem

        if transcript_item:
            if not isinstance(transcript_item, TranscriptItem):
                print(f"Error in show_transcript_view: Expected TranscriptItem, got {type(transcript_item)}")
                return
            print(f"GnomeRecastWindow: Received history-item-activated for {transcript_item.uuid}")
        else:
            if isinstance(sender, Gtk.Button):
                 print("GnomeRecastWindow: Sidebar 'Transcribe' button clicked. Navigating to transcript view.")
            else:
                 print("GnomeRecastWindow: show_transcript_view called without item. Navigating to transcript view.")
            self._set_active_view("transcript")
            return

        if hasattr(self, 'transcript_view') and self.transcript_view:
            print(f"GnomeRecastWindow: Loading transcript {transcript_item.uuid} into view.")
            self.transcript_view.load_transcript(transcript_item)
            print(f"GnomeRecastWindow: Setting visible child to transcript_view.")
            self._set_active_view("transcript")
        else:
            print("Error in show_transcript_view: TranscriptView not initialized or accessible.")


    def show_initial_view(self, button=None):
            """
            Switches the main view back to the initial view and resets relevant state.
            """
            print("GnomeRecastWindow: Switching back to initial view.")
            if hasattr(self, 'transcript_view') and self.transcript_view:
                if hasattr(self.transcript_view, 'player_controls') and self.transcript_view.player_controls:
                    if hasattr(self.transcript_view.player_controls, 'player') and self.transcript_view.player_controls.player:
                        print("GnomeRecastWindow: Stopping media player in transcript view.")
                        self.transcript_view.player_controls.player.stop()
                else:
                    print("GnomeRecastWindow: TranscriptView has no player_controls attribute.")
            else:
                print("GnomeRecastWindow: TranscriptView not found, cannot stop player.")


            self._set_active_view("initial")

    def show_history_view(self, button=None):
        """Switches the main view to the history view."""
        print("GnomeRecastWindow: Switching to history view.")
        self._set_active_view("history")
        if hasattr(self, 'reader_button'):
            self.reader_button.set_sensitive(False)
        self._selected_history_transcript = None


    def start_recording_ui(self, *args):
        """Configures the UI to show recording controls."""
        if self.is_recording:
            return

        print("GnomeRecastWindow: Starting recording UI.")
        self.is_recording = True

        print("GnomeRecastWindow: Starting audio capture.")
        self.recording_audio_buffer.clear()
        try:
            self.recording_audio_capturer = AudioCapturer(
                settings=self.settings,
                data_callback=self._on_recording_audio_data
            )
            self.recording_audio_capturer.start()
            print("GnomeRecastWindow: AudioCapturer started.")
        except Exception as e:
            print(f"GnomeRecastWindow: Error starting AudioCapturer: {e}")
            self.stop_recording_ui()
            return

        self.window_title_widget.set_visible(False)
        self.header_bar.set_title_widget(self.recording_controls_box)
        self.recording_controls_box.set_visible(True)

        self.recording_timer_label.set_text("00:00")
        self.recording_start_time = GLib.get_monotonic_time()
        if self.recording_timer_id:
                GLib.source_remove(self.recording_timer_id)
        self.recording_timer_id = GLib.timeout_add_seconds(1, self._update_recording_timer)
        print("GnomeRecastWindow: Recording UI started.")


    def stop_recording_ui(self):
        """Configures the UI back to the default state after recording stops."""
        if not self.is_recording:
            return

        print("GnomeRecastWindow: Stopping recording UI.")
        self.is_recording = False

        if self.recording_timer_id:
            GLib.source_remove(self.recording_timer_id)
            self.recording_timer_id = None
            print("GnomeRecastWindow: Recording timer stopped.")

        self.recording_controls_box.set_visible(False)
        self.header_bar.set_title_widget(self.window_title_widget)
        self.window_title_widget.set_visible(True)
        print("GnomeRecastWindow: Recording UI stopped.")
        if hasattr(self, 'initial_view') and self.initial_view:
             self.initial_view.reset_button_state()


    def _update_recording_timer(self):
        """Updates the recording timer label every second."""
        if not self.is_recording or self.recording_start_time is None:
            print("GnomeRecastWindow: Timer update called but not recording. Stopping timer.")
            self.recording_timer_id = None
            return GLib.SOURCE_REMOVE

        now = GLib.get_monotonic_time()
        elapsed_us = now - self.recording_start_time
        elapsed_s = int(elapsed_us // 1_000_000)

        minutes = elapsed_s // 60
        seconds = elapsed_s % 60
        time_str = f"{str(minutes).zfill(2)}:{str(seconds).zfill(2)}"
        self.recording_timer_label.set_text(time_str)

        return GLib.SOURCE_CONTINUE


    def _on_stop_recording_clicked(self, *args):
        """Handles the stop-recording signal or button click."""
        print("GnomeRecastWindow: Stop recording button clicked.")

        if self.recording_audio_capturer:
            print("GnomeRecastWindow: Stopping audio capture.")
            self.recording_audio_capturer.stop()
            # Ensure cleanup is called, potentially on idle_add if it involves GLib operations
            GLib.idle_add(self.recording_audio_capturer.cleanup_on_destroy)
            self.recording_audio_capturer = None
            print("GnomeRecastWindow: AudioCapturer stopped and cleanup scheduled.")
        else:
            print("GnomeRecastWindow: No active audio capturer found to stop.")

        self.stop_recording_ui()

        if self.recording_audio_buffer:
            print(f"GnomeRecastWindow: Saving recorded audio buffer ({len(self.recording_audio_buffer)} bytes).")
            try:
                with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as temp_file:
                    temp_wav_path = temp_file.name

                print(f"GnomeRecastWindow: Writing to temporary WAV file: {temp_wav_path}")
                with wave.open(temp_wav_path, 'wb') as wf:
                    wf.setnchannels(1)
                    wf.setsampwidth(2)
                    wf.setframerate(16000)
                    wf.writeframes(self.recording_audio_buffer)

                self._start_transcription_process([temp_wav_path])
            except Exception as e:
                print(f"GnomeRecastWindow: Error saving recording to WAV file: {e}")

            finally:
                self.recording_audio_buffer.clear()
                print("GnomeRecastWindow: Audio buffer cleared.")
        else:
            print("GnomeRecastWindow: No audio recorded.")

    def on_segment_generated(self, segment_dict: dict):
        """Handles a single segment generated by the transcriber."""
        print(f"Window: Received segment [{segment_dict.get('start', '?'):.2f}s->{segment_dict.get('end', '?'):.2f}s], scheduling UI update.")
        if 'start' in segment_dict and 'start_ms' not in segment_dict:
            segment_dict["start_ms"] = int(float(segment_dict["start"]) * 1000)
        if 'end' in segment_dict and 'end_ms' not in segment_dict:
            segment_dict["end_ms"] = int(float(segment_dict["end"]) * 1000)

        GLib.idle_add(self._idle_add_segment_callback, segment_dict)

    def _idle_add_segment_callback(self, segment_dict):
        """Helper function called by GLib.idle_add to add a segment with debugging."""
        print(f"Window (idle_add): Calling add_segment for [{segment_dict.get('start', '?'):.2f}s->{segment_dict.get('end', '?'):.2f}s].")
        if hasattr(self, 'transcript_view') and self.transcript_view:
            self.transcript_view.add_segment(segment_dict)
        else:
            print("Window (idle_add): Error - TranscriptView not found when trying to add segment.")
        return GLib.SOURCE_REMOVE

    def _start_transcription_process(self, file_paths: list, cleanup_paths: list | None = None):
        """
        Starts the transcription process for the given file paths, integrating progress
        and results directly into TranscriptionView. Optionally cleans up specified
        temporary files upon successful completion.

        Args:
            file_paths: A list of absolute paths to audio/video files.
            cleanup_paths: An optional list of absolute paths to files that should be
                            deleted after successful transcription.
        """
        if not file_paths:
            print("GnomeRecastWindow: No file paths provided for transcription.")
            return

        self.transcript_view.reset_view()

        GLib.idle_add(self._set_active_view, "transcript")

        def on_progress(fraction: float, total_segments: int = 0, completed_segments: int = 0):
            """Callback for transcription progress updates."""
            GLib.idle_add(self.transcript_view.update_progress, fraction, total_segments, completed_segments)

        # Updated on_completion to handle new parameters from transcriber
        def on_completion(status: str, transcript_segments: list, saved_json_path: Optional[str], save_error_message: Optional[str]):
            """Handles transcription completion, cleanup, and final state, including save status."""
            print(f"GnomeRecastWindow: Transcription process finished. Status: {status}, Saved JSON: {saved_json_path}, Save Error: {save_error_message}")

            # Determine primary success based on transcription itself
            transcription_successful = status == 'completed' or status == 'completed_save_failed'

            if cleanup_paths and transcription_successful: # Cleanup if transcription part was okay
                print(f"GnomeRecastWindow: Transcription part successful. Attempting cleanup for: {cleanup_paths}")
                for path in cleanup_paths:
                    try:
                        if os.path.exists(path):
                            os.remove(path)
                            print(f"GnomeRecastWindow: Successfully removed temporary file: {path}")
                        else:
                            print(f"GnomeRecastWindow: Temporary file not found for cleanup: {path}")
                    except OSError as e:
                        print(f"GnomeRecastWindow: Error removing temporary file {path}: {e}")
            elif cleanup_paths:
                print(f"GnomeRecastWindow: Transcription status was '{status}'. Skipping cleanup for: {cleanup_paths}")

            if status == 'completed': # Transcription and save successful
                toast_message = f"Saved ✓ {os.path.basename(saved_json_path)}" if saved_json_path else "Transcription complete, save path unknown."
                ToastPresenter.show(self, toast_message)
                GLib.idle_add(self.history_view.refresh_list)
                print(f"GnomeRecastWindow: Transcription and save successful. Segments added in real-time. History refreshed.")
            elif status == 'completed_save_failed':
                base_filename = os.path.basename(cleanup_paths[0]) if cleanup_paths else "transcript" # Get a filename for the toast
                toast_message = f"❌ Could not save {base_filename}: {save_error_message or 'Unknown error'}"
                ToastPresenter.show(self, toast_message)
                # Transcription itself was okay, segments might be in view, but not persisted.
                # Decide if history should be refreshed if a .tmp file might exist or if it's an overwrite fail.
                # For now, let's not refresh history if save failed, to avoid showing a non-existent item.
                print(f"GnomeRecastWindow: Transcription successful, but save failed. Segments might be in view.")
            elif status == 'error':
                toast_message = f"❌ Transcription failed: {save_error_message or 'Unknown error'}"
                ToastPresenter.show(self, toast_message)
                print(f"GnomeRecastWindow: Transcription failed. Error: {save_error_message}")
                if hasattr(self, 'initial_view') and self.initial_view:
                    GLib.idle_add(self.initial_view.reset_button_state)
                GLib.idle_add(self.show_initial_view)
            elif status == 'cancelled':
                ToastPresenter.show(self, "Transcription cancelled.")
                print(f"GnomeRecastWindow: Transcription cancelled by user.")
                # Optionally, revert to initial view or leave as is
                if hasattr(self, 'initial_view') and self.initial_view:
                    GLib.idle_add(self.initial_view.reset_button_state)
                GLib.idle_add(self.show_initial_view) # Or stay on transcript view if partially filled
            elif status == 'no_files':
                ToastPresenter.show(self, "No files selected for transcription.")
            else: # Other unexpected statuses
                ToastPresenter.show(self, f"Transcription finished with status: {status}")
                if hasattr(self, 'initial_view') and self.initial_view:
                    GLib.idle_add(self.initial_view.reset_button_state)
                GLib.idle_add(self.show_initial_view)


        self.transcriber.start_transcription(
            file_paths=file_paths,
            progress_callback=on_progress,
            segment_callback=self.on_segment_generated,
            completion_callback=on_completion
        )
        print(f"GnomeRecastWindow: Transcription started for {file_paths}")


    def _on_file_drop(self, drop_target, value, x, y):
        """Handles the 'drop' signal from the main view stack's drop target."""
        print(f"GnomeRecastWindow: Drop detected. Value type: {type(value)}")
        if isinstance(value, Gio.File):
            file_path = value.get_path()
            if file_path:
                print(f"GnomeRecastWindow: File dropped: {file_path}")
                if os.path.exists(file_path) and os.path.isfile(file_path):
                    if file_path.lower().endswith(".json"):
                        print(f"Attempting to import (drag & drop) JSON transcript: {file_path}")
                        self._import_transcript_file(file_path) # Use the new import handler
                    else:
                        # Assume it's an audio/video file for transcription
                        print(f"Attempting to transcribe (drag & drop) media file: {file_path}")
                        self.transcript_view.reset_view()
                        self._set_active_view("transcript")
                        self._start_transcription_process([file_path], cleanup_paths=[])
                    return True
                else:
                    print(f"GnomeRecastWindow: Dropped path is not a valid file: {file_path}")
                    return False
            else:
                print("GnomeRecastWindow: Dropped Gio.File has no path.")
                return False
        elif isinstance(value, Gtk.StringObject):
                text = value.get_string()
                print(f"GnomeRecastWindow: Text dropped (ignored): {text[:50]}...")
                return False
        else:
            print(f"GnomeRecastWindow: Unsupported drop value type: {type(value)}")
            return False

    def _create_mode_action(self):
        """Creates and adds a stateful action for mode selection."""
        action = Gio.SimpleAction.new_stateful(
            "select-mode", GLib.VariantType.new('s'), GLib.Variant.new_string(self._get_current_mode_key())
        )
        action.connect("change-state", self._on_select_mode)
        self.add_action(action)
        print("Action 'win.select-mode' created.")

    def _create_language_action(self):
        """Creates and adds a stateful action for language selection."""
        action = Gio.SimpleAction.new_stateful(
            "select-language", GLib.VariantType.new('s'), GLib.Variant.new_string(self._get_current_language_key())
        )
        action.connect("change-state", self._on_select_language)
        self.add_action(action)
        print("Action 'win.select-language' created.")

    def _create_export_action(self):
        """Creates and adds a simple action for exporting the transcript."""
        action = Gio.SimpleAction.new("export-transcript", None)
        action.connect("activate", self._on_export_transcript)
        action.set_enabled(False) # Initially disabled, enabled when transcript view is active
        self.add_action(action)
        print("Action 'win.export-transcript' created.")

    def _create_save_action(self):
        """Creates and adds a simple action for saving the current transcript."""
        action = Gio.SimpleAction.new("save-transcript", None)
        action.connect("activate", self._on_save_transcript)
        # Sensitivity will be managed based on transcript_view content
        # For now, let's assume it's enabled if transcript_view has content.
        # This will be checked in _on_save_transcript or by a separate update method.
        action.set_enabled(False) # Start disabled, enable when content is available
        self.add_action(action)
        # Accelerators for window actions are set on the application
        app = self.get_application()
        if app:
            app.set_accels_for_action("win.save-transcript", ["<Control>s"])
        print("Action 'win.save-transcript' (Ctrl+S) created.")

    def _create_open_action(self):
        """Creates and adds a simple action for opening a transcript or media file."""
        action = Gio.SimpleAction.new("open-file", None)
        action.connect("activate", self._on_open_file_activate)
        self.add_action(action)
        app = self.get_application()
        if app:
            # Using "win.open-file" to be consistent with other window actions if it's window-specific.
            # If it's a global app action that could be triggered without the window, "app.open-file" is fine.
            # Let's assume it's tied to this window's context for now.
            app.set_accels_for_action("win.open-file", ["<Control>o"])
        print("Action 'win.open-file' (Ctrl+O) created.")


    def _on_history_item_selected(self, history_view, transcript_item):
        """Updates UI when a transcript item is selected in history view."""
        print(f"Transcript selected: {transcript_item.output_filename}")
        self._selected_history_transcript = transcript_item
        if hasattr(self, 'reader_button'):
            # Enable reader button only if the selected item has segments
            self.reader_button.set_sensitive(bool(transcript_item and transcript_item.segments))

    def _on_select_mode(self, action, value):
        """Handles state change for the mode selection action."""
        new_mode_key = value.get_string()
        print(f"Changing mode to: {new_mode_key}")

        if new_mode_key in MODE_TO_MODEL:
            new_model_size = MODE_TO_MODEL[new_mode_key]
            self.settings.set_string("default-model", new_model_size)
            action.set_state(value)
        else:
            print(f"Warning: Unknown mode key selected: {new_mode_key}")

    def _on_select_language(self, action, value):
        """Handles state change for the language selection action."""
        new_lang_key = value.get_string()
        print(f"Changing language to: {new_lang_key}")

        if new_lang_key == "auto":
            self.settings.set_boolean("auto-detect-language", True)
        elif new_lang_key in LANGUAGE_MAP:
            self.settings.set_boolean("auto-detect-language", False)
            self.settings.set_string("target-language", new_lang_key)
        else:
            print(f"Warning: Unknown language key selected: {new_lang_key}")
            return

        action.set_state(value)


    def _get_current_mode_key(self) -> str:
        """Gets the current mode key based on GSettings."""
        current_model = self.settings.get_string("default-model")
        return MODEL_TO_MODE.get(current_model, "balanced")

    def _get_current_language_key(self) -> str:
        """Gets the current language key based on GSettings."""
        if self.settings.get_boolean("auto-detect-language"):
            return "auto"
        else:
            return self.settings.get_string("target-language")

    def _update_mode_button_label(self):
        """Updates the mode button label based on the current GSettings."""
        current_mode_key = self._get_current_mode_key()
        label = MODE_MAP.get(current_mode_key, "Unknown Mode")
        self.mode_button.set_label(label)
        mode_action = self.lookup_action("select-mode")
        if mode_action and mode_action.get_state().get_string() != current_mode_key:
                mode_action.set_state(GLib.Variant.new_string(current_mode_key))
        print(f"Mode button label updated to: {label}")

    def _update_language_button_label(self):
        """Updates the language button label based on the current GSettings."""
        current_lang_key = self._get_current_language_key()
        label = LANGUAGE_MAP.get(current_lang_key, "Unknown Lang")
        self.language_button.set_label(label)
        lang_action = self.lookup_action("select-language")
        if lang_action and lang_action.get_state().get_string() != current_lang_key:
                lang_action.set_state(GLib.Variant.new_string(current_lang_key))
        print(f"Language button label updated to: {label}")


    def _on_export_transcript(self, action, param):
        """Handles the 'activate' signal for the 'export-transcript' action."""
        print("Export Transcript action activated.")

        if not (hasattr(self, 'transcript_view') and self.transcript_view and
                hasattr(self.transcript_view, 'has_content') and self.transcript_view.has_content()):
            ToastPresenter.show(self, "Nothing to export.")
            print("Export action: No active transcript content to export.")
            return

        current_item = self.transcript_view.get_current_item()
        if not current_item:
            # Fallback: try to construct a temporary item from view data if no item is formally loaded
            # This case should be less common if transcription/load always sets current_item.
            # For now, we require a current_item to get metadata like output_filename_base.
             view_data = self.transcript_view.get_transcript_data_for_saving()
             if not view_data or not view_data.get("segments"):
                ToastPresenter.show(self, "No transcript data available to export.")
                return
            # Create a temporary TranscriptItem for export if one isn't set.
            # This is a simplified approach.
             current_item = TranscriptItem(
                source_path="", # No source path for an unsaved item
                transcript_text=view_data.get("text", ""),
                segments=[SegmentItem(**s) for s in view_data.get("segments", [])], # Reconstruct SegmentItem objects
                language=view_data.get("language", "en")
            )
             current_item.output_filename = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_export"


        dialog = Gtk.FileDialog.new()
        dialog.set_title("Export Transcript As...")

        # Define file filters
        filters = Gio.ListStore.new(Gtk.FileFilter)
        
        txt_filter = Gtk.FileFilter(); txt_filter.set_name("Plain Text (*.txt)"); txt_filter.add_pattern("*.txt")
        filters.append(txt_filter)
        
        md_filter = Gtk.FileFilter(); md_filter.set_name("Markdown (*.md)"); md_filter.add_pattern("*.md")
        filters.append(md_filter)
        
        srt_filter = Gtk.FileFilter(); srt_filter.set_name("SubRip Subtitle (*.srt)"); srt_filter.add_pattern("*.srt")
        filters.append(srt_filter)
        
        json_filter = Gtk.FileFilter(); json_filter.set_name("JSON Transcript (*.json)"); json_filter.add_pattern("*.json")
        filters.append(json_filter)
        
        dialog.set_filters(filters)

        # Pre-select last used filter
        if self.last_export_filter_name:
            for i in range(filters.get_n_items()):
                f = filters.get_item(i)
                if f.get_name() == self.last_export_filter_name:
                    dialog.set_default_filter(f)
                    break
        else:
            dialog.set_default_filter(txt_filter) # Default to TXT if no previous

        # Default filename
        base_name = os.path.splitext(current_item.output_filename)[0] if current_item.output_filename else "transcript"
        # Initial extension will be set by the dialog based on the selected filter if possible,
        # but Gtk.FileDialog does not directly use the filter for the initial name's extension.
        # We'll adjust it in the callback. For now, just set a base name.
        dialog.set_initial_name(base_name) # e.g., "YYYYMMDD_HHMMSS_new" or "transcript_export"

        print("Showing file export dialog...")
        dialog.save(self, None, self._on_export_dialog_finish, current_item)


    def _on_export_dialog_finish(self, dialog, result, transcript_item: TranscriptItem):
        """Callback executed after the user selects a file in the export dialog."""
        try:
            gfile: Optional[Gio.File] = dialog.save_finish(result)
            if gfile:
                target_path = gfile.get_path()
                if not target_path:
                    ToastPresenter.show(self, "❌ Invalid export path selected.")
                    return

                selected_filter = dialog.get_filter()
                if selected_filter:
                    self.last_export_filter_name = selected_filter.get_name()
                
                # Determine export format based on filename extension or selected filter
                # Gtk.FileDialog doesn't always enforce the extension from the filter on the Gio.File,
                # so checking the path is more reliable.
                file_ext = os.path.splitext(target_path)[1].lower()
                
                export_format = None
                if file_ext == ".txt":
                    export_format = "txt"
                elif file_ext == ".md":
                    export_format = "md"
                elif file_ext == ".srt":
                    export_format = "srt"
                elif file_ext == ".json":
                    export_format = "json"
                else:
                    # Fallback if extension is missing or unknown, try to infer from filter name
                    if self.last_export_filter_name:
                        if "Plain Text" in self.last_export_filter_name: export_format = "txt"; target_path += ".txt"
                        elif "Markdown" in self.last_export_filter_name: export_format = "md"; target_path += ".md"
                        elif "SubRip" in self.last_export_filter_name: export_format = "srt"; target_path += ".srt"
                        elif "JSON" in self.last_export_filter_name: export_format = "json"; target_path += ".json"
                
                if not export_format:
                    ToastPresenter.show(self, "❌ Unknown export format. Please select a filter or use a known extension.")
                    return

                print(f"Attempting to export transcript to: {target_path} as {export_format}")

                app = self.get_application()
                if not app or not hasattr(app, 'io_pool') or not app.io_pool:
                    ToastPresenter.show(self, "❌ Export failed: Thread pool error.")
                    return

                def export_io_operation():
                    try:
                        content_to_write: Any = ""
                        is_binary_write = False

                        if export_format == "txt":
                            content_to_write = export_utils.export_to_txt(transcript_item)
                        elif export_format == "md":
                            content_to_write = export_utils.export_to_md(transcript_item)
                        elif export_format == "srt":
                            content_to_write = export_utils.export_to_srt(transcript_item)
                        elif export_format == "json":
                            # Use the TranscriptItem's to_dict method for spec-compliant JSON
                            content_to_write = transcript_item.to_dict()
                            # atomic_write_json handles json.dump internally
                            atomic_write_json(content_to_write, target_path)
                            ToastPresenter.show(self, f"Exported ✓ {os.path.basename(target_path)}")
                            return # atomic_write_json handles writing

                        # For text-based formats
                        with open(target_path, "w", encoding='utf-8') as f:
                            f.write(content_to_write)
                        
                        ToastPresenter.show(self, f"Exported ✓ {os.path.basename(target_path)}")

                    except Exception as e_io:
                        print(f"Error during export I/O to {target_path}: {e_io}")
                        ToastPresenter.show(self, f"❌ Export failed: {e_io}")
                
                app.io_pool.submit(export_io_operation)

            else: # User cancelled
                print("Export operation cancelled by user.")
                # No toast for cancellation typically
        except GLib.Error as e:
            if e.matches(Gio.io_error_quark(), Gio.IOErrorEnum.CANCELLED):
                print("Export operation cancelled by user (GLib.Error).")
            else:
                print(f"GLib error during export dialog: {e}")
                ToastPresenter.show(self, f"❌ Export error: {e.code.value_nick}")
        except Exception as e_main:
            print(f"Unexpected error during export dialog callback: {e_main}")
            ToastPresenter.show(self, f"❌ Unexpected export error.")


    def _load_transcript_from_history(self, transcript_item: TranscriptItem):
        """
        Loads a TranscriptItem (selected from history) into the transcript view.
        Uses TranscriptView.load_transcript() directly.
        """
        if not transcript_item:
            print("Error: _load_transcript_from_history (double-click handler) called with None item.")
            if hasattr(self, 'reader_button'):
                self.reader_button.set_sensitive(False)
            self._selected_history_transcript = None
            return
        
        print(f"GnomeRecastWindow: _load_transcript_from_history called for item: {transcript_item.uuid if transcript_item else 'None'}")

        self._selected_history_transcript = transcript_item # Keep track of selected item for Reader button etc.
        if hasattr(self, 'reader_button'):
            self.reader_button.set_sensitive(bool(transcript_item.segments)) # Enable reader if segments exist
            print(f"Reader button sensitivity set for item {transcript_item.uuid}")

        if not hasattr(self, 'transcript_view') or not self.transcript_view:
            print("Error: TranscriptView not available to load history.")
            return

        print(f"GnomeRecastWindow: Queuing transcript_view.load_transcript for history item {transcript_item.uuid}")
        # The load_transcript method in TranscriptView now handles resetting and adding segments.
        GLib.idle_add(self.transcript_view.load_transcript, transcript_item)
        # Ensure _set_active_view is also called via idle_add to run on the main thread after load_transcript might have started
        GLib.idle_add(self._set_active_view, "transcript")
        print(f"GnomeRecastWindow: _load_transcript_from_history completed for {transcript_item.uuid}")

    def _on_open_file_activate(self, action, param):
        """Handles activation of the 'open-file' action (e.g., Ctrl+O or menu)."""
        print("Open File action activated.")
        dialog = Gtk.FileDialog.new()
        dialog.set_title("Open Transcript or Media File")
        # dialog.set_accept_label("Open") # Already default

        # Create filters
        json_filter = Gtk.FileFilter()
        json_filter.set_name("Transcript Files (*.json)")
        json_filter.add_mime_type("application/json")
        json_filter.add_pattern("*.json")

        # Common audio formats (extend as needed)
        audio_video_filter = Gtk.FileFilter()
        audio_video_filter.set_name("Audio/Video Files")
        # General types
        audio_video_filter.add_mime_type("audio/*")
        audio_video_filter.add_mime_type("video/*")
        # Specific common patterns (examples)
        audio_video_filter.add_pattern("*.mp3")
        audio_video_filter.add_pattern("*.wav")
        audio_video_filter.add_pattern("*.ogg")
        audio_video_filter.add_pattern("*.flac")
        audio_video_filter.add_pattern("*.mp4")
        audio_video_filter.add_pattern("*.mkv")
        audio_video_filter.add_pattern("*.mov")
        audio_video_filter.add_pattern("*.webm")


        all_supported_filter = Gtk.FileFilter()
        all_supported_filter.set_name("All Supported Files")
        all_supported_filter.add_filter(json_filter)
        all_supported_filter.add_filter(audio_video_filter)


        filters = Gio.ListStore.new(Gtk.FileFilter)
        filters.append(all_supported_filter) # Add combined filter first
        filters.append(json_filter)
        filters.append(audio_video_filter)
        
        dialog.set_filters(filters)
        dialog.set_default_filter(all_supported_filter) # Default to showing all supported

        # Set initial folder (optional, e.g., user's documents or last used)
        # For now, let it default or use a standard location like home or documents
        # default_folder = Gio.File.new_for_path(os.path.expanduser("~"))
        # dialog.set_initial_folder(default_folder)

        dialog.open(self, None, self._on_open_file_dialog_finish)

    def _on_open_file_dialog_finish(self, dialog, result):
        """Callback for Gtk.FileDialog.open()."""
        try:
            file: Optional[Gio.File] = dialog.open_finish(result)
            if file:
                file_path = file.get_path()
                if not file_path or not os.path.isfile(file_path):
                    ToastPresenter.show(self, f"❌ Invalid file selected.")
                    print(f"Open dialog: Invalid file path received: {file_path}")
                    return

                print(f"File selected for opening: {file_path}")
                
                # Check file extension to decide action
                if file_path.lower().endswith(".json"):
                    print(f"Attempting to import JSON transcript: {file_path}")
                    # This will call the import pipeline defined in Phase 4
                    self._import_transcript_file(file_path) # This method needs to be created
                else:
                    # Assume it's an audio/video file for transcription
                    print(f"Attempting to transcribe media file: {file_path}")
                    self.transcript_view.reset_view() # Reset view before starting new transcription
                    self._set_active_view("transcript")
                    # The _start_transcription_process method handles its own threading for transcription
                    self._start_transcription_process([file_path], cleanup_paths=[]) # No cleanup for user-opened files
            else:
                print("Open file operation cancelled by user.")
                # No toast needed for cancellation usually
        except GLib.Error as e:
            if e.matches(Gio.io_error_quark(), Gio.IOErrorEnum.CANCELLED):
                print("Open file operation cancelled by user (GLib.Error).")
            else:
                print(f"GLib error during file open dialog: {e}")
                ToastPresenter.show(self, f"❌ Error opening file: {e.code.value_nick}")
        except Exception as e:
            print(f"Unexpected error during file open dialog callback: {e}")
            ToastPresenter.show(self, f"❌ Unexpected error opening file.")


    def _import_transcript_file(self, json_file_path: str):
        """
        Handles the import of an external JSON transcript file.
        This implements Phase 4 of the plan.
        """
        app = self.get_application()
        if not app or not hasattr(app, 'io_pool') or not app.io_pool:
            ToastPresenter.show(self, "❌ Import failed: Thread pool error.")
            return

        def import_operation():
            try:
                # 1. Validation (using TranscriptItem.load_from_json which now does strict validation)
                print(f"Import operation: Validating {json_file_path}")
                loaded_item = TranscriptItem.load_from_json(json_file_path)
                
                transcripts_dir = os.path.join(GLib.get_user_data_dir(), 'GnomeRecast', 'transcripts')
                os.makedirs(transcripts_dir, exist_ok=True)
                
                original_basename = os.path.splitext(os.path.basename(json_file_path))[0]
                new_timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
                
                uuid_collision = False
                colliding_file_path = None
                # Basic UUID collision check (can be improved for performance on many files)
                for entry in os.scandir(transcripts_dir):
                    if entry.is_file() and entry.name.lower().endswith(".json"):
                        try:
                            temp_existing_item = TranscriptItem.load_from_json(os.path.join(transcripts_dir, entry.name))
                            if temp_existing_item.uuid == loaded_item.uuid:
                                uuid_collision = True
                                colliding_file_path = os.path.join(transcripts_dir, entry.name)
                                break
                        except Exception: # Ignore errors in existing files for this check
                            continue
                
                action_taken = "copy" # Default action
                if uuid_collision:
                    # Simplified: default to "keep_both" to avoid complex synchronous dialog from worker thread
                    print(f"UUID {loaded_item.uuid} collision with {colliding_file_path}. Defaulting to 'Keep Both'.")
                    action_taken = "keep_both"

                data_to_write = loaded_item.to_dict()

                if action_taken == "keep_both":
                    data_to_write['uuid'] = str(uuid.uuid4())
                    data_to_write['timestamp'] = new_timestamp_str
                    target_filename = f"{new_timestamp_str}_{original_basename}.json"
                    data_to_write['output_filename'] = target_filename
                elif action_taken == "replace" and colliding_file_path: # This case is less likely with current simplified logic
                    target_filename = os.path.basename(colliding_file_path)
                    data_to_write['output_filename'] = target_filename
                else: # Default "copy" behavior
                    target_filename = f"{new_timestamp_str}_{original_basename}.json"
                    # If not a collision, or if collision but we're not replacing,
                    # we might still want to update timestamp if it's a "copy new"
                    # For simplicity now, if it's a plain copy (no collision), use original item's timestamp for filename
                    # if not uuid_collision:
                    #    target_filename = f"{loaded_item.timestamp}_{original_basename}.json" # Needs YYYYMMDD_HHMMSS
                    # else (it's a non-colliding copy, or "copy" was chosen for some other reason)
                    data_to_write['timestamp'] = new_timestamp_str # Ensure new timestamp for new file name
                    data_to_write['output_filename'] = target_filename


                target_path = os.path.join(transcripts_dir, target_filename)
                atomic_write_json(data_to_write, target_path)
                
                ToastPresenter.show(self, f"Imported ✓ {os.path.basename(target_path)}")
                GLib.idle_add(self.history_view.refresh_list)
                
                final_item_to_load = TranscriptItem.load_from_json(target_path)
                GLib.idle_add(self.transcript_view.load_transcript, final_item_to_load)
                GLib.idle_add(self._set_active_view, "transcript")

            except Exception as e: # Catch-all for the import operation
                if isinstance(e, ValueError):
                    print(f"Import failed: Validation error - {e}")
                    GLib.idle_add(self._show_modal_message, "Invalid Transcript File", f"The file '{os.path.basename(json_file_path)}' is not a valid transcript file or is malformed.\n\nDetails: {e}")
                elif isinstance(e, FileNotFoundError):
                    print(f"Import failed: File not found - {e}")
                    GLib.idle_add(self._show_modal_message, "Import Error", f"File not found: {json_file_path}")
                elif isinstance(e, json.JSONDecodeError):
                    print(f"Import failed: JSON decode error - {e}")
                    GLib.idle_add(self._show_modal_message, "Import Error", f"Could not decode JSON from: {os.path.basename(json_file_path)}")
                else:
                    print(f"Import failed: Unexpected error - {e}", exc_info=True)
                    GLib.idle_add(self._show_modal_message, "Import Error", f"An unexpected error occurred while importing '{os.path.basename(json_file_path)}'.\nDetails: {str(e)[:100]}")
        # End of import_operation function definition

        # This call should be part of _import_transcript_file, after import_operation is defined.
        # Corrected indentation to 8 spaces (relative to class indent of 4).
        app.io_pool.submit(import_operation)

    def _show_modal_message(self, title: str, message: str, secondary_text: Optional[str] = None, msg_type: Gtk.MessageType = Gtk.MessageType.ERROR):
        """Displays a modal Gtk.MessageDialog."""
        dialog = Gtk.MessageDialog(
            transient_for=self,
            modal=True,
            message_type=msg_type,
            buttons=Gtk.ButtonsType.CLOSE,
            text=title,
        )
        if secondary_text:
            dialog.props.secondary_text = secondary_text
        dialog.connect("response", lambda d, r: d.destroy())
        dialog.present()


    def _on_save_transcript(self, action, param):
        """Handles the 'activate' signal for the 'save-transcript' action."""
        print("Save Transcript action activated (Ctrl+S).")
        # Check if transcript_view is active and has content
        if not (self.leaflet.get_visible_child_name() == "transcript" and
                hasattr(self.transcript_view, 'has_content') and
                self.transcript_view.has_content()):
            ToastPresenter.show(self, "Nothing to save.")
            print("Save action: No active transcript content to save.")
            return

        current_transcript_data = self.transcript_view.get_transcript_data_for_saving()
        if not current_transcript_data:
            ToastPresenter.show(self, "Could not retrieve transcript data to save.")
            return

        # If the current transcript came from history (_selected_history_transcript is set AND its source_path exists)
        # and it's currently loaded in the view (e.g. check if transcript_view's current item matches)
        # This logic needs to be robust: how do we know if transcript_view is displaying _selected_history_transcript?
        # For now, let's assume if _selected_history_transcript exists and its source_path is valid, we try to overwrite.
        # A more robust way would be for transcript_view to hold the TranscriptItem it's displaying.
        
        # Simplification: if self.transcript_view.current_item is not None and self.transcript_view.current_item.source_path:
        # This assumes transcript_view has a 'current_item' property that holds the loaded TranscriptItem.
        # This needs to be implemented in TranscriptView.load_transcript().
        
        target_item_for_save = self.transcript_view.get_current_item() # Needs implementation in TranscriptView

        if target_item_for_save and target_item_for_save.source_path and os.path.exists(target_item_for_save.source_path):
            # Overwrite existing file
            print(f"Attempting to overwrite existing transcript: {target_item_for_save.source_path}")
            try:
                # Update the target_item_for_save with data from current_transcript_data if necessary,
                # then call target_item_for_save.save() or directly use atomic_write_json.
                # For now, let's re-create the dict to ensure it's current.
                # This assumes current_transcript_data is a full dict matching TranscriptItem.to_dict()
                # This part needs careful handling of what current_transcript_data provides.
                # Ideally, we get a full TranscriptItem-like dict from the view.
                
                # Let's assume current_transcript_data is a dict ready for atomic_write_json
                # and contains all necessary fields (uuid, timestamp, segments, etc.)
                # If it's a new transcript that was loaded from an old one, it should retain original UUID and timestamp unless explicitly changed.
                
                # The TranscriptItem.save() method is better here if the view holds a full TranscriptItem.
                # For now, directly using atomic_write_json with data from view.
                
                # Construct the full dictionary to save, ensuring all fields from spec §1.1 are present.
                # This might involve merging view data with existing item data if it's an overwrite.
                
                # Simplest path for now: assume current_transcript_data IS the complete data to save.
                # This requires transcript_view.get_transcript_data_for_saving() to be comprehensive.
                
                # Get the application's I/O pool
                app = self.get_application()
                if not app or not hasattr(app, 'io_pool') or not app.io_pool:
                    print("Error: I/O thread pool not available on application object.")
                    ToastPresenter.show(self, "❌ Save failed: Thread pool error.")
                    return

                def save_operation():
                    try:
                        # Ensure all required fields are in current_transcript_data
                        # This is crucial for meeting the spec.
                        # Example: ensure 'language', 'source_path' (media), 'audio_source_path' (media) are there.
                        # If current_transcript_data doesn't have them, fetch from target_item_for_save.
                        data_to_save = {
                            "uuid": target_item_for_save.uuid,
                            "timestamp": datetime.strptime(target_item_for_save.timestamp, "%Y-%m-%d %H:%M:%S").strftime("%Y%m%d_%H%M%S"), # Convert to JSON format
                            "text": current_transcript_data.get("text", target_item_for_save.transcript_text),
                            "segments": current_transcript_data.get("segments", target_item_for_save.to_segment_dicts()),
                            "language": current_transcript_data.get("language", target_item_for_save.language),
                            "source_path": target_item_for_save.audio_source_path, # Media path
                            "audio_source_path": target_item_for_save.audio_source_path, # Media path
                            "output_filename": target_item_for_save.output_filename
                        }

                        atomic_write_json(data_to_save, target_item_for_save.source_path)
                        ToastPresenter.show(self, f"Saved ✓ {os.path.basename(target_item_for_save.source_path)}")
                        GLib.idle_add(self.history_view.refresh_list) # Refresh history as content changed
                    except Exception as e:
                        print(f"Error saving (overwrite) to {target_item_for_save.source_path}: {e}")
                        ToastPresenter.show(self, f"❌ Could not save {os.path.basename(target_item_for_save.source_path)}: {e}")

                app.io_pool.submit(save_operation)

            except Exception as e: # Catch errors before submitting to thread pool
                print(f"Error preparing to save (overwrite) {target_item_for_save.source_path}: {e}")
                ToastPresenter.show(self, f"❌ Save error: {e}")

        else:
            # New, unsaved session: Prompt with Gtk.FileDialog.save()
            print("New transcript session. Prompting for save location.")
            dialog = Gtk.FileDialog.new()
            dialog.set_title("Save Transcript As...")
            
            # Default directory and filename
            default_folder_path = os.path.join(GLib.get_user_data_dir(), 'GnomeRecast', 'transcripts')
            os.makedirs(default_folder_path, exist_ok=True)
            default_folder = Gio.File.new_for_path(default_folder_path)
            dialog.set_initial_folder(default_folder)
            
            default_filename = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_new.json"
            dialog.set_initial_name(default_filename)

            # File filter for JSON
            json_filter = Gtk.FileFilter()
            json_filter.set_name("JSON Transcript Files (*.json)")
            json_filter.add_mime_type("application/json")
            json_filter.add_pattern("*.json")
            
            filters = Gio.ListStore.new(Gtk.FileFilter)
            filters.append(json_filter)
            dialog.set_filters(filters)
            dialog.set_default_filter(json_filter)

            dialog.save(self, None, self._on_new_transcript_file_selected_for_save, current_transcript_data)

    def _on_new_transcript_file_selected_for_save(self, dialog, result, transcript_data_to_save):
        """Callback for Gtk.FileDialog.save() for new transcripts."""
        try:
            file = dialog.save_finish(result)
            if file:
                target_path = file.get_path()
                print(f"New transcript save path selected: {target_path}")

                # Ensure the data to save has all required fields from spec §1.1
                # This is a new save, so some fields need to be generated.
                final_data_to_save = {
                    "uuid": str(uuid.uuid4()), # New UUID
                    "timestamp": datetime.now().strftime("%Y%m%d_%H%M%S"), # New timestamp
                    "text": transcript_data_to_save.get("text", ""),
                    "segments": transcript_data_to_save.get("segments", []),
                    "language": transcript_data_to_save.get("language", self.settings.get_string("target-language") if not self.settings.get_boolean("auto-detect-language") else "en"), # Best guess for language
                    "source_path": "",  # No original media source for a brand new, unsaved transcript unless explicitly set
                    "audio_source_path": "", # ditto
                    "output_filename": os.path.basename(target_path)
                }
                
                app = self.get_application()
                if not app or not hasattr(app, 'io_pool') or not app.io_pool:
                    print("Error: I/O thread pool not available on application object.")
                    ToastPresenter.show(self, "❌ Save failed: Thread pool error.")
                    return

                def save_operation():
                    try:
                        atomic_write_json(final_data_to_save, target_path)
                        ToastPresenter.show(self, f"Saved ✓ {os.path.basename(target_path)}")
                        GLib.idle_add(self.history_view.refresh_list)
                        # After a successful new save, update the transcript_view's current item
                        # This requires TranscriptItem to be created and loaded back or updated in view
                        # For now, this part is deferred until TranscriptView has better state management.
                        # Ideally:
                        # new_item = TranscriptItem.load_from_json(target_path)
                        # if new_item:
                        # GLib.idle_add(self.transcript_view.set_current_item, new_item) # Method to be created
                    except Exception as e:
                        print(f"Error saving new transcript to {target_path}: {e}")
                        ToastPresenter.show(self, f"❌ Could not save {os.path.basename(target_path)}: {e}")
                
                app.io_pool.submit(save_operation)

            else:
                print("Save operation cancelled by user.")
                ToastPresenter.show(self, "Save cancelled.")
        except GLib.Error as e:
            if e.matches(Gio.io_error_quark(), Gio.IOErrorEnum.CANCELLED):
                 print("File save operation cancelled by user (GLib.Error).")
                 ToastPresenter.show(self, "Save cancelled.")
            else:
                 print(f"GLib error during file save dialog: {e}")
                 ToastPresenter.show(self, f"❌ Save error: {e}")
        except Exception as e:
            print(f"Unexpected error during file save dialog callback: {e}")
            ToastPresenter.show(self, f"❌ Unexpected save error: {e}")


    def _on_reader_button_clicked(self, button):
        """Handles the click event for the Reader button."""
        print("Reader button clicked.")
        if not self._selected_history_transcript:
            print("Error: Reader button clicked but no history item selected.")
            return

        full_text_parts = []
        if self._selected_history_transcript.segments:
            for segment in self._selected_history_transcript.segments:
                    # isinstance check removed as TranscriptItem.load_from_json ensures SegmentItem instances
                    start_m, start_s = divmod(int(segment.start), 60)
                    end_m, end_s = divmod(int(segment.end), 60)
                    timestamp = f"[{start_m:02d}:{start_s:02d} → {end_m:02d}:{end_s:02d}]"
                    full_text_parts.append(f"{timestamp}\n{segment.text}\n")
        full_text = "".join(full_text_parts)

        if not full_text:
            print("Warning: Selected history item generated no text for Reader mode.")
            return

        cleaned_text = re.sub(r"^\[\d{2}:\d{2}\s*→\s*\d{2}:\d{2}\]\n?", "", full_text, flags=re.MULTILINE)
        cleaned_text = cleaned_text.strip()

        reader_window = Adw.ApplicationWindow(application=self.get_application())
        reader_window.set_title("Reader Mode - Transcript")
        reader_window.set_resizable(True)
        reader_window.set_default_size(400, 600)
        reader_window.set_modal(True)
        reader_window.add_css_class("reader-popup-window")

        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        main_box.set_margin_top(6)
        main_box.set_margin_end(6)
        main_box.set_margin_start(6)
        main_box.set_margin_bottom(6)

        top_bar_overlay = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        top_bar_overlay.add_css_class("topbar")
        top_bar_overlay.set_valign(Gtk.Align.START)
        top_bar_overlay.set_halign(Gtk.Align.END)
        top_bar_overlay.set_margin_top(12)
        top_bar_overlay.set_margin_end(12)

        close_button = Gtk.Button(label="✕")
        close_button.connect("clicked", lambda btn: reader_window.close())
        top_bar_overlay.append(close_button)

        buffer = Gtk.TextBuffer()
        buffer.set_text(cleaned_text)

        text_view = Gtk.TextView(buffer=buffer)
        text_view.add_css_class("reader-text-view")
        text_view.set_editable(False)
        text_view.set_wrap_mode(Gtk.WrapMode.WORD)

        scroller = Gtk.ScrolledWindow()
        scroller.add_css_class("reader-scrolled-window")
        scroller.set_child(text_view)
        scroller.set_vexpand(True)
        scroller.set_hexpand(True)

        overlay = Gtk.Overlay()
        overlay.set_child(scroller)
        overlay.add_overlay(top_bar_overlay)

        reader_window.set_content(overlay)
        reader_window.present()

        print("Reader mode window displayed.")

