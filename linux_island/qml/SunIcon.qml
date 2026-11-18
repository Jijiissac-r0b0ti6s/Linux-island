import QtQuick

// Sun that follows the brightness: a bigger disc and longer, brighter rays as the level rises.
Item {
    id: sun
    property real level: 1
    property color color: "#ffffff"
    property real size: 18
    width: size
    height: size

    property real shown: Math.max(0, Math.min(1, level))
    Behavior on shown { NumberAnimation { duration: 160; easing.type: Easing.OutCubic } }

    Item {   // drawn on a 24 x 24 grid, like the other icons
        width: 24
        height: 24
        scale: sun.size / 24
        transformOrigin: Item.TopLeft

        Rectangle {
            readonly property real r: 2.6 + 1.6 * sun.shown
            x: 12 - r; y: 12 - r
            width: 2 * r; height: 2 * r; radius: r
            color: sun.color
        }
        Repeater {
            model: 8
            Item {
                required property int index
                x: 12; y: 12
                rotation: index * 45
                Rectangle {
                    readonly property real length: 1.6 + 2.6 * sun.shown
                    x: -0.85
                    y: -(5.6 + 0.9 * sun.shown) - length
                    width: 1.7
                    height: length
                    radius: 0.85
                    color: sun.color
                    opacity: 0.4 + 0.6 * sun.shown
                }
            }
        }
    }
}
