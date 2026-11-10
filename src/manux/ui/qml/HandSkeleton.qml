import QtQuick
import QtQuick.Controls
import "theme" as Theme

Item {
    id: root
    objectName: "liveHandSkeleton"
    required property var bridge
    property real imageWidth: width
    property real imageHeight: height
    readonly property var points: bridge.previewLandmarks
    Canvas {
        id: canvas
        objectName: "liveHandSkeletonCanvas"
        anchors.centerIn: parent
        width: root.imageWidth
        height: root.imageHeight
        onWidthChanged: requestPaint()
        onHeightChanged: requestPaint()
        onAvailableChanged: if (available) requestPaint()
        Connections { target: root.bridge; function onPreviewChanged() { canvas.requestPaint() } }
        onPaint: {
            if (!available) return
            let c = getContext("2d"); c.reset()
            c.save(); c.beginPath(); c.rect(0, 0, width, height); c.clip()
            // Body/head skeleton (tracking.body_assist): drawn only; the runtime decides where to search.
            let b = root.bridge.previewBody || []
            if (b.length === 33) {
                let bones = [[8,6],[6,5],[5,4],[4,0],[0,1],[1,2],[2,3],[3,7],[10,9],
                             [11,12],[11,13],[13,15],[12,14],[14,16],[15,17],[15,19],[15,21],[16,18],[16,20],[16,22],
                             [11,23],[12,24],[23,24],[23,25],[25,27],[24,26],[26,28]]
                c.strokeStyle = Theme.Studio.amber; c.lineWidth = 2; c.lineCap = "round"; c.globalAlpha = 0.8
                for (let e of bones) {
                    let a = b[e[0]], z = b[e[1]]
                    if (a[2] < 0.5 || z[2] < 0.5) continue
                    c.beginPath(); c.moveTo(a[0]*width, a[1]*height); c.lineTo(z[0]*width, z[1]*height); c.stroke()
                }
                c.fillStyle = Theme.Studio.amber
                for (let k = 0; k < 29; k++) {
                    let v = b[k]
                    if (v[2] >= 0.5) { c.beginPath(); c.arc(v[0]*width, v[1]*height, k < 11 ? 2 : 3, 0, Math.PI*2); c.fill() }
                }
                c.globalAlpha = 1
            }
            let r = root.bridge.previewBodyRoi || []
            if (r.length === 4) {
                c.strokeStyle = Theme.Studio.amber; c.lineWidth = 1.5
                c.setLineDash ? c.setLineDash([6, 4]) : null
                c.strokeRect(r[0]*width, r[1]*height, (r[2]-r[0])*width, (r[3]-r[1])*height)
                c.setLineDash ? c.setLineDash([]) : null
            }
            let p = root.points
            if (!p || p.length !== 21) { c.restore(); return }
            let chains = [[0,1,2,3,4],[0,5,6,7,8],[0,9,10,11,12],[0,13,14,15,16],[0,17,18,19,20],[5,9,13,17]]
            c.strokeStyle = Theme.Studio.mint; c.lineWidth = 2; c.lineCap = "round"
            for (let chain of chains) {
                c.beginPath()
                for (let k=0; k<chain.length; k++) {
                    let v=p[chain[k]]
                    if (k===0) c.moveTo(v[0]*width,v[1]*height); else c.lineTo(v[0]*width,v[1]*height)
                }
                c.stroke()
            }
            c.fillStyle = Theme.Studio.stageText
            for (let v of p) { c.beginPath(); c.arc(v[0]*width,v[1]*height,3,0,Math.PI*2); c.fill() }
            // Engine-provided pinch proximity and palm anchor; drawing never changes intent.
            for (let g of root.bridge.previewGuides) {
                let a=p[4], b=p[g[0]]
                c.strokeStyle = g[1] === "near" ? Theme.Studio.amber : Theme.Studio.mint
                c.beginPath(); c.moveTo(a[0]*width,a[1]*height); c.lineTo(b[0]*width,b[1]*height); c.stroke()
            }
            let anchor = root.bridge.previewAnchor
            if (anchor.length === 2) {
                c.strokeStyle = root.bridge.previewMoving ? Theme.Studio.mint : Theme.Studio.amber
                c.beginPath(); c.arc(anchor[0]*width,anchor[1]*height,10,0,Math.PI*2); c.stroke()
            }
            c.restore()
        }
    }
    Label {
        anchors { left: parent.left; top: parent.top; margins: Theme.Studio.gap }
        text: root.bridge.previewHandLabel + " · " + root.bridge.previewMode + " · " + root.bridge.previewGesture
        color: Theme.Studio.stageText
        font.family: Theme.Studio.font
        font.pixelSize: Theme.Studio.small
        background: Rectangle { color: Theme.Studio.stage; radius: 3; opacity: 0.85 }
    }
}
