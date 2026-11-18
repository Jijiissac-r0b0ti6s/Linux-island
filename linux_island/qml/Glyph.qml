import QtQuick
import QtQuick.Shapes

// Small filled icons drawn on a 24x24 grid, so no icon font or theme is required.
Item {
    id: glyph
    property string name: ""
    property color color: "#ffffff"
    property real size: 18
    // "volume" / "mute": the speaker's waves follow these
    property real level: 1
    property bool muted: name === "mute"
    readonly property bool speaker: name === "volume" || name === "mute"
    readonly property bool sunny: name === "sun"     // brightness: rays follow `level`
    width: size
    height: size

    readonly property var paths: ({
        "play": "M8 5 L19 12 L8 19 Z",
        "pause": "M6 5 H10 V19 H6 Z M14 5 H18 V19 H14 Z",
        "next": "M5 6 L13.5 12 L5 18 Z M15.5 6 H18 V18 H15.5 Z",
        "previous": "M19 6 L10.5 12 L19 18 Z M6 6 H8.5 V18 H6 Z",
        "volume": "M3 9 H7 L12 5 V19 L7 15 H3 Z M14.5 8 C17.6 9.6 17.6 14.4 14.5 16 L14.5 14 C15.8 13.2 15.8 10.8 14.5 10 Z M16.5 4.6 C22.6 7.4 22.6 16.6 16.5 19.4 L16.5 17.4 C20.6 15.2 20.6 8.8 16.5 6.6 Z",
        "mute": "M3 9 H7 L12 5 V19 L7 15 H3 Z M15.6 8.4 L21.6 14.4 L20.4 15.6 L14.4 9.6 Z M20.4 8.4 L21.6 9.6 L15.6 15.6 L14.4 14.4 Z",
        "sun": "M12 8 A4 4 0 1 0 12 16 A4 4 0 1 0 12 8 Z M11.2 2 H12.8 V5.5 H11.2 Z M11.2 18.5 H12.8 V22 H11.2 Z M2 11.2 H5.5 V12.8 H2 Z M18.5 11.2 H22 V12.8 H18.5 Z M16.5 6.4 L19 3.9 L20.1 5 L17.6 7.5 Z M7.5 6.4 L5 3.9 L3.9 5 L6.4 7.5 Z M16.5 17.6 L19 20.1 L20.1 19 L17.6 16.5 Z M7.5 17.6 L5 20.1 L3.9 19 L6.4 16.5 Z",
        "bolt": "M13 2 L5 13.5 H11 L10 22 L19 10 H13 Z",
        "headphones": "M12 3 A9 9 0 0 0 3 12 V18 A2 2 0 0 0 5 20 H8 V13 H5 V12 A7 7 0 0 1 19 12 V13 H16 V20 H19 A2 2 0 0 0 21 18 V12 A9 9 0 0 0 12 3 Z",
        "bluetooth": "M17.71 7.71 L12 2 h-1 v7.59 L6.41 5 L5 6.41 L10.59 12 L5 17.59 L6.41 19 L11 14.41 V22 h1 l5.71 -5.71 l-4.3 -4.29 l4.3 -4.29 z M13 5.83 l1.88 1.88 L13 9.59 V5.83 z m1.88 10.46 L13 18.17 v-3.76 l1.88 1.88 z",
        "settings": "M19.14 12.94c.04-.3.06-.61.06-.94 0-.32-.02-.64-.07-.94l2.03-1.58a.49.49 0 0 0 .12-.61l-1.92-3.32a.488.488 0 0 0-.59-.22l-2.39.96c-.5-.38-1.03-.7-1.62-.94l-.36-2.54a.484.484 0 0 0-.48-.41h-3.84c-.24 0-.43.17-.47.41l-.36 2.54c-.59.24-1.13.57-1.62.94l-2.39-.96c-.22-.08-.47 0-.59.22L2.74 8.87c-.12.21-.08.47.12.61l2.03 1.58c-.05.3-.09.63-.09.94s.02.64.07.94l-2.03 1.58a.49.49 0 0 0-.12.61l1.92 3.32c.12.22.37.29.59.22l2.39-.96c.5.38 1.03.7 1.62.94l.36 2.54c.05.24.24.41.48.41h3.84c.24 0 .44-.17.47-.41l.36-2.54c.59-.24 1.13-.56 1.62-.94l2.39.96c.22.08.47 0 .59-.22l1.92-3.32c.12-.22.07-.47-.12-.61l-2.01-1.58zM12 15.6c-1.98 0-3.6-1.62-3.6-3.6s1.62-3.6 3.6-3.6 3.6 1.62 3.6 3.6-1.62 3.6-3.6 3.6z",
        "display": "M2.5 4 H21.5 V16.5 H2.5 Z M4.5 6 V14.5 H19.5 V6 Z M8.5 18.5 H15.5 V20.5 H8.5 Z",
        "palette": "M12 3 A9 9 0 1 0 12 21 C13.1 21 13.5 20.2 13.5 19.5 C13.5 18.2 12.6 17.5 13.8 16.6 C14.6 16 15.8 16.2 17 16.2 C19.5 16.2 21 14.6 21 12 A9 9 0 0 0 12 3 Z M7.5 13 A1.5 1.5 0 1 0 7.5 10 A1.5 1.5 0 1 0 7.5 13 Z M10.5 9 A1.5 1.5 0 1 0 10.5 6 A1.5 1.5 0 1 0 10.5 9 Z M15 9.5 A1.5 1.5 0 1 0 15 6.5 A1.5 1.5 0 1 0 15 9.5 Z",
        "toggle": "M7 6.5 H17 A5.5 5.5 0 0 1 17 17.5 H7 A5.5 5.5 0 0 1 7 6.5 Z M17 9 A3 3 0 1 0 17 15 A3 3 0 1 0 17 9 Z",
        "moon": "M20 14.5 A8.5 8.5 0 1 1 9.5 3.5 A6.8 6.8 0 0 0 20 14.5 Z",
        "info": "M12 2 A10 10 0 1 0 12 22 A10 10 0 1 0 12 2 Z M11 10 H13 V17 H11 Z M11 6.5 H13 V8.5 H11 Z",
        "note": "M9 4 H19 V7 H11.5 V16.5 A3.2 3.2 0 1 1 9 13.6 Z"
    })

    VolumeIcon {
        visible: glyph.speaker
        size: glyph.size
        color: glyph.color
        level: glyph.level
        muted: glyph.muted
    }

    SunIcon {
        visible: glyph.sunny
        size: glyph.size
        color: glyph.color
        level: glyph.level
    }

    Shape {
        visible: !glyph.speaker && !glyph.sunny
        width: 24
        height: 24
        scale: glyph.size / 24
        transformOrigin: Item.TopLeft
        preferredRendererType: Shape.CurveRenderer
        ShapePath {
            strokeColor: "transparent"
            strokeWidth: 0
            fillColor: glyph.color
            PathSvg { path: glyph.paths[glyph.name] || "" }
        }
    }
}
