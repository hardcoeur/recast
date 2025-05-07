import gi
gi.require_version('GObject', '2.0')
gi.require_version('Wp', '0.5') # Or 0.4 depending on available version
from gi.repository import GObject, Wp, GLib

class DefaultSourceTracker(GObject.Object):
    """
    A GObject singleton that monitors the system's default audio input source
    using WirePlumber and emits a signal when it changes.
    """
    __gsignals__ = {
        'default-changed': (GObject.SignalFlags.RUN_FIRST, None, (str, int)),
        # gst_id: str, pw_serial: int
    }

    _instance = None
    _core = None
    _om = None
    _default_nodes_api = None # Technically, we monitor Wp.Metadata for default changes
    _default_node_props = {} # Stores properties of the current default node {gst_id, pw_serial}

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if hasattr(self, '_initialized') and self._initialized:
            return
        super().__init__()
        self._initialized = True
        
        try:
            Wp.init(Wp.InitFlags.ALL)
            # Use a new main context for WirePlumber core if running in a separate thread,
            # or None if integrating into an existing GLib.MainLoop on the main thread.
            # For a singleton GObject usually integrated with GTK, None (default context) is fine.
            self._core = Wp.Core.new(None, None) 
            
            if not self._core.connect():
                print("DefaultSourceTracker: Failed to connect to WirePlumber core")
                self._core = None 
                return

            self._om = Wp.ObjectManager.new()
            # We are interested in Wp.Metadata for default nodes.
            self._om.add_interest_full(Wp.Metadata, Wp.Constraint.new_full(
                Wp.PW_KEY_METADATA_NAME, "default", Wp.ConstraintVerb.EQUALS, # Default settings are stored in "default" metadata
            ))
            # Also need Wp.Node to resolve the default node name to its properties (like serial and path)
            self._om.add_interest_full(Wp.Node, Wp.Constraint.new_full(
                 Wp.PW_KEY_MEDIA_CLASS, "Audio/Source", Wp.ConstraintVerb.EQUALS, # Interested in Audio Sources
            ))
            
            self._om.connect("objects-changed", self._on_objects_changed_initial_setup)
            self._core.install_object_manager(self._om)
            print("DefaultSourceTracker: WirePlumber core connected and object manager installed.")

        except Exception as e:
            print(f"DefaultSourceTracker: Error initializing WirePlumber: {e}")
            if self._core and self._core.is_connected():
                self._core.disconnect()
            self._core = None

    def _on_objects_changed_initial_setup(self, om):
        # This callback is primarily for the initial setup of the metadata listener.
        # Once the "default" Wp.Metadata object is found, we connect to its "changed" signal.
        # print("DefaultSourceTracker: Objects changed (initial setup)")
        metadata = om.lookup_object(Wp.Constraint.new_full(
            Wp.PW_KEY_METADATA_NAME, "default", Wp.ConstraintVerb.EQUALS,
        ))
        if metadata and isinstance(metadata, Wp.Metadata):
            # print(f"DefaultSourceTracker: Found 'default' Wp.Metadata object: {metadata}")
            # Disconnect this handler as we only need to set up the listener once.
            om.disconnect_by_func(self._on_objects_changed_initial_setup)
            metadata.connect("changed", self._on_default_metadata_changed)
            # Perform an initial check for the default node
            GLib.idle_add(self._check_and_emit_default_node)


    def _on_default_metadata_changed(self, metadata, subject, key, value_type, value):
        # print(f"DefaultSourceTracker: Default metadata changed: subject={subject}, key={key}, value='{value}'")
        # We are interested in changes to the default audio source.
        # In WirePlumber, this is typically "default.audio.source" for ALSA node name,
        # or "default.bluez.source" for Bluetooth. The value is the node *name*.
        if key and ("default.audio.source" in key or "default.bluez.source" in key):
            # print(f"DefaultSourceTracker: Relevant metadata key '{key}' changed to '{value}'. Re-checking default node.")
            GLib.idle_add(self._check_and_emit_default_node)


    def _check_and_emit_default_node(self):
        if not self._core or not self._core.is_connected() or not self._om:
            # print("DefaultSourceTracker: Core not connected or ObjectManager not available.")
            return False # Important for GLib.idle_add to remove if it returns False

        try:
            # Find the "default" Wp.Metadata object again (could be cached)
            metadata_obj = self._om.lookup_object(Wp.Constraint.new_full(
                Wp.PW_KEY_METADATA_NAME, "default", Wp.ConstraintVerb.EQUALS,
            ))

            if not metadata_obj or not isinstance(metadata_obj, Wp.Metadata):
                # print("DefaultSourceTracker: 'default' Wp.Metadata object not found.")
                return False 

            # Try to get the default audio source node NAME first
            default_node_name = metadata_obj.get_property_value_for_subject(0, "default.audio.source") # Global subject (0)
            if not default_node_name: # Fallback for some systems or BT devices
                 default_node_name = metadata_obj.get_property_value_for_subject(0, "default.bluez.source")

            if not default_node_name:
                # print("DefaultSourceTracker: Could not determine default audio source node name from metadata.")
                if self._default_node_props: # If there was a previous default, signal it's gone
                    self._default_node_props = {}
                    self.emit("default-changed", "", -1)
                return False

            # Now, find the Wp.Node that corresponds to this default_node_name
            node = self._om.lookup_object(Wp.Constraint.new_full(
                Wp.PW_KEY_NODE_NAME, default_node_name, Wp.ConstraintVerb.EQUALS,
            ))

            if node and isinstance(node, Wp.Node):
                props = node.get_properties()
                if props:
                    # The GStreamer ID for pipewiresrc is usually the object path.
                    gst_id_for_pipewiresrc = props.get_string(Wp.PW_KEY_OBJECT_PATH)
                    if not gst_id_for_pipewiresrc: # Fallback if path isn't there for some reason
                        gst_id_for_pipewiresrc = props.get_string(Wp.PW_KEY_NODE_NAME)

                    pw_serial_obj = props.get_value(Wp.PW_KEY_OBJECT_SERIAL)
                    pw_serial = int(pw_serial_obj) if pw_serial_obj is not None else -1
                    
                    # Check if it actually changed from the last known default
                    if (self._default_node_props.get("gst_id") != gst_id_for_pipewiresrc or
                        self._default_node_props.get("pw_serial") != pw_serial):
                        # print(f"DefaultSourceTracker: Default audio source changed.")
                        # print(f"  New GST ID (for pipewiresrc): {gst_id_for_pipewiresrc}, PW Serial: {pw_serial}, Node Name: {default_node_name}")
                        self._default_node_props = {"gst_id": gst_id_for_pipewiresrc, "pw_serial": pw_serial, "name": default_node_name}
                        self.emit("default-changed", gst_id_for_pipewiresrc, pw_serial)
            else:
                # print(f"DefaultSourceTracker: Node with name '{default_node_name}' not found via ObjectManager.")
                if self._default_node_props: # If there was a previous default, signal it's gone
                    self._default_node_props = {}
                    self.emit("default-changed", "", -1)
        
        except Exception as e:
            print(f"DefaultSourceTracker: Error in _check_and_emit_default_node: {e}")
            if self._default_node_props: # If there was a previous default
                self._default_node_props = {}
                self.emit("default-changed", "", -1) # Signal error/loss of tracking
        
        return False # Remove from idle_add

    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = DefaultSourceTracker()
        return cls._instance

    def stop(self):
        print("DefaultSourceTracker: Stopping...")
        if self._core and self._core.is_connected():
            # print("DefaultSourceTracker: Disconnecting WirePlumber core.")
            self._core.disconnect()
        self._core = None
        self._om = None # Object manager is owned by core or needs explicit unref if not
        DefaultSourceTracker._instance = None 
        # print("DefaultSourceTracker: Stopped.")


if __name__ == '__main__':
    loop = GLib.MainLoop()

    def on_default_changed_cb(tracker, gst_id, pw_serial):
        print(f"\nCALLBACK: Default changed! GST ID (for pipewiresrc): '{gst_id}', PW Serial: {pw_serial}\n")

    tracker = DefaultSourceTracker.get_instance()
    
    if tracker._core and tracker._core.is_connected():
        tracker.connect("default-changed", on_default_changed_cb)
        print("DefaultSourceTracker initialized. Monitoring for default audio source changes.")
        print("Try changing your system's default microphone in sound/audio settings.")
    else:
        print("Failed to initialize DefaultSourceTracker. WirePlumber might not be running or accessible.")
        print("Exiting example.")
        exit()

    try:
        loop.run()
    except KeyboardInterrupt:
        print("\nExiting...")
    finally:
        if tracker:
            tracker.stop()
        if loop.is_running():
            loop.quit()