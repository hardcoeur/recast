import gi
gi.require_version('Gst', '1.0')
gi.require_version('GObject', '2.0')
from gi.repository import Gst, GObject

from dataclasses import dataclass
from typing import List, Optional

@dataclass
class AudioInputDevice:
    id: Optional[str]  # GStreamer device.id or special "default"
    name: str          # User-friendly name
    api: str           # e.g., "pipewire", "pulse", "alsa"
    device_type: str   # "physical", "monitor", "default"
    pw_serial: Optional[int] = None # PipeWire serial, if applicable
    gst_plugin_name: Optional[str] = None # e.g. pipewiresrc, pulsesrc

    def __str__(self):
        return self.name

    def __eq__(self, other):
        if not isinstance(other, AudioInputDevice):
            return NotImplemented
        return self.id == other.id and self.api == other.api and self.device_type == other.device_type

    def __hash__(self):
        return hash((self.id, self.api, self.device_type))

def get_input_devices() -> List[AudioInputDevice]:
    """
    Lists available audio input devices (microphones and monitors).
    Includes a special "Default PipeWire Source" if PipeWire is likely available.
    """
    devices = []
    Gst.init_check(None)

    # Add a "System Default" option. This will be handled by GSettings `follow-system-default`
    devices.append(AudioInputDevice(
        id="", # Special ID for system default
        name="System Default",
        api="default",
        device_type="default",
        gst_plugin_name="autoaudiosrc" # Fallback, actual determined by settings
    ))

    monitor = Gst.DeviceMonitor.new()
    monitor.add_filter("Audio/Source", None) # GstCaps.new_empty_simple("audio/source"))
    
    # It seems PipeWire is becoming standard, so we can try to add a default PW source.
    # The actual default tracking will be done by WpDefaultTracker.
    # This entry is more for user selection if they prefer PW explicitly.
    # We don't have PW serial here, it's a generic "use default pipewire"
    devices.append(AudioInputDevice(
        id="pipewire-default", # A special identifier for this choice
        name="Default PipeWire Source",
        api="pipewire",
        device_type="default",
        gst_plugin_name="pipewiresrc"
    ))

    if not monitor.start():
        print("Failed to start device monitor")
        # Fallback: at least provide ALSA default if monitor fails
        devices.append(AudioInputDevice(id="alsa-default", name="Default ALSA Source (Fallback)", api="alsa", device_type="default", gst_plugin_name="alsasrc"))
        return devices

    gst_devices = monitor.get_devices()
    if gst_devices:
        for device in gst_devices:
            name = device.get_display_name()
            api = "unknown"
            device_id = device.get_properties().get_string("device.id")
            gst_plugin_name = None
            
            # Determine API and device type
            # This is a heuristic. A more robust way might involve checking device.classes
            # or specific properties if GstDevice provides them.
            # For now, we rely on names and common GStreamer elements.
            if "alsa" in name.lower() or (device_id and "alsa" in device_id.lower()):
                api = "alsa"
                gst_plugin_name = "alsasrc"
            elif "pulse" in name.lower() or (device_id and "pulse" in device_id.lower()):
                api = "pulse"
                gst_plugin_name = "pulsesrc"
            elif "pipewire" in name.lower() or (device_id and ("pipewire" in device_id.lower() or "pw" in device_id.lower())):
                api = "pipewire"
                gst_plugin_name = "pipewiresrc"
            
            # Try to get device.api if available from GstDevice properties
            device_api_prop = device.get_properties().get_string("device.api")
            if device_api_prop:
                api = device_api_prop
                if api == "pipewire":
                    gst_plugin_name = "pipewiresrc"
                elif api == "alsa":
                    gst_plugin_name = "alsasrc"
                elif api == "pulse":
                    gst_plugin_name = "pulsesrc"


            device_type = "physical"
            if "monitor" in name.lower():
                device_type = "monitor"

            # For PipeWire, try to get the serial if available (though GstDevice might not expose it directly)
            # This might be more relevant when a specific device is chosen, not during general listing.
            # The pw_serial will be more reliably obtained via WirePlumber for the *default* device.
            pw_serial = None
            if api == "pipewire":
                # GstDevice might have 'object.serial' or similar for PW, needs checking Gst docs/PW integration
                # For now, we assume Gst.Device.get_properties() gives us what GStreamer knows.
                # If 'device.id' for pipewiresrc is the node ID (integer), that's useful.
                # If it's a string path, that's also fine for 'path' property of pipewiresrc.
                # The 'id' here is the GStreamer device.id, which pipewiresrc can use for its 'path' property
                # if it's a string, or potentially 'node-id' if it's an int.
                # The `micrefactor.md` implies `gst_id` is the device.id from GstDevice.
                pass


            devices.append(AudioInputDevice(
                id=device_id, 
                name=name, 
                api=api, 
                device_type=device_type,
                pw_serial=pw_serial, # Likely None here, to be filled by tracker for default
                gst_plugin_name=gst_plugin_name
            ))
    
    monitor.stop()
    
    # Remove duplicates that might arise from different ways of identifying defaults
    # For example, if GstDeviceMonitor lists a "Default" that is also our "Default PipeWire Source"
    # A more robust deduplication might be needed based on actual IDs if they overlap.
    # Using a set of tuples for properties that define uniqueness
    unique_devices = []
    seen_ids = set()
    for dev in devices:
        # For "System Default" and "Default PipeWire Source", name is unique enough.
        # For others, use the GStreamer device ID.
        lookup_key = dev.name if dev.device_type == "default" else dev.id
        if lookup_key not in seen_ids:
            unique_devices.append(dev)
            seen_ids.add(lookup_key)
            
    return unique_devices

if __name__ == '__main__':
    # Example usage:
    Gst.init(None)
    available_devices = get_input_devices()
    print("Available Audio Input Devices:")
    for dev in available_devices:
        print(f"- Name: {dev.name}")
        print(f"  ID: {dev.id}")
        print(f"  API: {dev.api}")
        print(f"  Type: {dev.device_type}")
        print(f"  GStreamer Plugin: {dev.gst_plugin_name}")
        if dev.pw_serial is not None:
            print(f"  PipeWire Serial: {dev.pw_serial}")