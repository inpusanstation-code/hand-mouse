import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "theme" as Theme

ColumnLayout {
    id: settings
    required property var controller
    property bool showDesktopSwitch: true
    property var speedRows: controller.sensitivityRows.filter(function(r) {
        return r.key === "cursor.relative_gain_min" || r.key === "cursor.relative_gain_max"
    })
    // Light palette on the controls themselves: the standard window sets none, so a dark Windows theme
    // would draw black handles and an unreadable check box (the studio window sets the same values).
    component LightPalette: Palette {
        window: "#FFFFFF"; windowText: "#112331"; base: "#F4F6F8"; text: "#112331"
        button: "#EDF3F5"; buttonText: "#112331"; highlight: "#46E5BD"; highlightedText: "#112331"
        mid: "#DEE5EA"; dark: "#526575"; light: "#FFFFFF"; midlight: "#F4F6F8"; shadow: "#526575"
    }
    spacing: Theme.Studio.gap / 2
    Repeater {
        model: settings.speedRows
        delegate: ColumnLayout {
            required property var modelData
            Layout.fillWidth: true; spacing: 0
            Label {
                Layout.fillWidth: true
                text: (modelData.key === "cursor.relative_gain_min" ? "기본 속도" : "빠른 이동 가속") + " · " + Number(modelData.value).toFixed(2)
                color: Theme.Studio.ink; font.pixelSize: Theme.Studio.small
            }
            Slider {
                objectName: "quickSpeed_" + modelData.key
                palette: LightPalette {}
                Layout.fillWidth: true
                from: modelData.minimum; to: modelData.maximum; stepSize: modelData.step
                value: modelData.value
                enabled: modelData.editable && !settings.controller.sensitivityPending
                id: speedSlider
                onMoved: saveDelay.restart()
                Timer {
                    id: saveDelay; interval: 350
                    onTriggered: {
                        let edits = {}; edits[modelData.key] = Number(speedSlider.value.toFixed(6))
                        settings.controller.applySensitivity(edits)
                    }
                }
                Accessible.name: modelData.label
            }
        }
    }
    // fist / open hand speed: which one is the fast one (settings/sensitivity.py PRESETS "preset.fist_style")
    property var fistRow: controller.sensitivityRows.filter(function(r) { return r.key === "preset.fist_style" })[0]
    Label {
        Layout.fillWidth: true; wrapMode: Text.Wrap
        text: "주먹 이동"
        color: Theme.Studio.ink; font.pixelSize: Theme.Studio.small
        visible: settings.fistRow !== undefined
    }
    RowLayout {
        Layout.fillWidth: true; spacing: 4
        visible: settings.fistRow !== undefined
        Repeater {
            model: settings.fistRow ? settings.fistRow.choices : []
            delegate: Button {
                required property string modelData
                required property int index
                objectName: "fistStyle_" + modelData
                Layout.fillWidth: true
                palette: LightPalette {}
                checkable: true
                checked: settings.fistRow.value === modelData
                text: modelData === "fast" ? "주먹 = 빠르게" : "주먹 = 정밀하게"
                enabled: settings.fistRow.editable && !settings.controller.sensitivityPending
                onClicked: {
                    checked = Qt.binding(function() { return settings.fistRow.value === modelData })
                    if (settings.fistRow.value !== modelData) settings.controller.applySensitivity({"preset.fist_style": modelData})
                }
                ToolTip.visible: hovered; ToolTip.text: settings.fistRow.choiceLabels[index]
            }
        }
    }
    Label {
        Layout.fillWidth: true; wrapMode: Text.Wrap
        text: settings.fistRow && settings.fistRow.value === "fast" ? "주먹은 빠르게 멀리 · 편 손은 세밀하게" : "편 손은 빠르게 · 주먹은 정밀하게"
        color: Theme.Studio.muted; font.pixelSize: Theme.Studio.small
    }
    CheckBox {
        visible: settings.showDesktopSwitch
        palette: LightPalette {}
        text: "바탕화면 보기 동작 사용"
        enabled: !settings.controller.advancedPending
        checked: settings.controller.showDesktopEnabled
        onClicked: settings.controller.setShowDesktopEnabled(checked)
    }
}
