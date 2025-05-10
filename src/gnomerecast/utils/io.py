import json
import logging
import os
import tempfile
from pathlib import Path

# Initialize logger for this module
logger = logging.getLogger(__name__)

def atomic_write_json(data: dict, file_path_str: str) -> None:
    """
    Atomically writes a dictionary to a JSON file.

    It first writes to a temporary file in the same directory, then renames it
    to the final destination, ensuring that the destination file is either
    the old version or the new version, never a partially written one.

    Args:
        data: The dictionary to write to JSON.
        file_path_str: The absolute path to the target JSON file.

    Raises:
        OSError: If file operations fail (e.g., permission issues).
        TypeError: If the data is not JSON serializable.
        ValueError: If JSON encoding fails for other reasons.
    """
    try:
        path_obj = Path(file_path_str)
        # Ensure the parent directory exists
        path_obj.parent.mkdir(parents=True, exist_ok=True)

        # Use NamedTemporaryFile in the same directory as the target file
        # to ensure os.replace works (it might fail across different filesystems).
        # delete=False is crucial as we handle the deletion/renaming manually.
        with tempfile.NamedTemporaryFile(
            mode='w',
            encoding='utf-8',
            dir=path_obj.parent,
            prefix=path_obj.name + '.',
            suffix='.tmp',
            delete=False
        ) as tmp_file:
            temp_file_path = tmp_file.name
            json.dump(data, tmp_file, indent=4, ensure_ascii=False)
            # Ensure data is written to disk before renaming
            tmp_file.flush()
            os.fsync(tmp_file.fileno())

        # Atomically replace the target file with the temporary file
        os.replace(temp_file_path, path_obj)
        logger.info(f"Successfully wrote JSON data to {path_obj}")

    except (OSError, IOError) as e:
        logger.error(f"Error writing JSON to {file_path_str}: {e}", exc_info=True)
        # Clean up the temporary file if it still exists and an error occurred
        if 'temp_file_path' in locals() and Path(temp_file_path).exists():
            try:
                os.remove(temp_file_path)
            except OSError as remove_err:
                logger.error(f"Error removing temporary file {temp_file_path}: {remove_err}", exc_info=True)
        raise  # Re-raise the original exception
    except (TypeError, ValueError) as e:
        logger.error(f"Error serializing data to JSON for {file_path_str}: {e}", exc_info=True)
        # Clean up the temporary file
        if 'temp_file_path' in locals() and Path(temp_file_path).exists():
            try:
                os.remove(temp_file_path)
            except OSError as remove_err:
                logger.error(f"Error removing temporary file {temp_file_path}: {remove_err}", exc_info=True)
        raise # Re-raise the original exception
    except Exception as e:
        logger.error(f"An unexpected error occurred during atomic_write_json for {file_path_str}: {e}", exc_info=True)
        if 'temp_file_path' in locals() and Path(temp_file_path).exists():
            try:
                os.remove(temp_file_path)
            except OSError as remove_err:
                logger.error(f"Error removing temporary file {temp_file_path}: {remove_err}", exc_info=True)
        raise

if __name__ == '__main__':
    # Example usage (for testing purposes)
    logging.basicConfig(level=logging.INFO)
    test_data_dir = Path(__file__).parent.parent.parent / "test_data" # Assuming a test_data directory at project root
    test_data_dir.mkdir(exist_ok=True)
    test_file = test_data_dir / "test_atomic_write.json"

    sample_data = {
        "name": "Test Recast",
        "version": "1.0",
        "items": [1, 2, 3],
        "settings": {"theme": "dark", "notifications": True}
    }

    print(f"Attempting to write to: {test_file}")
    try:
        atomic_write_json(sample_data, str(test_file))
        print(f"Successfully wrote to {test_file}")

        # Verify content
        with open(test_file, 'r', encoding='utf-8') as f:
            read_data = json.load(f)
        assert read_data == sample_data
        print("File content verified.")

    except Exception as e:
        print(f"An error occurred during example usage: {e}")

    finally:
        # Clean up the test file
        if test_file.exists():
            # os.remove(test_file)
            print(f"Test file {test_file} can be manually inspected or removed.")