import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Dialog {
    id: settings
    objectName: "studioSettings"
    required property var controller
    signal dataRequested()
    signal advancedRequested()
    property var settingRows: []
    readonly property var tabGroups: ["pinch", "cursor", "click"]   // one tab per function, then 표시 · 데이터
    property var draft: ({})
    property var edits: ({})
    function reload() {
        settingRows = controller.sensitivityRows
        let values = {}
        for (let row of settingRows) values[row.key] = row.value
        draft = values
        edits = {}
    }
    function changeValue(key, value) {
        let values = Object.assign({}, draft)
        let changes = Object.assign({}, edits)
        values[key] = value
        changes[key] = value
        draft = values
        edits = changes
    }
    anchors.centerIn: parent
    width: Math.min(660, parent.width - 48)
    height: Math.min(740, parent.height - 48)
    title: "설정"
    modal: true
    focus: true
    padding: 20
    background: Rectangle { color: "white"; radius: 14; border.color: "#DEE5EA" }
    onAboutToShow: reload()
    contentItem: ColumnLayout {
        spacing: 10
        TabBar {
            id: tabs
            objectName: "sensitivityTabs"
            Layout.fillWidth: true
            TabButton { text: "스크롤 · 창 전환"; objectName: "pinchSensitivityTab" }
            TabButton { text: "커서"; objectName: "cursorSensitivityTab" }
            TabButton { text: "클릭 · 드래그"; objectName: "clickSensitivityTab" }
            TabButton { text: "표시 · 데이터" }
        }
        Label {
            Layout.fillWidth: true
            visible: tabs.currentIndex < 3
            text: ["엄지·검지로 잡아 스크롤하는 핀치와 엄지·새끼 창 전환의 감도입니다. 수치를 직접 입력할 수도 있습니다.",
                   "느린 이동과 빠른 이동 감도를 따로 조절합니다. 주먹 판정은 손바닥 모드에 적용됩니다.",
                   "좌클릭(엄지·중지)·우클릭(엄지·약지)의 감도와 드래그를 시작하는 방식입니다."][tabs.currentIndex]
            wrapMode: Text.Wrap
            color: "#526575"
        }
        ScrollView {
            id: scroll
            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true
            contentWidth: availableWidth
            ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
            ColumnLayout {
                width: scroll.availableWidth
                spacing: 12
                Repeater {
                    model: settings.settingRows
                    delegate: ColumnLayout {
                        required property var modelData
                        Layout.fillWidth: true
                        visible: modelData.group === settings.tabGroups[tabs.currentIndex]
                        spacing: 2
                        Label { text: modelData.label; font.bold: true; color: "#112331" }
                        ComboBox {
                            objectName: "sensitivity-choice-" + modelData.key
                            Layout.fillWidth: true
                            visible: modelData.kind === "choice"
                            enabled: modelData.editable && !settings.controller.sensitivityPending
                            model: modelData.choiceLabels
                            currentIndex: modelData.choices.indexOf(settings.draft[modelData.key] ?? modelData.value)
                            onActivated: settings.changeValue(modelData.key, modelData.choices[currentIndex])
                        }
                        RowLayout {
                            Layout.fillWidth: true
                            visible: modelData.kind !== "choice"
                            Slider {
                                objectName: "sensitivity-slider-" + modelData.key
                                Layout.fillWidth: true
                                from: modelData.minimum; to: modelData.maximum; stepSize: modelData.step
                                value: modelData.kind === "choice" ? 0 : (settings.draft[modelData.key] ?? modelData.value)
                                enabled: modelData.editable && !settings.controller.sensitivityPending
                                onMoved: settings.changeValue(modelData.key, Number(value.toFixed(6)))
                            }
                            TextField {
                                objectName: "sensitivity-value-" + modelData.key
                                Layout.preferredWidth: 86
                                horizontalAlignment: TextInput.AlignRight
                                text: String(settings.draft[modelData.key] ?? modelData.value)
                                enabled: modelData.editable && !settings.controller.sensitivityPending
                                inputMethodHints: Qt.ImhFormattedNumbersOnly
                                selectByMouse: true
                                onTextEdited: settings.changeValue(modelData.key, text.trim() ? Number(text) : NaN)
                            }
                        }
                        Label {
                            text: modelData.editable ? modelData.hint : "현재 프로필이 지정한 값입니다. 기본 프로필에서 변경하세요."
                            Layout.fillWidth: true; wrapMode: Text.Wrap; color: "#526575"; font.pixelSize: 12
                        }
                    }
                }
                ColumnLayout {
                    Layout.fillWidth: true
                    visible: tabs.currentIndex === 1 && !settings.controller.pointerOnly
                    spacing: 4
                    Label { text: "커서 보정"; font.bold: true; color: "#112331" }
                    RowLayout {
                        Layout.fillWidth: true
                        Button {
                            objectName: "settingsPalmCalibration"
                            Layout.fillWidth: true
                            enabled: !settings.controller.palmCalibrating && !settings.controller.trackingActive
                            text: settings.controller.palmCalibrated ? "커서 방향 보정 다시" : "커서 방향 보정"
                            onClicked: { settings.close(); settings.controller.beginPalmCalibration() }
                            ToolTip.visible: hovered; ToolTip.delay: 400
                            ToolTip.text: "손을 위·아래·왼쪽·오른쪽으로 움직여 카메라 각도를 잽니다. 손을 곧게 움직여도 커서가 비스듬히 가는 문제를 바로잡습니다."
                        }
                        Button {
                            visible: settings.controller.palmCalibrated && !settings.controller.palmCalibrating
                            text: "초기화"
                            onClicked: settings.controller.resetPalmCalibration()
                            ToolTip.visible: hovered; ToolTip.delay: 400; ToolTip.text: "방향 보정을 지우고 보정 전 방향으로 돌아갑니다."
                        }
                    }
                    Button {
                        objectName: "settingsPointerSetup"
                        Layout.fillWidth: true
                        visible: settings.controller.pointerSetupAvailable
                        enabled: settings.controller.recMode === "off" && !settings.controller.trackingActive
                        text: "커서 자동 설정"
                        onClicked: { settings.close(); settings.controller.beginPointerSetup() }
                        ToolTip.visible: hovered; ToolTip.delay: 400
                        ToolTip.text: "화면 몇 곳을 손으로 가리키며 내 자세에 맞는 커서 범위·속도를 자동으로 맞춥니다. 자리나 카메라를 바꿨을 때 쓰세요."
                    }
                    Label {
                        Layout.fillWidth: true; wrapMode: Text.Wrap; color: "#526575"; font.pixelSize: 12
                        text: "자리·카메라를 바꿨거나 커서가 비스듬히·좁게 움직일 때 쓰세요. 누르면 설정 창이 닫히고 안내가 시작됩니다."
                    }
                }
                ColumnLayout {
                    Layout.fillWidth: true
                    visible: tabs.currentIndex === 1
                    Label { text: "검지 포인터 추가 감도 · " + settings.controller.pointerSensitivity + "%"; color: "#112331" }
                    Slider {
                        Layout.fillWidth: true
                        from: 50; to: 150; stepSize: 5
                        value: settings.controller.pointerSensitivity
                        onMoved: settings.controller.setPointerSensitivity(Math.round(value))
                    }
                }
                ColumnLayout {
                    Layout.fillWidth: true
                    visible: tabs.currentIndex === 3
                    CheckBox {
                        text: "커서 옆 손가락 표시"
                        checked: settings.controller.fingerOverlay
                        onClicked: settings.controller.setFingerOverlay(checked)
                    }
                    CheckBox {
                        text: "화면 구석 상태 표시"
                        checked: settings.controller.overlayVisible
                        onClicked: settings.controller.setOverlayVisible(checked)
                    }
                    CheckBox {
                        objectName: "closeToTray"
                        visible: settings.controller.trayAvailable
                        text: "창 닫기(X)를 누르면 트레이로 숨기기 (끄면 완전히 종료)"
                        checked: settings.controller.closeToTray
                        onClicked: settings.controller.setCloseToTray(checked)
                    }
                    Button {
                        text: "데이터 관리 · 녹화 별명 · train / eval"
                        Layout.fillWidth: true
                        onClicked: settings.dataRequested()
                    }
                    Label {
                        text: "이전 작업 가져오기와 별도 평가 검증도 데이터 관리에서 실행합니다."
                        wrapMode: Text.Wrap; Layout.fillWidth: true; color: "#526575"
                    }
                }
            }
        }
        Label {
            text: settings.controller.sensitivityStatus || "변경한 민감도는 ‘적용’을 누르면 저장됩니다. 적용 후 제어를 다시 시작하세요."
            wrapMode: Text.Wrap; Layout.fillWidth: true; color: "#526575"; font.pixelSize: 12
        }
        RowLayout {
            Layout.fillWidth: true
            Button {
                text: "현재 탭 기본값"
                visible: tabs.currentIndex < 3
                enabled: !settings.controller.sensitivityPending
                onClicked: {
                    let group = settings.tabGroups[tabs.currentIndex]
                    for (let row of settings.settingRows)
                        if (row.group === group && row.editable) settings.changeValue(row.key, row.defaultValue)
                }
            }
            Item { Layout.fillWidth: true }
            Button {
                text: "적용"
                objectName: "applySensitivity"
                enabled: Object.keys(settings.edits).length > 0 && !settings.controller.sensitivityPending
                onClicked: settings.controller.applySensitivity(settings.edits)
            }
            Button { text: "고급 설정"; onClicked: { settings.close(); settings.advancedRequested() } }
            Button { text: "닫기"; onClicked: settings.close() }
        }
    }
    Connections {
        target: settings.controller
        function onSensitivityApplied() { settings.reload() }
    }
    onClosed: controller.persistPointerSettings()
}
