import QtQuick
import QtQuick.Window

// The control hand drawn on the screen in the virtual hand mode (from virtual-hand-20261110 `virtualHandWindow`).
// A click-through, always-on-top, frameless window centred on the palm; the dot is where a click lands (between the
// drawn thumb and index). It only shows what controller.virtualHand says; it judges nothing.
Window {
    id: overlay
    required property var controller
    readonly property var hand: controller.virtualHand
    readonly property bool hasHand: hand && hand.pts !== undefined && hand.pts.length === 42
    readonly property real dpr: hasHand && hand.scale > 0 ? hand.scale : 1.0
    readonly property int side: 340                                   // logical px; the drawn hand is 110 px big
    objectName: "virtualHandOverlay"
    width: side; height: side
    color: "transparent"
    flags: Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.WindowTransparentForInput
           | Qt.WindowDoesNotAcceptFocus | Qt.NoDropShadowWindowHint
    visible: hasHand && !fade.expired
    x: hasHand ? Math.round(hand.palm[0] / dpr - side / 2) : 0
    y: hasHand ? Math.round(hand.palm[1] / dpr - side / 2) : 0

    // a lost hand stays faint where it was for 0.4 s (most losses come back within that time in the source's data)
    Timer { id: fade; property bool expired: false; interval: 400; onTriggered: expired = true }
    onHandChanged: {
        if (hasHand && hand.lost) { if (!fade.running && !fade.expired) fade.start() }
        else { fade.stop(); fade.expired = false }
        canvas.requestPaint()
    }

    Canvas {
        id: canvas
        anchors.fill: parent
        opacity: overlay.hasHand && overlay.hand.lost ? .35 : .9
        readonly property var bones: [[0,1],[1,2],[2,3],[3,4],[0,5],[5,6],[6,7],[7,8],[5,9],[9,10],[10,11],[11,12],
                                      [9,13],[13,14],[14,15],[15,16],[13,17],[17,18],[18,19],[19,20],[0,17]]
        onPaint: {
            const ctx = getContext("2d")
            ctx.reset()
            if (!overlay.hasHand) return
            const p = overlay.hand.pts, cx = width / 2, cy = height / 2
            ctx.lineCap = "round"
            ctx.strokeStyle = overlay.hand.grip ? "#B54708" : "#0B6E5B"
            ctx.lineWidth = 5
            for (const b of bones) {
                ctx.beginPath()
                ctx.moveTo(cx + p[2 * b[0]], cy + p[2 * b[0] + 1])
                ctx.lineTo(cx + p[2 * b[1]], cy + p[2 * b[1] + 1])
                ctx.stroke()
            }
            ctx.fillStyle = "#FFFFFF"
            for (let i = 0; i < 21; i++) {
                ctx.beginPath(); ctx.arc(cx + p[2 * i], cy + p[2 * i + 1], 3.5, 0, 2 * Math.PI); ctx.fill()
            }
            const c = overlay.hand.click
            if (c && c.length === 2) {
                ctx.beginPath(); ctx.arc(cx + c[0], cy + c[1], 9, 0, 2 * Math.PI)
                if (overlay.hand.aim) { ctx.strokeStyle = "#46E5BD"; ctx.lineWidth = 2; ctx.stroke() }   // where it would click
                else { ctx.fillStyle = "#46E5BD"; ctx.fill() }                                          // clicking / dragging here
            }
        }
    }
}
