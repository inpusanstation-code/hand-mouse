import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../theme" as Theme

// "평소 사용 구간 고치기": short pieces of normal use the app saved (joints only). The person says what each was; only
// labelled pieces become training data, used by the normal retrain -> held-out check -> install flow.
// Laid out top to bottom so it fits the narrow column of the 녹화 page (every line takes the full width).
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
        Copy { Layout.fillWidth: true; text: "평소 사용 구간 고치기"; font.bold: true; font.pixelSize: Theme.Studio.body + 1 }
        RowLayout {                                         // a bare check box + a label that wraps in a narrow column
            Layout.fillWidth: true
            spacing: 8
            StudioCheck {
                id: collect
                objectName: "everydayCollect"
                checked: box.controller.everydayCollect
                onClicked: box.controller.setEverydayCollect(checked)
                Accessible.name: collectLabel.text
            }
            Copy {
                id: collectLabel
                objectName: "everydayCollectLabel"
                Layout.fillWidth: true
                text: "제어 중 평소 사용 구간 저장"
                TapHandler { onTapped: box.controller.setEverydayCollect(!collect.checked) }
            }
        }
        Copy {
            Layout.fillWidth: true; color: Theme.Studio.muted; font.pixelSize: Theme.Studio.small
            text: "손이 뭔가 한 짧은 구간을 손 관절 좌표로만 저장합니다(영상 없음). 실제로 하려던 동작을 고른 구간만 학습에 씁니다."
        }
        RowLayout {
            Layout.fillWidth: true
            Copy { Layout.fillWidth: true; text: "검토할 구간 " + box.controller.everydayCandidates.length + "개"; font.pixelSize: Theme.Studio.small }
            StudioButton { text: "새로고침"; onClicked: box.controller.refreshEveryday() }
        }
        Repeater {
            model: box.controller.everydayCandidates
            delegate: ColumnLayout {
                id: row
                required property var modelData
                Layout.fillWidth: true
                spacing: 4
                Rectangle { Layout.fillWidth: true; height: 1; color: Theme.Studio.line }
                Copy {
                    Layout.fillWidth: true; font.pixelSize: Theme.Studio.small
                    text: modelData.created.slice(5, 16) + " · " + Number(modelData.seconds).toFixed(1) + "초 · 규칙이 한 일: " + modelData.action_text
                }
                StudioSelect { id: pick; Layout.fillWidth: true; model: box.controller.everydayChoiceLabels }
                RowLayout {
                    Layout.fillWidth: true
                    StudioButton { Layout.fillWidth: true; text: "이 동작으로 저장"; primary: true; enabled: box.idle; onClicked: box.controller.labelEveryday(row.modelData.path, pick.currentIndex) }
                    StudioButton { text: "버리기"; enabled: box.idle; onClicked: box.controller.discardEveryday(row.modelData.path) }
                }
            }
        }
        Copy {
            Layout.fillWidth: true; visible: box.controller.everydayNote !== ""
            text: box.controller.everydayNote; font.pixelSize: Theme.Studio.small; color: Theme.Studio.mintDark
        }
    }
}
