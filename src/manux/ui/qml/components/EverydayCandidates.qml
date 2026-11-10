import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../theme" as Theme

// "평소 사용 구간 고치기": short pieces of normal use the app saved (joints only). The person says what each was; only
// labelled pieces become training data, used by the normal retrain -> held-out check -> install flow.
Rectangle {
    id: box
    required property var controller
    property bool idle: true
    implicitHeight: col.implicitHeight + Theme.Studio.gap * 2
    color: Theme.Studio.paper; radius: Theme.Studio.radius; border.color: Theme.Studio.line
    component Copy: Label { color: Theme.Studio.ink; font.family: Theme.Studio.font; font.pixelSize: Theme.Studio.body; wrapMode: Text.Wrap }
    Component.onCompleted: controller.refreshEveryday()

    ColumnLayout {
        id: col
        anchors { left: parent.left; right: parent.right; top: parent.top; margins: Theme.Studio.gap }
        spacing: 6
        RowLayout {
            Layout.fillWidth: true
            Copy { text: "평소 사용 구간 고치기"; font.bold: true; font.pixelSize: Theme.Studio.body + 2; Layout.fillWidth: true }
            StudioCheck {
                objectName: "everydayCollect"
                text: "평소 사용 구간 저장"
                checked: box.controller.everydayCollect
                onClicked: box.controller.setEverydayCollect(checked)
            }
        }
        Copy {
            Layout.fillWidth: true; color: Theme.Studio.muted; font.pixelSize: Theme.Studio.small
            text: "켜 두면 제어 중 손이 뭔가 한 짧은 구간을 손 관절 좌표로만 저장합니다(영상 없음). 아래에서 실제로 하려던 동작을 고르면 학습 데이터가 되고, 고르지 않은 구간은 학습에 쓰지 않습니다. 오작동 구간에 정답을 달아 두면 다음 학습에 반영됩니다."
        }
        RowLayout {
            Copy { text: "검토할 구간 " + box.controller.everydayCandidates.length + "개"; Layout.fillWidth: true }
            StudioButton { text: "새로고침"; onClicked: box.controller.refreshEveryday() }
        }
        Repeater {
            model: box.controller.everydayCandidates
            delegate: RowLayout {
                id: row
                required property var modelData
                Layout.fillWidth: true
                Copy {
                    Layout.preferredWidth: 190
                    text: modelData.created.slice(5, 16) + " · " + Number(modelData.seconds).toFixed(1) + "초 · 규칙: " + modelData.action_text
                    font.pixelSize: Theme.Studio.small
                }
                StudioSelect { id: pick; Layout.fillWidth: true; model: box.controller.everydayChoiceLabels }
                StudioButton { text: "저장"; primary: true; enabled: box.idle; onClicked: box.controller.labelEveryday(row.modelData.path, pick.currentIndex) }
                StudioButton { text: "버리기"; enabled: box.idle; onClicked: box.controller.discardEveryday(row.modelData.path) }
            }
        }
        Copy {
            Layout.fillWidth: true; visible: box.controller.everydayNote !== ""
            text: box.controller.everydayNote; font.pixelSize: Theme.Studio.small; color: Theme.Studio.mintDark
        }
    }
}
