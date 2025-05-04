import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Gtk, Adw, Gio, GLib
import typing
from typing import Optional
import threading
import wave
import tempfile
import os

if typing.TYPE_CHECKING:
    from ..window import GnomeRecastWindow
    from ..audio.capture import AudioCapturer, AudioBuffer

class ProgressDialog(Gtk.Dialog):
    """
    A modal dialog to indicate transcription progress and allow cancellation.
    """
    def __init__(self, transient_for: 'GnomeRecastWindow', transcriber, show_stop_button=False, **kwargs):
        super().__init__(transient_for=transient_for, **kwargs)

        self.capturer: typing.Optional['AudioCapturer'] = None
        self.audio_buffer: typing.Optional['AudioBuffer'] = None
        self.is_monitor_recording = show_stop_button
        self._temp_wav_path: typing.Optional[str] = None

        self.transcriber = transcriber
        self._transcriber_cancellation_token: Optional[object] = None
        self._download_cancel_event: Optional[threading.Event] = None

        if self.is_monitor_recording:
            self.set_title("Recording App Audio…")
            initial_label = "Recording system audio output..."
        else:
            self.set_title("Transcribing…")
            initial_label = "Preparing..."

        self.set_modal(True)
        self.set_deletable(False)

        content_area = self.get_content_area()
        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, margin_top=12, margin_bottom=12, margin_start=12, margin_end=12)
        content_area.append(main_box)

        self.spinner = Gtk.Spinner(spinning=True, halign=Gtk.Align.CENTER)
        main_box.append(self.spinner)

        self.label = Gtk.Label(label=initial_label, halign=Gtk.Align.CENTER, hexpand=True)
        main_box.append(self.label)

        button_label = "Stop Recording" if self.is_monitor_recording else "Cancel"
        self.add_button(button_label, Gtk.ResponseType.CANCEL)
        self.connect("response", self._on_response)

    def set_transcriber_cancellation_token(self, token):
        """Stores the cancellation token provided by the Transcriber."""
        self._transcriber_cancellation_token = token

    def set_download_cancel_event(self, event: threading.Event):
        """Stores the threading.Event used to signal download cancellation."""
        self._download_cancel_event = event

    def set_capturer(self, capturer: 'AudioCapturer', audio_buffer: 'AudioBuffer'):
        """Stores the AudioCapturer instance and buffer."""
        self.capturer = capturer
        self.audio_buffer = audio_buffer

    def update_transcription_progress(self, filename, percentage):
        """Updates the progress label specifically for transcription."""
        if self.get_visible():
            self.label.set_text(f"Processing: {filename} ({percentage:.0f}%)")

    def update_progress(self, title: Optional[str] = None, percentage: Optional[float] = None, text: Optional[str] = None):
        """
        Updates the dialog's title, progress bar fraction, and label text.
        Use negative percentage for indeterminate (-1) or special states (-2 cancelled).
        """
        if not self.get_visible():
            return

        if title:
            self.set_title(title)

        if percentage is not None:
            if percentage < 0:
                pass
            else:
                 pass

        if text:
            self.label.set_text(text)

    def set_progress_text(self, text: str):
         """Sets the text of the progress label."""
         if self.get_visible():
              self.label.set_text(text)


    def on_completion(self, status, transcript_items=None):
        """
        Handles the completion signal from the Transcriber.

        Args:
            status (str): The final status ('completed', 'cancelled', 'error', 'no_files').
            transcript_items (list | None): A list of TranscriptItem objects if completed, else None or [].
        """
        print(f"\nTranscription finished with status: {status}")

        if status == 'completed' and transcript_items:
            print("--- Transcription Results ---")
            if transcript_items:
                for item in transcript_items:
                    text_preview = (item.transcript_text[:100] + '...') if len(item.transcript_text) > 100 else item.transcript_text
                    print(f"- Source: {item.source_path}\n"
                          f"  UUID: {item.uuid}\n"
                          f"  Timestamp: {item.timestamp}\n"
                          f"  Output: {item.output_filename}\n"
                          f"  Text: {text_preview}\n"
                          f"  Segments: {len(item.segments) if item.segments else 0}")
            else:
                print("  (No transcripts generated)")
            print("-----------------------------")

            main_window = self.get_transient_for()
            if main_window and hasattr(main_window, 'show_transcript_view') and transcript_items:
                print("Requesting main window to switch to transcript view...")
                GLib.idle_add(main_window.show_transcript_view, None, transcript_items[0])
            elif not main_window:
                 print("Could not get transient_for window to switch view.")
            elif not hasattr(main_window, 'show_transcript_view'):
                 print(f"Transient window does not have show_transcript_view method.")

        elif status == 'error':
            print("  An error occurred during transcription. Check logs above.")
            main_window = self.get_transient_for()
            if main_window and hasattr(main_window, 'show_initial_view'):
                print("Requesting main window to switch back to initial view (error)...")
                GLib.idle_add(main_window.show_initial_view)
        elif status == 'cancelled':
            print("  Transcription was cancelled by the user.")
            main_window = self.get_transient_for()
            if main_window and hasattr(main_window, 'show_initial_view'):
                print("Requesting main window to switch back to initial view (cancelled)...")
                GLib.idle_add(main_window.show_initial_view)
        elif status == 'no_files':
             print("  No files were provided for transcription.")
             main_window = self.get_transient_for()
             if main_window and hasattr(main_window, 'show_initial_view'):
                 print("Requesting main window to switch back to initial view (no files)...")
                 GLib.idle_add(main_window.show_initial_view)


        if self._temp_wav_path and os.path.exists(self._temp_wav_path):
            try:
                os.remove(self._temp_wav_path)
                print(f"Cleaned up temporary file: {self._temp_wav_path}")
                self._temp_wav_path = None
            except OSError as e:
                print(f"Error removing temporary file {self._temp_wav_path}: {e}")

        if not self.is_visible():
             print("Progress dialog already closed.")
             return
        print("Closing progress dialog.")
        self.close()

    def _on_response(self, dialog, response_id):
        """Handles dialog response signals."""
        if response_id == Gtk.ResponseType.CANCEL:
            cancel_button = self.get_widget_for_response(Gtk.ResponseType.CANCEL)

            if hasattr(self, '_download_cancel_event') and self._download_cancel_event:
                print("Cancel button clicked (Download Phase). Setting event.")
                self._download_cancel_event.set()
                if cancel_button:
                    cancel_button.set_sensitive(False)
                    cancel_button.set_label("Cancelling...")

            elif self.is_monitor_recording:
                print("Stop Recording button clicked.")
                if cancel_button:
                    cancel_button.set_sensitive(False)
                    cancel_button.set_label("Stopping...")
                self._stop_monitor_recording_flow()

            else:
                print("Cancel button clicked (Transcription Phase).")
                if self.transcriber and self._transcriber_cancellation_token:
                    print("Attempting to cancel transcription...")
                    if cancel_button:
                        cancel_button.set_sensitive(False)
                        cancel_button.set_label("Cancelling...")
                    self.transcriber.cancel_transcription(self._transcriber_cancellation_token)
                else:
                    print("Transcriber or cancellation token not set. Closing dialog.")
                    self.close()

    def _stop_monitor_recording_flow(self):
        """Stops monitor recording, saves audio, and starts transcription."""
        print("Stopping monitor recording flow...")

        if self.capturer:
            print("Stopping AudioCapturer...")
            self.capturer.stop()
        else:
            print("Error: AudioCapturer instance not found.")
            self.on_completion("error")
            return

        if not self.audio_buffer or not self.audio_buffer.get_data():
            print("Error: Audio buffer is empty or not found.")
            self.on_completion("error")
            return

        stop_button = self.get_widget_for_response(Gtk.ResponseType.CANCEL)
        if stop_button:
            stop_button.set_sensitive(False)
            stop_button.set_label("Processing...")
        self.label.set_text("Saving recorded audio...")
        self.spinner.start()

        try:
            print("Saving audio buffer to temporary WAV file...")
            rate = self.audio_buffer.get_rate()
            channels = self.audio_buffer.get_channels()
            width = self.audio_buffer.get_width()
            data = self.audio_buffer.get_data()

            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as temp_f:
                self._temp_wav_path = temp_f.name
                print(f"Temporary WAV file path: {self._temp_wav_path}")

                with wave.open(temp_f, 'wb') as wf:
                    wf.setnchannels(channels)
                    wf.setsampwidth(width)
                    wf.setframerate(rate)
                    wf.writeframes(data)
            print("Temporary WAV file saved successfully.")

        except Exception as e:
            print(f"Error saving temporary WAV file: {e}")
            self.on_completion("error")
            return

        if self._temp_wav_path:
            self.label.set_text("Processing recorded audio...")
            print(f"Starting transcription for {self._temp_wav_path}...")

            def cleanup_temp_file():
                if self._temp_wav_path and os.path.exists(self._temp_wav_path):
                    try:
                        os.remove(self._temp_wav_path)
                        print(f"Transcriber callback cleaned up temp file: {self._temp_wav_path}")
                        self._temp_wav_path = None
                    except OSError as e:
                        print(f"Error in transcriber cleanup removing temp file {self._temp_wav_path}: {e}")
                else:
                    print("Transcriber cleanup: Temp file already removed or path not set.")


            new_token = self.transcriber.start_transcription(
                [self._temp_wav_path],
                progress_callback=self.update_transcription_progress,
                completion_callback=self.on_completion,
                cleanup_callback=cleanup_temp_file
            )
            self.set_transcriber_cancellation_token(new_token)

            if stop_button:
                 stop_button.set_sensitive(True)
                 stop_button.set_label("Cancel")
            self.is_monitor_recording = False

        else:
            print("Error: Temporary WAV path not set after saving.")
            self.on_completion("error")