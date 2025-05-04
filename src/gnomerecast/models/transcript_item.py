import gi
gi.require_version('GObject', '2.0')
from gi.repository import GObject
import uuid
import os
import json
from datetime import datetime
import pathlib

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
    source_path = GObject.Property(type=str, nick='Source Path', blurb='Original audio/video file path')
    transcript_text = GObject.Property(type=str, nick='Transcript Text', blurb='Full text content')
    timestamp = GObject.Property(type=str, nick='Timestamp', blurb='Creation timestamp (YYYY-MM-DD HH:MM:SS)')
    output_filename = GObject.Property(type=str, nick='Output Filename', blurb='Proposed permanent filename')
    segments = GObject.Property(type=GObject.TYPE_PYOBJECT, nick='Segments', blurb='List of SegmentItem objects')
    audio_source_path = GObject.Property(type=str, default=None, nick='Audio Source Path', blurb='Path to the original audio/video file')

    @classmethod
    def load_from_json(cls, json_path: str):
        """
        Loads transcript data from a JSON file.

        Args:
            json_path: The full path to the .json transcript file.

        Returns:
            A TranscriptItem instance populated with data, or None if an error occurs.
        """
        try:
            json_path_obj = pathlib.Path(json_path)

            if not json_path_obj.is_file() or json_path_obj.suffix != '.json':
                return None


            with json_path_obj.open('r', encoding='utf-8') as f:
                data = json.load(f)

            item_uuid = data.get('uuid')
            timestamp = data.get('timestamp')
            output_filename = data.get('output_filename', json_path_obj.name)
            source_path = data.get('source_path', f"Unknown source ({json_path_obj.name})")
            audio_source_path_val = data.get('audio_source_path')
            transcript_text = data.get('text', '')
            segments_data = data.get('segments', [])

            if not item_uuid or not timestamp:
                 print(f"Warning: Missing required 'uuid' or 'timestamp' in {json_path_obj.name}. Skipping.")
                 return None

            segments = []
            if isinstance(segments_data, list):
                for seg_dict in segments_data:
                    if isinstance(seg_dict, dict):
                         start = seg_dict.get('start')
                         end = seg_dict.get('end')
                         text = seg_dict.get('text', '')
                         speaker = seg_dict.get('speaker', '')
                         if start is not None and end is not None:
                             try:
                                 segments.append(SegmentItem(start=float(start), end=float(end), text=text, speaker=speaker))
                             except (ValueError, TypeError):
                                 print(f"Warning: Skipping segment with invalid start/end type in {json_path_obj.name}")
                         else:
                             print(f"Warning: Skipping segment with missing start/end in {json_path_obj.name}")

            return cls(
                source_path=source_path,
                audio_source_path=audio_source_path_val,
                transcript_text=transcript_text,
                item_uuid=item_uuid,
                timestamp=timestamp,
                output_filename=output_filename,
                segments=segments
            )

        except FileNotFoundError:
            return None
        except json.JSONDecodeError:
            print(f"Error: Could not decode JSON from file: {json_path}")
            return None
        except Exception as e:
            print(f"Error loading transcript from {json_path}: {e}")
            return None

    def __init__(self, source_path: str, transcript_text: str,
                 audio_source_path: str | None = None,
                 item_uuid: str | None = None, timestamp: str | None = None,
                 output_filename: str | None = None, segments: list | None = None):
        """
        Initializes a TranscriptItem.

        Args:
            source_path: Path to the .json metadata file.
            transcript_text: The transcribed text content.
            audio_source_path: Path to the original audio/video file (optional).
            item_uuid: Optional existing UUID. If None, a new one is generated.
            timestamp: Optional existing timestamp string. If None, the current time is used.
            output_filename: Optional proposed output filename. If None, generated from UUID.
            segments: Optional list of SegmentItem objects. Defaults to an empty list.
        """
        super().__init__()

        generated_uuid = item_uuid if item_uuid else str(uuid.uuid4())
        generated_timestamp = timestamp if timestamp else datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        generated_output_filename = output_filename if output_filename else f"{generated_uuid}.json"
        parsed_segments = segments if segments is not None else []

        if not all(isinstance(s, SegmentItem) for s in parsed_segments):
             print(f"Warning: Invalid segment data passed to TranscriptItem constructor for {generated_uuid}. Segments cleared.")
             parsed_segments = []


        self.set_property('uuid', generated_uuid)
        self.set_property('source_path', source_path)
        self.set_property('transcript_text', transcript_text)
        self.set_property('timestamp', generated_timestamp)
        self.set_property('output_filename', generated_output_filename)
        self.set_property('segments', parsed_segments)
        self.set_property('audio_source_path', audio_source_path)

    def to_dict(self) -> dict:
        """
        Serializes the TranscriptItem to a dictionary suitable for JSON storage.
        """
        return {
            'uuid': self.uuid,
            'source_path': self.source_path,
            'audio_source_path': self.audio_source_path,
            'transcript_text': self.transcript_text,
            'timestamp': self.timestamp,
            'output_filename': self.output_filename,
            'segments': [
                {
                    'start': seg.start,
                    'end': seg.end,
                    'text': seg.text,
                    'speaker': seg.speaker
                } for seg in self.segments
            ]
        }

    def __repr__(self):
        return (f"<TranscriptItem(uuid='{self.uuid}', source='{self.source_path}', "
                f"audio_source='{self.audio_source_path}', "
                f"timestamp='{self.timestamp}', output='{self.output_filename}')>")