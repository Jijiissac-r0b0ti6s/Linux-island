import QtQuick

// The big clock shared by the island's screensaver card and the full-screen saver window.
// Both draw it at the same spot so the window can fade in around the card without a seam.
Column {
    property date now: new Date()
    spacing: 4
    Text {
        anchors.horizontalCenter: parent.horizontalCenter
        text: Qt.formatTime(parent.now, "hh:mm")
        color: "#ffffff"
        font.pixelSize: 84
        font.weight: Font.DemiBold
    }
    Text {
        anchors.horizontalCenter: parent.horizontalCenter
        text: Qt.formatDate(parent.now, "dddd, d MMMM")
        color: "#98989f"
        font.pixelSize: 18
    }
}
