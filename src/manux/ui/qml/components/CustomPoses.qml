import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../theme" as Theme

// "내 동작 바로 등록": a few demonstrations make a new gesture at once (perception/pose_memory.py). The person picks
// the command in the review step and nothing is registered until 저장 (2026-11-10 request). What is registered is
// listed in its own window ("등록된 동작 보기"). The bridge does no judging; it shows controller.customPose* and
// sends requests.
Rectangle {
    id: box
    required property var controller
    property bool idle: true
    readonly property var session: controller.customPoseSession
    readonly property bool running: session && ["rest", "prep", "do", "training"].indexOf(session.state) >= 0
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
            text: "쉬는 손을 5초 보여 준 다음, 새 손 모양을 1.5초씩 3번 보여 주면 몇 초 안에 학습합니다. 실행할 명령이나 키를 고르고 ‘저장’을 누르면 바로 쓸 수 있습니다. 등록하는 동안 마우스는 움직이지 않습니다."
        }
        Copy {                                               // 2026-11-10: what makes a demonstration count
            objectName: "customPoseTips"
            Layout.fillWidth: true; visible: !box.running && !box.reviewing
            font.pixelSize: Theme.Studio.small; color: Theme.Studio.ink
            text: "잘 잡히게 하려면\n① 손을 카메라 가운데에, 손 전체가 보이게\n② ‘쉬는 손’ 5초: 평소처럼 손을 움직이세요(펴기, 살짝 쥐기, 흔들기). 새 동작이 아닌 손을 배웁니다\n③ ‘지금’이 뜨면 새 손 모양을 그대로 유지 (3번)\n④ 평소에 잘 안 하는 뚜렷한 모양일수록 좋습니다(예: 락 사인, 엄지 척)"
        }

        // ---- 1. name and start
        ColumnLayout {                                       // stacked: fits the narrow side column of the main page
            Layout.fillWidth: true; visible: !box.running && !box.reviewing; spacing: 4
            StudioField { id: poseName; objectName: "customPoseName"; Layout.fillWidth: true; placeholderText: "동작 이름 (예: 락 사인)"; maximumLength: 30 }
            StudioButton {
                Layout.fillWidth: true
                objectName: "customPoseStart"; text: "새 동작 등록 시작"; primary: true
                ToolTip.visible: hovered; ToolTip.delay: 500
                ToolTip.text: "쉬는 손 5초 → (준비 1.2초 → 자세 1.5초) x 3번 → 학습 몇 초. 끝나면 얼마나 잘 알아보는지와 예상 오작동을 보여 주고, 명령을 고르고 저장하면 바로 쓸 수 있습니다. 그동안 마우스는 움직이지 않습니다."
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
                text: !box.session ? "" : "‘" + box.session.name + "’ "
                      + (box.session.state === "rest" ? "쉬는 손 · 평소처럼 손을 움직이세요(펴기·살짝 쥐기·흔들기)"
                         : box.session.state === "training" ? "학습 중… 몇 초 걸립니다"
                         : box.session.demo + " / " + box.session.demos + " · "
                           + (box.session.state === "prep" ? "곧 ‘지금’ · 새 손 모양을 준비하세요" : "지금! 새 손 모양 그대로"))
                      + (box.session.state === "training" ? "" : " · " + Number(box.session.seconds).toFixed(1) + "초")
                color: box.session && box.session.state === "do" ? Theme.Studio.mintDark : Theme.Studio.ink
            }
            Copy {
                Layout.fillWidth: true; font.pixelSize: Theme.Studio.small; color: "#B54708"
                visible: box.session && !box.session.hand && box.session.state !== "training"
                text: "손이 보이지 않아 시간이 멈췄습니다. 카메라에 손을 보여 주세요."
            }
            StudioButton { text: "그만두기"; onClicked: box.controller.cancelCustomPose() }
        }

        // ---- 3. review: the person picks the command; nothing is registered until 저장
        ColumnLayout {
            id: review
            Layout.fillWidth: true; visible: box.reviewing; spacing: 4
            readonly property var presets: box.controller.customPosePresets
            property int choice: 0
            readonly property bool custom: choice === presets.length - 1
            onVisibleChanged: if (visible) { choice = 0; reviewKeys.text = "" }
            Copy {
                objectName: "customPoseReport"
                Layout.fillWidth: true
                text: !box.reviewing || !box.session.report ? "" :
                      box.session.report.demos + "번 중 " + box.session.report.recognised + "번을 나머지만으로 학습해도 알아봤습니다. "
                      + (box.session.report.fires_per_min === null || box.session.report.fires_per_min === undefined
                         ? "지난 녹화를 아직 읽는 중이라 이번 쉬는 손만으로 배웠습니다(오작동 예상치 없음). "
                         : "예상 오작동: 분당 " + Number(box.session.report.fires_per_min).toFixed(1) + "번 (지난 녹화 "
                           + Number(box.session.report.checked_minutes).toFixed(0) + "분 기준). ")
                      + (box.session.report.confused_with ? "이미 등록한 ‘" + box.session.report.confused_with + "’와 헷갈립니다. " : "")
                      + (box.session.report.reliable ? "쓸 만합니다."
                         : box.session.report.confused_with ? "그 동작과 더 다른 모양으로 다시 해 보세요."
                         : box.session.report.rest_fires ? "평소 손 모양과 너무 비슷합니다. 손가락을 더 접거나 펴서 더 뚜렷한 모양으로 다시 해 보세요."
                         : "‘지금’ 동안 손을 움직이지 말고, 세 번 모두 같은 모양으로 보여 주세요.")
                color: box.reviewing && box.session.report && box.session.report.reliable ? Theme.Studio.mintDark : "#B54708"
            }
            Copy { Layout.fillWidth: true; text: "실행할 명령"; font.pixelSize: Theme.Studio.small; color: Theme.Studio.muted }
            CommandPicker {
                objectName: "customPoseReviewAction"
                Layout.fillWidth: true
                presets: review.presets
                currentIndex: review.choice
                onActivated: function (index) { review.choice = index; if (review.custom) reviewKeys.forceActiveFocus() }
            }
            StudioField {
                id: reviewKeys
                objectName: "customPoseReviewKeys"
                Layout.fillWidth: true; visible: review.custom
                placeholderText: "키 조합 · 예: ctrl+shift+n, win+e, alt+tab, f5"
            }
            // 2026-11-10: how long the pose must be held before it runs (a passing hand should not)
            RowLayout {
                Layout.fillWidth: true
                Copy { text: "유지 시간(초)"; font.pixelSize: Theme.Studio.small; color: Theme.Studio.muted }
                StudioField {
                    id: reviewHold
                    objectName: "customPoseReviewHold"
                    Layout.preferredWidth: 80
                    text: box.reviewing && box.session.report && box.session.report.hold !== undefined ? Number(box.session.report.hold).toFixed(1) : "0.4"
                    validator: DoubleValidator { bottom: 0.0; top: 3.0; decimals: 2; notation: DoubleValidator.StandardNotation }
                    inputMethodHints: Qt.ImhFormattedNumbersOnly
                }
                Copy {
                    Layout.fillWidth: true; font.pixelSize: Theme.Studio.small; color: Theme.Studio.muted
                    text: !box.reviewing || !box.session.report ? "" :
                          (box.session.report.fires_at_hold === null || box.session.report.fires_at_hold === undefined
                           ? "자동 " + Number(box.session.report.hold).toFixed(1) + "초 (기본값)"
                           : "자동 " + Number(box.session.report.hold).toFixed(1) + "초 · 스쳐 가는 손 분당 "
                             + Number(box.session.report.fires_at_hold).toFixed(1) + "번")
                }
            }
            Copy {
                Layout.fillWidth: true; font.pixelSize: Theme.Studio.small; color: Theme.Studio.muted
                text: "‘저장’을 눌러야 등록됩니다. 버리면 아무것도 남지 않습니다."
            }
            RowLayout {
                Layout.fillWidth: true
                StudioButton {
                    objectName: "customPoseApprove"; Layout.fillWidth: true; text: "저장"; primary: true
                    enabled: !review.custom || reviewKeys.text.trim() !== ""
                    onClicked: {
                        const p = review.presets[review.choice]
                        const hold = parseFloat(reviewHold.text)
                        box.controller.approveCustomPose(review.custom ? "keys.press" : p.action, review.custom ? reviewKeys.text : p.keys,
                                                         isNaN(hold) ? -1 : Math.min(3, Math.max(0, hold)))
                    }
                }
                StudioButton { text: "버리기"; onClicked: box.controller.cancelCustomPose() }
            }
        }

        Copy {
            Layout.fillWidth: true; visible: box.controller.customPoseMessage !== ""
            text: box.controller.customPoseMessage; font.pixelSize: Theme.Studio.small; color: Theme.Studio.muted
        }

        // ---- 4. what is registered: its own window, every registered gesture listed one under another
        StudioButton {
            objectName: "customPoseListOpen"
            Layout.fillWidth: true
            text: "등록된 동작 보기 (" + box.controller.customPoses.length + "개)"
            onClicked: registered.open()
        }
    }

    Popup {
        id: registered
        objectName: "customPoseList"
        parent: Overlay.overlay
        anchors.centerIn: parent
        width: Math.min(560, parent ? parent.width - 48 : 560)
        height: Math.min(listCol.implicitHeight + Theme.Studio.pad * 2, parent ? parent.height - 48 : 640)
        padding: Theme.Studio.pad; modal: true; focus: true
        background: Rectangle { color: Theme.Studio.paper; radius: Theme.Studio.radius; border.color: Theme.Studio.line }
        contentItem: Flickable {
            clip: true
            contentHeight: listCol.implicitHeight
            boundsBehavior: Flickable.StopAtBounds
            ScrollBar.vertical: ScrollBar {}
            ColumnLayout {
                id: listCol
                width: parent.width
                spacing: 6
                RowLayout {
                    Layout.fillWidth: true
                    Copy { Layout.fillWidth: true; text: "등록된 동작 " + box.controller.customPoses.length + "개"; font.bold: true; font.pixelSize: Theme.Studio.body + 2 }
                    StudioButton { objectName: "customPoseListClose"; text: "닫기"; onClicked: registered.close() }
                }
                Copy {
                    Layout.fillWidth: true; visible: box.controller.customPoses.length === 0
                    text: "아직 등록된 동작이 없습니다. 새 동작을 보여 주고 마지막에 ‘저장’을 누르면 여기에 나타납니다."
                    color: Theme.Studio.muted
                }
                Copy {
                    Layout.fillWidth: true; visible: box.controller.customPoseMessage !== ""
                    text: box.controller.customPoseMessage; font.pixelSize: Theme.Studio.small; color: Theme.Studio.muted
                }
                Repeater {
                    model: box.controller.customPoses
                    delegate: ColumnLayout {
                        id: poseRow
                        required property var modelData
                        required property int index
                        readonly property var presets: box.controller.customPosePresets
                        readonly property int customIndex: presets.length - 1                 // "직접 입력…"
                        function presetIndex() {
                            for (let i = 0; i < presets.length - 1; i++)
                                if (presets[i].action === modelData.action && presets[i].keys === modelData.keys) return i
                            return modelData.action === "keys.press" ? customIndex : 0
                        }
                        property int pending: -1                                               // picked, not saved yet
                        readonly property int shown: pending >= 0 ? pending : presetIndex()
                        readonly property bool custom: shown === customIndex
                        Layout.fillWidth: true
                        spacing: 4
                        Rectangle { Layout.fillWidth: true; height: 1; color: Theme.Studio.line }
                        RowLayout {
                            Layout.fillWidth: true
                            Copy { text: (poseRow.index + 1) + ". " + poseRow.modelData.name; font.bold: true; Layout.fillWidth: true; elide: Text.ElideRight }
                            Copy {
                                text: !poseRow.modelData.action ? "명령 없음"
                                      : poseRow.modelData.keys_label || poseRow.presets[poseRow.presetIndex()].label
                                color: poseRow.modelData.action ? Theme.Studio.mintDark : Theme.Studio.muted; font.pixelSize: Theme.Studio.small
                                Layout.maximumWidth: 220; elide: Text.ElideRight
                            }
                            StudioButton { text: "삭제"; enabled: box.idle && !box.running; onClicked: box.controller.removeCustomPose(poseRow.modelData.slot) }
                        }
                        RowLayout {                                   // how long it must be held before it runs
                            Layout.fillWidth: true
                            Copy { text: "유지 시간(초)"; font.pixelSize: Theme.Studio.small; color: Theme.Studio.muted }
                            StudioField {
                                id: holdField
                                objectName: "customPoseHold-" + poseRow.modelData.slot
                                Layout.preferredWidth: 80
                                text: Number(poseRow.modelData.hold).toFixed(2)
                                validator: DoubleValidator { bottom: 0.0; top: 3.0; decimals: 2; notation: DoubleValidator.StandardNotation }
                                inputMethodHints: Qt.ImhFormattedNumbersOnly
                                ToolTip.visible: hovered; ToolTip.delay: 500
                                ToolTip.text: "이 손 모양을 이만큼 유지해야 명령이 실행됩니다. 늘리면 스쳐 지나가는 손에 덜 반응하고, 줄이면 더 빨리 반응합니다. 소수점도 됩니다."
                                onAccepted: holdSave.clicked()
                            }
                            StudioButton {
                                id: holdSave
                                objectName: "customPoseHoldSave-" + poseRow.modelData.slot
                                text: "적용"
                                enabled: holdField.acceptableInput && Math.abs(parseFloat(holdField.text) - poseRow.modelData.hold) > 1e-6
                                onClicked: box.controller.setCustomPoseHold(poseRow.modelData.slot, parseFloat(holdField.text))
                            }
                            Item { Layout.fillWidth: true }
                        }
                        CommandPicker {
                            objectName: "customPoseAction-" + poseRow.modelData.slot
                            Layout.fillWidth: true
                            ToolTip.visible: hovered; ToolTip.delay: 500
                            ToolTip.text: "이 손 모양을 취하면 실행할 명령이나 단축키입니다. 검색해서 고르고 ‘저장’을 누르세요. 목록에 없으면 맨 아래 ‘직접 입력’으로 아무 키 조합이나 넣을 수 있습니다."
                            presets: poseRow.presets
                            currentIndex: poseRow.shown
                            onActivated: function (index) {
                                poseRow.pending = index === poseRow.presetIndex() && index !== poseRow.customIndex ? -1 : index
                                if (index === poseRow.customIndex) { keysField.text = poseRow.modelData.keys; keysField.forceActiveFocus() }
                            }
                        }
                        RowLayout {
                            Layout.fillWidth: true
                            visible: poseRow.custom || poseRow.pending >= 0
                            StudioField {
                                id: keysField
                                objectName: "customPoseKeys-" + poseRow.modelData.slot
                                Layout.fillWidth: true; visible: poseRow.custom
                                text: poseRow.modelData.keys
                                placeholderText: "키 조합 · 예: ctrl+shift+n, win+e, alt+tab, f5"
                                ToolTip.visible: hovered; ToolTip.delay: 500
                                ToolTip.text: "키 이름을 +로 이어 쓰세요. 예: ctrl+c, win+shift+s, alt+tab, f5, playpause, 한영. Enter로 저장합니다."
                                onAccepted: saveRow.clicked()
                                onTextEdited: if (poseRow.pending < 0) poseRow.pending = poseRow.customIndex
                            }
                            Item { Layout.fillWidth: true; visible: !poseRow.custom }
                            StudioButton {
                                id: saveRow
                                objectName: "customPoseSave-" + poseRow.modelData.slot
                                text: "저장"; primary: true
                                enabled: poseRow.pending >= 0 && (!poseRow.custom || keysField.text.trim() !== "")
                                onClicked: {
                                    const p = poseRow.presets[poseRow.shown]
                                    box.controller.setCustomPoseAction(poseRow.modelData.slot, poseRow.custom ? "keys.press" : p.action,
                                                                       poseRow.custom ? keysField.text : p.keys)
                                    poseRow.pending = -1
                                }
                            }
                            StudioButton {
                                text: "되돌리기"; visible: poseRow.pending >= 0
                                onClicked: { poseRow.pending = -1; keysField.text = poseRow.modelData.keys }
                            }
                        }
                    }
                }
                Copy {
                    Layout.fillWidth: true; visible: box.controller.customPoses.length > 0
                    font.pixelSize: Theme.Studio.small; color: Theme.Studio.muted
                    text: "명령을 바꾸면 그 줄의 ‘저장’을 눌러야 적용됩니다. Win 키도 쓸 수 있습니다(예: win+e). Alt+F4·Ctrl+W·Win+L·Delete처럼 창·세션을 닫거나 지우는 키와 긴급 정지 키 Pause는 연결할 수 없습니다."
                }
            }
        }
    }
}
