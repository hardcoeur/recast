import gi
gi.require_version('GObject', '2.0')
from gi.repository import GObject
import uuid
import os
import json
from datetime import datetime
import pathlib
import logging # Added
from ..utils.io import atomic_write_json # Added

logger = logging.getLogger(__name__) # Added

class SegmentItem(GObject.Object):
    """
    Represents a single segment of a transcript.
    """
    __gtype_name__ = 'SegmentItem'

    start = GObject.Property(type=float, nick='Start Time', blurb='Segment start time (seconds)')
    end = GObject.Property(type=float, nick='End Time', blurb='Segment end time (seconds)')
    text = GObject.Property(type=str, nick='Text', blurb='Segment text content')
    speaker = GObject.Property(type=str, nick='Speaker', blurb='Identified speaker (placeholder)', default='')

    def __init__(self, start: float, end: float, text: str, speaker: str = ''):
        """
        Initializes a SegmentItem.

        Args:
            start: Start time in seconds.
            end: End time in seconds.
            text: Text content of the segment.
            speaker: Speaker identifier (optional, defaults to empty).
        """
        super().__init__()
        self.set_property('start', start)
        self.set_property('end', end)
        self.set_property('text', text)
        self.set_property('speaker', speaker)

    def __repr__(self):
        return f"<SegmentItem(start={self.start:.2f}, end={self.end:.2f}, text='{self.text[:20]}...')>"


