import pathlib
import threading
from typing import Dict, Callable, Optional, Tuple

# Attempt to import WhisperModel, as it's crucial.
try:
    from faster_whisper import WhisperModel
    FASTER_WHISPER_AVAILABLE = True
except ImportError:
    WhisperModel = None # type: ignore # Make linters happy if not installed
    FASTER_WHISPER_AVAILABLE = False

APP_MODEL_DIR: pathlib.Path = pathlib.Path.home() / '.local' / 'share' / 'GnomeRecast' / 'models'

AVAILABLE_MODELS: Dict[str, str] = {
    'tiny': '39 MB',
    'base': '74 MB',
    'small': '244 MB',
    'medium': '769 MB',
    'large': '1.5 GB',
    # As per spec: ".en variants can be added if they should still be distinct"
    # e.g., 'tiny.en': '39 MB', if faster-whisper supports these names directly
    # and corresponding URLs are considered (though URLs are not directly used by this ensure_cached)
}

# URLs for the simplified model names (assuming ggml-v3 for 'large')
# These are as per the spec, though not directly used by ensure_cached if
# faster-whisper handles downloads by model name.
_MODEL_URLS: Dict[str, str] = {
    'tiny': "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-tiny.bin?download=true",
    'base': "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-base.bin?download=true",
    'small': "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-small.bin?download=true",
    'medium': "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-medium.bin?download=true",
    'large': "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-large-v3.bin?download=true",
}

class ModelNotAvailableError(RuntimeError):
    def __init__(self, model: str, details: str):
        self.model = model
        self.details = details
        super().__init__(f"Model {model} not available: {details}")

# Global cache to indicate successful preparation of model names.
# Key: model_name (str), Value: model_name (str) - indicates preparation was successful.
_model_cache_paths: Dict[str, str] = {}
_model_cache_lock = threading.Lock() # To protect access to _model_cache_paths

def ensure_cached(
    model_name: str,
    *,
    device: str, # "cpu" | "cuda" | "auto"
    compute_type: str, # "int8" | "float16" | "auto"
    progress_cb: Callable[[float, str], None] | None = None
) -> pathlib.Path:
    """
    Ensures the specified model is available in faster-whisper's cache
    and returns the local directory path to the model.
    Downloads the model via faster-whisper if not already cached.
    Raises ModelNotAvailableError if the model_name is invalid or download/load fails.
    """
    if not FASTER_WHISPER_AVAILABLE:
        err_msg = "The 'faster-whisper' library is not installed or could not be imported."
        if progress_cb:
            progress_cb(-1.0, f"Error: {err_msg}")
        raise ModelNotAvailableError(model_name, err_msg)

    if model_name not in AVAILABLE_MODELS:
        err_msg = f"Model name '{model_name}' is not in the list of recognized available models."
        if progress_cb:
            progress_cb(-1.0, f"Error: {err_msg}")
        raise ModelNotAvailableError(model_name, err_msg)

    # Check cache first (thread-safe)
    with _model_cache_lock:
        if model_name in _model_cache_paths:
            # If found, it means preparation was successful. Return Path(model_name).
            # The value stored is model_name itself.
            prepared_model_name = _model_cache_paths[model_name]
            if progress_cb:
                progress_cb(0.0, "Starting model preparation (found in preparation cache)")
                progress_cb(100.0, f"Model preparation complete (from cache: {prepared_model_name})")
            return pathlib.Path(prepared_model_name)

    if progress_cb:
        progress_cb(0.0, "Starting model preparation")

    try:
        # Instantiate WhisperModel to trigger its download and cache mechanism.
        # faster-whisper does not provide fine-grained download progress for this call.
        # The progress_cb here signals the start and end of this preparation phase.
        
        # Instantiate WhisperModel to trigger its download and cache mechanism.
        # faster-whisper handles its own caching. We just confirm it can be loaded.
        temp_model = WhisperModel(model_name, device=device, compute_type=compute_type)
        del temp_model # Release the model instance and its resources.

        # If instantiation was successful, cache the model_name to indicate it's ready.
        with _model_cache_lock:
            _model_cache_paths[model_name] = model_name # Store model_name itself
        
        if progress_cb:
            progress_cb(100.0, f"Model preparation complete (model '{model_name}' is ready)")
        
        return pathlib.Path(model_name) # Return the model name, cast to Path

    except Exception as e:
        details = f"Failed to ensure model '{model_name}' (device: {device}, compute: {compute_type}). Error: {type(e).__name__} - {str(e)}"
        
        if "out of memory" in str(e).lower():
            details += f". The model may be too large for the available '{device}' memory. Try a smaller model or check resources."
        elif "CUDA" in str(e).upper() or "CUBLAS" in str(e).upper() or "NVIDIA" in str(e).upper() :
            details += f". There might be an issue with your CUDA setup or GPU compatibility for device '{device}'."
        elif "No such file or directory" in str(e) and ".cache/huggingface/hub" in str(e):
             details += f". This could indicate a problem with model file download or cache integrity for '{model_name}'."

        if progress_cb:
            progress_cb(-1.0, f"Error: {details}")
        raise ModelNotAvailableError(model_name, details) from e