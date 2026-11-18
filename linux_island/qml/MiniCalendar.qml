import QtQuick

// Compact month grid with today highlighted.
Column {
    id: cal
    // changes once a day, so the grid is not rebuilt every second
    property string dayKey: ""
    readonly property date today: { dayKey; return new Date() }
    readonly property int firstDay: Qt.locale().firstDayOfWeek   // 0 = Sunday
    readonly property var cells: {
        const y = today.getFullYear(), m = today.getMonth()
        const lead = (new Date(y, m, 1).getDay() - firstDay + 7) % 7
        const count = new Date(y, m + 1, 0).getDate()
        let out = []
        for (let i = 0; i < lead; i++)
            out.push(0)
        for (let d = 1; d <= count; d++)
            out.push(d)
        return out
    }
    spacing: 3

    Text {
        text: Qt.formatDate(cal.today, "MMMM yyyy")
        color: "#ffffff"
        font.pixelSize: 11
        font.weight: Font.DemiBold
    }
    Grid {
        columns: 7
        Repeater {
            model: 7
            Text {
                required property int index
                width: 20; height: 14
                horizontalAlignment: Text.AlignHCenter
                text: Qt.locale().dayName((cal.firstDay + index) % 7, Locale.NarrowFormat)
                color: "#98989f"
                font.pixelSize: 9
            }
        }
        Repeater {
            model: cal.cells
            Item {
                required property int modelData
                readonly property bool isToday: modelData === cal.today.getDate()
                width: 20; height: 16
                Rectangle {
                    anchors.centerIn: parent
                    width: 16; height: 16; radius: 8
                    color: "#ffffff"
                    visible: parent.isToday
                }
                Text {
                    anchors.centerIn: parent
                    text: parent.modelData > 0 ? parent.modelData : ""
                    color: parent.isToday ? "#000000" : "#ffffff"
                    font.pixelSize: 10
                    font.weight: parent.isToday ? Font.Bold : Font.Normal
                }
            }
        }
    }
}
