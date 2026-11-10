import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../theme" as Theme

// "내 동작 바로 등록": a few demonstrations make a new gesture at once (perception/pose_memory.py), then the person
// picks the command it runs. The bridge does no judging; it shows controller.customPose* and sends requests.
Rectangle {
    id: box
    required property var controller
    property bool idle: true
    readonly property var session: controller.customPoseSession
    readonly property bool running: session && ["prep", "do", "rest"].indexOf(session.state) >= 0
    readonly property bool reviewing: session && session.state === "review"
    implicitHeight: col.implicitHeight + Theme.Studio.gap * 2
    color: Theme.Studio.paper; radius: Theme.Studio.radius; border.color: Theme.Studio.line
    component Copy: Label { color: Theme.Studio.ink; font.family: Theme.Studio.font; font.pixelSize: Theme.Studio.body; wrapMode: Text.Wrap }

    ColumnLayout {
        id: col
        anchors { left: parent.left; right: parent.right; top: parent.top; margins: Theme.Studio.gap }
        spacing: 6
        Copy { text: "내 동작 바로 등록"; font.bold: true; font.pixelSize: Theme.Studio.body + 2 }
        Copy {
            Layout.fillWidth: true; color: Theme.Studio.muted; font.pixelSize: Theme.Studio.small
            text: "새 손 모양을 5번 보여 주면 바로 쓸 수 있습니다(학습 없음). 그다음 실행할 명령을 고르세요. 명령을 고르기 전에는 아무 일도 하지 않습니다. 쓸 자세 그대로 보여 주세요. 등록하는 동안 마우스는 움직이지 않습니다."
        }

        // ---- 1. name and start
        RowLayout {
            Layout.fillWidth: true; visible: !box.running && !box.reviewing
            StudioField { id: poseName; objectName: "customPoseName"; Layout.fillWidth: true; placeholderText: "동작 이름 (예: 락 사인)"; maximumLength: 30 }
            StudioButton {
                objectName: "customPoseStart"; text: "등록 시작"; primary: true
                enabled: box.idle && poseName.text.trim().length > 0 && box.controller.customPoses.length < 8
                onClicked: box.controller.startCustomPose(poseName.text)
            }
        }

        // ---- 2. demonstrating
        ColumnLayout {
            Layout.fillWidth: true; visible: box.running; spacing: 2
            Copy {
                objectName: "customPoseProgress"
                Layout.fillWidth: true; font.bold: true
                text: !box.session ? "" : "‘" + box.session.name + "’ " + box.session.demo + " / " + box.session.demos + " · "
                      + ({"prep": "준비하세요", "do": "지금 자세를 유지하세요", "rest": "손을 편하게 두세요"})[box.session.state]
                      + " · " + Number(box.session.seconds).toFixed(1) + "초"
                color: box.session && box.session.state === "do" ? Theme.Studio.mintDark : Theme.Studio.ink
            }
            Copy {
                Layout.fillWidth: true; font.pixelSize: Theme.Studio.small; color: "#B54708"
                visible: box.session && !box.session.hand
                text: "손이 보이지 않아 시간이 멈췄습니다. 카메라에 손을 보여 주세요."
            }
            StudioButton { text: "그만두기"; onClicked: box.controller.cancelCustomPose() }
        }

        // ---- 3. review: the person decides
        ColumnLayout {
            Layout.fillWidth: true; visible: box.reviewing; spacing: 4
            Copy {
                objectName: "customPoseReport"
                Layout.fillWidth: true
                text: !box.reviewing || !box.session.report ? "" :
                      "시연 " + box.session.report.demos + "번 중 " + box.session.report.recognised + "번을 다른 시연만으로 알아봤습니다. "
                      + (box.session.report.rest_fires ? "쉬는 자세에서도 잡혔습니다. " : "")
                      + (box.session.report.confused_with ? "‘" + box.session.report.confused_with + "’ 자세와 헷갈립니다. " : "")
                      + (box.session.report.reliable ? "쓸 만합니다." : "불안정합니다. 다른 모양으로 다시 해 보기를 권합니다.")
                color: box.reviewing && box.session.report && box.session.report.reliable ? Theme.Studio.mintDark : "#B54708"
            }
            RowLayout {
                StudioButton { objectName: "customPoseApprove"; text: "저장"; primary: true; onClicked: box.controller.approveCustomPose() }
                StudioButton { text: "버리기"; onClicked: box.controller.cancelCustomPose() }
            }
        }

        Copy {
            Layout.fillWidth: true; visible: box.controller.customPoseMessage !== ""
            text: box.controller.customPoseMessage; font.pixelSize: Theme.Studio.small; color: Theme.Studio.muted
        }

        // ---- 4. registered gestures and their commands
        Repeater {
            model: box.controller.customPoses
            delegate: RowLayout {
                required property var modelData
                Layout.fillWidth: true
                Copy { text: modelData.name; font.bold: true; Layout.preferredWidth: 120; elide: Text.ElideRight }
                StudioSelect {
                    objectName: "customPoseAction-" + modelData.slot
                    Layout.fillWidth: true
                    model: box.controller.customPoseCommandLabels
                    currentIndex: Math.max(0, box.controller.customPoseCommandIds.indexOf(modelData.action))
                    onActivated: box.controller.setCustomPoseAction(modelData.slot, box.controller.customPoseCommandIds[currentIndex])
                }
                StudioButton { text: "삭제"; enabled: box.idle && !box.running; onClicked: box.controller.removeCustomPose(modelData.slot) }
            }
        }
    }
}
