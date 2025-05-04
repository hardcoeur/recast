import requests
import threading
import os
import pathlib
from typing import Optional, Callable, Tuple
from gi.repository import GLib

ProgressCallback = Callable[[int, int, Optional[str]], None]

def download_file(
    url: str,
    target_path: pathlib.Path,
    progress_callback: Optional[ProgressCallback] = None,
    cancel_event: Optional[threading.Event] = None
) -> Tuple[str, Optional[str]]:
    """
    Downloads a file from a URL to a target path, reporting progress and allowing cancellation.

    Args:
        url: The URL to download the file from.
        target_path: The pathlib.Path object representing the destination file path.
        progress_callback: A function to call with (current_bytes, total_bytes, error_message) updates.
                           It's the caller's responsibility to ensure this callback is thread-safe
                           or marshalled to the correct thread (e.g., using GLib.idle_add).
        cancel_event: A threading.Event object to signal cancellation.

    Returns:
        A tuple containing:
        - status string: 'completed', 'cancelled', or 'error'.
        - error message string (if status is 'error'), otherwise None.
    """
    temp_path = target_path.with_suffix(target_path.suffix + ".part")
    status = "error"
    error_message = None
    downloaded_size = 0
    total_size = -1

    try:
        target_path.parent.mkdir(parents=True, exist_ok=True)

        print(f"Starting download: {url} to {target_path}")

        response = requests.get(url, stream=True, timeout=60)
        response.raise_for_status()

        total_size = int(response.headers.get('content-length', 0))
        chunk_size = 8192

        if progress_callback:
            progress_callback(0, total_size, None)

        with open(temp_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=chunk_size):
                if cancel_event and cancel_event.is_set():
                    print(f"Download cancellation requested: {url}")
                    status = "cancelled"


                    f.close()
                    temp_path.unlink(missing_ok=True)
                    print(f"Partial download file deleted: {temp_path}")
                    return status, None

                if chunk:
                    f.write(chunk)
                    downloaded_size += len(chunk)
                    if progress_callback:
                        progress_callback(downloaded_size, total_size, None)

        temp_path.rename(target_path)
        print(f"Download completed: {url}")
        status = "completed"
        if progress_callback:
            progress_callback(downloaded_size, total_size, None)

    except requests.exceptions.Timeout:
        error_message = "Connection timed out."
        print(f"Error downloading file {url}: {error_message}")
        if temp_path.exists():
            temp_path.unlink(missing_ok=True)
        if progress_callback:
            progress_callback(downloaded_size, total_size, error_message)
    except requests.exceptions.RequestException as e:
        error_message = f"Network error: {e}"
        print(f"Error downloading file {url}: {error_message}")
        if temp_path.exists():
            temp_path.unlink(missing_ok=True)
        if progress_callback:
            progress_callback(downloaded_size, total_size, error_message)
    except OSError as e:
        error_message = f"File system error: {e}"
        print(f"Error saving file {url} to {target_path}: {error_message}")
        if temp_path.exists():
            temp_path.unlink(missing_ok=True)
        if progress_callback:
            progress_callback(downloaded_size, total_size, error_message)
    except Exception as e:
        error_message = f"Unexpected error: {e}"
        print(f"Unexpected error during download of {url}: {error_message}")
        if 'temp_path' in locals() and temp_path.exists():
             temp_path.unlink(missing_ok=True)
        if progress_callback:
            progress_callback(downloaded_size, total_size, error_message)

    return status, error_message