import QtQuick
import QtQuick.Window

// The control hand drawn on the screen in the virtual hand mode, as in the hand-mouse branch
// feat/online-learning-virtual-hand-20261110 (`virtualHandWindow` in src/dashboard.qml), which the 2026-11-10 report
// asked to follow again ("다른 프로젝트들과 병합하면서 가상손 모드의 좋은 부분들을 너무 많이 잃었다"):
// - camera frames come ~30 times a second and unevenly: the joints AND the window glide toward the newest frame at the
//   screen's own rate (each display frame closes a share of the gap, time constant `glide`), so the motion is continuous;
// - a dark outline under a light line, so the hand shows on light and dark windows alike.
// A click-through, always-on-top, frameless window centred on the cursor (the clicking point). The hand is drawn shifted
// by `anchor` so that its thumb-index point sits on the cursor; the ring there is where a click lands.
// It only shows what controller.virtualHand says; it judges nothing.
Window {
    id: overlay
    required property var controller
    readonly property var hand: controller.virtualHand
    readonly property bool hasHand: hand && hand.pts !== undefined && hand.pts.length === 42
    readonly property int side: Math.max(340, Math.round((hasHand && hand.size > 0 ? hand.size : 110) * 3.0))   // logical px
    objectName: "virtualHandOverlay"
    width: side; height: side
    color: "transparent"
    flags: Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.WindowTransparentForInput
           | Qt.WindowDoesNotAcceptFocus | Qt.NoDropShadowWindowHint
    visible: hasHand && !fade.expired

    readonly property real glide: 0.04       // s: time constant of the glide (the source's value)
    property var shown: null                 // joints as drawn now (logical px around the palm)
    property var shownAnchor: [0, 0]
    property real shownX: 0                  // the cursor (window centre) as drawn now, logical px
    property real shownY: 0

    function target() {
        const h = controller.virtualHand
        if (!(h && h.pts !== undefined && h.pts.length === 42)) return null
        const k = h.scale > 0 ? h.scale : 1.0
        return {pts: h.pts, anchor: h.anchor || [0, 0], x: h.palm[0] / k, y: h.palm[1] / k, lost: h.lost}
    }
    function placeAt(px, py) { x = Math.round(px - width / 2); y = Math.round(py - height / 2) }

    // a lost hand stays faint where it was for 0.4 s (most losses come back within that time in the source's data)
    Timer { id: fade; property bool expired: false; interval: 400; onTriggered: { expired = true; overlay.shown = null } }
    onHandChanged: {
        const t = target()
        if (t === null) { shown = null; fade.stop(); fade.expired = false; return }
        if (t.lost) { if (!fade.running && !fade.expired) fade.start() }
        else { fade.stop(); fade.expired = false }
        if (shown === null) {                  // first frame (or back after a loss): start where the hand is
            shown = t.pts.slice(); shownAnchor = t.anchor.slice(); shownX = t.x; shownY = t.y
            placeAt(shownX, shownY)
        }
        canvas.requestPaint()
    }
    FrameAnimation {
        running: overlay.visible && overlay.shown !== null
        onTriggered: {
            const t = overlay.target()
            if (t === null || overlay.shown === null) return
            const k = 1 - Math.exp(-Math.min(frameTime, 0.1) / overlay.glide)
            const pts = overlay.shown
            for (let i = 0; i < pts.length; i++) pts[i] += (t.pts[i] - pts[i]) * k
            const a = overlay.shownAnchor
            a[0] += (t.anchor[0] - a[0]) * k; a[1] += (t.anchor[1] - a[1]) * k
            overlay.shownX += (t.x - overlay.shownX) * k
            overlay.shownY += (t.y - overlay.shownY) * k
            overlay.placeAt(overlay.shownX, overlay.shownY)
            canvas.requestPaint()
        }
    }

    Canvas {
        id: canvas
        anchors.fill: parent
        opacity: overlay.hasHand && overlay.hand.lost ? .35 : 1.0
        readonly property var bones: [[0,1],[1,2],[2,3],[3,4],[0,5],[5,6],[6,7],[7,8],[5,9],[9,10],[10,11],[11,12],
                                      [9,13],[13,14],[14,15],[15,16],[13,17],[17,18],[18,19],[19,20],[0,17]]
        readonly property var tips: ({"index": 8, "middle": 12, "ring": 16, "pinky": 20})
        onPaint: {
            const ctx = getContext("2d")
            ctx.reset()
            const p = overlay.shown
            if (!overlay.hasHand || p === null) return
            const a = overlay.shownAnchor
            const cx = width / 2 - a[0], cy = height / 2 - a[1]          // the palm, so that the anchor lands on the cursor
            ctx.lineCap = "round"
            // a dark outline under a light line (fist: amber line): visible on light and dark windows alike
            for (let pass = 0; pass < 2; pass++) {
                ctx.strokeStyle = pass === 0 ? "rgba(17,35,49,0.55)" : (overlay.hand.grip ? "#F2B544" : "rgba(245,247,248,0.95)")
                ctx.lineWidth = pass === 0 ? 7 : 3.5
                ctx.beginPath()
                for (const b of bones) {
                    ctx.moveTo(cx + p[2 * b[0]], cy + p[2 * b[0] + 1])
                    ctx.lineTo(cx + p[2 * b[1]], cy + p[2 * b[1] + 1])
                }
                ctx.stroke()
            }
            ctx.fillStyle = "#46E5BD"
            for (let i = 0; i < 21; i++) {
                ctx.beginPath(); ctx.arc(cx + p[2 * i], cy + p[2 * i + 1], i % 4 === 0 && i > 0 ? 5 : 3.5, 0, 2 * Math.PI); ctx.fill()
            }
            // thumb -> finger lines of the pinch the hand is making (hand-mouse branch): near, pinched, action
            const colors = {"near": "#F2B544", "pinched": "#2FBF8F", "action": "#E5484D"}
            const guides = overlay.hand.guides || []
            for (const g of guides) {
                const tip = tips[g[0]]
                if (tip === undefined) continue
                ctx.strokeStyle = colors[g[1]] || "#F2B544"
                ctx.lineWidth = g[1] === "near" ? 3 : 5
                ctx.beginPath(); ctx.moveTo(cx + p[8], cy + p[9]); ctx.lineTo(cx + p[2 * tip], cy + p[2 * tip + 1]); ctx.stroke()
            }
            const action = overlay.hand.action || ""
            if (!overlay.hand.grip) {                                    // the cursor: where a click lands
                ctx.beginPath(); ctx.arc(width / 2, height / 2, overlay.hand.aim ? 6 : 9, 0, 2 * Math.PI)
                ctx.strokeStyle = action !== "" ? "#E5484D" : (overlay.hand.aim ? "rgba(17,35,49,0.45)" : "#112331")
                ctx.lineWidth = overlay.hand.aim ? 2 : 3
                ctx.stroke()
            }
            if (action !== "") {                                         // the action's name next to it (0.8 s)
                ctx.font = "bold 16px 'Malgun Gothic'"
                ctx.lineWidth = 4; ctx.strokeStyle = "rgba(255,255,255,0.9)"
                ctx.strokeText(action, width / 2 + 14, height / 2 - 12)
                ctx.fillStyle = "#E5484D"
                ctx.fillText(action, width / 2 + 14, height / 2 - 12)
            }
        }
    }
}
