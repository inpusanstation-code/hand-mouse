import QtQuick
import QtQuick.Controls

// The virtual hand's box on the camera preview (from virtual-hand-20261110 `boxLayer`): its inside is the whole monitor.
// Shown in the virtual hand mode; while bridge.boxEditing, drag on the image to draw a new one. Placed inside the
// preview Image like HandSkeleton (imageWidth/imageHeight = the painted image).
Item {
    id: layer
    objectName: "virtualBoxLayer"
    required property var bridge
    property real imageWidth: width
    property real imageHeight: height
    visible: bridge.movementStyle === "virtual"

    Item {
        id: area
        anchors.centerIn: parent
        width: layer.imageWidth; height: layer.imageHeight
        property point start
        property point end
        property bool dragging: false
        readonly property var box: layer.bridge.virtualBox
        Rectangle {
            x: area.dragging ? Math.min(area.start.x, area.end.x) : area.box[0] * area.width
            y: area.dragging ? Math.min(area.start.y, area.end.y) : area.box[1] * area.height
            width: area.dragging ? Math.abs(area.end.x - area.start.x) : (area.box[2] - area.box[0]) * area.width
            height: area.dragging ? Math.abs(area.end.y - area.start.y) : (area.box[3] - area.box[1]) * area.height
            color: layer.bridge.boxEditing ? Qt.rgba(0.27, 0.9, 0.74, 0.12) : "transparent"
            border.color: "#46E5BD"; border.width: layer.bridge.boxEditing ? 3 : 2; radius: 4
        }
        Rectangle {
            visible: layer.bridge.boxEditing
            anchors { top: parent.top; horizontalCenter: parent.horizontalCenter; topMargin: 8 }
            width: Math.min(parent.width - 16, hint.implicitWidth + 24); height: hint.implicitHeight + 10
            radius: height / 2; color: Qt.rgba(0.06, 0.09, 0.16, 0.72)
            Text {
                id: hint
                anchors.centerIn: parent; width: parent.width - 24
                horizontalAlignment: Text.AlignHCenter; wrapMode: Text.Wrap
                text: "손을 움직일 영역을 끌어서 그리세요 · 이 영역이 모니터 전체가 됩니다"
                color: "#F5F7F8"; font.pixelSize: 13
            }
        }
        MouseArea {
            objectName: "virtualBoxDraw"
            anchors.fill: parent
            enabled: layer.bridge.boxEditing
            cursorShape: layer.bridge.boxEditing ? Qt.CrossCursor : Qt.ArrowCursor
            onPressed: function (mouse) { area.start = Qt.point(mouse.x, mouse.y); area.end = area.start; area.dragging = true }
            onPositionChanged: function (mouse) {
                area.end = Qt.point(Math.max(0, Math.min(area.width, mouse.x)), Math.max(0, Math.min(area.height, mouse.y)))
            }
            onReleased: {
                area.dragging = false
                layer.bridge.setVirtualBox(area.start.x / area.width, area.start.y / area.height,
                                           area.end.x / area.width, area.end.y / area.height)
            }
        }
    }
}
