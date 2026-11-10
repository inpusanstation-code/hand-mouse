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
        Copy { Layout.fillWidth: true; text: "새 동작 바로 등록"; font.bold: true; font.pixelSize: Theme.Studio.body + 2 }
        Copy {
            Layout.fillWidth: true; color: Theme.Studio.muted; font.pixelSize: Theme.Studio.small
            text: "새 손 모양을 5번 보여 주면 바로 쓸 수 있습니다(학습 없음). 그다음 실행할 명령이나 키를 고르세요. 쓸 자세 그대로 보여 주세요. 등록하는 동안 마우스는 움직이지 않습니다."
        }

        // ---- 1. name and start
        ColumnLayout {                                       // stacked: fits the narrow side column of the main page
            Layout.fillWidth: true; visible: !box.running && !box.reviewing; spacing: 4
            StudioField { id: poseName; objectName: "customPoseName"; Layout.fillWidth: true; placeholderText: "동작 이름 (예: 락 사인)"; maximumLength: 30 }
            StudioButton {
                Layout.fillWidth: true
                objectName: "customPoseStart"; text: "새 동작 등록 시작"; primary: true
                ToolTip.visible: hovered; ToolTip.delay: 500
                ToolTip.text: "준비 1.5초 → 자세 2초 → 쉬기 1초를 5번 반복합니다. 끝나면 얼마나 잘 알아보는지 보여 주고, 저장하면 바로 쓸 수 있습니다. 그동안 마우스는 움직이지 않습니다."
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
                Layout.fillWidth: true
                StudioButton { objectName: "customPoseApprove"; Layout.fillWidth: true; text: "저장"; primary: true; onClicked: box.controller.approveCustomPose() }
                StudioButton { text: "버리기"; onClicked: box.controller.cancelCustomPose() }
            }
        }

        Copy {
            Layout.fillWidth: true; visible: box.controller.customPoseMessage !== ""
            text: box.controller.customPoseMessage; font.pixelSize: Theme.Studio.small; color: Theme.Studio.muted
        }

        // ---- 4. registered gestures and their commands
        // ---- registered gestures and what each one runs: a command from the list, or a key combination typed in
        Repeater {
            model: box.controller.customPoses
            delegate: ColumnLayout {
                id: poseRow
                required property var modelData
                readonly property var presets: box.controller.customPosePresets
                readonly property int customIndex: presets.length - 1                 // "직접 입력…"
                function presetIndex() {
                    for (let i = 0; i < presets.length - 1; i++)
                        if (presets[i].action === modelData.action && presets[i].keys === modelData.keys) return i
                    return modelData.action === "keys.press" ? customIndex : 0
                }
                property bool typing: false
                Layout.fillWidth: true
                spacing: 4
                Rectangle { Layout.fillWidth: true; height: 1; color: Theme.Studio.line }
                RowLayout {
                    Layout.fillWidth: true
                    Copy { text: poseRow.modelData.name; font.bold: true; Layout.fillWidth: true; elide: Text.ElideRight }
                    Copy {
                        visible: poseRow.modelData.keys_label !== ""
                        text: poseRow.modelData.keys_label; color: Theme.Studio.mintDark; font.pixelSize: Theme.Studio.small
                    }
                    StudioButton { text: "삭제"; enabled: box.idle && !box.running; onClicked: box.controller.removeCustomPose(poseRow.modelData.slot) }
                }
                StudioSelect {
                    objectName: "customPoseAction-" + poseRow.modelData.slot
                    Layout.fillWidth: true
                    ToolTip.visible: hovered; ToolTip.delay: 500
                    ToolTip.text: "이 손 모양을 취하면 실행할 명령이나 단축키입니다. 목록에 없으면 맨 아래 ‘직접 입력’으로 아무 키 조합이나 넣을 수 있습니다."
                    model: poseRow.presets.map(function (p) { return p.label })
                    currentIndex: poseRow.typing ? poseRow.customIndex : poseRow.presetIndex()
                    onActivated: function (index) {
                        const p = poseRow.presets[index]
                        if (p.keys === "*") { poseRow.typing = true; keysField.text = poseRow.modelData.keys; keysField.forceActiveFocus(); return }
                        poseRow.typing = false
                        box.controller.setCustomPoseAction(poseRow.modelData.slot, p.action, p.keys)
                    }
                }
                RowLayout {
                    Layout.fillWidth: true
                    visible: poseRow.typing || poseRow.presetIndex() === poseRow.customIndex
                    StudioField {
                        id: keysField
                        objectName: "customPoseKeys-" + poseRow.modelData.slot
                        Layout.fillWidth: true
                        text: poseRow.modelData.keys
                        placeholderText: "키 조합 · 예: ctrl+shift+n, win+e, alt+tab, f5"
                        ToolTip.visible: hovered; ToolTip.delay: 500
                        ToolTip.text: "키 이름을 +로 이어 쓰세요. 예: ctrl+c, win+shift+s, alt+tab, f5, playpause, 한영. Enter로 적용합니다."
                        onAccepted: applyKeys.clicked()
                    }
                    StudioButton {
                        id: applyKeys
                        text: "적용"; primary: true; enabled: keysField.text.trim() !== ""
                        onClicked: { poseRow.typing = false; box.controller.setCustomPoseAction(poseRow.modelData.slot, "keys.press", keysField.text) }
                    }
                }
            }
        }
        Copy {
            Layout.fillWidth: true; visible: box.controller.customPoses.length > 0
            font.pixelSize: Theme.Studio.small; color: Theme.Studio.muted
            text: "Win 키도 쓸 수 있습니다(예: win+e). Alt+F4·Ctrl+W·Win+L·Delete처럼 창·세션을 닫거나 지우는 키와 긴급 정지 키 Pause는 연결할 수 없습니다."
        }
    }
}
