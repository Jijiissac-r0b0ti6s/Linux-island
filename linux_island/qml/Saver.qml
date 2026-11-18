import QtQuick

// Full-screen screensaver window for one monitor. The compositor fades the whole window in and
// out (window opacity), so nothing here animates while it covers the screen.
Rectangle {
    id: saver
    required property int clockY      // centre of the island's screensaver card, in this window's coordinates
    property bool details: false      // set once the window is fully shown: now playing + battery
    property date now: new Date()
    color: "#000000"

    Timer { interval: 1000; running: saver.visible; repeat: true; onTriggered: saver.now = new Date() }

    readonly property bool vivid: cfg.theme === "vivid"
    Rectangle {   // vivid: a soft glow of the artwork colour from below
        anchors.fill: parent
        visible: saver.vivid && cfg.show_media !== false && media.available
        opacity: saver.details ? 1 : 0
        Behavior on opacity { NumberAnimation { duration: 600 } }
        gradient: Gradient {
            GradientStop { position: 0.55; color: "transparent" }
            GradientStop { position: 1; color: Qt.rgba(Qt.color(media.accent).r, Qt.color(media.accent).g, Qt.color(media.accent).b, 0.22) }
        }
    }

    SaverClock {
        id: clock
        now: saver.now
        x: (saver.width - width) / 2
        y: saver.clockY - height / 2
    }

    Column {
        anchors.horizontalCenter: parent.horizontalCenter
        y: clock.y + clock.height + 48
        spacing: 22
        opacity: saver.details ? 1 : 0
        Behavior on opacity { NumberAnimation { duration: 500 } }

        Row {
            visible: cfg.show_media !== false && media.available
            anchors.horizontalCenter: parent.horizontalCenter
            spacing: 14
            Artwork { width: 52; height: 52; radius: 10; source: media.artUrl }
            Column {
                anchors.verticalCenter: parent.verticalCenter
                spacing: 2
                Text {
                    width: Math.min(implicitWidth, 420); elide: Text.ElideRight
                    text: media.title || media.player
                    color: "#ffffff"; font.pixelSize: 17; font.weight: Font.DemiBold
                }
                Text {
                    width: Math.min(implicitWidth, 420); elide: Text.ElideRight
                    text: (media.playing ? "" : "Paused  ·  ") + (media.artist || media.player)
                    color: "#98989f"; font.pixelSize: 14
                }
            }
        }
        Row {
            visible: battery.available
            anchors.horizontalCenter: parent.horizontalCenter
            spacing: 6
            Text {
                anchors.verticalCenter: parent.verticalCenter
                text: battery.percent + "%" + (battery.charging ? " charging" : "")
                color: "#98989f"; font.pixelSize: 13
            }
            BatteryIcon { size: 20; anchors.verticalCenter: parent.verticalCenter }
        }
    }

    MouseArea {   // a click (like any input) ends the screensaver
        anchors.fill: parent
        onClicked: lock.wake()
    }
}
