import QtQuick
import QtQuick.Shapes

// Speaker whose sound waves follow the volume: none below a third, one wave up to two thirds,
// two waves above; a cross when muted. Waves fade in and out as the level moves.
Item {
    id: icon
    property real level: 1
    property bool muted: false
    property color color: "#ffffff"
    property real size: 18
    width: size
    height: size

    readonly property bool silent: muted || level <= 0.001
    property real wave1: !silent && level > 0.33 ? 1 : 0
    property real wave2: !silent && level > 0.66 ? 1 : 0
    property real cross: silent ? 1 : 0
    Behavior on wave1 { NumberAnimation { duration: 160; easing.type: Easing.OutCubic } }
    Behavior on wave2 { NumberAnimation { duration: 160; easing.type: Easing.OutCubic } }
    Behavior on cross { NumberAnimation { duration: 160; easing.type: Easing.OutCubic } }

    function tint(a) { return Qt.rgba(icon.color.r, icon.color.g, icon.color.b, icon.color.a * a) }

    Shape {
        width: 24
        height: 24
        scale: icon.size / 24
        transformOrigin: Item.TopLeft
        preferredRendererType: Shape.CurveRenderer
        ShapePath {
            strokeColor: "transparent"; strokeWidth: 0
            fillColor: icon.color
            PathSvg { path: "M3 9 H7 L12 5 V19 L7 15 H3 Z" }
        }
        ShapePath {
            strokeColor: "transparent"; strokeWidth: 0
            fillColor: icon.tint(icon.wave1)
            PathSvg { path: "M14.5 8 C17.6 9.6 17.6 14.4 14.5 16 L14.5 14 C15.8 13.2 15.8 10.8 14.5 10 Z" }
        }
        ShapePath {
            strokeColor: "transparent"; strokeWidth: 0
            fillColor: icon.tint(icon.wave2)
            PathSvg { path: "M16.5 4.6 C22.6 7.4 22.6 16.6 16.5 19.4 L16.5 17.4 C20.6 15.2 20.6 8.8 16.5 6.6 Z" }
        }
        ShapePath {
            strokeColor: "transparent"; strokeWidth: 0
            fillColor: icon.tint(icon.cross)
            PathSvg { path: "M15.6 8.4 L21.6 14.4 L20.4 15.6 L14.4 9.6 Z M20.4 8.4 L21.6 9.6 L15.6 15.6 L14.4 14.4 Z" }
        }
    }
}
