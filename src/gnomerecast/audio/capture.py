import gi
gi.require_version('Gst', '1.0')
gi.require_version('GObject', '2.0')
gi.require_version('Gio', '2.0') # For Gio.Settings

from gi.repository import Gst, GLib, GObject, Gio
from typing import Optional, Callable

# Import new utilities
from ..audio.device_utils import get_input_devices, AudioInputDevice
from ..audio.wp_default_tracker import DefaultSourceTracker


class AudioCapturer(GObject.Object):
    """
    Captures audio using GStreamer, provides raw audio data via a callback or signal,
    and supports dynamic device selection and default device tracking.
    """
    __gsignals__ = {
        'source-changed': (GObject.SignalFlags.RUN_FIRST, None, (str,)), # Emits new source description
        'error': (GObject.SignalFlags.RUN_FIRST, None, (str,)), # Emits error message
        # PyGObject ≥ 3.50 no longer maps the builtin `bytes` type;
        # use the generic Python‑object GType instead.
        'data-ready': (GObject.SignalFlags.RUN_FIRST, None, (object,)),
    }

    def __init__(self, settings: Gio.Settings, data_callback: Optional[Callable[[bytes], None]] = None):
        super().__init__()
        Gst.init_check(None)

        self._settings = settings
        self._data_callback = data_callback

        self.pipeline: Optional[Gst.Pipeline] = None
        self.appsink: Optional[Gst.Element] = None
        
        self._current_gst_id: Optional[str] = None # Actual ID used by the current pipeline source
        self._current_pw_serial: Optional[int] = None # PW serial if applicable to current source
        self._is_following_system_default: bool = False # Reflects if tracker is active and being followed
        self._tracker_instance: Optional[DefaultSourceTracker] = None
        self._tracker_signal_handler_id: int = 0
        
        # Read initial settings
        self._target_device_id: Optional[str] = self._settings.get_string("mic-input-device-id")
        self._follow_system_default_setting: bool = self._settings.get_boolean("follow-system-default")

        # Connect to GSettings changes
        self._settings_changed_handler_id_id = self._settings.connect(f"changed::mic-input-device-id", self._on_settings_changed)
        self._settings_changed_handler_follow = self._settings.connect(f"changed::follow-system-default", self._on_settings_changed)
        
        # Initial pipeline setup and tracker management, scheduled on main loop
        GLib.idle_add(self._update_tracker_and_pipeline_from_settings)


    def _on_settings_changed(self, settings, key):
        print(f"AudioCapturer: Setting '{key}' changed in GSettings. Re-evaluating pipeline and tracker.")
        self._target_device_id = self._settings.get_string("mic-input-device-id")
        self._follow_system_default_setting = self._settings.get_boolean("follow-system-default")
        GLib.idle_add(self._update_tracker_and_pipeline_from_settings)

    def _manage_tracker_subscription(self):
        """Connects or disconnects from DefaultSourceTracker based on settings."""
        if self._follow_system_default_setting:
            if not self._tracker_instance:
                self._tracker_instance = DefaultSourceTracker.get_instance()
                if self._tracker_instance._core and self._tracker_instance._core.is_connected(): # Check if tracker initialized correctly
                    print("AudioCapturer: Subscribing to DefaultSourceTracker.")
                    self._tracker_signal_handler_id = self._tracker_instance.connect(
                        "default-changed", self._on_tracker_default_changed
                    )
                    # Trigger an initial check/move with current tracker default
                    if self._tracker_instance._default_node_props.get("gst_id") is not None:
                         GLib.idle_add(self.move_to,
                                       self._tracker_instance._default_node_props["gst_id"],
                                       self._tracker_instance._default_node_props.get("pw_serial"))
                    else: # If tracker has no default yet, ensure pipeline reflects this state
                        GLib.idle_add(self._rebuild_pipeline_from_settings, True) # Pass True to indicate tracker context

                else:
                    print("AudioCapturer: DefaultSourceTracker instance obtained but not connected to WirePlumber. Cannot track defaults.")
                    self._tracker_instance = None # Don't hold a non-functional instance
            # else: already subscribed
        else: # Not following system default
            if self._tracker_instance and self._tracker_signal_handler_id > 0:
                print("AudioCapturer: Unsubscribing from DefaultSourceTracker.")
                self._tracker_instance.disconnect(self._tracker_signal_handler_id)
                self._tracker_signal_handler_id = 0
                # self._tracker_instance.stop() # Singleton should manage its own lifecycle or be stopped globally
                self._tracker_instance = None # Release our reference
            self._is_following_system_default = False # Ensure this flag is reset

    def _on_tracker_default_changed(self, tracker, gst_id: str, pw_serial: int):
        print(f"AudioCapturer: Received 'default-changed' from tracker. GST ID: {gst_id}, PW Serial: {pw_serial}")
        if self._follow_system_default_setting: # Double check setting before acting
            GLib.idle_add(self.move_to, gst_id, pw_serial)
        else:
            print("AudioCapturer: Ignored 'default-changed' as 'follow-system-default' GSetting is false.")


    def _cleanup_pipeline_sync(self):
        """Synchronously stops and nulls the pipeline. Call from main thread."""
        if self.pipeline:
            print("AudioCapturer: Cleaning up existing pipeline...")
            self.pipeline.set_state(Gst.State.NULL)
            self.pipeline = None
            self.appsink = None
            print("AudioCapturer: Pipeline cleaned up.")

    def _build_pipeline(self, target_gst_id_from_setting: Optional[str], 
                        follow_default_from_setting: bool, 
                        tracker_gst_id: Optional[str] = None, 
                        tracker_pw_serial: Optional[int] = None) -> bool:
        """
        Builds the GStreamer pipeline. Must be called on the main GLib thread.
        Uses tracker_gst_id if follow_default_from_setting is true and tracker_gst_id is valid.
        Otherwise, uses target_gst_id_from_setting.
        """
        self._cleanup_pipeline_sync() # Ensure any old pipeline is gone

        source_element_name: Optional[str] = None
        source_properties = {}
        effective_gst_id_used: Optional[str] = None # For logging/status

        # Determine the source element and its properties
        if follow_default_from_setting:
            self._is_following_system_default = True # Mark that we are in this mode
            if tracker_gst_id and tracker_gst_id != "error": # Prioritize tracker's info
                print(f"AudioCapturer: Following system default via tracker. GST ID: {tracker_gst_id}, PW Serial: {tracker_pw_serial}")
                source_element_name = "pipewiresrc" # Assume tracker provides PipeWire compatible ID
                source_properties["path"] = tracker_gst_id
                # If pipewiresrc needs serial: source_properties["serial"] = tracker_pw_serial (or similar)
                effective_gst_id_used = tracker_gst_id
                self._current_gst_id = tracker_gst_id # Store what tracker gave us
                self._current_pw_serial = tracker_pw_serial
            elif target_gst_id_from_setting == "pipewire-default": # User chose "Default PipeWire Source"
                 source_element_name = "pipewiresrc"
                 effective_gst_id_used = "pipewire-default (selected)"
                 print(f"AudioCapturer: Following system default, selected 'Default PipeWire Source'. Using pipewiresrc.")
                 self._current_gst_id = "pipewire-default"
            else: # General system default, use autoaudiosrc
                source_element_name = "autoaudiosrc"
                effective_gst_id_used = "autoaudiosrc (system default)"
                print(f"AudioCapturer: Following system default. Using autoaudiosrc.")
                self._current_gst_id = "" # Represents auto
        elif target_gst_id_from_setting: # Specific device selected, not following default
            self._is_following_system_default = False
            effective_gst_id_used = target_gst_id_from_setting
            print(f"AudioCapturer: Using specific device ID: {target_gst_id_from_setting}")
            
            # Find device details from device_utils
            # Caching this list could be an optimization if it's slow
            available_devices = get_input_devices() 
            selected_audio_device: Optional[AudioInputDevice] = None
            for dev in available_devices:
                if dev.id == target_gst_id_from_setting:
                    selected_audio_device = dev
                    break
            
            if selected_audio_device and selected_audio_device.gst_plugin_name:
                source_element_name = selected_audio_device.gst_plugin_name
                if source_element_name == "pipewiresrc":
                    source_properties["path"] = selected_audio_device.id
                elif source_element_name == "pulsesrc":
                    source_properties["device"] = selected_audio_device.id
                elif source_element_name == "alsasrc": # Basic ALSA handling
                    source_properties["device"] = selected_audio_device.id 
                print(f"AudioCapturer: Found device '{selected_audio_device.name}', using plugin '{source_element_name}' with ID '{selected_audio_device.id}'")
            else:
                print(f"AudioCapturer: Device ID '{target_gst_id_from_setting}' not found or no plugin info. Falling back to autoaudiosrc.")
                source_element_name = "autoaudiosrc"
                effective_gst_id_used = f"{target_gst_id_from_setting} (not found, using autoaudiosrc)"
            self._current_gst_id = target_gst_id_from_setting # Store the user's selection
        else: # No specific device, not following default (e.g. initial empty settings)
            self._is_following_system_default = False
            source_element_name = "autoaudiosrc"
            effective_gst_id_used = "autoaudiosrc (no selection)"
            print("AudioCapturer: No specific device and not following default. Using autoaudiosrc.")
            self._current_gst_id = ""

        if not source_element_name:
            self.emit("error", "Fatal: Could not determine audio source element name.")
            return False

        print(f"AudioCapturer: Attempting to build with source: {source_element_name}, props: {source_properties}")

        try:
            self.pipeline = Gst.Pipeline.new("capture-pipeline")
            source = Gst.ElementFactory.make(source_element_name, "audio-source")
            if not source:
                self.emit("error", f"Failed to create source element: {source_element_name}")
                return False
            for key, value in source_properties.items():
                source.set_property(key, value)

            queue = Gst.ElementFactory.make("queue", "audio-queue")
            audioconvert = Gst.ElementFactory.make("audioconvert", "audio-convert")
            audioresample = Gst.ElementFactory.make("audioresample", "audio-resample")
            capsfilter = Gst.ElementFactory.make("capsfilter", "audio-caps")
            self.appsink = Gst.ElementFactory.make("appsink", "audio-sink")

            if not all([self.pipeline, source, queue, audioconvert, audioresample, capsfilter, self.appsink]):
                self.emit("error", "Failed to create one or more GStreamer elements.")
                return False

            caps = Gst.Caps.from_string("audio/x-raw,format=S16LE,rate=16000,channels=1")
            capsfilter.set_property("caps", caps)
            self.appsink.set_property("emit-signals", True)
            self.appsink.set_property("max-buffers", 2) # Slightly larger queue for appsink
            self.appsink.set_property("drop", True)
            self.appsink.connect("new-sample", self._on_new_sample)

            self.pipeline.add_many(source, queue, audioconvert, audioresample, capsfilter, self.appsink)
            if not Gst.Element.link_many(source, queue, audioconvert, audioresample, capsfilter, self.appsink):
                self.emit("error", "Failed to link GStreamer elements.")
                self._cleanup_pipeline_sync()
                return False
            
            print(f"AudioCapturer: Pipeline built successfully with {source_element_name} (Effective ID: {effective_gst_id_used}).")
            self.emit("source-changed", f"Using: {source_element_name} (ID: {effective_gst_id_used or 'default'})")
            return True

        except Exception as e:
            self.emit("error", f"Exception during pipeline construction: {e}")
            self._cleanup_pipeline_sync()
            return False
        
    def _rebuild_pipeline_from_settings(self, is_tracker_context: bool = False) -> bool:
        """
        Helper to rebuild pipeline based on current GSettings.
        is_tracker_context indicates if the rebuild is due to "follow default" mode,
        affecting which ID (user-selected or tracker-provided) is prioritized.
        """
        print(f"AudioCapturer: Rebuilding pipeline. Target ID from GSetting: '{self._target_device_id}', Follow Default GSetting: {self._follow_system_default_setting}, IsTrackerContext: {is_tracker_context}")
        
        is_playing = False
        if self.pipeline and self.pipeline.get_state(0)[1] == Gst.State.PLAYING:
            is_playing = True
        
        # Determine which IDs to use based on context
        id_from_gsettings = self._target_device_id
        follow_gsetting = self._follow_system_default_setting
        
        tracker_id_to_use = None
        tracker_serial_to_use = None

        if is_tracker_context and self._tracker_instance and self._tracker_instance._default_node_props:
            # If in tracker context, use the tracker's current known default if available.
            # This means self._current_gst_id and self._current_pw_serial should reflect tracker state.
            tracker_id_to_use = self._current_gst_id
            tracker_serial_to_use = self._current_pw_serial
            print(f"AudioCapturer: Rebuild in tracker context. Using tracker ID: {tracker_id_to_use}, Serial: {tracker_serial_to_use}")
        
        # _build_pipeline decides based on follow_gsetting and availability of tracker_id_to_use
        if self._build_pipeline(target_gst_id_from_setting=id_from_gsettings,
                                follow_default_from_setting=follow_gsetting,
                                tracker_gst_id=tracker_id_to_use, # Pass current tracker info
                                tracker_pw_serial=tracker_serial_to_use):
            if is_playing:
                self.start()
        else:
            print("AudioCapturer: Failed to rebuild pipeline from settings.")
            # Error signal should have been emitted by _build_pipeline
            
        return GLib.SOURCE_REMOVE # For GLib.idle_add

    def _on_new_sample(self, appsink):
        sample = appsink.emit("pull-sample")
        if sample:
            buffer = sample.get_buffer()
            if buffer:
                success, map_info = buffer.map(Gst.MapFlags.READ)
                if success:
                    data = bytes(map_info.data)
                    if self._data_callback: self._data_callback(data)
                    self.emit("data-ready", data)
                    buffer.unmap(map_info)
                    return Gst.FlowReturn.OK
        return Gst.FlowReturn.ERROR

    def start(self):
        def _do_start():
            if self.pipeline:
                current_state = self.pipeline.get_state(0)[1]
                if current_state == Gst.State.PLAYING:
                    print("AudioCapturer: Pipeline already playing.")
                    return GLib.SOURCE_REMOVE
                if current_state == Gst.State.NULL or current_state == Gst.State.READY:
                    print("AudioCapturer: Starting pipeline...")
                    ret = self.pipeline.set_state(Gst.State.PLAYING)
                    if ret == Gst.StateChangeReturn.FAILURE:
                        self.emit("error", "Unable to set the pipeline to the playing state.")
                    # ASYNC and SUCCESS are fine.
                else: # PAUSED etc.
                     print(f"AudioCapturer: Pipeline in state {current_state}, attempting to set to PLAYING.")
                     self.pipeline.set_state(Gst.State.PLAYING) # Try anyway
            else:
                self.emit("error", "Cannot start, pipeline not built.")
            return GLib.SOURCE_REMOVE
        GLib.idle_add(_do_start)

    def stop(self):
        def _do_stop():
            if self.pipeline:
                print("AudioCapturer: Stopping pipeline...")
                self.pipeline.set_state(Gst.State.NULL)
                print("AudioCapturer: Pipeline stopped (set to NULL).")
            return GLib.SOURCE_REMOVE
        GLib.idle_add(_do_stop)

    def move_to(self, new_gst_id: str, new_pw_serial: Optional[int] = None):
        """
        Runtime reconfiguration, typically called by DefaultSourceTracker if following system default.
        """
        def _do_move():
            print(f"AudioCapturer: move_to called. New GST ID: {new_gst_id}, New PW Serial: {new_pw_serial}")
            if not self._follow_system_default_setting: # Check GSetting, not just internal state
                print("AudioCapturer: move_to ignored, GSetting 'follow-system-default' is false.")
                return GLib.SOURCE_REMOVE

            # Update current tracked identifiers
            self._current_gst_id = new_gst_id
            self._current_pw_serial = new_pw_serial
            self._is_following_system_default = True # Explicitly affirm we are acting on tracker info
            
            is_playing = False
            if self.pipeline and self.pipeline.get_state(0)[1] == Gst.State.PLAYING:
                is_playing = True
            
            # Rebuild pipeline with the new default device info from tracker
            if self._build_pipeline(target_gst_id_from_setting=self._target_device_id, # Keep user's choice as fallback
                                    follow_default_from_setting=True, # We are in follow mode
                                    tracker_gst_id=new_gst_id,
                                    tracker_pw_serial=new_pw_serial):
                if is_playing:
                    self.start()
            else:
                print(f"AudioCapturer: Failed to move to new source {new_gst_id}")
                self.emit("error", f"Failed to switch to new default source: {new_gst_id}")
            return GLib.SOURCE_REMOVE
            
        GLib.idle_add(_do_move)

    def set_data_callback(self, callback: Optional[Callable[[bytes], None]]):
        self._data_callback = callback

    def cleanup_on_destroy(self):
        """Call this when the capturer is no longer needed to release resources."""
        print("AudioCapturer: Cleaning up on destroy...")
        if self._settings: # Disconnect GSettings handlers
            if hasattr(self, '_settings_changed_handler_id_id') and self._settings_changed_handler_id_id > 0:
                self._settings.disconnect(self._settings_changed_handler_id_id)
                self._settings_changed_handler_id_id = 0
            if hasattr(self, '_settings_changed_handler_follow') and self._settings_changed_handler_follow > 0:
                self._settings.disconnect(self._settings_changed_handler_follow)
                self._settings_changed_handler_follow = 0
        self._settings = None # Release settings object reference

        # Disconnect from DefaultSourceTracker
        if self._tracker_instance and self._tracker_signal_handler_id > 0:
            print("AudioCapturer: Disconnecting from DefaultSourceTracker during cleanup.")
            self._tracker_instance.disconnect(self._tracker_signal_handler_id)
            self._tracker_signal_handler_id = 0
        # Decided not to call self._tracker_instance.stop() here as it's a singleton.
        # It should be stopped globally when the application exits if necessary.
        self._tracker_instance = None
        
        # Ensure pipeline is stopped and cleaned on the main thread
        # Use a list of idle_adds to ensure order if needed, or rely on separate calls
        if self.pipeline:
            # Schedule stop and then cleanup. These are already idle_add internally.
            self.stop()
            # _cleanup_pipeline_sync needs to be explicitly on idle_add if called from here
            GLib.idle_add(self._cleanup_pipeline_sync)
        
        print("AudioCapturer: Cleanup process initiated and mostly complete.")