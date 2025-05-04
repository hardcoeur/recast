import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Gtk, Adw, GLib, Gio, Gdk, Pango
import wave
import tempfile
import os
import re

from typing import Optional
from .audio.capture import AudioCapturer
from .views.transcript_view import TranscriptionView
from .views.initial_view import InitialView
from .transcription.transcriber import Transcriber
from .views.history_view import HistoryView
from .models.transcript_item import TranscriptItem, SegmentItem


LANGUAGE_MAP = {"auto": "Auto Detect", "en": "English", "es": "Spanish"}
REVERSE_LANGUAGE_MAP = {v: k for k, v in LANGUAGE_MAP.items()}

MODE_MAP = {"fast": "Fast", "balanced": "Balanced", "accurate": "Accurate"}
MODE_TO_MODEL = {"fast": "tiny", "balanced": "base", "accurate": "small"}
MODEL_TO_MODE = {v: k for k, v in MODE_TO_MODEL.items()}

class GnomeRecastWindow(Adw.ApplicationWindow):
    """The main application window for GnomeRecast."""


    def __init__(self, app_menu: Optional[Gio.MenuModel] = None, **kwargs):
        super().__init__(**kwargs)

        self.settings = Gio.Settings.new("org.gnome.GnomeRecast")

        self.set_title("")
        self.set_default_size(800, 600)

        self.recording_audio_capturer = None
        self.recording_audio_buffer = bytearray()

        self.transcriber = Transcriber()
        self._selected_history_transcript: Optional[TranscriptItem] = None

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
        self.history_view = HistoryView(on_transcript_selected=self._load_transcript_from_history)
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
        toolbar_view.set_content(self.leaflet)

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

        self._add_sidebar_button("data/icons/compass.png", self.show_initial_view, "Home")
        self._add_sidebar_button("data/icons/headset.png", self.show_transcript_view, "Transcribe")
        self._add_sidebar_button("data/icons/history.png", self.show_history_view, "History")


        self._create_language_action()
        self._create_mode_action()
        self._create_export_action()

        self._update_language_button_label()
        self._update_mode_button_label()

        self.settings.connect("changed::target-language", lambda s, k: self._update_language_button_label())
        self.settings.connect("changed::auto-detect-language", lambda s, k: self._update_language_button_label())
        self.settings.connect("changed::default-model", lambda s, k: self._update_mode_button_label())


    def _add_sidebar_button(self, icon_path, callback, tooltip_text):
        """Creates a Gtk.Button with an icon, connects it, and adds it to the sidebar."""
        icon = Gtk.Picture.new_for_filename(icon_path)
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
            is_transcript_view = (view_name == "transcript")
            export_action = self.lookup_action("export-transcript")
            if export_action:
                export_action.set_enabled(is_transcript_view)

            if hasattr(self, "reader_button"):
               is_history_view = (view_name == "history")
               self.reader_button.set_visible(is_history_view)
               if not is_history_view:
                    self.reader_button.set_sensitive(False)
                    self._selected_history_transcript = None

            print(f"GnomeRecastWindow: Switched active view to '{view_name}'. Export enabled: {is_transcript_view}")
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
                self._on_recording_audio_data,
                source_type="mic"
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
            self.recording_audio_capturer = None
            print("GnomeRecastWindow: AudioCapturer stopped.")
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

        def on_completion(status: str, transcript_items: list):
            """Handles transcription completion, cleanup, and final state."""
            print(f"GnomeRecastWindow: Transcription completed with status: {status}")

            if cleanup_paths and status == 'completed':
                print(f"GnomeRecastWindow: Transcription successful. Attempting cleanup for: {cleanup_paths}")
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

            if status != 'completed' or not transcript_items:
                print(f"GnomeRecastWindow: Transcription failed or produced no items. Returning to initial view.")
                if hasattr(self, 'initial_view') and self.initial_view:
                    GLib.idle_add(self.initial_view.reset_button_state)
                GLib.idle_add(self.show_initial_view)
            else:
                print(f"GnomeRecastWindow: Transcription successful. Segments were added in real-time.")
                GLib.idle_add(self.history_view.refresh_list)

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
                    self._start_transcription_process([file_path])
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
        action.set_enabled(False)
        self.add_action(action)
        print("Action 'win.export-transcript' created.")

    def _on_history_item_selected(self, history_view, transcript_item):
        """Updates UI when a transcript item is selected in history view."""
        print(f"Transcript selected: {transcript_item.output_filename}")
        self._selected_history_transcript = transcript_item
        if hasattr(self, 'reader_button'):
            self.reader_button.set_sensitive(True)

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

        if not hasattr(self, 'transcript_view') or not self.transcript_view:
            print("Error: TranscriptView not available.")
            return

        try:
            transcript_text = self.transcript_view.get_full_text()
        except AttributeError:
             print("Error: TranscriptionView does not have a 'get_full_text' method.")
             return
        except Exception as e:
            print(f"Error getting transcript text: {e}")
            return

        if not transcript_text:
            print("No transcript text available to export.")
            return

        dialog = Gtk.FileDialog.new()
        dialog.set_title("Export Transcript As...")


        print("Showing file save dialog...")
        dialog.save(self, None, self._on_transcript_file_selected, transcript_text)


    def _on_transcript_file_selected(self, dialog, result, transcript_text):
        """Callback executed after the user selects a file in the save dialog."""
        print("File save dialog finished.")
        try:
            file = dialog.save_finish(result)
            if file is not None:
                path = file.get_path()
                print(f"Attempting to save transcript to: {path}")
                try:
                    with open(path, "w", encoding='utf-8') as f:
                        f.write(transcript_text)
                    print(f"Transcript successfully saved to {path}")
                except Exception as e:
                    print(f"Error writing transcript to file {path}: {e}")
                    error_dialog = Gtk.MessageDialog(
                        transient_for=self,
                        modal=True,
                        message_type=Gtk.MessageType.ERROR,
                        buttons=Gtk.ButtonsType.CLOSE,
                        text="Error Saving File",
                        secondary_text=f"Could not write transcript to '{os.path.basename(path)}':\n{e}"
                    )
                    error_dialog.connect("response", lambda d, r: d.destroy())
                    error_dialog.show()
            else:
                print("File save operation cancelled by user.")

        except GLib.Error as e:
            if e.matches(Gio.io_error_quark(), Gio.IOErrorEnum.CANCELLED):
                 print("File save operation cancelled by user (GLib.Error).")
            else:
                 print(f"GLib error during file save: {e}")
                 error_dialog = Gtk.MessageDialog(
                     transient_for=self,
                     modal=True,
                     message_type=Gtk.MessageType.ERROR,
                     buttons=Gtk.ButtonsType.CLOSE,
                     text="Error Saving File",
                     secondary_text=f"An error occurred during the save operation:\n{e}"
                 )
                 error_dialog.connect("response", lambda d, r: d.destroy())
                 error_dialog.show()


    def _load_transcript_from_history(self, transcript_item: TranscriptItem):
        """Loads segments from a selected history item into the transcript view."""
        if not transcript_item:
            print("Error: _load_transcript_from_history called with None item.")
            if hasattr(self, 'reader_button'):
                self.reader_button.set_sensitive(False)
            self._selected_history_transcript = None
            return

        self._selected_history_transcript = transcript_item
        if hasattr(self, 'reader_button'):
            self.reader_button.set_sensitive(True)
            print(f"Reader button enabled for item {transcript_item.uuid}")

        segment_dicts = []
        if transcript_item.segments:
            print(f"Processing {len(transcript_item.segments)} segments from history item {transcript_item.uuid}...")
            for i, seg in enumerate(transcript_item.segments):
                if isinstance(seg, SegmentItem):
                    segment_dicts.append({
                        "id": i,
                        "start": seg.start,
                        "end": seg.end,
                        "text": seg.text,
                        "start_ms": int(seg.start * 1000),
                        "end_ms": int(seg.end * 1000)
                    })
                else:
                    print(f"Warning: Segment {i} in history item {transcript_item.uuid} is not a SegmentItem instance (type: {type(seg)}).")
        else:
            print(f"Warning: History item {transcript_item.uuid} has no segments attribute or it's empty.")

        print(f"Loading {len(segment_dicts)} processed segments from history...")
        if not hasattr(self, 'transcript_view') or not self.transcript_view:
            print("Error: TranscriptView not available to load history.")
            return

        GLib.idle_add(self.transcript_view.reset_view)

        for segment_dict in segment_dicts:
            GLib.idle_add(self.transcript_view.add_segment, segment_dict)

        GLib.idle_add(self._set_active_view, "transcript")


    def _on_reader_button_clicked(self, button):
        """Handles the click event for the Reader button."""
        print("Reader button clicked.")
        if not self._selected_history_transcript:
            print("Error: Reader button clicked but no history item selected.")
            return

        full_text_parts = []
        if self._selected_history_transcript.segments:
            for segment in self._selected_history_transcript.segments:
                 if isinstance(segment, SegmentItem):
                    start_m, start_s = divmod(int(segment.start), 60)
                    end_m, end_s = divmod(int(segment.end), 60)
                    timestamp = f"[{start_m:02d}:{start_s:02d} → {end_m:02d}:{end_s:02d}]"
                    full_text_parts.append(f"{timestamp}\n{segment.text}\n")
                 else:
                    print(f"Warning: Skipping non-SegmentItem in reader mode: {type(segment)}")
        full_text = "".join(full_text_parts)

        if not full_text:
            print("Warning: Selected history item generated no text for Reader mode.")
            return

        cleaned_text = re.sub(r"^\[\d{2}:\d{2}\s*→\s*\d{2}:\d{2}\]\n?", "", full_text, flags=re.MULTILINE)
        cleaned_text = cleaned_text.strip()

        reader_window = Adw.ApplicationWindow(application=self.get_application())
        reader_window.set_title("Reader Mode - Transcript")
        reader_window.set_resizable(True)
        reader_window.set_default_size(600, 400)
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
