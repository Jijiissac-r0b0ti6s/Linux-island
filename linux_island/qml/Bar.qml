import QtQuick

// Thin progress bar that doubles as a slider when `interactive` is set.
Item {
    id: bar
    property real value: 0
    property bool interactive: false
    property color fill: "#ffffff"
    signal moved(real v)

    implicitHeight: 16
    implicitWidth: 100

    Rectangle {
        id: track
        anchors.verticalCenter: parent.verticalCenter
        width: parent.width
        height: bar.interactive && (area.pressed || area.containsMouse) ? 8 : 5
        radius: height / 2
        color: "#33ffffff"
        clip: true
        Behavior on height { NumberAnimation { duration: 120 } }

        Rectangle {
            height: parent.height
            width: parent.width * Math.max(0, Math.min(1, bar.value))
            radius: height / 2
            color: bar.fill
            Behavior on width {
                enabled: !area.pressed
                NumberAnimation { duration: 140; easing.type: Easing.OutCubic }
            }
        }
    }

    MouseArea {
        id: area
        anchors.fill: parent
        enabled: bar.interactive
        hoverEnabled: true
        function update(x) { bar.moved(Math.max(0, Math.min(1, x / width))) }
        onPressed: mouse => update(mouse.x)
        onPositionChanged: mouse => { if (pressed) update(mouse.x) }
    }
}
