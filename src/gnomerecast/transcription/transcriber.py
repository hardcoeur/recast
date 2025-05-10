import threading
import typing as t
import os
import json
import uuid
import weakref # Added
from datetime import datetime
from faster_whisper import WhisperModel
from faster_whisper.transcribe import TranscriptionOptions

from gi.repository import GLib, Gio

from ..utils.models import ModelNotAvailableError, ensure_cached # Updated import
from ..utils.io import atomic_write_json # Added



ProgressCallback = t.Callable[[float, int, int], None]
SegmentCallback = t.Callable[[dict], None]
# CompletionCallback will now also indicate save status and path
CompletionCallback = t.Callable[[str, t.List[dict], t.Optional[str], t.Optional[str]], None]
# status, segments, saved_json_path, save_error_message


class Transcriber:
    """
    Handles the transcription process in a separate thread using faster-whisper.
    """
    _MODEL_POOL: t.Dict[t.Tuple[str, str, str], WhisperModel] = weakref.WeakValueDictionary()

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
        status = "completed" # Default status
        all_files_segments: t.List[dict] = []
        saved_json_path: t.Optional[str] = None
        save_error_message: t.Optional[str] = None
        current_overall_transcription_pct: float = 0.0
        current_segments_done: int = 0

        permanent_storage_dir = os.path.join(GLib.get_user_data_dir(), 'GnomeRecast', 'transcripts')
        os.makedirs(permanent_storage_dir, exist_ok=True)
        print(f"Ensured permanent storage directory exists: {permanent_storage_dir}")

        print("Transcription thread started.")
        model = None

        try:
            try:
                settings = Gio.Settings.new("org.hardcoeur.Recast")
                selected_model_name = settings.get_string("default-model")
                auto_detect = settings.get_boolean("auto-detect-language")
                lang_to_use = None if auto_detect else settings.get_string("target-language")
                enable_translation = settings.get_boolean("enable-translation")
                device_mode = settings.get_string("whisper-device-mode")
                compute_type_setting = settings.get_string("whisper-compute-type")
                print(f"Thread using settings: model_name={selected_model_name}, lang={lang_to_use or 'auto'}, translate={enable_translation}, device_mode={device_mode}, compute_type={compute_type_setting}")
            except Exception as e:
                print(f"Error reading GSettings in thread: {e}. Using default transcription parameters.")
                selected_model_name = "base"
                lang_to_use = None
                enable_translation = False
                device_mode = "cpu"
                compute_type_setting = "auto"

            # Ensure model is cached before loading
            try:
                # Adapt progress_cb for ensure_cached.
                # ensure_cached progress_cb is Callable[[float, str], None]
                # - percent: 0.0 for start, 100.0 for done, -1.0 for error
                # - message: string description
                # Main progress_callback is Callable[[float (overall_pct), int (segments_done), float (model_download_pct)], None]
                def _ensure_cached_progress_adapter(model_dl_pct_raw: float, message: str):
                    print(f"ensure_cached progress: {model_dl_pct_raw}%, message: {message}")
                    if progress_callback:
                        model_download_progress = model_dl_pct_raw / 100.0 if model_dl_pct_raw >= 0 else model_dl_pct_raw
                        # During model download/prep, overall transcription pct and segments_done are 0 or last known.
                        # Here, we assume they are 0 as this happens before main transcription loop.
                        GLib.idle_add(progress_callback,
                                      current_overall_transcription_pct, # Use current/last known overall %
                                      current_segments_done,             # Use current/last known segments
                                      model_download_progress)           # Actual model download/prep %
                    if model_dl_pct_raw == -1.0 and "Error:" in message: # Error from ensure_cached
                        # This error will be raised as ModelNotAvailableError, so just log here.
                        print(f"ensure_cached reported error: {message}")


                model_dir_path = ensure_cached(
                    model_name=selected_model_name,
                    device=device_mode,
                    compute_type=compute_type_setting,
                    progress_cb=_ensure_cached_progress_adapter if progress_callback else None
                )
                print(f"Model directory ensured at: {model_dir_path}")
                # Signal model download/preparation is complete by sending 100% for model_download_pct,
                # or -1.0 if it was already cached and ensure_cached sent 100 immediately.
                # The last call from _ensure_cached_progress_adapter should handle the 100% state.
                # If transcription starts, model_download_pct becomes -1.0.

            except ModelNotAvailableError as e:
                print(f"[ERROR] Model not available: {e.details}")
                status = "error"
                # Error already sent via _ensure_cached_progress_adapter with -1.0
                # completion_callback will be called in finally block.
                save_error_message = f"model-unavailable:{e.details}"
                GLib.idle_add(completion_callback, status, [], None, save_error_message)
                return
            except Exception as cache_err:
                print(f"[ERROR] Failed to ensure model is cached: {cache_err}")
                status = "error"
                save_error_message = f"Caching error: {str(cache_err)}"
                if progress_callback: # Send a generic model error if specific adapter didn't catch it.
                    GLib.idle_add(progress_callback, current_overall_transcription_pct, current_segments_done, -1.0)
                GLib.idle_add(completion_callback, status, [], None, save_error_message)
                return

            # Model is ready, set model_download_pct to -1 for subsequent transcription progress
            if progress_callback:
                GLib.idle_add(progress_callback, current_overall_transcription_pct, current_segments_done, -1.0)


            if device_mode == "cuda":
                device = "cuda"
                compute_type = "float16"
            elif device_mode == "cpu":
                device = "cpu"
                compute_type = "int8"
            else:  # 'auto'
                device = "auto"
                compute_type = "auto" # faster-whisper will pick the best for the auto-selected device
            print(f"User preferred device mode: {device_mode}, Effective device for WhisperModel: {device}, Compute type: {compute_type}")

            try:
                model_key = (selected_model_name, device, compute_type)
                if model_key in Transcriber._MODEL_POOL:
                    model = Transcriber._MODEL_POOL[model_key]
                    print(f"Reusing cached WhisperModel instance for {model_key}")
                else:
                    print(f"Initializing WhisperModel with directory: {model_dir_path}, device={device}, compute_type={compute_type}")
                    # model_dir_path is from the new ensure_cached
                    model = WhisperModel(model_size_or_path=str(model_dir_path), device=device, compute_type=compute_type)
                    Transcriber._MODEL_POOL[model_key] = model
                    print(f"Cached new WhisperModel instance for {model_key}")
                print("Faster-whisper model ready.")
            except Exception as model_load_err:
                print(f"[ERROR] Failed to load faster-whisper model: {model_load_err}")
                status = "error"
                # Provide more context if model_dir_path was involved
                err_detail_msg = f"Failed to load model from {model_dir_path if 'model_dir_path' in locals() else selected_model_name}: {model_load_err}"
                GLib.idle_add(completion_callback, status, [], None, err_detail_msg)
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

                        current_segments_done = i + 1
                        if progress_callback:
                            if total_duration > 0:
                                current_overall_transcription_pct = min(segment.end / total_duration, 1.0)
                                GLib.idle_add(progress_callback, current_overall_transcription_pct, current_segments_done, -1.0)
                            else:
                                current_overall_transcription_pct = 0.0 # Or some other appropriate value
                                GLib.idle_add(progress_callback, current_overall_transcription_pct, current_segments_done, -1.0)

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
                        current_overall_transcription_pct = 1.0
                        # current_segments_done is already updated
                        final_completed_count = last_segment_index + 1 if last_segment_index >=0 else current_segments_done
                        GLib.idle_add(progress_callback, current_overall_transcription_pct, final_completed_count, -1.0)

                    print(f"Finished processing segments for {file_path}.")

                    if status == "completed":
                        unique_id = str(uuid.uuid4())
                        timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
                        base_name = os.path.splitext(os.path.basename(file_path))[0]
                        destination_filename = f"{timestamp_str}_{base_name}.json"
                        destination_path = os.path.join(permanent_storage_dir, destination_filename)
                        print(f"Generated metadata: UUID={unique_id}, Timestamp={timestamp_str}, DestFile={destination_filename}")

                        # Prepare segments for JSON file storage as per spec (start, end, text, speaker)
                        segments_for_file = []
                        for seg_data in current_file_segments: # current_file_segments contains richer dicts
                            segments_for_file.append({
                                "start": round(seg_data['start'], 3),
                                "end": round(seg_data['end'], 3),
                                "text": seg_data['text'], # Already stripped
                                "speaker": ""  # Default speaker, as not directly provided by whisper segments
                            })

                        # final_json_data must match the structure defined in docs/refactordevspec.txt §1.1
                        # and expected by TranscriptItem.load_from_json
                        final_json_data = {
                            "uuid": unique_id,
                            "timestamp": timestamp_str,  # Format: YYYYMMDD_HHMMSS
                            "text": current_full_text.strip(),
                            "segments": segments_for_file,
                            "language": info.language if info else "unknown", # Ensure info is not None
                            "source_path": file_path,  # Path to the original media file
                            "audio_source_path": file_path, # Path to the original media file (spec has both)
                            "output_filename": destination_filename # Basename of the JSON file
                        }

                        try:
                            print(f"Attempting to save final transcript JSON to: {destination_path} using atomic_write_json")
                            # This is a blocking call but we are in a worker thread.
                            atomic_write_json(final_json_data, destination_path)
                            print(f"JSON saved successfully to {destination_path} via atomic_write_json.")
                            saved_json_path = destination_path # Store for completion callback
                            # status remains "completed"
                            all_files_segments.extend(current_file_segments) # Keep using richer segments for callback
                        except Exception as save_err:
                            print(f"[ERROR] Failed to save transcript JSON to {destination_path} using atomic_write_json: {save_err}")
                            status = "completed_save_failed" # Indicate transcription was ok, but save failed
                            save_error_message = str(save_err)


                except Exception as transcribe_err:
                    print(f"[ERROR] faster-whisper transcribe failed for {file_path}: {transcribe_err}")
                    status = "error" # Transcription error itself
                    save_error_message = str(transcribe_err) # Use this field for the primary error
                    break # Stop processing further files on transcription error


        finally:
            print(f"Transcription thread finishing with overall status: {status}")
            # Pass segments if transcription itself completed, regardless of save status for this specific callback argument
            final_segments_to_pass = all_files_segments if (status.startswith("completed") or status == "cancelled") else []
            GLib.idle_add(completion_callback, status, final_segments_to_pass, saved_json_path, save_error_message)
            print("Completion callback scheduled with save status.")


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
            GLib.idle_add(completion_callback, "no_files", [], None, "No files provided.")
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
