import threading
import typing as t
import os
import json
import uuid
from datetime import datetime
import torch
from faster_whisper import WhisperModel
from faster_whisper.transcribe import TranscriptionOptions

from gi.repository import GLib, Gio


ProgressCallback = t.Callable[[float, int, int], None]
SegmentCallback = t.Callable[[dict], None]
CompletionCallback = t.Callable[[str, t.List[dict]], None]


class Transcriber:
    """
    Handles the transcription process in a separate thread using faster-whisper.
    """

    def _run_transcription_thread(
        self,
        file_paths: t.List[str],
        progress_callback: ProgressCallback,
        segment_callback: SegmentCallback,
        completion_callback: CompletionCallback,
        cancellation_token: threading.Event,
    ):
        """
        The actual worker function that runs in a separate thread.
        Uses faster-whisper for in-process transcription.
        """
        total_files = len(file_paths)
        status = "completed"
        all_files_segments: t.List[dict] = []

        permanent_storage_dir = os.path.join(GLib.get_user_data_dir(), 'GnomeRecast', 'transcripts')
        os.makedirs(permanent_storage_dir, exist_ok=True)
        print(f"Ensured permanent storage directory exists: {permanent_storage_dir}")

        print("Transcription thread started.")
        model = None

        try:
            try:
                settings = Gio.Settings.new("org.gnome.GnomeRecast")
                model_to_use = settings.get_string("default-model")
                auto_detect = settings.get_boolean("auto-detect-language")
                lang_to_use = None if auto_detect else settings.get_string("target-language")
                enable_translation = settings.get_boolean("enable-translation")
                device_mode = settings.get_string("whisper-device-mode")
                print(f"Thread using settings: model={model_to_use}, lang={lang_to_use or 'auto'}, translate={enable_translation}, device_mode={device_mode}")
            except Exception as e:
                print(f"Error reading GSettings in thread: {e}. Using default transcription parameters.")
                model_to_use = "base"
                lang_to_use = None
                enable_translation = False

            if device_mode == "cuda" and torch.cuda.is_available():
                device = "cuda"
                compute_type = "float16"
            elif device_mode == "cpu":
                device = "cpu"
                compute_type = "int8"
            else:
                device = "cuda" if torch.cuda.is_available() else "cpu"
                compute_type = "float16" if device == "cuda" else "int8"
            print(f"Selected device mode: {device_mode}, Determined device: {device}, Compute type: {compute_type}")

            try:
                model = WhisperModel(model_size_or_path=model_to_use, device=device, compute_type=compute_type)
                print("Faster-whisper model loaded successfully.")
            except Exception as model_load_err:
                print(f"[ERROR] Failed to load faster-whisper model '{model_to_use}': {model_load_err}")
                status = "error"
                GLib.idle_add(completion_callback, status, [])
                return

            for index, file_path in enumerate(file_paths):
                if cancellation_token.is_set():
                    print(f"Cancellation requested. Stopping transcription.")
                    status = "cancelled"
                    break

                print(f"\n--- Starting processing for file {index + 1}/{total_files}: {file_path} ---")

                current_file_segments: t.List[dict] = []
                current_full_text: str = ""
                total_duration: float = 0.0
                info = None

                try:
                    language_arg = None if lang_to_use == "auto" or not lang_to_use else lang_to_use
                    task_arg = "translate" if enable_translation else "transcribe"


                    print(f"Starting faster-whisper transcription for: {file_path}")
                    print(f"  Task: {task_arg}, Language: {language_arg or 'auto detect'}")
                    segments_generator, info = model.transcribe(
                        file_path,
                        beam_size=5,
                        task=task_arg,
                        language=language_arg,
                        word_timestamps=False,
                        vad_filter=False,

                    )
                    total_duration = info.duration
                    print(f"Transcription initiated. Detected language: {info.language}, Probability: {info.language_probability:.2f}, Duration: {total_duration:.2f}s")

                    print("Iterating over segments generator...")
                    last_segment_index = -1

                    for i, segment in enumerate(segments_generator):
                        if cancellation_token.is_set():
                            print(f"Cancellation requested during segment processing.")
                            status = "cancelled"
                            break

                        last_segment_index = i

                        if progress_callback:
                            if total_duration > 0:
                                fraction = min(segment.end / total_duration, 1.0)
                                GLib.idle_add(progress_callback, fraction, i + 1, -1)
                            else:
                                GLib.idle_add(progress_callback, 0.0, i + 1, -1)

                        segment_dict = {
                            "id": i,
                            "text": segment.text.strip(),
                            "start": segment.start,
                            "end": segment.end,
                            "start_ms": int(segment.start * 1000),
                            "end_ms": int(segment.end * 1000),
                        }
                        current_file_segments.append(segment_dict)
                        current_full_text += segment.text

                        if segment_callback:
                            print(f"Transcriber: Generated segment [{segment_dict['start']:.2f}s->{segment_dict['end']:.2f}s], calling callback.")
                            GLib.idle_add(segment_callback, segment_dict)


                    if status == "cancelled":
                         break

                    if status == "completed" and progress_callback:
                        final_fraction = 1.0
                        final_completed_count = last_segment_index + 1 if last_segment_index >= 0 else 0
                        GLib.idle_add(progress_callback, final_fraction, final_completed_count, -1)

                    print(f"Finished processing segments for {file_path}.")

                    if status == "completed":
                        unique_id = str(uuid.uuid4())
                        timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
                        base_name = os.path.splitext(os.path.basename(file_path))[0]
                        destination_filename = f"{timestamp_str}_{base_name}.json"
                        destination_path = os.path.join(permanent_storage_dir, destination_filename)
                        print(f"Generated metadata: UUID={unique_id}, Timestamp={timestamp_str}, DestFile={destination_filename}")

                        final_json_data = {
                            "uuid": unique_id,
                            "timestamp": timestamp_str,
                            "text": current_full_text.strip(),
                            "segments": current_file_segments,
                            "language": info.language,
                            "source_path": destination_path,
                            "audio_source_path": file_path,
                            "output_filename": destination_filename
                        }

                        try:
                            print(f"Saving final transcript JSON to: {destination_path}")
                            with open(destination_path, 'w', encoding='utf-8') as f:
                                json.dump(final_json_data, f, ensure_ascii=False, indent=2)
                            print("JSON saved successfully.")
                            all_files_segments.extend(current_file_segments)
                        except Exception as save_err:
                            print(f"[ERROR] Failed to save transcript JSON to {destination_path}: {save_err}")


                except Exception as transcribe_err:
                    print(f"[ERROR] faster-whisper transcribe failed for {file_path}: {transcribe_err}")
                    status = "error"
                    break


        finally:
            print(f"Transcription thread finishing with status: {status}")
            final_segments_to_pass = all_files_segments if status == "completed" else []
            GLib.idle_add(completion_callback, status, final_segments_to_pass)
            print("Completion callback scheduled.")


    def start_transcription(
        self,
        file_paths: t.List[str],
        progress_callback: ProgressCallback,
        segment_callback: SegmentCallback,
        completion_callback: CompletionCallback,
    ) -> threading.Event:
        """
        Starts the transcription process in a background thread using faster-whisper.
        """
        if not file_paths:
            print("No files selected for transcription.")
            GLib.idle_add(completion_callback, "no_files", [])
            return threading.Event()

        cancellation_token = threading.Event()

        def transcription_worker():
            self._run_transcription_thread(
                file_paths=file_paths,
                progress_callback=progress_callback,
                segment_callback=segment_callback,
                completion_callback=completion_callback,
                cancellation_token=cancellation_token
            )

        thread = threading.Thread(
            target=transcription_worker,
            daemon=True
        )
        thread.start()
        print(f"[Transcriber] Started transcription for {len(file_paths)} file(s).")
        return cancellation_token