class TranscriptItem(GObject.Object):
    """
    Represents a single completed transcription result.
    """
    __gtype_name__ = 'TranscriptItem'

    uuid = GObject.Property(type=str, nick='UUID', blurb='Unique identifier')
    source_path = GObject.Property(type=str, nick='JSON File Path', blurb='Path to the .json transcript file itself')
    transcript_text = GObject.Property(type=str, nick='Transcript Text', blurb='Full text content')
    timestamp = GObject.Property(type=str, nick='Timestamp', blurb='Creation timestamp (YYYYMMDD_HHMMSS in JSON, YYYY-MM-DD HH:MM:SS internally)')
    output_filename = GObject.Property(type=str, nick='Output Filename', blurb='Filename of the JSON transcript file (basename of source_path)')
    segments = GObject.Property(type=GObject.TYPE_PYOBJECT, nick='Segments', blurb='List of SegmentItem objects')
    audio_source_path = GObject.Property(type=str, default="", nick='Media Source Path', blurb='Path to the original audio/video file that was transcribed')
    language = GObject.Property(type=str, default="en", nick='Language', blurb='Detected language code (e.g., "en", "es")')


    @classmethod
    def load_from_json(cls, json_file_path: str):
        """
        Loads transcript data from a JSON file according to docs/refactordevspec.txt.

        Args:
            json_file_path: The full path to the .json transcript file.

        Returns:
            A TranscriptItem instance populated with data.
        Raises:
            FileNotFoundError: If the json_file_path does not exist.
            json.JSONDecodeError: If the file content is not valid JSON.
            ValueError: If the JSON content is malformed or missing mandatory keys
                        as per docs/refactordevspec.txt §1.1.
        """
        try:
            path_obj = pathlib.Path(json_file_path)
            if not path_obj.is_file():
                raise FileNotFoundError(f"Transcript JSON file not found: {json_file_path}")

            with path_obj.open('r', encoding='utf-8') as f:
                data = json.load(f)

            # Validate mandatory keys as per docs/refactordevspec.txt §1.1
            # Mandatory keys in JSON: uuid, timestamp, text, segments, language, source_path (media), audio_source_path (media), output_filename (JSON filename)
            # Note: The spec lists 'source_path' and 'audio_source_path' for media. We'll prioritize 'audio_source_path' if both exist.
            # The 'output_filename' in JSON should match the actual JSON filename.
            # The 'source_path' for the TranscriptItem object itself will be json_file_path.

            spec_mandatory_keys = ['uuid', 'timestamp', 'text', 'segments', 'language', 'output_filename']
            # 'source_path' (media) and 'audio_source_path' (media) are also in spec, handle them carefully
            
            missing_keys = [key for key in spec_mandatory_keys if key not in data]
            if missing_keys:
                raise ValueError(f"JSON file {json_file_path} is missing mandatory keys: {', '.join(missing_keys)}")

            # Check for media path keys
            if 'audio_source_path' not in data and 'source_path' not in data:
                raise ValueError(f"JSON file {json_file_path} must contain either 'audio_source_path' or 'source_path' for the media file.")

            item_uuid = data['uuid']
            json_timestamp_str = data['timestamp'] # Expected YYYYMMDD_HHMMSS from spec
            transcript_text = data['text']
            segments_data = data['segments']
            language_code = data['language']
            output_filename_from_json = data['output_filename']

            # Media path: prioritize 'audio_source_path', then 'source_path' from JSON for the media file
            media_path = data.get('audio_source_path', data.get('source_path'))

            if not isinstance(item_uuid, str) or not item_uuid:
                raise ValueError(f"Invalid or missing 'uuid' (must be non-empty string) in {json_file_path}")
            if not isinstance(json_timestamp_str, str) or not json_timestamp_str: # TODO: Add more specific format validation for YYYYMMDD_HHMMSS
                raise ValueError(f"Invalid or missing 'timestamp' (must be non-empty string) in {json_file_path}")
            try: # Validate timestamp format
                datetime.strptime(json_timestamp_str, "%Y%m%d_%H%M%S")
            except ValueError as e:
                raise ValueError(f"Invalid 'timestamp' format in {json_file_path}. Expected YYYYMMDD_HHMMSS. Error: {e}") from e
            if not isinstance(transcript_text, str): # Allow empty string for text
                 raise ValueError(f"Invalid 'text' (must be string) in {json_file_path}")
            if not isinstance(language_code, str) or not language_code :
                raise ValueError(f"Invalid or missing 'language' (must be non-empty string) in {json_file_path}")
            if not isinstance(output_filename_from_json, str) or not output_filename_from_json:
                raise ValueError(f"Invalid or missing 'output_filename' (must be non-empty string) in {json_file_path}")
            if output_filename_from_json != path_obj.name:
                logger.warning(f"Output filename in JSON ('{output_filename_from_json}') does not match actual filename ('{path_obj.name}') for {json_file_path}. Using actual filename as definitive.")


            segments = []
            if not isinstance(segments_data, list):
                raise ValueError(f"'segments' field must be a list in {json_file_path}")

            for i, seg_dict in enumerate(segments_data):
                if not isinstance(seg_dict, dict):
                    logger.warning(f"Segment at index {i} is not a dictionary in {json_file_path}. Skipping.")
                    continue

                try:
                    # Try to get 'text' first, as it's essential.
                    text = seg_dict.get('text')
                    if text is None: # Explicitly check for None, as empty string is valid
                        logger.warning(f"Segment at index {i} in {json_file_path} is missing 'text'. Skipping.")
                        continue
                    text = str(text).strip()

                    # Handle 'start' and 'end' times, preferring direct float values
                    # then 'start_ms'/'end_ms', then falling back if neither.
                    start_time_s: float | None = None
                    end_time_s: float | None = None

                    if 'start' in seg_dict and isinstance(seg_dict['start'], (float, int)):
                        start_time_s = float(seg_dict['start'])
                    elif 'start_ms' in seg_dict and isinstance(seg_dict['start_ms'], (float, int)):
                        start_time_s = float(seg_dict['start_ms']) / 1000.0
                    
                    if 'end' in seg_dict and isinstance(seg_dict['end'], (float, int)):
                        end_time_s = float(seg_dict['end'])
                    elif 'end_ms' in seg_dict and isinstance(seg_dict['end_ms'], (float, int)):
                        end_time_s = float(seg_dict['end_ms']) / 1000.0

                    if start_time_s is None or end_time_s is None:
                        logger.warning(f"Segment at index {i} in {json_file_path} is missing valid 'start'/'end' times or 'start_ms'/'end_ms'. Skipping.")
                        continue
                    
                    # Speaker is optional as per spec, defaults to ""
                    speaker = str(seg_dict.get('speaker', ''))

                    segments.append(SegmentItem(start=start_time_s, end=end_time_s, text=text, speaker=speaker))
                
                except (ValueError, TypeError) as e:
                    logger.warning(f"Malformed segment data at index {i} in {json_file_path} (type error or value error: {e}). Skipping.")
                    continue
                except Exception as e_seg: # Catch any other unexpected error within segment processing
                    logger.error(f"Unexpected error processing segment at index {i} in {json_file_path}: {e_seg}", exc_info=True)
                    continue # Skip this segment and try the next

            # The 'source_path' for the TranscriptItem constructor is the path to the JSON file itself.
            # The 'output_filename' for constructor is derived from this json_file_path.
            return cls(
                source_path=str(path_obj),      # Path to this JSON file
                audio_source_path=media_path,   # Path to the original media
                transcript_text=transcript_text,
                item_uuid=item_uuid,
                timestamp_str=json_timestamp_str, # Pass YYYYMMDD_HHMMSS to constructor
                segments=segments,
                language=language_code
            )

        except (FileNotFoundError, json.JSONDecodeError, ValueError) as e: # Re-raise specific, handled exceptions
            logger.error(f"Failed to load transcript from {json_file_path}: {e}", exc_info=True)
            raise
        except Exception as e: # Catch any other unexpected error
            logger.error(f"Unexpected error loading transcript from {json_file_path}: {e}", exc_info=True)
            # Wrap unexpected errors in ValueError for consistent error type from this method
            raise ValueError(f"An unexpected error occurred while loading {json_file_path}") from e


    def __init__(self, source_path: str, transcript_text: str,
                 audio_source_path: str | None = "", # Default to empty string as per GObject prop
                 item_uuid: str | None = None,
                 timestamp_str: str | None = None, # Expects YYYYMMDD_HHMMSS from load_from_json, or None
                 segments: list | None = None,
                 language: str | None = "en"): # Default to "en" as per GObject prop
        """
        Initializes a TranscriptItem.

        Args:
            source_path: Path to the .json metadata file for this transcript.
            transcript_text: The transcribed text content.
            audio_source_path: Path to the original audio/video file (optional).
            item_uuid: Optional existing UUID. If None, a new one is generated.
            timestamp_str: Optional existing timestamp string.
                           If from JSON, expected format YYYYMMDD_HHMMSS.
                           If None, current time is used and formatted to YYYY-MM-DD HH:MM:SS for internal use.
            segments: Optional list of SegmentItem objects. Defaults to an empty list.
            language: Language code (e.g., "en"). Defaults to "en".
        """
        super().__init__()

        self.set_property('uuid', item_uuid if item_uuid else str(uuid.uuid4()))
        self.set_property('source_path', source_path) # Path to this JSON file
        self.set_property('transcript_text', transcript_text)

        if timestamp_str:
            try:
                # Convert YYYYMMDD_HHMMSS from JSON to YYYY-MM-DD HH:MM:SS for internal storage
                dt_obj = datetime.strptime(timestamp_str, "%Y%m%d_%H%M%S")
                internal_timestamp = dt_obj.strftime("%Y-%m-%d %H:%M:%S")
            except ValueError:
                logger.warning(f"Invalid timestamp format '{timestamp_str}' for UUID {self.uuid}. Using current time. Expected YYYYMMDD_HHMMSS.")
                internal_timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        else:
            internal_timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.set_property('timestamp', internal_timestamp)

        # output_filename is the basename of the JSON file path (source_path)
        self.set_property('output_filename', pathlib.Path(source_path).name if source_path else f"{self.uuid}.json")
        
        parsed_segments = segments if segments is not None else []
        if not all(isinstance(s, SegmentItem) for s in parsed_segments):
             logger.warning(f"Invalid segment data passed to TranscriptItem constructor for {self.uuid}. Segments cleared.")
             parsed_segments = []
        self.set_property('segments', parsed_segments)
        self.set_property('audio_source_path', audio_source_path if audio_source_path is not None else "")
        self.set_property('language', language if language is not None else "en")


    def to_dict(self) -> dict:
        """
        Serializes the TranscriptItem to a dictionary suitable for JSON storage,
        adhering to the spec in docs/refactordevspec.txt §1.1.
        Keys: uuid, timestamp (YYYYMMDD_HHMMSS), text, segments, language,
              source_path (media), audio_source_path (media), output_filename (JSON filename)
        """
        # Convert internal timestamp (YYYY-MM-DD HH:MM:SS) to JSON format (YYYYMMDD_HHMMSS)
        try:
            dt_obj = datetime.strptime(self.timestamp, "%Y-%m-%d %H:%M:%S")
            json_timestamp = dt_obj.strftime("%Y%m%d_%H%M%S")
        except ValueError:
            logger.warning(f"Could not parse internal timestamp '{self.timestamp}' for UUID {self.uuid} during to_dict. Using as is for JSON.")
            # Fallback: try to convert if it's already in YYYYMMDD_HHMMSS due to direct setting or error
            try:
                datetime.strptime(self.timestamp, "%Y%m%d_%H%M%S") # just validate
                json_timestamp = self.timestamp
            except ValueError: # if truly unparseable by either format
                 logger.error(f"Unparseable internal timestamp '{self.timestamp}' for UUID {self.uuid}. Defaulting timestamp in JSON.")
                 json_timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")


        return {
            'uuid': self.uuid,
            'timestamp': json_timestamp,
            'text': self.transcript_text, # Full transcript text
            'segments': [ # List of segment objects
                {
                    'start': round(seg.start, 3), # float seconds, rounded
                    'end': round(seg.end, 3),     # float seconds, rounded
                    'text': seg.text,             # string, trimmed (SegmentItem __init__ should handle trim if needed)
                    'speaker': seg.speaker        # string, may be empty
                } for seg in self.segments
            ],
            'language': self.language, # string
            'source_path': self.audio_source_path, # Path to original media file (as per spec example for this key)
            'audio_source_path': self.audio_source_path, # Path to original media file (explicitly named)
            'output_filename': self.output_filename # Basename of the JSON file itself (e.g., "YYYYMMDD_HHMMSS_basename.json")
        }

    def to_segment_dicts(self) -> list[dict]:
        """
        Returns the list of segment data as dictionaries.
        New method as per spec §7.
        """
        return [
            {
                'start': round(seg.start, 3),
                'end': round(seg.end, 3),
                'text': seg.text,
                'speaker': seg.speaker
            } for seg in self.segments
        ]

    def save(self):
        """
        Saves the current transcript item to its `source_path` (which is the JSON file path)
        using `atomic_write_json`.
        New method as per spec §7.
        This method itself does not handle threading; the caller should use a thread pool.
        """
        if not self.source_path:
            # This should ideally not happen if object is constructed correctly via load_from_json or with a valid path.
            raise ValueError("Cannot save TranscriptItem: source_path (JSON file path) is not set.")
        
        data_to_save = self.to_dict()
        try:
            # The self.source_path property should point to the target JSON file.
            atomic_write_json(data_to_save, self.source_path)
            logger.info(f"TranscriptItem {self.uuid} saved to {self.source_path}")
        except Exception as e:
            logger.error(f"Failed to save TranscriptItem {self.uuid} to {self.source_path}: {e}", exc_info=True)
            raise # Re-raise to allow caller to handle (e.g., show toast in UI)


    def __repr__(self):
        return (f"<TranscriptItem(uuid='{self.uuid}', json_file='{self.source_path}', "
                f"media_file='{self.audio_source_path}', lang='{self.language}', "
                f"timestamp='{self.timestamp}')>")