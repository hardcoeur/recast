import gi
gi.require_version('Gtk', '4.0')
from gi.repository import Gtk, Gio, GLib
import wave
import tempfile
import os
import concurrent.futures
from ..audio.capture import AudioCapturer
from faster_whisper import WhisperModel
import torch


class DictationOverlay(Gtk.Window):
    """
    A floating, always-on-top window for live dictation transcription.
    """
    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        self.add_css_class("dictation-overlay-window")
        self.settings = Gio.Settings.new("org.gnome.GnomeRecast")

        self.set_title("GnomeRecast Dictation")
        self.set_decorated(False)
        self.set_keep_above(True)
        self.set_default_size(400, 250)
        self.set_resizable(False)

        self.audio_capturer = AudioCapturer(self._on_audio_data_received)
        self.audio_buffer = bytearray()

        self.sample_rate = 16000
        self.channels = 1
        self.bytes_per_sample = 2

        self.chunk_duration_seconds = 5
        self.chunk_size_bytes = int(
            self.sample_rate * self.channels * self.bytes_per_sample * self.chunk_duration_seconds
        )

        self.thread_pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)

        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5)
        main_box.add_css_class("dictation-main-box")
        main_box.set_margin_top(5)
        main_box.set_margin_bottom(5)
        main_box.set_margin_start(5)
        main_box.set_margin_end(5)
        self.set_child(main_box)

        scrolled_window = Gtk.ScrolledWindow()
        scrolled_window.add_css_class("dictation-scrolled-window")
        scrolled_window.set_hexpand(True)
        scrolled_window.set_vexpand(True)
        scrolled_window.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        main_box.append(scrolled_window)

        self.transcript_view = Gtk.TextView()
        self.transcript_view.add_css_class("dictation-transcript-view")
        self.transcript_view.set_editable(False)
        self.transcript_view.set_cursor_visible(False)
        self.transcript_view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self.transcript_buffer = self.transcript_view.get_buffer()
        self.transcript_buffer.set_text("Start speaking...")
        scrolled_window.set_child(self.transcript_view)

        status_bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        status_bar.add_css_class("dictation-status-bar")
        main_box.append(status_bar)


        self.word_count_label = Gtk.Label(label="Words: 0 / 250")
        self.word_count_label.add_css_class("dictation-word-count-label")
        self.word_count_label.set_halign(Gtk.Align.START)
        status_bar.append(self.word_count_label)


        spacer = Gtk.Box()
        spacer.add_css_class("dictation-spacer")
        spacer.set_hexpand(True)
        status_bar.append(spacer)


        self.copy_button = Gtk.Button(icon_name="edit-copy-symbolic")
        self.copy_button.add_css_class("dictation-copy-button")
        self.copy_button.set_tooltip_text("Copy Transcript")

        status_bar.append(self.copy_button)
        self.copy_button.connect("clicked", self._on_copy_clicked)


    def _on_audio_data_received(self, audio_data: bytes):
        """Callback function for receiving audio data."""
        self.audio_buffer.extend(audio_data)

        while len(self.audio_buffer) >= self.chunk_size_bytes:
            chunk_to_process = self.audio_buffer[:self.chunk_size_bytes]
            self.audio_buffer = self.audio_buffer[self.chunk_size_bytes:]
            self._process_audio_chunk(bytes(chunk_to_process))

    def _process_audio_chunk(self, audio_chunk: bytes):
        """
        Submits an audio chunk to the thread pool for asynchronous transcription.
        """
        print(f"Submitting audio chunk of size: {len(audio_chunk)} for transcription.")
        self.thread_pool.submit(self._transcribe_chunk_task, audio_chunk)

    def _transcribe_chunk_task(self, audio_chunk: bytes):
        """
        Task executed in the thread pool to transcribe an audio chunk.
        Saves chunk to WAV, transcribes, cleans up, and schedules UI update.
        """
        temp_wav_path = None
        transcribed_text = None
        try:
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as temp_wav_file:
                temp_wav_path = temp_wav_file.name

            with wave.open(temp_wav_path, 'wb') as wf:
                wf.setnchannels(self.channels)
                wf.setsampwidth(self.bytes_per_sample)
                wf.setframerate(self.sample_rate)
                wf.writeframes(audio_chunk)


            model_to_use = self.settings.get_string("default-model")
            auto_detect = self.settings.get_boolean("auto-detect-language")
            lang_to_use = self.settings.get_string("target-language")
            enable_translation = self.settings.get_boolean("enable-translation")
            device_mode = self.settings.get_string("whisper-device-mode")

            model = None
            try:
                if device_mode == "cuda" and torch.cuda.is_available():
                    device = "cuda"
                    compute_type = "float16"
                elif device_mode == "cpu":
                    device = "cpu"
                    compute_type = "int8"
                else:
                    device = "cuda" if torch.cuda.is_available() else "cpu"
                    compute_type = "float16" if device == "cuda" else "int8"
                print(f"BG Task: Selected device mode: {device_mode}, Determined device: {device}, Compute type: {compute_type}")

                model = WhisperModel(model_to_use, device=device, compute_type=compute_type)
            except Exception as model_load_err:
                print(f"BG Task: Failed to load faster-whisper model '{model_to_use}': {model_load_err}")
                return

            try:
                language_arg = None if auto_detect else lang_to_use
                task_arg = "translate" if enable_translation else "transcribe"
                print(f"BG Task: Transcribing chunk {temp_wav_path} (lang={language_arg}, task={task_arg})")

                segments_generator, info = model.transcribe(
                    temp_wav_path,
                    beam_size=5,
                    task=task_arg,
                    language=language_arg

                )

                chunk_text = ""
                for segment in segments_generator:
                    chunk_text += segment.text

                transcribed_text = chunk_text.strip()

            except Exception as transcribe_err:
                print(f"BG Task: faster-whisper transcribe failed for chunk {temp_wav_path}: {transcribe_err}")
                transcribed_text = None

            if transcribed_text:
                print(f"BG Task: Transcription successful: '{transcribed_text}'")
                GLib.idle_add(self._append_actual_text, transcribed_text + " ")
            else:
                print("BG Task: Transcription returned no text or failed for this chunk.")


        except Exception as e:
            print(f"BG Task: Unexpected error processing audio chunk: {e}")
        finally:
            if temp_wav_path and os.path.exists(temp_wav_path):
                try:
                    os.remove(temp_wav_path)
                except OSError as e:
                    print(f"BG Task: Error removing temporary WAV file {temp_wav_path}: {e}")


    def _append_actual_text(self, text_to_append: str):
        """Appends transcribed text to the transcript view and updates word count."""
        end_iter = self.transcript_buffer.get_end_iter()
        self.transcript_buffer.insert(end_iter, text_to_append)

        start_iter = self.transcript_buffer.get_start_iter()
        end_iter = self.transcript_buffer.get_end_iter()
        full_text = self.transcript_buffer.get_text(start_iter, end_iter, False)
        word_count = len(full_text.split())
        self.word_count_label.set_text(f"Words: {word_count} / 250")
        return False

    def _on_copy_clicked(self, button):
        """Handles the copy button click event."""
        clipboard = Gtk.Display.get_default().get_clipboard()
        buffer = self.transcript_buffer
        start_iter = buffer.get_start_iter()
        end_iter = buffer.get_end_iter()
        text_content = buffer.get_text(start_iter, end_iter, False)
        clipboard.set(text_content)
        print("Dictation text copied to clipboard.")

    def do_show(self):
        """Override show signal to start audio capture."""
        self.audio_buffer.clear()
        self.transcript_buffer.set_text("")
        self.word_count_label.set_text("Words: 0 / 250")

        print("DictationOverlay: Starting audio capture...")
        try:
            self.audio_capturer.start()
        except Exception as e:
            print(f"DictationOverlay: Error starting audio capture: {e}")
        super().do_show()
    def do_close(self):
        """Override close signal to stop audio capture and shut down thread pool."""
        print("DictationOverlay: Stopping audio capture and shutting down thread pool...")
        try:
            self.audio_capturer.stop()
        except Exception as e:
            print(f"DictationOverlay: Error stopping audio capture: {e}")

        self.thread_pool.shutdown(wait=False, cancel_futures=True)
        print("DictationOverlay: Thread pool shutdown initiated.")

        super().do_close()