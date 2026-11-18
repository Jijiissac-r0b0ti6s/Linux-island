import QtQuick

Item {
    id: button
    property alias name: icon.name
    property alias level: icon.level      // volume icon: how many waves
    property real size: 20
    property bool filled: false          // solid accent disc behind the icon
    property color fillColor: "#ffffff"
    signal clicked()

    width: size + 14
    height: size + 14
    opacity: enabled ? 1 : 0.3

    Rectangle {
        anchors.fill: parent
        radius: width / 2
        color: button.filled ? button.fillColor : "#ffffff"
        opacity: button.filled ? (area.pressed ? 0.75 : area.containsMouse ? 0.9 : 1)
                               : area.pressed ? 0.22 : area.containsMouse ? 0.12 : 0
        Behavior on opacity { NumberAnimation { duration: 100 } }
    }
    Glyph {
        id: icon
        anchors.centerIn: parent
        size: button.size
        color: button.filled ? "#000000" : "#ffffff"
        scale: area.pressed ? 0.88 : 1
        Behavior on scale { NumberAnimation { duration: 100 } }
    }
    MouseArea {
        id: area
        anchors.fill: parent
        hoverEnabled: true
        onClicked: button.clicked()
    }
}
