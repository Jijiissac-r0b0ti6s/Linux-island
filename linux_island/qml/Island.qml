import QtQuick
import "battery.js" as Battery

// Root of one island window. `media`, `audio`, `brightness`, `battery`, `camera`, `microphone`, `bluetooth`,
// `lock` and `cfg` are context properties shared by every monitor's window.
Item {
    id: root
    required property var win
    required property string screenName
    required property int homeCentre   // y of the home card's centre line inside this window

    property bool expanded: false
    // the card's position is being changed from the settings panel (several updates in a row)
    property bool retargeting: false
    onHomeCentreChanged: {
        retargeting = true
        retargetEnd.restart()
    }
    Timer { id: retargetEnd; interval: 400; onTriggered: root.retargeting = false }
    // Screensaver and lock: the pill swoops down into a clock card, then the full-screen saver window
    // fades in around it (SaverWindow in app.py); on the way back the card waits for the fade-out.
    readonly property bool saver: lock.idle || (cfg.lock_transition !== false && (lock.locked || lock.locking))
    property bool saverHold: false               // the card stays until the saver window has faded out
    readonly property bool saverCard: saver || saverHold
    readonly property bool card: saverCard
    readonly property int saverWidth: 460
    readonly property int saverHeight: 220
    onSaverChanged: {
        if (saver) {
            saverHold = true
            hud = ""
            expanded = false
        }
        win.setSaver(saver)
    }
    readonly property bool home: cfg.home_on_empty_desktop && desktop.emptyScreens.indexOf(screenName) >= 0
    readonly property bool open: expanded || home
    readonly property real homeScale: 1.25
    readonly property string dayKey: Qt.formatDate(now, "yyyy-MM-dd")
    property string hud: ""   // "", "volume", "brightness", "power" or "device"
    property string hudScreen: ""      // monitor a brightness pop-up refers to
    property string hudGlyph: ""        // "device" pop-up: icon, text and battery percent (-1 = unknown)
    property string hudLabel: ""
    property int hudPercent: -1

    readonly property bool vivid: cfg.theme === "vivid"
    // feature switches from the settings panel
    readonly property bool hasMedia: cfg.show_media !== false && media.available
    readonly property bool camOn: cfg.dot_camera !== false && camera.active
    readonly property bool micOn: cfg.dot_mic !== false && microphone.active
    readonly property color pillColor: cfg.pill_color || "#000000"
    readonly property color userAccent: cfg.accent_color || "#34c759"
    property color accent: vivid && hasMedia ? media.accent : userAccent
    Behavior on accent { ColorAnimation { duration: 500 } }
    readonly property color barFill: hasMedia ? accent : "#ffffff"
    readonly property real myBrightness: {
        const v = brightness.levels[screenName]
        return v === undefined ? -1 : v
    }
    readonly property int dotsWidth: (root.camOn ? 12 : 0) + (root.micOn ? 12 : 0)
    property date now: new Date()

    // pill shape without the saver; `mode` also decides which content is shown
    readonly property string shape: card ? "saver" : open ? "expanded" : hud !== "" ? "hud" : root.hasMedia ? "media" : "idle"
    readonly property string mode: saverCard ? "saver" : shape
    readonly property int panelWidth: 400     // media / clock / sliders column
    readonly property int sideWidth: 172      // time + calendar column, home card only
    readonly property int expandedWidth: home ? panelWidth + sideWidth : panelWidth
    // monitors whose brightness can be controlled, laptop panel first
    readonly property var monitors: Object.keys(brightness.levels).sort((a, b) => isLaptop(b) - isLaptop(a) || a.localeCompare(b))
    // home card: header, devices line, volume, then one brightness slider per monitor (two per row)
    readonly property int homeHeight: pad + (root.hasMedia ? 136 : 48) + 8 + 20 + 8 + 20
                                      + Math.ceil(monitors.length / 2) * 28 + pad - 2
    readonly property int expandedHeight: home ? homeHeight : root.hasMedia ? 202 : 108
    readonly property int pad: 18
    readonly property color dim: "#98989f"

    function showHud(kind) {
        if (open || saverCard)
            return
        hud = kind
        hudTimer.restart()
    }
    function showDevice(icon, text, percent) {
        hudGlyph = icon
        hudLabel = text
        hudPercent = percent
        showHud("device")
    }
    function isLaptop(name) { return /^(eDP|LVDS|DSI)/.test(name) }
    function clock(seconds) {
        const s = Math.max(0, Math.floor(seconds))
        return Math.floor(s / 60) + ":" + String(s % 60).padStart(2, "0")
    }
    function pushMask() {
        // clicks land where the pill is drawn: take its on-screen corners, whatever it is scaled about
        const tl = pill.mapToItem(root, 0, 0)
        const br = pill.mapToItem(root, pill.width, pill.height)
        win.setInputRect(tl.x, tl.y, br.x - tl.x, br.y - tl.y)
    }

    Timer { interval: 1000; running: true; repeat: true; onTriggered: root.now = new Date() }
    Timer { id: hudTimer; interval: cfg.hud_timeout_ms; onTriggered: root.hud = "" }
    Timer { id: collapseTimer; interval: 400; onTriggered: root.expanded = false }
    // short delay so the popup doesn't open when the pointer merely passes over the pill
    // hover opens the popup once the pointer has settled on the pill (passing over it doesn't)
    Timer {
        id: openTimer
        interval: 300
        onTriggered: {
            if (typeof islandDebug !== "undefined" && islandDebug)
                console.log("island: popup opened by hover (pointer moved " + Math.round(hover.travel)
                            + " px onto the pill, then rested " + interval + " ms)")
            root.hud = ""
            root.expanded = true
        }
    }

    Connections { target: audio; function onChanged() { if (cfg.popup_volume !== false) root.showHud("volume") } }
    Connections {
        target: brightness
        function onChanged(name) {
            if (cfg.popup_brightness === false)
                return
            root.hudScreen = name
            root.showHud("brightness")
        }
    }
    Connections {
        target: audio
        function onOutputChanged(name, headphones) { if (cfg.popup_devices !== false) root.showDevice(headphones ? "headphones" : "volume", name, -1) }
    }
    Connections {
        target: bluetooth
        function onDeviceEvent(name, connected, battery, audio) {
            if (cfg.popup_devices === false)
                return
            root.showDevice(audio ? "headphones" : "bluetooth", connected ? name : name + " disconnected", battery)
        }
    }
    Connections { target: battery; function onPluggedChanged() { if (cfg.popup_power !== false) root.showHud("power") } }

    Rectangle {
        id: pill
        anchors.horizontalCenter: parent.horizontalCenter
        objectName: "pill"
        y: root.card ? root.homeCentre - root.saverHeight / 2
           : root.home ? root.homeCentre - root.expandedHeight * root.homeScale / 2 : 0
        scale: root.home && !root.card ? root.homeScale : 1
        color: root.pillColor
        border.color: root.vivid && root.hasMedia && !root.card ? Qt.rgba(root.accent.r, root.accent.g, root.accent.b, 0.55) : "#26ffffff"
        border.width: 1
        clip: true

        // vivid theme: the open card is washed with the artwork's colour
        Rectangle {
            anchors.fill: parent
            radius: pill.radius
            visible: root.vivid && opacity > 0
            opacity: root.open && root.hasMedia && !root.card ? 1 : 0
            Behavior on opacity { NumberAnimation { duration: 300 } }
            gradient: Gradient {
                orientation: Gradient.Horizontal
                GradientStop { position: 0; color: Qt.rgba(root.accent.r, root.accent.g, root.accent.b, 0.42) }
                GradientStop { position: 0.8; color: Qt.rgba(root.accent.r, root.accent.g, root.accent.b, 0.04) }
            }
        }

        width: root.shape === "saver" ? root.saverWidth : root.shape === "expanded" ? root.expandedWidth : root.shape === "idle" ? 156 : 250
        height: root.shape === "saver" ? root.saverHeight : root.shape === "expanded" ? root.expandedHeight : 28
        radius: root.card ? 36 : root.open ? 30 : 14

        // Growing (swooping down) springs and overshoots; shrinking back up glides without overshoot,
        // so the pill never pokes out of the top of the window or wobbles below its size. The screensaver
        // card also settles without wobble, so the saver window can fade in exactly around it.
        Behavior on width {
            id: widthMotion
            SpringAnimation {
                readonly property bool settle: root.card || widthMotion.targetValue < pill.width
                spring: settle ? 9 : 4.2; epsilon: 0.2
                damping: settle ? 1.0 : 0.34
            }
        }
        Behavior on height {
            id: heightMotion
            SpringAnimation {
                readonly property bool settle: root.card || heightMotion.targetValue < pill.height
                spring: settle ? 9 : 4.2; epsilon: 0.2
                damping: settle ? 1.0 : 0.34
            }
        }
        Behavior on radius { NumberAnimation { duration: 220 } }
        // the swoop: travel and growth overshoot slightly, then settle
        Behavior on y {
            id: yMotion
            NumberAnimation {
                // the home card's height is being adjusted in settings: glide, don't bounce
                duration: root.retargeting ? 220 : 650
                easing.type: root.retargeting ? Easing.OutCubic
                           : yMotion.targetValue < pill.y ? Easing.InOutCubic : Easing.OutBack
                easing.overshoot: 1.2
            }
        }
        Behavior on scale {
            id: scaleMotion
            NumberAnimation {
                duration: 650
                easing.type: scaleMotion.targetValue < pill.scale ? Easing.InOutCubic : Easing.OutBack
                easing.overshoot: 1.2
            }
        }

        onXChanged: root.pushMask()
        onYChanged: root.pushMask()
        onScaleChanged: root.pushMask()
        onWidthChanged: root.pushMask()
        onHeightChanged: root.pushMask()
        Component.onCompleted: root.pushMask()

        // Hover opens the popup only when the pointer has really moved onto the pill and then settled
        // there. Not when the pill grows under a resting pointer (a song starts, a volume / brightness
        // pop-up), not for the pointer just passing over on its way somewhere else, and not for the
        // tiny jitter some X servers report while the pill animates.
        HoverHandler {
            id: hover
            property point start
            property bool placed: false    // `start` holds the first real position of this hover
            property real travel: 0        // furthest the pointer has got from where it came in (jitter in place stays ~0)
            readonly property point at: point.scenePosition
            readonly property int minTravel: 6
            function wantsOpen() { return !root.saverCard && cfg.open_on_hover !== false }
            onHoveredChanged: {
                placed = false             // the position reported with the hover itself can be stale
                travel = 0
                openTimer.stop()
                if (hovered)
                    collapseTimer.stop()
                else
                    collapseTimer.restart()
            }
            onAtChanged: {
                if (!hovered)
                    return
                if (!placed) {
                    start = at
                    placed = true
                    return
                }
                travel = Math.max(travel, Math.abs(at.x - start.x) + Math.abs(at.y - start.y))
                // every real move restarts the wait: it opens once the pointer rests on the pill
                if (!root.expanded && wantsOpen() && travel >= minTravel)
                    openTimer.restart()
            }
        }
        WheelHandler {
            enabled: cfg.scroll_volume !== false
            onWheel: event => audio.nudge(event.angleDelta.y > 0 ? 0.05 : -0.05)
        }
        MouseArea {
            anchors.fill: parent
            enabled: !root.open && !root.saverCard
            onClicked: { root.hud = ""; root.expanded = true }
        }

        // ---------- screensaver: clock card ----------
        Item {
            anchors.fill: parent
            opacity: root.mode === "saver" && root.card ? 1 : 0
            visible: opacity > 0
            Behavior on opacity { NumberAnimation { duration: 220 } }
            SaverClock {
                now: root.now
                anchors.centerIn: parent
            }
        }

        // ---------- idle: clock ----------
        Item {
            anchors.fill: parent
            opacity: root.mode === "idle" ? 1 : 0
            visible: opacity > 0
            Behavior on opacity { NumberAnimation { duration: 160 } }
            Text {
                anchors.centerIn: parent
                text: Qt.formatDateTime(root.now, cfg.clock_format)
                color: "#ffffff"
                font.pixelSize: 13
                font.weight: Font.DemiBold
            }
        }

        // ---------- compact now-playing ----------
        Item {
            anchors.fill: parent
            opacity: root.mode === "media" ? 1 : 0
            visible: opacity > 0
            Behavior on opacity { NumberAnimation { duration: 160 } }

            Artwork {
                id: smallArt
                x: 6; width: 20; height: 20; radius: 5
                anchors.verticalCenter: parent.verticalCenter
                source: media.artUrl
            }
            Text {
                anchors.left: smallArt.right
                anchors.leftMargin: 8
                anchors.right: bars.left
                anchors.rightMargin: 8
                anchors.verticalCenter: parent.verticalCenter
                text: media.title || media.player
                color: "#ffffff"
                elide: Text.ElideRight
                font.pixelSize: 12
                font.weight: Font.Medium
            }
            Row {
                id: bars
                anchors.right: parent.right
                anchors.rightMargin: 12 + root.dotsWidth
                anchors.verticalCenter: parent.verticalCenter
                height: 14
                spacing: 2
                Repeater {
                    model: [520, 380, 640, 450]
                    Rectangle {
                        required property int modelData
                        width: 3; radius: 1.5
                        color: root.accent
                        anchors.verticalCenter: parent.verticalCenter
                        height: 4
                        SequentialAnimation on height {
                            running: media.playing && root.mode === "media"
                            loops: Animation.Infinite
                            NumberAnimation { to: 14; duration: modelData; easing.type: Easing.InOutSine }
                            NumberAnimation { to: 4; duration: modelData; easing.type: Easing.InOutSine }
                        }
                    }
                }
            }
        }

        // ---------- volume / brightness / power pop-up ----------
        Item {
            anchors.fill: parent
            opacity: root.mode === "hud" ? 1 : 0
            visible: opacity > 0
            Behavior on opacity { NumberAnimation { duration: 160 } }

            readonly property bool isPower: root.hud === "power"
            readonly property real level: root.hud === "brightness" ? (brightness.levels[root.hudScreen] || 0)
                                        : root.hud === "power" ? battery.percent / 100
                                        : audio.muted ? 0 : audio.volume

            BatteryIcon {
                visible: parent.isPower
                x: 10; size: 24
                normal: "#ffffff"
                anchors.verticalCenter: parent.verticalCenter
            }
            Glyph {
                id: hudIcon
                x: 10; size: 16
                anchors.verticalCenter: parent.verticalCenter
                name: root.hud === "device" ? root.hudGlyph : root.hud === "brightness" ? "sun"
                    : audio.muted || audio.volume === 0 ? "mute" : "volume"
                level: root.hud === "device" ? 1 : parent.level
                visible: !parent.isPower
                color: "#ffffff"
            }
            Text {   // device name, or what the charger is doing (no level bar: that's for volume / brightness)
                id: hudMessage
                visible: root.hud === "device" || parent.isPower
                anchors.left: hudIcon.right
                anchors.leftMargin: parent.isPower ? 16 : 10
                anchors.right: hudText.left
                anchors.rightMargin: 6
                anchors.verticalCenter: parent.verticalCenter
                text: parent.isPower ? ({ "charging": "Charging", "full": "Fully charged", "plugged": "Plugged in" })[battery.state]
                                         || "On battery"
                                     : root.hudLabel
                color: "#ffffff"
                elide: Text.ElideRight
                font.pixelSize: 12
                font.weight: Font.Medium
            }
            Bar {
                visible: root.hud === "volume" || root.hud === "brightness"
                anchors.left: hudIcon.right
                anchors.leftMargin: 10
                anchors.right: hudText.left
                anchors.rightMargin: 10
                anchors.verticalCenter: parent.verticalCenter
                value: parent.level
                fill: "#ffffff"
            }
            Text {
                id: hudText
                anchors.right: parent.right
                anchors.rightMargin: 12 + root.dotsWidth
                anchors.verticalCenter: parent.verticalCenter
                width: 34
                horizontalAlignment: Text.AlignRight
                text: root.hud === "device" ? (root.hudPercent >= 0 ? root.hudPercent + "%" : "")
                                            : Math.round(parent.level * 100) + "%"
                color: parent.isPower ? Battery.tone(battery.percent, battery.charging) : "#ffffff"
                font.pixelSize: 12
                font.weight: Font.DemiBold
            }
        }

        // ---------- expanded ----------
        Item {
            id: panel
            width: root.expandedWidth
            Behavior on width { NumberAnimation { duration: 320; easing.type: Easing.OutCubic } }
            height: root.expandedHeight
            anchors.horizontalCenter: parent.horizontalCenter
            opacity: root.mode === "expanded" ? 1 : 0
            visible: opacity > 0
            Behavior on opacity { NumberAnimation { duration: 200 } }

            readonly property int inner: root.panelWidth - 2 * root.pad
            readonly property string status: {
                // the home card already shows the time (right) and battery (below); the popup's battery
                // follows this line as BatteryLabel, the same battery icon as everywhere else
                let parts = [root.home ? Qt.formatDate(root.now, "dddd, d MMMM") : Qt.formatDateTime(root.now, cfg.clock_format)]
                if (root.camOn)
                    parts.push("Camera in use" + (camera.app ? " by " + camera.app : ""))
                if (root.micOn)
                    parts.push("Mic in use")
                return parts.join("  ·  ")
            }

            // --- now playing ---
            Item {
                visible: root.hasMedia
                x: root.pad; y: root.pad
                width: panel.inner; height: 136

                Artwork { id: bigArt; width: 64; height: 64; radius: 12; source: media.artUrl }
                Column {
                    anchors.left: bigArt.right
                    anchors.leftMargin: 12
                    anchors.right: parent.right
                    anchors.rightMargin: 14
                    anchors.verticalCenter: bigArt.verticalCenter
                    spacing: 2
                    Text {
                        width: parent.width; elide: Text.ElideRight
                        text: media.title || "Unknown title"
                        color: "#ffffff"; font.pixelSize: 15; font.weight: Font.DemiBold
                    }
                    Text {
                        width: parent.width; elide: Text.ElideRight
                        text: media.artist || media.player
                        color: root.dim; font.pixelSize: 13
                    }
                    Row {
                        width: parent.width
                        spacing: 0
                        Text {
                            width: Math.min(implicitWidth, parent.width - (statusBattery.visible ? statusBattery.width : 0))
                            elide: Text.ElideRight
                            text: panel.status
                            color: root.dim; font.pixelSize: 11
                        }
                        BatteryLabel {
                            id: statusBattery
                            visible: battery.available && !root.home
                            prefix: "  ·  "
                            dim: root.dim
                        }
                    }
                }

                Text {
                    id: elapsed
                    y: 78; width: 38
                    text: media.positionKnown ? root.clock(media.position) : "--:--"
                    color: root.dim; font.pixelSize: 11
                }
                Bar {
                    anchors.left: elapsed.right
                    anchors.right: total.left
                    anchors.verticalCenter: elapsed.verticalCenter
                    interactive: media.length > 0
                    fill: root.barFill
                    value: media.length > 0 && media.positionKnown ? media.position / media.length : 0
                    onMoved: v => media.seek(v)
                }
                Text {
                    id: total
                    y: 78; width: 38
                    anchors.right: parent.right
                    horizontalAlignment: Text.AlignRight
                    text: media.length > 0 ? root.clock(media.length) : "--:--"
                    color: root.dim; font.pixelSize: 11
                }

                Row {
                    y: 100
                    anchors.horizontalCenter: parent.horizontalCenter
                    spacing: 22
                    IconButton { name: "previous"; enabled: media.canPrevious; onClicked: media.previous() }
                    IconButton { name: media.playing ? "pause" : "play"; size: 24; filled: true; fillColor: root.accent; onClicked: media.playPause() }
                    IconButton { name: "next"; enabled: media.canNext; onClicked: media.next() }
                }
            }

            // --- nothing playing: clock header ---
            Item {
                visible: !root.hasMedia
                x: root.pad; y: root.pad - 4
                width: panel.inner; height: 40
                Text {
                    id: bigClock
                    anchors.verticalCenter: parent.verticalCenter
                    text: Qt.formatTime(root.now, "hh:mm")
                    color: "#ffffff"; font.pixelSize: 28; font.weight: Font.DemiBold
                }
                Column {
                    anchors.right: parent.right
                    anchors.rightMargin: 14
                    anchors.verticalCenter: parent.verticalCenter
                    spacing: 2
                    Text {
                        anchors.right: parent.right
                        text: Qt.formatDate(root.now, "dddd, d MMMM")
                        color: "#ffffff"; font.pixelSize: 13
                    }
                    Row {
                        anchors.right: parent.right
                        BatteryLabel {
                            visible: battery.available && !root.home
                            prefix: "Battery "
                            dim: root.dim
                        }
                        Text {
                            text: (root.camOn ? "  ·  Camera in use" + (camera.app ? " by " + camera.app : "") : "")
                                + (root.micOn ? "  ·  Mic in use" : "")
                            color: root.dim; font.pixelSize: 11
                        }
                    }
                }
            }

            // --- home card only: time and month calendar ---
            Item {
                x: root.panelWidth
                width: root.sideWidth
                height: parent.height
                opacity: root.home ? 1 : 0
                visible: opacity > 0
                Behavior on opacity { NumberAnimation { duration: 250 } }

                Rectangle { y: root.pad; width: 1; height: parent.height - 2 * root.pad; color: "#26ffffff" }
                Column {
                    x: 16
                    anchors.verticalCenter: parent.verticalCenter
                    spacing: 6
                    Text {
                        visible: root.hasMedia   // otherwise the big clock on the left already shows it
                        text: Qt.formatTime(root.now, "hh:mm")
                        color: "#ffffff"; font.pixelSize: 24; font.weight: Font.DemiBold
                    }
                    MiniCalendar { dayKey: root.dayKey }
                }
            }

            // --- bottom block: devices line (home), volume, brightness ---
            Column {
                x: root.pad
                width: panel.inner
                anchors.bottom: parent.bottom
                anchors.bottomMargin: root.pad - 2
                spacing: 8

                // battery and connected Bluetooth devices
                Row {
                    visible: root.home
                    height: 20
                    spacing: 6
                    BatteryIcon {
                        visible: battery.available
                        size: 20
                        normal: "#ffffff"
                        anchors.verticalCenter: parent.verticalCenter
                    }
                    Text {
                        visible: battery.available
                        anchors.verticalCenter: parent.verticalCenter
                        text: battery.percent + "%" + (battery.charging ? " charging" : "")
                        color: "#ffffff"; font.pixelSize: 11
                    }
                    Item { width: 10; height: 1; visible: battery.available }
                    Glyph {
                        size: 13; name: "bluetooth"
                        anchors.verticalCenter: parent.verticalCenter
                        color: bluetooth.devices.length > 0 ? "#0a84ff" : root.dim
                    }
                    Text {
                        anchors.verticalCenter: parent.verticalCenter
                        width: Math.min(implicitWidth, 220)
                        elide: Text.ElideRight
                        text: bluetooth.devices.length === 0 ? "No device connected"
                            : bluetooth.devices.map(d => d.name + (d.battery >= 0 ? " " + d.battery + "%" : "")).join(",  ")
                        color: bluetooth.devices.length > 0 ? "#ffffff" : root.dim
                        font.pixelSize: 11
                    }
                }

                Row {
                    spacing: 18
                    // the popup pairs volume with this monitor's brightness; the home card lists every monitor below
                    readonly property bool pair: !root.home && root.myBrightness >= 0
                    readonly property real cell: pair ? (panel.inner - spacing) / 2 : panel.inner

                    Item {
                        width: parent.cell; height: 20
                        IconButton {
                            id: volIcon
                            x: -7; size: 16
                            anchors.verticalCenter: parent.verticalCenter
                            name: audio.muted || audio.volume === 0 ? "mute" : "volume"
                            level: audio.volume
                            onClicked: audio.toggleMute()
                        }
                        Bar {
                            anchors.left: volIcon.right
                            anchors.leftMargin: 2
                            anchors.right: parent.right
                            anchors.verticalCenter: parent.verticalCenter
                            interactive: true
                            value: audio.muted ? 0 : audio.volume
                            onMoved: v => audio.setVolume(v)
                        }
                    }
                    Item {
                        visible: parent.pair
                        width: parent.cell; height: 20
                        Glyph {
                            id: sunIcon
                            size: 16; name: "sun"
                            level: root.myBrightness
                            anchors.verticalCenter: parent.verticalCenter
                        }
                        Bar {
                            anchors.left: sunIcon.right
                            anchors.leftMargin: 9
                            anchors.right: parent.right
                            anchors.verticalCenter: parent.verticalCenter
                            interactive: true
                            value: root.myBrightness
                            onMoved: v => brightness.setLevel(root.screenName, v)
                        }
                    }
                }

                // home card: one brightness slider per controllable monitor
                Grid {
                    visible: root.home && root.monitors.length > 0
                    columns: 2
                    columnSpacing: 18
                    rowSpacing: 8
                    Repeater {
                        model: root.monitors
                        Item {
                            required property string modelData
                            width: root.monitors.length > 1 ? (panel.inner - 18) / 2 : panel.inner
                            height: 20
                            Glyph {
                                id: monIcon
                                size: 16; name: "sun"
                                level: brightness.levels[parent.modelData] || 0
                                anchors.verticalCenter: parent.verticalCenter
                            }
                            Text {
                                id: monLabel
                                anchors.left: monIcon.right
                                anchors.leftMargin: 6
                                anchors.verticalCenter: parent.verticalCenter
                                width: 40
                                elide: Text.ElideRight
                                text: root.isLaptop(parent.modelData) ? "Laptop" : parent.modelData
                                color: root.dim; font.pixelSize: 10
                            }
                            Bar {
                                anchors.left: monLabel.right
                                anchors.leftMargin: 4
                                anchors.right: parent.right
                                anchors.verticalCenter: parent.verticalCenter
                                interactive: true
                                value: brightness.levels[parent.modelData] || 0
                                onMoved: v => brightness.setLevel(parent.modelData, v)
                            }
                        }
                    }
                }
            }
        }

        // ---------- settings button (home card only) ----------
        IconButton {
            name: "settings"
            size: 15
            x: pill.width - width - 8
            y: 6
            opacity: root.mode === "expanded" && root.home ? 0.55 : 0
            visible: opacity > 0
            Behavior on opacity { NumberAnimation { duration: 200 } }
            onClicked: { root.expanded = false; win.openSettings() }
        }

        // ---------- privacy dots (all modes): green = camera, orange = microphone ----------
        Row {
            spacing: 4
            x: pill.width - width - (root.home ? 46 : root.open ? 14 : 8)
            y: root.open ? 14 : (pill.height - height) / 2
            Rectangle { width: 8; height: 8; radius: 4; color: "#34c759"; visible: root.camOn }
            Rectangle { width: 8; height: 8; radius: 4; color: "#ff9f0a"; visible: root.micOn }
            SequentialAnimation on opacity {
                running: root.camOn || root.micOn
                loops: Animation.Infinite
                NumberAnimation { to: 0.45; duration: 900 }
                NumberAnimation { to: 1; duration: 900 }
            }
        }
    }
}
