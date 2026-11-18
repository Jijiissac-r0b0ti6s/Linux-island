import QtQuick
import QtQuick.Effects

// Album art with rounded corners; falls back to a note icon when the player gives none.
Item {
    id: art
    property string source: ""
    property real radius: 6
    readonly property bool loaded: image.status === Image.Ready

    Rectangle {
        anchors.fill: parent
        radius: art.radius
        color: "#2c2c2e"
        visible: !art.loaded
        Glyph { anchors.centerIn: parent; name: "note"; size: parent.width * 0.6; color: "#8e8e93" }
    }
    Image {
        id: image
        anchors.fill: parent
        source: art.source
        sourceSize: Qt.size(160, 160)
        fillMode: Image.PreserveAspectCrop
        asynchronous: true
        visible: false
        layer.enabled: true
    }
    Item {
        id: mask
        anchors.fill: parent
        visible: false
        layer.enabled: true
        Rectangle { anchors.fill: parent; radius: art.radius }
    }
    MultiEffect {
        anchors.fill: parent
        source: image
        maskEnabled: true
        maskSource: mask
        visible: art.loaded
    }
}
