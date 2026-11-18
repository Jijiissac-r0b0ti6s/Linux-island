import QtQuick
import "battery.js" as Battery

// The bolt, coloured by the charge: green while charging, yellow at 50 % or less,
// red at 20 % or less, otherwise the surrounding text colour.
Item {
    id: icon
    property int percent: battery.percent
    property bool charging: battery.charging
    property real size: 18
    property color normal: "#98989f"           // above 50 % and not charging
    readonly property color tone: Battery.tone(percent, charging)
    width: bolt.width
    height: bolt.height

    Glyph {
        id: bolt
        size: Math.round(icon.size * 0.65)
        name: "bolt"
        color: icon.tone.toString() === "#ffffff" ? icon.normal : icon.tone
        Behavior on color { ColorAnimation { duration: 300 } }
    }
}
