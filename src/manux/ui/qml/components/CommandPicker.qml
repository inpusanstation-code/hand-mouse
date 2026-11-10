import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../theme" as Theme

// A command dropdown with a search box at the top of its list (2026-11-10: "옵션이 너무 많아서 찾기가 힘들다").
// `presets` = [{label, action, keys}]; `currentIndex` / `activated(index)` use indexes into the FULL list, like
// a ComboBox, so callers do not care about the filter. Typing narrows the list by label or key text
// (spaces separate words that must all match); Enter picks the first match. It judges nothing.
Item {
    id: picker
    property var presets: []
    property int currentIndex: 0
    signal activated(int index)
    property alias hovered: field.hovered
    implicitHeight: 42
    implicitWidth: 220
    activeFocusOnTab: true

    function matches(p, words) {
        const text = (p.label + " " + (p.keys || "")).toLowerCase()
        for (const w of words) if (text.indexOf(w) < 0) return false
        return true
    }
    function filtered() {
        const words = search.text.trim().toLowerCase().split(/\s+/).filter(function (w) { return w.length > 0 })
        const out = []
        for (let i = 0; i < picker.presets.length; i++)
            if (words.length === 0 || matches(picker.presets[i], words)) out.push(i)
        return out
    }
    function choose(index) {
        popup.close()
        if (index >= 0 && index < picker.presets.length) picker.activated(index)
    }

    Button {
        id: field
        anchors.fill: parent
        leftPadding: 12; rightPadding: 32
        font.family: Theme.Studio.font; font.pixelSize: 13
        onClicked: popup.opened ? popup.close() : popup.open()
        contentItem: Text {
            text: picker.currentIndex >= 0 && picker.currentIndex < picker.presets.length ? picker.presets[picker.currentIndex].label : ""
            color: Theme.Studio.ink; font: field.font; verticalAlignment: Text.AlignVCenter; elide: Text.ElideRight
        }
        background: Rectangle {
            radius: 10; color: Theme.Studio.paper
            border.width: field.activeFocus || popup.opened ? 2 : 1
            border.color: field.activeFocus || popup.opened ? Theme.Studio.mintDark : Theme.Studio.line
            Item {
                width: 10; height: 10; x: parent.width - width - 12; y: (parent.height - height) / 2
                Rectangle { x: 1; y: 3; width: 6; height: 2; rotation: 45; color: Theme.Studio.muted }
                Rectangle { x: 5; y: 3; width: 6; height: 2; rotation: -45; color: Theme.Studio.muted }
            }
        }
    }

    Popup {
        id: popup
        objectName: "commandPickerPopup"
        y: picker.height + 5
        width: Math.max(picker.width, 260)
        padding: 6
        onOpened: { search.text = ""; list.currentIndex = -1; search.forceActiveFocus() }
        background: Rectangle { radius: 12; color: Theme.Studio.paper; border.color: Theme.Studio.line }
        contentItem: ColumnLayout {
            spacing: 4
            StudioField {
                id: search
                objectName: "commandPickerSearch"
                Layout.fillWidth: true
                placeholderText: "명령 검색 (예: 복사, 캡처, win+e)"
                Keys.onDownPressed: { list.forceActiveFocus(); list.currentIndex = 0 }
                onAccepted: { const f = list.model; if (f.length > 0) picker.choose(f[0]) }
                Keys.onEscapePressed: popup.close()
            }
            Label {
                visible: list.count === 0
                text: "맞는 명령이 없습니다. 맨 아래 ‘직접 입력’으로 키 조합을 넣을 수 있습니다."
                wrapMode: Text.Wrap; Layout.fillWidth: true
                color: Theme.Studio.muted; font.family: Theme.Studio.font; font.pixelSize: Theme.Studio.small
            }
            ListView {
                id: list
                objectName: "commandPickerList"
                Layout.fillWidth: true
                Layout.preferredHeight: Math.min(contentHeight, 260)
                clip: true
                model: popup.opened ? picker.filtered() : []
                ScrollIndicator.vertical: ScrollIndicator {}
                Keys.onReturnPressed: if (currentIndex >= 0) picker.choose(model[currentIndex])
                Keys.onEscapePressed: popup.close()
                delegate: ItemDelegate {
                    required property var modelData
                    required property int index
                    width: ListView.view.width
                    implicitHeight: 38
                    highlighted: ListView.isCurrentItem
                    onClicked: picker.choose(modelData)
                    contentItem: Text {
                        text: picker.presets[modelData].label; color: Theme.Studio.ink
                        font.family: Theme.Studio.font; font.pixelSize: 13
                        verticalAlignment: Text.AlignVCenter; elide: Text.ElideRight
                    }
                    background: Rectangle {
                        radius: 7
                        color: modelData === picker.currentIndex || parent.highlighted || parent.hovered ? Theme.Studio.mintWash : Theme.Studio.paper
                    }
                }
            }
        }
    }
    readonly property alias popupOpen: popup.opened
    function open() { popup.open() }
}
