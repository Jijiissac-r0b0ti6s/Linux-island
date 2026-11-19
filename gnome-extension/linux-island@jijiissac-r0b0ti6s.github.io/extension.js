// Linux Island helper: tells Linux Island which monitors have no open application window.
//
// Wayland hides other apps' windows from normal programs, so the island (which runs through
// XWayland there) can't see native Wayland apps such as recent Chrome, Brave or VS Code. GNOME
// Shell sees every window; this extension answers one question over D-Bus and announces changes.
//
//   object    /io/github/LinuxIsland/Windows   (on org.gnome.Shell, session bus)
//   method    EmptyMonitors(as connectors) -> as   monitors (by connector name, e.g. "DP-1")
//                                                  with no visible window on the active workspace
//   signal    Changed()                            windows opened / closed / minimised / moved
import Gio from 'gi://Gio';
import GLib from 'gi://GLib';
import Meta from 'gi://Meta';
import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import {Extension} from 'resource:///org/gnome/shell/extensions/extension.js';

const OBJECT_PATH = '/io/github/LinuxIsland/Windows';
const INTERFACE = `
<node>
  <interface name="io.github.LinuxIsland.Windows">
    <method name="EmptyMonitors">
      <arg type="as" direction="in" name="connectors"/>
      <arg type="as" direction="out" name="empty"/>
    </method>
    <property name="Version" type="u" access="read"/>
    <signal name="Changed"/>
  </interface>
</node>`;

const APP_WINDOWS = [Meta.WindowType.NORMAL, Meta.WindowType.DIALOG, Meta.WindowType.MODAL_DIALOG];

export default class LinuxIslandHelper extends Extension {
    enable() {
        this._signals = [];
        this._windows = new Map();   // MetaWindow -> its signal ids
        this._pending = 0;
        this._dbus = Gio.DBusExportedObject.wrapJSObject(INTERFACE, this);
        this._dbus.export(Gio.DBus.session, OBJECT_PATH);

        const changed = () => this._queueChanged();
        this._connect(global.display, 'window-created', (_display, window) => {
            this._watch(window);
            changed();
        });
        this._connect(global.display, 'window-entered-monitor', changed);
        this._connect(global.display, 'window-left-monitor', changed);
        this._connect(global.workspace_manager, 'active-workspace-changed', changed);
        this._connect(Main.layoutManager, 'monitors-changed', changed);
        for (const actor of global.get_window_actors())
            this._watch(actor.meta_window);
    }

    disable() {
        for (const [object, id] of this._signals)
            object.disconnect(id);
        this._signals = [];
        for (const [window, ids] of this._windows)
            ids.forEach(id => window.disconnect(id));
        this._windows.clear();
        if (this._pending)
            GLib.source_remove(this._pending);
        this._pending = 0;
        this._dbus.unexport();
        this._dbus = null;
    }

    get Version() {
        return 1;
    }

    EmptyMonitors(connectors) {
        const monitors = global.backend.get_monitor_manager();
        const workspace = global.workspace_manager.get_active_workspace();
        const busy = new Set();
        for (const actor of global.get_window_actors()) {
            const window = actor.meta_window;
            if (!window || window.minimized || window.is_skip_taskbar())
                continue;
            if (!APP_WINDOWS.includes(window.get_window_type()))
                continue;   // desktop icons, docks, menus, ...
            if (!window.is_on_all_workspaces() && window.get_workspace() !== workspace)
                continue;
            busy.add(window.get_monitor());
        }
        return connectors.filter(connector => {
            const index = monitors.get_monitor_for_connector(connector);
            return index >= 0 && !busy.has(index);
        });
    }

    _connect(object, signal, callback) {
        this._signals.push([object, object.connect(signal, callback)]);
    }

    _watch(window) {
        if (!window || this._windows.has(window))
            return;
        const changed = () => this._queueChanged();
        const ids = [
            window.connect('notify::minimized', changed),
            window.connect('workspace-changed', changed),
            window.connect('unmanaged', () => {
                const signalIds = this._windows.get(window);
                this._windows.delete(window);
                signalIds?.forEach(id => window.disconnect(id));
                changed();
            }),
        ];
        this._windows.set(window, ids);
    }

    _queueChanged() {
        // a burst of window events becomes one signal
        if (this._pending)
            return;
        this._pending = GLib.timeout_add(GLib.PRIORITY_DEFAULT, 60, () => {
            this._pending = 0;
            this._dbus?.emit_signal('Changed', null);
            return GLib.SOURCE_REMOVE;
        });
    }
}
