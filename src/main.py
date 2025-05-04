#!/usr/bin/env python3

import sys
import gi

gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
gi.require_version('Gst', '1.0')

from gi.repository import Gtk, Adw, Gst
from gnomerecast.application import GnomeRecastApplication

if __name__ == "__main__":
    Gst.init(None)
    app = GnomeRecastApplication()
    exit_status = app.run(sys.argv)
    sys.exit(exit_status)