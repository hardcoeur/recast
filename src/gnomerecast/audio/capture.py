import gi
gi.require_version('Gst', '1.0')
from gi.repository import Gst, GLib

def list_audio_input_devices() -> list[str]:
    """
    Lists available audio input devices (sources) using Gst.DeviceMonitor.

    Returns:
        A list of strings, where each string is the display name of an audio input device.
        Returns an empty list if no devices are found or an error occurs.
    """
    devices_list = []
    monitor = None
    try:
        monitor = Gst.DeviceMonitor()
        if not monitor:
            print("Error: Could not create Gst.DeviceMonitor.")
            return []

        caps = Gst.Caps.new_empty_simple("audio/x-raw")
        monitor.add_filter("Audio/Source", caps)

        if not monitor.start():
            print("Error: Could not start Gst.DeviceMonitor.")
            return []

        devices = monitor.get_devices()
        if devices:
            for device in devices:
                display_name = device.get_display_name()

                if display_name:
                    devices_list.append(display_name)
                else:
                    print(f"Warning: Found an audio device without a display name.")
        else:
            print("No audio input devices found.")

    except Exception as e:
        print(f"An error occurred while listing audio devices: {e}")
    finally:
        if monitor:
            monitor.stop()

    print(f"Found audio input devices: {devices_list}")
    return devices_list
class AudioCapturer:
    """
    Captures audio using GStreamer and provides raw audio data via a callback.
    """
    def __init__(self, data_callback, source_type="mic"):
        """
        Initializes the AudioCapturer.

        Args:
            data_callback: A function to be called with raw audio data (bytes).
            source_type (str): The type of audio source to capture ("mic" or "monitor").
                               Defaults to "mic".
        """
        Gst.init(None)
        self.data_callback = data_callback
        self.source_type = source_type
        self.pipeline = None

        pipeline_string = None
        if self.source_type == "monitor":

            pipeline_string = (
                "audiotestsrc is-live=true wave=silence ! "
                "audioconvert ! audioresample ! "
                "capsfilter caps=audio/x-raw,format=S16LE,rate=16000,channels=1 ! "
                "appsink name=sink emit-signals=True max-buffers=1 drop=True"
            )
            try:
                self.pipeline = Gst.parse_launch(pipeline_string)
            except GLib.Error as e:
                print(f"Failed to create monitor placeholder pipeline: {e}. Audio capture will not work.")
                return
        elif self.source_type == "mic":


            mic_pipeline_string = (
                "pulsesrc ! audioconvert ! audioresample ! "
                "capsfilter caps=audio/x-raw,format=S16LE,rate=16000,channels=1 ! "
                "appsink name=sink emit-signals=True max-buffers=1 drop=True"
            )

            try:
                self.pipeline = Gst.parse_launch(mic_pipeline_string)
            except GLib.Error as e:
                print(f"Failed to create pipeline with pulsesrc: {e}. Trying autoaudiosrc...")
                mic_pipeline_string = (
                    "autoaudiosrc ! audioconvert ! audioresample ! "
                    "capsfilter caps=audio/x-raw,format=S16LE,rate=16000,channels=1 ! "
                    "appsink name=sink emit-signals=True max-buffers=1 drop=True"
                )
                try:
                     self.pipeline = Gst.parse_launch(mic_pipeline_string)
                except GLib.Error as e2:
                     print(f"Failed to create pipeline with autoaudiosrc: {e2}. Audio capture will not work.")
                     return
        else:
             print(f"Error: Invalid source_type '{self.source_type}'. Must be 'mic' or 'monitor'.")
             return


        if self.pipeline:
            appsink = self.pipeline.get_by_name('sink')
        if not appsink:
            print("Error: Could not find 'sink' element in the pipeline.")

            return


        appsink.connect("new-sample", self._on_new_sample)

    def _on_new_sample(self, appsink):
        """
        Handles the 'new-sample' signal from the appsink element.
        """
        sample = appsink.emit("pull-sample")
        if sample:
            buffer = sample.get_buffer()
            if buffer:
                success, map_info = buffer.map(Gst.MapFlags.READ)
                if success:
                    audio_data = map_info.data
                    if self.data_callback:

                        self.data_callback(bytes(audio_data))
                    buffer.unmap(map_info)
                    return Gst.FlowReturn.OK
                else:
                    print("Error: Failed to map buffer.")
            else:
                print("Error: Failed to get buffer from sample.")
        else:
            print("Error: Failed to pull sample from appsink.")

        return Gst.FlowReturn.ERROR

    def start(self):
        """
        Starts the audio capture pipeline.
        """
        if self.pipeline:
            if self.source_type == "monitor":
                 print("Starting audio capture pipeline (using MONITOR PLACEHOLDER - audiotestsrc)...")
            else:
                 print("Starting audio capture pipeline (mic)...")
            ret = self.pipeline.set_state(Gst.State.PLAYING)
            if ret == Gst.StateChangeReturn.FAILURE:
                print("Error: Unable to set the pipeline to the playing state.")
            elif ret == Gst.StateChangeReturn.ASYNC:
                print("Pipeline state change is asynchronous.")
            elif ret == Gst.StateChangeReturn.SUCCESS:
                 print("Pipeline started successfully.")

    def stop(self):
        """
        Stops the audio capture pipeline.
        """
        if self.pipeline:
            print("Stopping audio capture pipeline...")
            self.pipeline.set_state(Gst.State.NULL)
            print("Pipeline stopped.")


if __name__ == '__main__':
    import time
    from gi.repository import GLib


    def print_audio_data_size(data):
        print(f"Received audio data chunk of size: {len(data)} bytes")


    main_loop = GLib.MainLoop()


    capturer = AudioCapturer(print_audio_data_size)
    capturer.start()


    try:
        print("Running audio capture for 5 seconds...")
        GLib.timeout_add_seconds(5, main_loop.quit)
        main_loop.run()
    except KeyboardInterrupt:
        print("Interrupted by user.")
    finally:

        capturer.stop()
        print("Audio capture finished.")