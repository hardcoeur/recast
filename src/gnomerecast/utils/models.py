import os
import pathlib
import requests
import threading
import pathlib
from typing import List, Dict, Union, Optional, Callable, Tuple
from gi.repository import GLib

from .download import download_file, ProgressCallback as DownloadProgressCallback

APP_MODEL_DIR = pathlib.Path.home() / ".local" / "share" / "GnomeRecast" / "models"

AVAILABLE_MODELS = {
    "tiny.en": {"url": "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-tiny.en.bin?download=true", "size": "~75 MB"},
    "tiny": {"url": "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-tiny.bin?download=true", "size": "~75 MB"},
    "base.en": {"url": "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-base.en.bin?download=true", "size": "~142 MB"},
    "base": {"url": "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-base.bin?download=true", "size": "~142 MB"},
    "small.en": {"url": "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-small.en.bin?download=true", "size": "~466 MB"},
    "small": {"url": "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-small.bin?download=true", "size": "~466 MB"},
    "medium.en": {"url": "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-medium.en.bin?download=true", "size": "~1.5 GB"},
    "medium": {"url": "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-medium.bin?download=true", "size": "~1.5 GB"},
    "large-v2": {"url": "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-large-v2.bin?download=true", "size": "~2.9 GB"},
    "large-v3": {"url": "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-large-v3.bin?download=true", "size": "~2.9 GB"},
}


def get_available_models() -> Dict[str, Dict[str, str]]:
    """Returns a dictionary of available models for download."""
    return AVAILABLE_MODELS.copy()


def _format_size(size_bytes: int) -> str:
    """Formats size in bytes to a human-readable string (KB, MB, GB)."""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024**2:
        return f"{size_bytes / 1024:.1f} KB"
    elif size_bytes < 1024**3:
        return f"{size_bytes / (1024**2):.1f} MB"
    else:
        return f"{size_bytes / (1024**3):.1f} GB"

def list_local_models() -> List[Dict[str, Union[str, int]]]:
    """
    Checks the application's model directory for downloaded ggml models (.bin files)
    and returns their details.
    """
    local_models = []
    if not APP_MODEL_DIR.exists():
        print(f"Application model directory not found: {APP_MODEL_DIR}")
        return local_models

    print(f"Checking for models in: {APP_MODEL_DIR}")
    try:
        for item in APP_MODEL_DIR.glob("ggml-*.bin"):
            if item.is_file():
                model_name = item.name.replace("ggml-", "").replace(".bin", "")
                print(f"Found local model file: {item.name} (parsed as: {model_name})")
                try:
                    size_bytes = item.stat().st_size
                    formatted_size = _format_size(size_bytes)
                    local_models.append({
                        "name": model_name,
                        "path": str(item),
                        "size": formatted_size,
                        "size_bytes": size_bytes,
                    })
                except OSError as e:
                    print(f"Error getting stats for {item}: {e}")
                    local_models.append({
                        "name": model_name,
                        "path": str(item),
                        "size": "Error",
                        "size_bytes": -1,
                    })
    except OSError as e:
        print(f"Error scanning model directory {APP_MODEL_DIR}: {e}")

    local_models.sort(key=lambda x: x["name"])

    print(f"Detected local models: {local_models}")
    return local_models


def download_model(
    model_name: str,
    download_url: str,
    target_dir: pathlib.Path,
    progress_callback: Optional[Callable[[str, float, Optional[str]], None]] = None,
    cancel_event: Optional[threading.Event] = None
) -> Tuple[str, Optional[str]]:
    """
    Downloads a model file using the generic download utility, reporting progress
    and allowing cancellation via callbacks compatible with the model management UI.

    Args:
        model_name: The name of the model (used for callbacks).
        download_url: The URL to download the model from.
        target_dir: The pathlib.Path directory to save the model file in.
        progress_callback: A function to call with (model_name, percentage, error_message) updates.
                           The percentage will be:
                           - 0.0 to 100.0 for progress
                           - -1.0 for error
                           - -2.0 for cancelled
                           Must be scheduled on the main thread (e.g., using GLib.idle_add).
        cancel_event: A threading.Event object to signal cancellation.

    Returns:
        A tuple containing:
        - status string: 'completed', 'cancelled', or 'error'.
        - error message string (if status is 'error'), otherwise None.
    """
    filename = download_url.split('/')[-1].split('?')[0]
    if not filename or not filename.endswith(".bin"):
        filename = f"ggml-{model_name}.bin"
        print(f"Warning: Could not reliably determine filename from URL '{download_url}'. Using '{filename}'.")

    target_path = target_dir / filename

    def _model_progress_wrapper(current_bytes: int, total_bytes: int, error_msg: Optional[str]):
        if progress_callback:
            percentage = -1.0
            if error_msg:
                percentage = -1.0
            elif cancel_event and cancel_event.is_set():
                 percentage = -2.0
            elif total_bytes > 0:
                percentage = (current_bytes / total_bytes) * 100
            elif current_bytes > 0:
                percentage = 0.0
            else:
                 percentage = 0.0

            GLib.idle_add(progress_callback, model_name, percentage, error_msg)

    status, error_message = download_file(
        url=download_url,
        target_path=target_path,
        progress_callback=_model_progress_wrapper if progress_callback else None,
        cancel_event=cancel_event
    )

    if progress_callback:
        final_percentage = -1.0
        if status == "completed":
            final_percentage = 100.0
        elif status == "cancelled":
            final_percentage = -2.0


        GLib.idle_add(progress_callback, model_name, final_percentage, error_message if status == "error" else None)

    return status, error_message