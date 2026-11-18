.pragma library
// One colour rule for every battery display.
var LOW = 20
var MID = 50
function tone(percent, charging) {
    if (charging)
        return "#34c759"          // green
    if (percent <= LOW)
        return "#ff453a"          // red
    if (percent <= MID)
        return "#ffd60a"          // yellow
    return "#ffffff"
}
