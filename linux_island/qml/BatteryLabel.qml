import QtQuick

// "<prefix>64%" followed by the bolt: green charging, yellow at 50 % or less, red at 20 % or less.
Row {
    property string prefix: ""
    property color dim: "#98989f"
    spacing: 3
    Text {
        anchors.verticalCenter: parent.verticalCenter
        text: parent.prefix + battery.percent + "%"
        color: parent.dim; font.pixelSize: 11
    }
    BatteryIcon {
        anchors.verticalCenter: parent.verticalCenter
        size: 17
        normal: parent.dim
    }
}
