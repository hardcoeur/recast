import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    # Ensure this matches the actual SegmentItem class if used, or just TranscriptItem
    from ..models.transcript_item import TranscriptItem, SegmentItem

def _format_timestamp_srt(seconds: float) -> str:
    """Formats seconds into SRT timestamp HH:MM:SS,ms."""
    delta = datetime.timedelta(seconds=seconds)
    hours, remainder = divmod(delta.total_seconds(), 3600)
    minutes, seconds = divmod(remainder, 60)
    milliseconds = int((seconds - int(seconds)) * 1000)
    return f"{int(hours):02}:{int(minutes):02}:{int(seconds):02},{milliseconds:03}"

def _format_timestamp_md(seconds: float) -> str:
    """Formats seconds into MD timestamp HH:MM:SS."""
    delta = datetime.timedelta(seconds=seconds)
    hours, remainder = divmod(delta.total_seconds(), 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{int(hours):02}:{int(minutes):02}:{int(seconds):02}"

def export_to_txt(transcript_item: 'TranscriptItem') -> str:
    """Exports the transcript item to plain text with double newlines between segments."""
    if not transcript_item or not transcript_item.segments:
        return ""

    # Assuming transcript_item.segments is a list of SegmentItem objects
    return "\n\n".join(segment.text.strip() for segment in transcript_item.segments if hasattr(segment, 'text') and segment.text)

def export_to_md(transcript_item: 'TranscriptItem') -> str:
    """Exports the transcript item to Markdown format."""
    if not transcript_item.segments:
        return ""

    md_content = []
    for segment in transcript_item.segments:
        start_time_str = _format_timestamp_md(segment.start)
        segment_text = segment.text.strip() if segment.text else ""
        md_content.append(f"**[{start_time_str}]** {segment_text}")

    return "\n\n".join(md_content)

def export_to_srt(transcript_item: 'TranscriptItem') -> str:
    """Exports the transcript item to SRT format."""
    if not transcript_item.segments:
        return ""

    srt_content = []
    for i, segment in enumerate(transcript_item.segments):
        start_time_str = _format_timestamp_srt(segment.start)
        end_time_str = _format_timestamp_srt(segment.end)
        segment_text = segment.text.strip() if segment.text else ""

        srt_content.append(str(i + 1))
        srt_content.append(f"{start_time_str} --> {end_time_str}")
        srt_content.append(segment_text)
        srt_content.append("")

    return "\n".join(srt_content)