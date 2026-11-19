import QtQuick
import QtQuick.Controls
import QtQuick.Controls.Material
import QtQuick.Dialogs
import QtQuick.Layouts

// Settings panel. `settings` (SettingsBackend in settings.py) saves every change immediately;
// the running island picks it up from the config file.
ApplicationWindow {
    id: window
    width: 940
    height: 680
    minimumWidth: 760
    minimumHeight: 560
    visible: true
    title: "Linux Island Settings"

    Material.theme: Material.Dark
    Material.accent: v.accent_color
    color: theme.bg

    readonly property var v: settings.values
    property int page: 0

    QtObject {
        id: theme
        readonly property color bg: "#141416"
        readonly property color sidebar: "#1b1b1f"
        readonly property color card: "#212126"
        readonly property color line: "#2e2e34"
        readonly property color text: "#f2f2f7"
        readonly property color dim: "#9a9aa2"
        readonly property int radius: 12
    }

    readonly property var pages: [
        { title: "General", icon: "display", summary: "Where the island appears and when it starts" },
        { title: "Appearance", icon: "palette", summary: "Colours, clock and pop-ups" },
        { title: "Features", icon: "toggle", summary: "Turn parts of the island on or off" },
        { title: "Screensaver & lock", icon: "moon", summary: "What happens when you step away" },
        { title: "About", icon: "info", summary: "Version, settings file and reset" },
    ]

    function put(key, value) { settings.set(key, value) }

    // sliders: save at most every 120 ms while dragging (the island follows live without a flood
    // of updates), and once more on release
    property var pending: ({})
    function putSoon(key, value) {
        pending[key] = value
        if (!throttle.running)
            throttle.start()
    }
    function flush() {
        const p = pending
        pending = ({})
        throttle.stop()
        for (const key in p)
            settings.set(key, p[key])
    }
    Timer { id: throttle; interval: 120; onTriggered: window.flush() }

    // =====================================================================
    // building blocks
    // =====================================================================

    // a rounded group of rows
    component Card: Rectangle {
        default property alias rows: column.data
        Layout.fillWidth: true
        implicitHeight: column.implicitHeight
        radius: theme.radius
        color: theme.card
        ColumnLayout {
            id: column
            width: parent.width
            spacing: 0
        }
    }

    // one setting: title and explanation on the left, its control on the right
    component SettingRow: Item {
        id: row
        property string title
        property string detail
        property bool divider: true          // line under the row (off for the last row of a card)
        default property alias control: slot.data
        Layout.fillWidth: true
        implicitHeight: Math.max(60, texts.implicitHeight + 24)
        opacity: enabled ? 1 : 0.45

        ColumnLayout {
            id: texts
            anchors.left: parent.left
            anchors.leftMargin: 18
            anchors.right: slot.left
            anchors.rightMargin: 16
            anchors.verticalCenter: parent.verticalCenter
            spacing: 2
            Label { text: row.title; color: theme.text; font.pixelSize: 14; Layout.fillWidth: true; elide: Text.ElideRight }
            Label {
                text: row.detail
                visible: text !== ""
                color: theme.dim
                font.pixelSize: 12
                wrapMode: Text.Wrap
                Layout.fillWidth: true
            }
        }
        Row {
            id: slot
            anchors.right: parent.right
            anchors.rightMargin: 14
            anchors.verticalCenter: parent.verticalCenter
            spacing: 8
        }
        Rectangle {
            visible: row.divider
            anchors.bottom: parent.bottom
            anchors.left: parent.left
            anchors.leftMargin: 18
            anchors.right: parent.right
            height: 1
            color: theme.line
        }
    }

    // a row whose control is an on/off switch
    component SwitchRow: SettingRow {
        id: srow
        property bool checked
        signal toggled(bool on)
        Switch {
            checked: srow.checked
            onToggled: srow.toggled(checked)
        }
    }

    // a heading above a card
    component GroupTitle: Label {
        Layout.topMargin: 22
        Layout.bottomMargin: 8
        Layout.leftMargin: 4
        color: theme.dim
        font.pixelSize: 12
        font.weight: Font.DemiBold
        font.capitalization: Font.AllUppercase
        font.letterSpacing: 0.8
    }

    // segmented choice: a row of joined buttons, one selected
    component Segmented: Rectangle {
        id: seg
        property var options: []          // [{ label, value }]
        property var current
        signal chosen(var value)
        implicitWidth: segRow.implicitWidth + 6
        implicitHeight: 34
        radius: 9
        color: "#16161a"
        border.color: theme.line
        Row {
            id: segRow
            anchors.centerIn: parent
            spacing: 2
            Repeater {
                model: seg.options
                Rectangle {
                    required property var modelData
                    readonly property bool selected: JSON.stringify(seg.current) === JSON.stringify(modelData.value)
                    width: segLabel.implicitWidth + 26
                    height: 28
                    radius: 7
                    color: selected ? "#3a3a42" : segArea.containsMouse ? "#24242a" : "transparent"
                    Behavior on color { ColorAnimation { duration: 120 } }
                    Label {
                        id: segLabel
                        anchors.centerIn: parent
                        text: parent.modelData.label
                        color: parent.selected ? theme.text : theme.dim
                        font.pixelSize: 13
                        font.weight: parent.selected ? Font.DemiBold : Font.Normal
                    }
                    MouseArea {
                        id: segArea
                        anchors.fill: parent
                        hoverEnabled: true
                        cursorShape: Qt.PointingHandCursor
                        onClicked: seg.chosen(parent.modelData.value)
                    }
                }
            }
        }
    }

    // a round colour choice
    component Swatch: Rectangle {
        id: swatch
        property color swatchColor
        property bool selected
        signal picked()
        width: 30; height: 30; radius: 15
        color: swatchColor
        border.width: selected ? 2 : 1
        border.color: selected ? "#ffffff" : "#45454d"
        Rectangle {   // selection ring
            visible: swatch.selected
            anchors.centerIn: parent
            width: parent.width + 8; height: width; radius: width / 2
            color: "transparent"
            border.width: 2
            border.color: Qt.rgba(1, 1, 1, 0.35)
        }
        MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor; onClicked: swatch.picked() }
    }

    // a colour row: preset swatches and a custom picker
    component ColourRow: SettingRow {
        id: crow
        property string key
        property var presets: []
        Repeater {
            model: crow.presets
            Swatch {
                required property string modelData
                anchors.verticalCenter: parent.verticalCenter
                swatchColor: modelData
                selected: String(v[crow.key]).toLowerCase() === modelData
                onPicked: put(crow.key, modelData)
            }
        }
        Rectangle {   // custom colour
            anchors.verticalCenter: parent.verticalCenter
            width: 30; height: 30; radius: 15
            readonly property bool custom: crow.presets.indexOf(String(v[crow.key]).toLowerCase()) < 0
            color: custom ? v[crow.key] : "transparent"
            border.width: custom ? 2 : 1
            border.color: custom ? "#ffffff" : "#5a5a63"
            Label { anchors.centerIn: parent; text: "+"; visible: !parent.custom; color: theme.dim; font.pixelSize: 17 }
            MouseArea {
                anchors.fill: parent
                cursorShape: Qt.PointingHandCursor
                onClicked: { colorDialog.key = crow.key; colorDialog.selectedColor = v[crow.key]; colorDialog.open() }
            }
            ToolTip.visible: customHover.hovered
            ToolTip.text: "Custom colour"
            HoverHandler { id: customHover }
        }
    }

    // scrolling page with a title, a summary and centred content
    component Page: ScrollView {
        id: pg
        default property alias content: body.data
        property int index
        contentWidth: availableWidth
        clip: true
        ColumnLayout {
            id: body
            width: Math.min(pg.availableWidth - 64, 640)
            x: (pg.availableWidth - width) / 2
            spacing: 0
            Label {
                Layout.topMargin: 32
                text: window.pages[pg.index].title
                color: theme.text
                font.pixelSize: 26
                font.weight: Font.DemiBold
            }
            Label {
                Layout.topMargin: 4
                Layout.bottomMargin: 6
                text: window.pages[pg.index].summary
                color: theme.dim
                font.pixelSize: 14
            }
        }
    }

    // =====================================================================
    // layout
    // =====================================================================
    RowLayout {
        anchors.fill: parent
        spacing: 0

        // ---------- sidebar ----------
        Rectangle {
            Layout.fillHeight: true
            Layout.preferredWidth: 236
            color: theme.sidebar

            ColumnLayout {
                anchors.fill: parent
                anchors.margins: 14
                spacing: 2

                // app header
                RowLayout {
                    Layout.topMargin: 8
                    Layout.bottomMargin: 20
                    Layout.leftMargin: 6
                    spacing: 12
                    Rectangle {
                        width: 40; height: 40; radius: 11
                        color: "#2a2a31"
                        Rectangle {
                            anchors.centerIn: parent
                            width: 28; height: 13; radius: 6.5
                            color: v.pill_color
                            border.color: "#4a4a52"
                            Rectangle { anchors.right: parent.right; anchors.rightMargin: 5; anchors.verticalCenter: parent.verticalCenter
                                width: 7; height: 3; radius: 1.5; color: v.accent_color }
                        }
                    }
                    ColumnLayout {
                        spacing: 0
                        Label { text: "Linux Island"; color: theme.text; font.pixelSize: 16; font.weight: Font.DemiBold }
                        Label { text: "Settings"; color: theme.dim; font.pixelSize: 12 }
                    }
                }

                // pages
                Repeater {
                    model: window.pages
                    Rectangle {
                        required property int index
                        required property var modelData
                        readonly property bool selected: window.page === index
                        Layout.fillWidth: true
                        implicitHeight: 40
                        radius: 9
                        color: selected ? Qt.rgba(1, 1, 1, 0.09) : navArea.containsMouse ? Qt.rgba(1, 1, 1, 0.04) : "transparent"
                        Behavior on color { ColorAnimation { duration: 120 } }
                        Rectangle {   // accent marker
                            visible: parent.selected
                            width: 3; height: 18; radius: 1.5
                            anchors.left: parent.left
                            anchors.verticalCenter: parent.verticalCenter
                            color: v.accent_color
                        }
                        Row {
                            anchors.left: parent.left
                            anchors.leftMargin: 14
                            anchors.verticalCenter: parent.verticalCenter
                            spacing: 12
                            Glyph {
                                anchors.verticalCenter: parent.verticalCenter
                                name: parent.parent.modelData.icon
                                size: 17
                                color: parent.parent.selected ? theme.text : theme.dim
                            }
                            Label {
                                anchors.verticalCenter: parent.verticalCenter
                                text: parent.parent.modelData.title
                                color: parent.parent.selected ? theme.text : "#c7c7cc"
                                font.pixelSize: 14
                                font.weight: parent.parent.selected ? Font.DemiBold : Font.Normal
                            }
                        }
                        MouseArea {
                            id: navArea
                            anchors.fill: parent
                            hoverEnabled: true
                            cursorShape: Qt.PointingHandCursor
                            onClicked: window.page = parent.index
                        }
                    }
                }

                Item { Layout.fillHeight: true }

                // status
                Rectangle {
                    Layout.fillWidth: true
                    implicitHeight: statusCol.implicitHeight + 24
                    radius: 10
                    color: "#232328"
                    ColumnLayout {
                        id: statusCol
                        anchors.left: parent.left
                        anchors.right: parent.right
                        anchors.verticalCenter: parent.verticalCenter
                        anchors.margins: 12
                        spacing: 8
                        RowLayout {
                            spacing: 8
                            Rectangle { width: 8; height: 8; radius: 4; color: settings.running ? "#34c759" : "#ff453a" }
                            Label {
                                text: settings.running ? "Island is running" : "Island is not running"
                                color: theme.text; font.pixelSize: 13
                            }
                        }
                        Label {
                            text: settings.running ? "Changes apply straight away" : "Start it to see your changes"
                            color: theme.dim; font.pixelSize: 11
                        }
                        Button {
                            visible: !settings.running
                            text: "Start island"
                            Layout.fillWidth: true
                            highlighted: true
                            onClicked: settings.startIsland()
                        }
                    }
                }
            }
        }

        // ---------- pages ----------
        StackLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            currentIndex: window.page

            // ===== General =====
            Page {
                index: 0

                // first start after installing
                Rectangle {
                    id: welcomeCard
                    visible: settings.welcome
                    Layout.fillWidth: true
                    Layout.topMargin: 18
                    implicitHeight: welcomeCol.implicitHeight + 32
                    radius: theme.radius
                    color: Qt.rgba(Qt.color(v.accent_color).r, Qt.color(v.accent_color).g, Qt.color(v.accent_color).b, 0.13)
                    border.color: Qt.rgba(Qt.color(v.accent_color).r, Qt.color(v.accent_color).g, Qt.color(v.accent_color).b, 0.45)
                    ColumnLayout {
                        id: welcomeCol
                        anchors.left: parent.left; anchors.right: parent.right
                        anchors.verticalCenter: parent.verticalCenter
                        anchors.margins: 18
                        spacing: 6
                        Label { text: "Welcome to Linux Island"; color: theme.text; font.pixelSize: 17; font.weight: Font.DemiBold }
                        Label {
                            Layout.fillWidth: true
                            wrapMode: Text.Wrap
                            color: "#d1d1d6"; font.pixelSize: 13
                            text: "The pill is at the top of your screen. Pick the monitors it should use below, then choose colours and features from the sidebar. Every change applies straight away.\n\nYou can come back here any time: Linux Island Settings in the app menu, or the gear on the home card (minimise every window on a monitor)."
                        }
                        Button { text: "Got it"; flat: true; onClicked: settings.dismissWelcome() }
                    }
                }

                GroupTitle { text: "Monitors" }
                Card {
                    SettingRow {
                        title: "Show the island on"
                        detail: "With chosen monitors, it moves to the primary one while none of them is connected"
                        divider: true
                        Segmented {
                            options: [{ label: "All", value: "all" }, { label: "Primary", value: "primary" }, { label: "Chosen", value: "chosen" }]
                            current: typeof v.monitors === "string" ? v.monitors : "chosen"
                            onChosen: value => {
                                if (value === "chosen")   // start from the monitors the island is on now
                                    put("monitors", settings.monitors.filter(m => v.monitors === "all" || m.primary).map(m => m.name))
                                else
                                    put("monitors", value)
                            }
                        }
                    }
                    Repeater {
                        model: settings.monitors
                        SettingRow {
                            required property var modelData
                            required property int index
                            enabled: typeof v.monitors !== "string"
                            title: modelData.name + (modelData.laptop ? "  ·  Laptop screen" : "")
                            detail: modelData.size + (modelData.primary ? "  ·  primary" : "")
                            divider: index < settings.monitors.length - 1
                            CheckBox {
                                checked: v.monitors === "all" || (v.monitors === "primary" ? modelData.primary : v.monitors.indexOf(modelData.name) >= 0)
                                onToggled: settings.setMonitor(modelData.name, checked)
                            }
                        }
                    }
                }

                GroupTitle { text: "Startup" }
                Card {
                    SwitchRow {
                        title: "Start on login"
                        detail: "Launch the island automatically when you sign in"
                        divider: false
                        checked: settings.autostart
                        onToggled: on => settings.autostart = on
                    }
                }

                GroupTitle { text: "Position" }
                Card {
                    SettingRow {
                        title: "Gap above the pill"
                        detail: "Space between the top of the screen (or panel) and the pill, in pixels"
                        divider: false
                        SpinBox { from: 0; to: 40; value: v.top_margin; editable: true; onValueModified: put("top_margin", value) }
                    }
                }
                Item { Layout.preferredHeight: 32 }
            }

            // ===== Appearance =====
            Page {
                index: 1

                // live preview
                Rectangle {
                    Layout.fillWidth: true
                    Layout.topMargin: 18
                    implicitHeight: 178
                    radius: theme.radius
                    gradient: Gradient {
                        GradientStop { position: 0; color: "#2b2b33" }
                        GradientStop { position: 1; color: "#1c1c22" }
                    }
                    Label { x: 16; y: 12; text: "Preview"; color: theme.dim; font.pixelSize: 11 }
                    Column {
                        anchors.centerIn: parent
                        spacing: 16
                        Rectangle {   // the pill
                            anchors.horizontalCenter: parent.horizontalCenter
                            width: 250; height: 28; radius: 14
                            color: v.pill_color
                            border.color: "#33ffffff"
                            Rectangle { x: 6; anchors.verticalCenter: parent.verticalCenter; width: 18; height: 18; radius: 5; color: "#55555f" }
                            Label { x: 32; anchors.verticalCenter: parent.verticalCenter; text: "Song title"; font.pixelSize: 12; color: "#ffffff" }
                            Row {
                                anchors.right: parent.right; anchors.rightMargin: 12
                                anchors.verticalCenter: parent.verticalCenter
                                spacing: 2
                                Repeater {
                                    model: [6, 13, 8, 14]
                                    Rectangle { required property int modelData; width: 3; height: modelData; radius: 1.5; color: v.accent_color; anchors.verticalCenter: parent.verticalCenter }
                                }
                            }
                        }
                        Rectangle {   // the open card
                            anchors.horizontalCenter: parent.horizontalCenter
                            width: 340; height: 76; radius: 22
                            color: v.pill_color
                            border.color: "#33ffffff"
                            Rectangle { x: 16; y: 14; width: 48; height: 48; radius: 10; color: "#55555f" }
                            Label { x: 76; y: 16; text: "Song title"; color: "#ffffff"; font.pixelSize: 13; font.weight: Font.DemiBold }
                            Rectangle { x: 76; y: 44; width: 170; height: 4; radius: 2; color: "#33ffffff"
                                Rectangle { width: parent.width * 0.55; height: parent.height; radius: 2; color: v.accent_color } }
                            Rectangle {
                                anchors.right: parent.right; anchors.rightMargin: 18
                                anchors.verticalCenter: parent.verticalCenter
                                width: 34; height: 34; radius: 17; color: v.accent_color
                                Glyph { anchors.centerIn: parent; name: "play"; size: 16; color: "#000000" }
                            }
                        }
                    }
                }

                GroupTitle { text: "Colours" }
                Card {
                    SettingRow {
                        title: "Colour comes from"
                        detail: v.theme === "vivid" ? "The album art of what's playing; the accent below when nothing is"
                                                    : "Always the accent colour below"
                        Segmented {
                            options: [{ label: "Album art", value: "vivid" }, { label: "Accent", value: "classic" }]
                            current: v.theme === "vivid" ? "vivid" : "classic"
                            onChosen: value => put("theme", value)
                        }
                    }
                    ColourRow {
                        title: "Accent"
                        detail: "Equaliser, play button and progress bar"
                        key: "accent_color"
                        presets: settings.accents.slice(0, 7)
                    }
                    ColourRow {
                        title: "Pill"
                        detail: "Background of the pill and its cards"
                        key: "pill_color"
                        presets: settings.pills
                        divider: false
                    }
                }

                GroupTitle { text: "Clock" }
                Card {
                    SettingRow {
                        title: "Format"
                        detail: "Shown in the pill when nothing is playing"
                        divider: false
                        ComboBox {
                            id: clockPreset
                            width: 220
                            readonly property var formats: ["ddd d MMM  hh:mm", "ddd d MMM  h:mm AP", "hh:mm", "h:mm AP", "dddd hh:mm"]
                            model: ["Wed 18 Nov  15:05", "Wed 18 Nov  3:05 PM", "15:05", "3:05 PM", "Wednesday 15:05"]
                            currentIndex: Math.max(0, formats.indexOf(v.clock_format))
                            onActivated: i => put("clock_format", formats[i])
                        }
                    }
                }

                GroupTitle { text: "Pop-ups" }
                Card {
                    SettingRow {
                        title: "Stay visible for"
                        detail: "Volume, brightness, charger and device pop-ups"
                        divider: false
                        Slider {
                            id: hudSlider
                            width: 180
                            from: 800; to: 4000; stepSize: 100
                            value: v.hud_timeout_ms
                            onMoved: putSoon("hud_timeout_ms", value)
                            onPressedChanged: if (!pressed) window.flush()
                        }
                        Label { anchors.verticalCenter: parent.verticalCenter; width: 40; text: (hudSlider.value / 1000).toFixed(1) + " s"; color: theme.dim }
                    }
                }
                Item { Layout.preferredHeight: 32 }
            }

            // ===== Features =====
            Page {
                index: 2

                GroupTitle { text: "In the pill" }
                Card {
                    Repeater {
                        model: settings.features.filter(f => ["show_media", "dot_camera", "dot_mic"].indexOf(f.key) >= 0)
                        SwitchRow {
                            required property var modelData
                            required property int index
                            title: modelData.title; detail: modelData.detail
                            divider: index < 2
                            checked: v[modelData.key] === true
                            onToggled: on => put(modelData.key, on)
                        }
                    }
                }

                GroupTitle { text: "Pop-ups" }
                Card {
                    Repeater {
                        model: settings.features.filter(f => f.key.indexOf("popup_") === 0)
                        SwitchRow {
                            required property var modelData
                            required property int index
                            title: modelData.title; detail: modelData.detail
                            divider: index < 3
                            checked: v[modelData.key] === true
                            onToggled: on => put(modelData.key, on)
                        }
                    }
                }

                GroupTitle { text: "Interaction" }
                Card {
                    Repeater {
                        model: settings.features.filter(f => ["open_on_hover", "scroll_volume", "home_on_empty_desktop"].indexOf(f.key) >= 0)
                        SwitchRow {
                            required property var modelData
                            required property int index
                            readonly property bool unavailable: modelData.key === "home_on_empty_desktop" && settings.waylandSession
                                                                && settings.helperState !== "active"
                            enabled: !unavailable
                            title: modelData.title
                            detail: unavailable ? "In a Wayland session this needs the Linux Island helper GNOME extension (Screensaver and lock page)" : modelData.detail
                            divider: index < 2
                            checked: v[modelData.key] === true
                            onToggled: on => put(modelData.key, on)
                        }
                    }
                }
                Item { Layout.preferredHeight: 32 }
            }

            // ===== Screensaver & lock =====
            Page {
                index: 3

                GroupTitle { text: "Screensaver" }
                Card {
                    SwitchRow {
                        title: "Screensaver"
                        detail: "When idle, the pill swoops into a clock card and the screen fades to a black clock"
                        checked: v.screensaver_minutes > 0
                        onToggled: on => put("screensaver_minutes", on ? 5 : 0)
                    }
                    SettingRow {
                        title: "Show on"
                        detail: "Monitors without the pill fade to the same black clock (also when locking)"
                        Segmented {
                            options: [{ label: "All monitors", value: "all" }, { label: "Pill monitors", value: "island" }]
                            current: v.screensaver_screens === "island" ? "island" : "all"
                            onChosen: value => put("screensaver_screens", value)
                        }
                    }
                    SettingRow {
                        enabled: v.screensaver_minutes > 0
                        title: "Start after"
                        detail: "Minutes without mouse or keyboard input"
                        SpinBox { from: 1; to: 120; value: Math.max(1, v.screensaver_minutes); editable: true; onValueModified: put("screensaver_minutes", value) }
                    }
                    SettingRow {
                        enabled: settings.running && v.screensaver_minutes > 0
                        title: "Try it"
                        detail: "Shows the screensaver now; move the mouse to end it"
                        divider: false
                        Button { text: "Preview"; flat: true; onClicked: settings.previewScreensaver() }
                    }
                }

                GroupTitle { text: "Lock screen" }
                Card {
                    SwitchRow {
                        title: "Lock animation"
                        detail: "The same clock card and black fade before the lock screen, and back after unlocking"
                        divider: settings.lockShortcutAvailable
                        checked: v.lock_transition === true
                        onToggled: on => put("lock_transition", on)
                    }
                    SwitchRow {
                        visible: settings.lockShortcutAvailable
                        title: "Use the island for the lock shortcut"
                        detail: "So the animation also plays when you press GNOME's lock keys (Ctrl+Alt+L)"
                        divider: false
                        checked: settings.lockShortcut
                        onToggled: on => settings.lockShortcut = on
                    }
                }

                GroupTitle { text: "Home card" }
                Card {
                    SettingRow {
                        visible: settings.helperState !== "no-gnome"
                        title: "GNOME helper extension"
                        detail: ({
                            "active": "On: the home card sees every window, Wayland apps included",
                            "off": "Off. " + (settings.waylandSession ? "Needed for the home card in this Wayland session" : "Optional on X11; lets the home card see every window"),
                            "missing": "Installed; GNOME loads new extensions when you log in. Turn it on now and it starts at your next login",
                            "pending": "Turned on: it starts when you next log out and back in",
                            "error": "GNOME reported an error with it; log out and back in, then try again",
                            "out-of-date": "Not made for this GNOME version yet",
                            "not-installed": "Not installed; it comes with the Linux Island package (or install.sh)",
                        })[settings.helperState] || ""
                        Rectangle {
                            anchors.verticalCenter: parent.verticalCenter
                            visible: settings.helperState === "active"
                            width: 8; height: 8; radius: 4; color: "#34c759"
                        }
                        Button {
                            visible: settings.helperState === "off" || settings.helperState === "missing"
                            text: settings.helperState === "missing" ? "Turn on at next login" : "Turn on"
                            flat: true
                            onClicked: settings.enableHelper()
                        }
                    }
                    SettingRow {
                        enabled: v.home_on_empty_desktop === true
                        title: "Height on screen"
                        detail: "Where the card sits when every window is minimised"
                        divider: false
                        Slider {
                            id: homeSlider
                            width: 180
                            from: 0.2; to: 0.6; stepSize: 0.02
                            value: v.home_position
                            onMoved: putSoon("home_position", value)
                            onPressedChanged: if (!pressed) window.flush()
                        }
                        Label { anchors.verticalCenter: parent.verticalCenter; width: 40; text: Math.round(homeSlider.value * 100) + " %"; color: theme.dim }
                    }
                }
                Item { Layout.preferredHeight: 32 }
            }

            // ===== About =====
            Page {
                index: 4

                Card {
                    Layout.topMargin: 18
                    SettingRow {
                        title: "Linux Island " + settings.version
                        detail: "A dynamic-island style pill for the Linux desktop (X11)"
                        divider: true
                    }
                    SettingRow {
                        title: "Settings file"
                        detail: settings.configPath
                        divider: false
                    }
                }

                GroupTitle { text: "Reset" }
                Card {
                    SettingRow {
                        title: "Restore all defaults"
                        detail: "Every setting goes back to how the island comes installed"
                        divider: false
                        Button { text: "Restore…"; flat: true; Material.foreground: "#ff6961"; onClicked: confirmReset.open() }
                    }
                }
                Item { Layout.preferredHeight: 32 }
            }
        }
    }

    ColorDialog {
        id: colorDialog
        property string key: ""
        title: "Choose a colour"
        onAccepted: window.put(key, selectedColor.toString())
    }

    Dialog {
        id: confirmReset
        anchors.centerIn: parent
        modal: true
        title: "Restore all defaults?"
        standardButtons: Dialog.Ok | Dialog.Cancel
        Label { text: "Every setting goes back to how the island comes installed."; color: theme.dim }
        onAccepted: settings.resetAll()
    }
}
