import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Gio, GObject, Adw

import logging

log = logging.getLogger(__name__)

class AppItem(GObject.Object):
    __gtype_name__ = 'AppItem'

    name = GObject.Property(type=str)
    icon = GObject.Property(type=Gio.Icon)
    app_info = GObject.Property(type=Gio.AppInfo)

    def __init__(self, name, icon, app_info):
        super().__init__()
        self.props.name = name
        self.props.icon = icon
        self.props.app_info = app_info


class AppSelectionDialog(Gtk.Dialog):
    """
    A dialog window to select an installed application.
    """
    def __init__(self, parent):
        super().__init__(transient_for=parent, modal=True)

        self.set_title("Select Application to Record")
        self.set_default_size(400, 300)

        self.add_button("_Cancel", Gtk.ResponseType.CANCEL)
        record_button = self.add_button("_Record", Gtk.ResponseType.ACCEPT)
        record_button.set_sensitive(False)

        content_area = self.get_content_area()
        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin_top=10, margin_bottom=10, margin_start=10, margin_end=10)
        content_area.append(main_box)

        scrolled_window = Gtk.ScrolledWindow()
        scrolled_window.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scrolled_window.set_vexpand(True)
        main_box.append(scrolled_window)

        self.list_store = Gio.ListStore(item_type=AppItem)
        self.selection_model = Gtk.SingleSelection(model=self.list_store)
        self.app_list_view = Gtk.ListView(model=self.selection_model)
        self.app_list_view.set_show_separators(True)
        scrolled_window.set_child(self.app_list_view)

        factory = Gtk.SignalListItemFactory()
        factory.connect("setup", self._on_factory_setup)
        factory.connect("bind", self._on_factory_bind)
        self.app_list_view.set_factory(factory)

        self._populate_app_list()

        self.selection_model.connect("notify::selected-item", self._on_app_selection_changed)

    def _on_factory_setup(self, factory, list_item):
        """Sets up the widget structure for a list item."""
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12, margin_top=6, margin_bottom=6, margin_start=6, margin_end=6)
        icon_image = Gtk.Image(icon_size=Gtk.IconSize.LARGE)
        label = Gtk.Label(halign=Gtk.Align.START, hexpand=True)
        box.append(icon_image)
        box.append(label)
        list_item.set_child(box)

    def _on_factory_bind(self, factory, list_item):
        """Binds the data from an AppItem to the list item's widgets."""
        box = list_item.get_child()
        icon_image = box.get_first_child()
        label = box.get_last_child()
        app_item = list_item.get_item()

        if app_item:
            icon_image.set_from_gicon(app_item.props.icon)
            label.set_text(app_item.props.name)
        else:
            icon_image.set_from_gicon(None)
            label.set_text("")


    def _populate_app_list(self):
        """Fetches installed applications and populates the list store."""
        log.info("Populating application list...")
        self.list_store.remove_all()
        try:
            app_infos = Gio.AppInfo.get_all()
            count = 0
            for app_info in app_infos:
                if app_info.get_name() and app_info.get_icon():
                    if app_info.should_show():
                        name = app_info.get_name()
                        icon = app_info.get_icon()
                        app_item = AppItem(name=name, icon=icon, app_info=app_info)
                        self.list_store.append(app_item)
                        count += 1
            log.info(f"Found {count} suitable applications.")
        except Exception as e:
            log.error(f"Error fetching application list: {e}", exc_info=True)


    def _on_app_selection_changed(self, selection_model, param):
        """Enables/disables the Record button based on selection."""
        selected_item = selection_model.get_selected_item()
        record_button = self.get_widget_for_response(Gtk.ResponseType.ACCEPT)
        if record_button:
            record_button.set_sensitive(selected_item is not None)

    def get_selected_app_info(self) -> Gio.AppInfo | None:
        """
        Returns the Gio.AppInfo of the selected application.

        Returns:
            Gio.AppInfo | None: The selected app's info, or None if no selection.
        """
        selected_item_gobj = self.selection_model.get_selected_item()
        if isinstance(selected_item_gobj, AppItem):
            return selected_item_gobj.props.app_info
        return None