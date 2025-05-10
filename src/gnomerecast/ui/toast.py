import gi
import time
import weakref
from weakref import ReferenceType # Added import

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, GLib, Adw

class ToastPresenter:
    """Singleton presenter for managing toast notifications across the application."""
    
    _instance = None
    _registry: weakref.WeakKeyDictionary[Adw.ToastOverlay, ReferenceType[Gtk.Window] | None] = weakref.WeakKeyDictionary()
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._last_toast = {}  # Tracks last shown toast per (message, title) pair
        return cls._instance
    
    @classmethod
    def attach(cls, overlay: Adw.ToastOverlay) -> None:
        """Register a toast overlay with the presenter and its root window."""
        if overlay not in cls._registry:
            root_window = overlay.get_root()
            if isinstance(root_window, Gtk.Window):
                cls._registry[overlay] = weakref.ref(root_window)
            else:
                # Log a warning if the root is not a Gtk.Window or not found
                print(f"Warning: Could not find a Gtk.Window root for overlay {overlay}. Storing with None.")
                cls._registry[overlay] = None
    
    @classmethod
    def show(cls, parent: Gtk.Widget, message: str, timeout: int = 3) -> None:
        """Show a toast message attached to the nearest registered overlay."""
        
        if cls._instance is None:
            cls() # Ensure singleton instance is created and _last_toast initialized on instance
            
        # This inner function will be scheduled by GLib.idle_add
        def _actual_add_toast():
            overlay = None
            widget = parent
            while widget:
                if isinstance(widget, Adw.ToastOverlay) and widget in cls._registry:
                    overlay = widget
                    break
                widget = widget.get_parent()

            if not overlay:
                # Try to find any registered overlay if parent-based search fails
                if cls._registry:
                    # Attempt to get the first available overlay from the registry
                    # This is a fallback, ideally parent should lead to an overlay
                    try:
                        overlay = next(iter(cls._registry.keys()))
                        print(f"ToastPresenter.show: Overlay not found for parent {parent}. Using first registered overlay: {overlay}")
                    except StopIteration:
                        pass # _registry is empty
                
            if not overlay:
                print(f"Toast fallback (no overlay for parent {parent}): {message}")
                return

            # Coalesce duplicate toasts within 1 second
            current_time = time.time()
            # Use overlay's root window for title, if available
            root_for_title = overlay.get_root()
            window_title = root_for_title.get_title() if root_for_title and hasattr(root_for_title, 'get_title') else "Unknown Window"
            toast_key = (message, window_title)
            
            # print(f"DEBUG: ToastPresenter:show_toast - message='{message}', window_title='{window_title}', toast_key={toast_key}")
            
            if toast_key in ToastPresenter._instance._last_toast:
                last_time = ToastPresenter._instance._last_toast[toast_key]
                if current_time - last_time < 1.0:  # Within 1 second window
                    return
            
            ToastPresenter._instance._last_toast[toast_key] = current_time
            toast = Adw.Toast.new(message)
            toast.set_timeout(timeout)
            overlay.add_toast(toast)
        
        GLib.idle_add(_actual_add_toast)

    @classmethod
    def show_global(cls, message: str, timeout: int = 3) -> None:
        """
        Display a toast on the first registered overlay (main window if identifiable)
        when the caller has no widget context (e.g. worker threads).
        """
        
        if cls._instance is None:
            cls() # Ensure singleton instance is created and _last_toast initialized on instance
            
        # This inner function will be scheduled by GLib.idle_add
        def _actual_add_global_toast():
            target_overlay: Adw.ToastOverlay | None = None
            
            # Attempt to find the "main" window overlay first.
            # This is a heuristic: assumes main window might have a specific title
            # or is simply the first one that has a valid Gtk.Window root.
            # A more robust way might involve a specific registration for the main window.
            main_window_title_candidates = ["GnomeRecast", "Recast"] # Adjust as needed
            
            for overlay, window_ref in cls._registry.items():
                if window_ref:
                    window = window_ref()
                    if window and hasattr(window, 'get_title'):
                        title = window.get_title()
                        if title in main_window_title_candidates:
                            target_overlay = overlay
                            break # Found a candidate for main window
            
            # If no "main" window overlay found, use the first valid one
            if not target_overlay:
                for overlay, window_ref in cls._registry.items():
                    if window_ref and window_ref(): # Check if window still exists
                        target_overlay = overlay
                        break # Found any valid overlay
            
            if not target_overlay:
                 # As a last resort, try any overlay even if its window_ref is None (less ideal)
                if not target_overlay and cls._registry:
                    try:
                        target_overlay = next(iter(cls._registry.keys()))
                    except StopIteration:
                        pass # Registry is empty

            if not target_overlay:
                print(f"Toast fallback (show_global, no registered overlays): {message}")
                return

            # Coalesce duplicate toasts within 1 second
            current_time = time.time()
            # Use overlay's root window for title, if available
            root_for_title = target_overlay.get_root()
            window_title = root_for_title.get_title() if root_for_title and hasattr(root_for_title, 'get_title') else "Global Toast"
            toast_key = (message, window_title)

            # print(f"DEBUG: ToastPresenter:show_global - message='{message}', window_title='{window_title}', toast_key={toast_key}")

            if toast_key in ToastPresenter._instance._last_toast:
                last_time = ToastPresenter._instance._last_toast[toast_key]
                if current_time - last_time < 1.0: # Within 1 second window
                    return
            
            ToastPresenter._instance._last_toast[toast_key] = current_time
            toast = Adw.Toast.new(message)
            toast.set_timeout(timeout)
            target_overlay.add_toast(toast)

        GLib.idle_add(_actual_add_global_toast)