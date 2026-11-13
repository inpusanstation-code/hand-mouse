import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "theme" as Theme

ApplicationWindow {
    id: window
    width: 1280
    height: 860
    minimumWidth: 960
    minimumHeight: 660
    visible: true
    title: dashboard.appTitle
    color: Theme.Studio.surface
    onClosing: function (close) {
        if (dashboard.hidesToTray) {
            close.accepted = false   // tray mode: keep running, quit from the tray menu
            dashboard.hideDashboard()
        } else {
            dashboard.requestClose()
        }
    }
    // design tokens from manux-merged-20261110 (src/theme/Studio.qml); the old names stay so every screen follows them
    readonly property color navy: Theme.Studio.ink
    readonly property color ink: Theme.Studio.ink
    readonly property color muted: Theme.Studio.muted
    readonly property color mint: Theme.Studio.mint
    readonly property color primaryBlue: Theme.Studio.mintDark
    readonly property color primaryBlueDark: "#0F5E4E"
    readonly property color dangerRed: Theme.Studio.danger
    readonly property color line: Theme.Studio.line
    font.family: Theme.Studio.font
    // one macro step (src/macro.py) in words, for the AI proposal cards and the AI connection list
    function stepText(st) {
        var names = {"key": "단축키", "type": "글자 입력", "wait": "기다리기", "open": "열기", "mouse": "마우스", "youtube": "유튜브 키"}
        if (st.do === "wait") return st.value + "초 기다리기"
        if (st.do === "type") return "'" + st.value + "' 입력"
        if (st.do === "open") return st.value + " 열기"
        return (names[st.do] || st.do) + " " + st.value
    }

    component TextLabel: Label {
        color: window.navy
        font.pixelSize: 14
    }
    // accent = 선택/활성화된 상태(연두/민트색 #46E5BD), primary = 주요 실행 버튼(진파랑 #1D4ED8), 기본 = 중립 실행 버튼
    component ActionButton: Button {
        id: button
        focusPolicy: Qt.NoFocus
        property bool accent: false
        property bool primary: false
        property bool danger: false
        implicitHeight: 40
        leftPadding: 14
        rightPadding: 14
        opacity: enabled ? 1 : 0.42
        contentItem: TextLabel {
            text: button.text
            font.pixelSize: Theme.Studio.body
            font.bold: true
            color: button.danger ? "#FFFFFF" : Theme.Studio.ink
            horizontalAlignment: Text.AlignHCenter
            verticalAlignment: Text.AlignVCenter
            elide: Text.ElideRight
        }
        // Studio button (manux StudioButton): primary = mint, accent = selected (mint wash, dark mint edge)
        background: Rectangle {
            radius: Theme.Studio.radius - 2
            color: button.danger ? (button.down ? "#7F2733" : Theme.Studio.danger)
                : button.down ? "#BCEFE1"
                : button.primary ? Theme.Studio.mint
                : button.accent ? Theme.Studio.mintWash
                : button.hovered ? Theme.Studio.mintWash : Theme.Studio.surface
            border.color: button.activeFocus || button.accent ? Theme.Studio.mintDark
                : (button.primary || button.danger) ? "transparent" : Theme.Studio.line
            border.width: (button.accent || button.activeFocus) ? 2 : 1
        }
    }
    component CompactButton: Button {
        id: cbutton
        focusPolicy: Qt.NoFocus
        property bool accent: false
        property bool primary: false
        property bool danger: false
        implicitHeight: 30
        leftPadding: 10
        rightPadding: 10
        opacity: enabled ? 1 : 0.42
        contentItem: TextLabel {
            text: cbutton.text
            font.pixelSize: 12
            font.bold: true
            color: cbutton.danger ? "#FFFFFF" : Theme.Studio.ink
            horizontalAlignment: Text.AlignHCenter
            verticalAlignment: Text.AlignVCenter
        }
        background: Rectangle {
            radius: 7
            color: cbutton.danger ? (cbutton.down ? "#7F2733" : Theme.Studio.danger)
                : cbutton.down ? "#BCEFE1"
                : cbutton.primary ? Theme.Studio.mint
                : cbutton.accent ? Theme.Studio.mintWash
                : cbutton.hovered ? Theme.Studio.mintWash : Theme.Studio.surface
            border.color: cbutton.activeFocus || cbutton.accent ? Theme.Studio.mintDark
                : (cbutton.primary || cbutton.danger) ? "transparent" : Theme.Studio.line
            border.width: cbutton.accent ? 2 : 1
        }
    }

    // [사례 보기] (2026-11-11): one taught gesture's collected uses (src/use_view.py), each replayed as the hand around the command
    Dialog {
        id: useCasesDialog
        objectName: "useCasesDialog"
        anchors.centerIn: parent
        width: Math.min(1100, window.width - 48)
        height: window.height - 80
        modal: true
        readonly property var cases: dashboard.useCases
        readonly property var items: cases.items || []
        property int current: 0
        property int frame: 0
        property bool playing: true
        readonly property var shown: items.length > 0 ? items[Math.min(current, items.length - 1)] : null
        // the review session before learning (src/use_review.py, 2026-11-11): each waiting use is passed or rejected here
        readonly property bool review: cases.review === true
        property int lastCount: -1
        function count(v) { var n = 0; for (var i = 0; i < items.length; i++) if ((items[i].review || "") === v) n++; return n }
        readonly property int nOk: count("ok")
        readonly property int nBad: count("bad")
        readonly property int nLeft: count("")
        // every use has a verdict (2026-11-12, "전부 다 하면 다했다는 메세지"): review = none left to look at;
        // the plain viewer = each row is passed, rejected or marked with F
        readonly property bool allDone: {
            if (cases.loading || items.length === 0) return false
            if (review) return nLeft === 0
            for (var i = 0; i < items.length; i++)
                if (!items[i].marked && items[i].review !== "ok" && items[i].review !== "bad") return false
            return true
        }
        function judge(v) {
            if (!review || shown === null) return
            var i = Math.min(current, items.length - 1)
            // a verdict hands the list a new model, which scrolls it back to the top (2026-11-11): keep where it was
            var y = caseList.contentY
            dashboard.judgeUseCase(i, v)
            var its = dashboard.useCases.items || []
            for (var k = 1; k <= its.length; k++) {            // on to the next one not looked at yet
                var j = (i + k) % its.length
                if (!its[j].review) { current = j; playing = true; break }
            }
            keepList(y)
        }
        // put the list back at y (when given) and scroll just enough that the row being played is on screen
        function keepList(y) {
            Qt.callLater(function () {
                caseList.forceLayout()
                if (y !== undefined) caseList.contentY = y
                if (items.length > 0) caseList.positionViewAtIndex(Math.min(current, items.length - 1), ListView.Contain)
            })
        }
        title: (review ? "오탐지 검토 · " : "모은 사용 사례 · ") + (cases.name || "")
        // (a verdict changes the rows but not the list: stay on the row)
        onItemsChanged: { if (!(cases.judged > 0 && items.length === lastCount)) { current = 0; frame = 0 } lastCount = items.length }
        onCurrentChanged: { frame = 0; keepList() }
        onClosed: if (review) dashboard.finishUseReview()
        Shortcut { sequence: "1"; enabled: useCasesDialog.visible && useCasesDialog.review; onActivated: useCasesDialog.judge("ok") }
        Shortcut { sequence: "2"; enabled: useCasesDialog.visible && useCasesDialog.review; onActivated: useCasesDialog.judge("bad") }
        footer: DialogButtonBox {
            onRejected: useCasesDialog.close()
            Button {
                objectName: "useCasesClose"
                text: "닫기"
                DialogButtonBox.buttonRole: DialogButtonBox.RejectRole
            }
        }
        Timer {
            interval: 1000 / 15
            repeat: true
            running: useCasesDialog.visible && useCasesDialog.playing && useCasesDialog.shown !== null
                     && (useCasesDialog.shown.frames || []).length > 1
            onTriggered: {
                var n = useCasesDialog.shown.frames.length
                useCasesDialog.frame = (useCasesDialog.frame + 1) % n
                caseCanvas.requestPaint()
            }
        }
        contentItem: ColumnLayout {
            spacing: 10
            TextLabel {
                Layout.fillWidth: true
                text: useCasesDialog.cases.loading ? "불러오는 중…"
                      : useCasesDialog.cases.error ? useCasesDialog.cases.error
                      : useCasesDialog.items.length === 0 ? "아직 모은 사례가 없어요. 이 동작을 쓰면 실행될 때마다 앞뒤 손 움직임이 저장돼요."
                      : useCasesDialog.cases.note ? useCasesDialog.cases.note
                      : useCasesDialog.review ? "학습 전에 하나씩 봐 주세요. 의도한 동작이면 [통과], 우연히 잘못 잡힌 것이면 [오탐지]. "
                        + "통과한 사례만 이 동작으로 학습하고, 오탐지는 '이 동작이 아님' 예시로 따로 배워요. 빨간 선이 명령이 실행된 순간이에요."
                      : "이 동작이 실행될 때마다 저장된 손 움직임이에요 (최근 " + useCasesDialog.items.length + "개). "
                        + "빨간 선이 명령이 실행된 순간이에요. F로 '원하지 않음'을 표시한 사례는 '아님'으로 학습돼요."
                wrapMode: Text.Wrap
                color: window.muted
                font.pixelSize: 12
            }
            // the session is finished: say so plainly, not only in the counts under the replay
            Rectangle {
                objectName: "useReviewDone"
                visible: useCasesDialog.allDone
                Layout.fillWidth: true
                implicitHeight: doneText.implicitHeight + 20
                radius: 8
                color: "#E6F6EF"
                border.color: "#6CCB9F"
                Text {
                    id: doneText
                    objectName: "useReviewDoneText"
                    anchors.fill: parent
                    anchors.margins: 10
                    verticalAlignment: Text.AlignVCenter
                    wrapMode: Text.Wrap
                    color: "#15803D"
                    font.pixelSize: 14
                    font.bold: true
                    text: useCasesDialog.review
                          ? "검토를 모두 마쳤어요 (" + useCasesDialog.items.length + "개 · 통과 " + useCasesDialog.nOk
                            + " · 오탐지 " + useCasesDialog.nBad + "). [닫기]를 누르면 통과한 사례를 다시 세고, 필요한 수가 차면 자동 학습이 시작돼요."
                          : "이 사례들은 모두 판정했어요 (" + useCasesDialog.items.length + "개 · 통과 " + useCasesDialog.nOk
                            + " · 아님 " + (useCasesDialog.items.length - useCasesDialog.nOk) + "). 더 할 일은 없어요."
                }
            }
            RowLayout {
                Layout.fillWidth: true
                Layout.fillHeight: true
                spacing: 12
                // the list of uses, newest first
                Rectangle {
                    Layout.preferredWidth: 300
                    Layout.fillHeight: true
                    radius: 8
                    color: "#FFFFFF"
                    border.color: window.line
                    ListView {
                        id: caseList
                        objectName: "useCasesList"
                        anchors.fill: parent
                        anchors.margins: 6
                        clip: true
                        spacing: 4
                        model: useCasesDialog.items
                        delegate: Rectangle {
                            required property var modelData
                            required property int index
                            width: caseList.width
                            height: 44
                            radius: 6
                            color: index === useCasesDialog.current ? "#E6F6EF" : (rowMouse.containsMouse ? "#F5F8F7" : "transparent")
                            border.color: index === useCasesDialog.current ? "#6CCB9F" : "transparent"
                            Column {
                                anchors.verticalCenter: parent.verticalCenter
                                anchors.left: parent.left
                                anchors.leftMargin: 10
                                spacing: 2
                                Text {
                                    text: (useCasesDialog.review ? index + 1 : useCasesDialog.items.length - index) + ".  " + modelData.when
                                          + (modelData.direction ? "   " + modelData.direction : "")
                                    font.pixelSize: 12
                                    font.bold: true
                                    color: window.ink
                                }
                                Text {
                                    text: modelData.marked ? modelData.mark_text
                                          : modelData.review === "ok" ? "통과 (이 동작으로 학습)"
                                          : modelData.review === "bad" ? "오탐지 ('아님'으로 학습)"
                                          : useCasesDialog.review ? "아직 안 봄" : "실행됨 (검토 전)"
                                    font.pixelSize: 11
                                    font.bold: modelData.review === "ok" || modelData.review === "bad"
                                    color: modelData.marked || modelData.review === "bad" ? "#B91C1C"
                                           : modelData.review === "ok" ? "#15803D" : window.muted
                                }
                            }
                            MouseArea {
                                id: rowMouse
                                anchors.fill: parent
                                hoverEnabled: true
                                onClicked: { useCasesDialog.current = index; useCasesDialog.playing = true }
                            }
                        }
                    }
                }
                // the replay
                ColumnLayout {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    spacing: 8
                    Rectangle {
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        radius: 10
                        color: "#0E1B26"
                        Canvas {
                            id: caseCanvas
                            objectName: "useCasesCanvas"
                            readonly property real side: Math.min(width, height)
                            anchors.fill: parent
                            anchors.margins: 12
                            onWidthChanged: requestPaint()
                            onHeightChanged: requestPaint()
                            Connections { target: useCasesDialog; function onShownChanged() { caseCanvas.requestPaint() } }
                            onPaint: {
                                var c = getContext("2d"); c.reset()
                                var shownCase = useCasesDialog.shown
                                if (!shownCase || !shownCase.frames || shownCase.frames.length === 0) return
                                var p = shownCase.frames[Math.min(useCasesDialog.frame, shownCase.frames.length - 1)]
                                var s = side, ox = (width - s) / 2, oy = (height - s) / 2
                                var fired = Math.abs(useCasesDialog.frame - shownCase.fire) <= 2
                                var chains = [[0,1,2,3,4],[0,5,6,7,8],[0,9,10,11,12],[0,13,14,15,16],[0,17,18,19,20],[5,9,13,17]]
                                c.lineCap = "round"; c.lineJoin = "round"
                                for (var pass = 0; pass < 2; pass++) {
                                    c.strokeStyle = pass === 0 ? "rgba(0,0,0,0.5)" : (fired ? "#F87171" : "#6EE7C8")
                                    c.lineWidth = pass === 0 ? 9 : 5
                                    for (var k = 0; k < chains.length; k++) {
                                        var ch = chains[k]
                                        c.beginPath()
                                        for (var i = 0; i < ch.length; i++) {
                                            var v = p[ch[i]]
                                            if (i === 0) c.moveTo(ox + v[0] * s, oy + v[1] * s); else c.lineTo(ox + v[0] * s, oy + v[1] * s)
                                        }
                                        c.stroke()
                                    }
                                }
                                c.fillStyle = "#FFFFFF"
                                for (var j = 0; j < 21; j++) {
                                    c.beginPath(); c.arc(ox + p[j][0] * s, oy + p[j][1] * s, j % 4 === 0 && j > 0 ? 6 : 4, 0, Math.PI * 2); c.fill()
                                }
                            }
                        }
                        Text {
                            anchors.top: parent.top
                            anchors.left: parent.left
                            anchors.margins: 12
                            visible: useCasesDialog.shown !== null
                            text: useCasesDialog.shown === null ? ""
                                  : Math.abs(useCasesDialog.frame - useCasesDialog.shown.fire) <= 2 ? "▶ 명령 실행"
                                  : useCasesDialog.frame < useCasesDialog.shown.fire ? "실행 전" : "실행 후"
                            color: useCasesDialog.shown !== null && Math.abs(useCasesDialog.frame - useCasesDialog.shown.fire) <= 2 ? "#F87171" : "#94A3B8"
                            font.pixelSize: 14
                            font.bold: true
                        }
                    }
                    // timeline: where the command ran
                    Rectangle {
                        Layout.fillWidth: true
                        implicitHeight: 10
                        radius: 5
                        color: "#E5EFEA"
                        readonly property int n: useCasesDialog.shown ? Math.max(1, (useCasesDialog.shown.frames || []).length - 1) : 1
                        Rectangle {
                            width: parent.width * useCasesDialog.frame / parent.n
                            height: parent.height
                            radius: 5
                            color: "#10B981"
                        }
                        Rectangle {
                            visible: useCasesDialog.shown !== null
                            x: useCasesDialog.shown ? parent.width * useCasesDialog.shown.fire / parent.n - 1.5 : 0
                            y: -4
                            width: 3
                            height: parent.height + 8
                            color: "#EF4444"
                        }
                        MouseArea {
                            anchors.fill: parent
                            onClicked: function (m) {
                                useCasesDialog.playing = false
                                useCasesDialog.frame = Math.round(m.x / width * parent.n)
                                caseCanvas.requestPaint()
                            }
                        }
                    }
                    RowLayout {
                        Layout.fillWidth: true
                        spacing: 6
                        CompactButton {
                            text: "◀ 이전"
                            enabled: useCasesDialog.current > 0
                            onClicked: useCasesDialog.current--
                        }
                        CompactButton {
                            text: useCasesDialog.playing ? "일시정지" : "재생"
                            onClicked: useCasesDialog.playing = !useCasesDialog.playing
                        }
                        CompactButton {
                            text: "다음 ▶"
                            enabled: useCasesDialog.current < useCasesDialog.items.length - 1
                            onClicked: useCasesDialog.current++
                        }
                        Item { Layout.fillWidth: true }
                        Text {
                            text: useCasesDialog.shown ? ("실행 " + useCasesDialog.shown.before + "초 전 ~ " + useCasesDialog.shown.after + "초 후") : ""
                            font.pixelSize: 12
                            color: window.muted
                        }
                    }
                    // the verdict of the use being shown, and how far the session is
                    RowLayout {
                        objectName: "useReviewBar"
                        visible: useCasesDialog.review && useCasesDialog.shown !== null
                        Layout.fillWidth: true
                        spacing: 6
                        CompactButton {
                            objectName: "useReviewOk"
                            text: "통과 (1)"
                            accent: useCasesDialog.shown !== null && useCasesDialog.shown.review === "ok"
                            onClicked: useCasesDialog.judge("ok")
                        }
                        CompactButton {
                            objectName: "useReviewBad"
                            text: "오탐지 (2)"
                            danger: useCasesDialog.shown !== null && useCasesDialog.shown.review === "bad"
                            onClicked: useCasesDialog.judge("bad")
                        }
                        Text {
                            Layout.fillWidth: true
                            text: "통과 " + useCasesDialog.nOk + "  ·  오탐지 " + useCasesDialog.nBad + "  ·  남음 " + useCasesDialog.nLeft
                                  + (useCasesDialog.nLeft === 0 ? "   · 다 봤어요" : "")
                            font.pixelSize: 12
                            font.bold: true
                            color: useCasesDialog.nLeft === 0 ? "#15803D" : window.ink
                            wrapMode: Text.Wrap
                        }
                        CompactButton {
                            objectName: "useReviewRest"
                            visible: useCasesDialog.nLeft > 0
                            text: "남은 " + useCasesDialog.nLeft + "개 모두 통과"
                            onClicked: confirmDialog.ask("남은 사례 모두 통과",
                                "아직 안 본 " + useCasesDialog.nLeft + "개를 보지 않고 통과시킵니다. 오탐지가 섞여 있으면 그대로 학습돼요.",
                                "모두 통과", function () { dashboard.judgeUseRest("ok") })
                        }
                    }
                }
            }
        }
    }
    // The candidate of the exported gesture model next to the one in use (src/onnx_candidate.py): applied only here
    Dialog {
        id: onnxDialog
        objectName: "onnxDialog"
        anchors.centerIn: parent
        width: Math.min(820, window.width - 48)
        modal: true
        readonly property var cand: dashboard.onnxCandidate
        title: cand.ready === true ? "새 손짓 모델 후보" : "손짓 모델"
        contentItem: ColumnLayout {
            spacing: 10
            TextLabel {
                Layout.fillWidth: true
                visible: onnxDialog.cand.ready === true
                text: "쓰면서 모은 사례 " + (onnxDialog.cand.trained_on || 0) + "개와 안내 녹화로 앱이 새로 학습한 후보예요 ("
                      + (onnxDialog.cand.created || "") + ", " + (onnxDialog.cand.minutes || 0) + "분 걸림). "
                      + "[적용]을 누르기 전까지는 지금 모델을 그대로 써요. 지금 모델: " + (onnxDialog.cand.current_trained || "알 수 없음") + " 학습."
                wrapMode: Text.Wrap
                font.pixelSize: 12
                color: window.muted
            }
            TextLabel {
                Layout.fillWidth: true
                visible: onnxDialog.cand.ready !== true
                text: "기다리는 새 후보는 없어요. 적용했던 모델이 마음에 들지 않으면 이전 모델로 되돌릴 수 있어요."
                wrapMode: Text.Wrap
                font.pixelSize: 12
                color: window.muted
            }
            // what | the model in use | the candidate
            GridLayout {
                visible: onnxDialog.cand.ready === true
                Layout.fillWidth: true
                id: onnxGrid
                readonly property bool base: onnxDialog.cand.has_baseline === true
                columns: base ? 4 : 3
                columnSpacing: 14
                rowSpacing: 6
                TextLabel { text: "비교"; font.bold: true; font.pixelSize: 12; Layout.row: 0; Layout.column: 0 }
                TextLabel { text: "지금 모델"; font.bold: true; font.pixelSize: 12; Layout.row: 0; Layout.column: 1 }
                // the same training without the collected uses (scripts/onnx_auto_update.py): what the uses changed
                TextLabel { text: "기준 (사례 없이)"; font.bold: true; font.pixelSize: 12; visible: onnxGrid.base; Layout.row: 0; Layout.column: 2 }
                TextLabel { text: "새 후보"; font.bold: true; font.pixelSize: 12; Layout.row: 0; Layout.column: onnxGrid.base ? 3 : 2 }
                Repeater {
                    model: onnxGrid.base ? (onnxDialog.cand.rows || []) : []
                    delegate: TextLabel {
                        required property var modelData
                        required property int index
                        Layout.row: index + 1
                        Layout.column: 2
                        text: modelData.baseline
                        font.pixelSize: 12
                        color: window.muted
                    }
                }
                Repeater {
                    model: onnxDialog.cand.rows || []
                    delegate: TextLabel {
                        required property var modelData
                        Layout.fillWidth: true
                        Layout.preferredWidth: onnxGrid.base ? 300 : 360
                        text: modelData.what
                        font.pixelSize: 12
                        wrapMode: Text.Wrap
                        Layout.row: index + 1
                        Layout.column: 0
                        required property int index
                    }
                }
                Repeater {
                    model: onnxDialog.cand.rows || []
                    delegate: TextLabel {
                        required property var modelData
                        required property int index
                        Layout.row: index + 1
                        Layout.column: 1
                        text: modelData.current
                        font.pixelSize: 12
                        color: window.muted
                    }
                }
                Repeater {
                    model: onnxDialog.cand.rows || []
                    delegate: TextLabel {
                        required property var modelData
                        required property int index
                        Layout.row: index + 1
                        Layout.column: onnxGrid.base ? 3 : 2
                        text: modelData.candidate + (modelData.better === "yes" ? "  (나아짐)" : modelData.better === "no" ? "  (나빠짐)" : "")
                        font.pixelSize: 12
                        font.bold: modelData.better !== ""
                        color: modelData.better === "yes" ? "#15803D" : modelData.better === "no" ? "#B91C1C" : window.ink
                    }
                }
            }
            Repeater {
                model: onnxDialog.cand.notes || []
                delegate: TextLabel {
                    required property var modelData
                    Layout.fillWidth: true
                    text: "· " + modelData
                    font.pixelSize: 12
                    color: window.muted
                    wrapMode: Text.Wrap
                }
            }
            RowLayout {
                Layout.fillWidth: true
                spacing: 6
                CompactButton {
                    objectName: "onnxRollback"
                    visible: onnxDialog.cand.can_rollback === true
                    text: "이전 모델로 되돌리기"
                    onClicked: confirmDialog.ask("이전 손짓 모델로 되돌리기", "지금 쓰는 손짓 모델을 바로 전에 쓰던 모델로 바꿉니다.",
                                                 "되돌리기", function () { dashboard.rollbackOnnxModel() })
                }
                Item { Layout.fillWidth: true }
                CompactButton {
                    objectName: "onnxClose"
                    text: "닫기"
                    onClicked: onnxDialog.close()
                }
                CompactButton {
                    objectName: "onnxDiscard"
                    visible: onnxDialog.cand.ready === true
                    text: "버리기"
                    onClicked: { dashboard.discardOnnxCandidate(); onnxDialog.close() }
                }
                CompactButton {
                    objectName: "onnxApply"
                    visible: onnxDialog.cand.ready === true
                    accent: true
                    text: "적용"
                    onClicked: confirmDialog.ask("새 손짓 모델 적용", "지금 모델을 보관하고 새 후보로 바꿉니다. 나중에 [이전 모델로 되돌리기]로 돌아갈 수 있어요.",
                                                 "적용", function () { if (dashboard.applyOnnxCandidate()) onnxDialog.close() })
                }
            }
        }
    }
    // A short notice (dashboard.notify): something the person has to know that is not worth a place in the window -
    // a finished learning round that changed something. Goes away by itself; a click closes it.
    Popup {
        id: toastPopup
        objectName: "toast"
        x: Math.round((window.width - width) / 2)
        y: window.height - height - 36
        padding: 14
        modal: false
        focus: false
        closePolicy: Popup.NoAutoClose
        background: Rectangle { radius: 10; color: "#112331"; opacity: 0.96 }
        contentItem: Text {
            objectName: "toastText"
            text: (dashboard.toast && dashboard.toast.text) || ""
            color: "white"
            font.pixelSize: 13
            wrapMode: Text.Wrap
            width: Math.min(620, window.width - 120)
            MouseArea { anchors.fill: parent; onClicked: toastPopup.close() }
        }
        Timer { id: toastTimer; interval: 9000; onTriggered: toastPopup.close() }
        Connections {
            target: dashboard
            // a shown hand that another gesture answers to as well: asked, never refused (src/gesture_overlap.py)
            function onOverlapAsk(kind, what, words) {
                confirmDialog.ask("겹치는 동작이 있어요", words, "그래도 저장", function () { dashboard.overlapConfirmed(kind, what) })
            }
            function onToastChanged() {
                if (((dashboard.toast && dashboard.toast.text) || "") !== "") { toastPopup.open(); toastTimer.restart() }
            }
        }
    }

    // Connect gestures in words (AI): its own window, opened from the top bar (was the 5-4 sub-tab of the bindings)
    Dialog {
        id: llmDialog
        objectName: "llmDialog"
        anchors.centerIn: parent
        width: Math.min(1560, window.width - 48)
        height: window.height - 48
        modal: true
        title: "말·글로 연결 (AI)"
        // 2026-11-11: [새 동작 등록] sits at the bottom beside Close - "done with this one, on to the next" (it was in
        // the teaching row, among the buttons of the shape being taught)
        footer: DialogButtonBox {
            onRejected: llmDialog.close()
            // (both buttons written out: with standardButtons + one more button only that one showed, 2026-11-11)
            Button {
                objectName: "llmClose"
                text: "닫기"
                DialogButtonBox.buttonRole: DialogButtonBox.RejectRole
            }
            Button {
                objectName: "poseTeachNew"
                readonly property var pose: dashboard.llmContext.pose || {}
                readonly property var teach: dashboard.llmContext.teach || {}
                text: "🆕 새 동작 등록"
                font.bold: true
                enabled: pose.state !== "countdown" && pose.state !== "holding" && teach.state !== "training"
                DialogButtonBox.buttonRole: DialogButtonBox.ActionRole
                onClicked: {
                    llmScroll.ScrollBar.vertical.position = 0      // the look is shown at the top
                    dashboard.poseTeachNew()
                }
            }
        }
        contentItem: Item {
                    // =========================================================================
                    // SUB-TAB 4: CONNECT GESTURES IN WORDS (LLM: Claude / OpenAI / Gemini / OpenRouter / Ollama)
                    // src/llm_binding.py proposes, the user ticks, only then it is saved. Speech = Windows voice typing.
                    // =========================================================================
                    Rectangle {
                        id: llmPanel
                        objectName: "llmPanel"
                        anchors.fill: parent
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        radius: 10
                        color: "#F7FAFB"
                        border.color: window.line
                        readonly property var cfg: dashboard.llmSettings
                        readonly property var result: dashboard.llmResult
                        readonly property var proposals: result.proposals || []
                        ScrollView {
                            id: llmScroll
                            anchors.top: parent.top
                            anchors.bottom: parent.bottom
                            anchors.left: parent.left
                            anchors.right: llmListPane.left
                            anchors.margins: 12
                            clip: true
                            contentWidth: availableWidth
                            ColumnLayout {
                                width: parent.width
                                spacing: 8

                                TextLabel {
                                    Layout.fillWidth: true
                                    text: "하고 싶은 연결을 말하거나 적으면, AI가 동작 연결을 제안합니다. 확인하고 고른 것만 저장돼요."
                                    font.bold: true
                                    wrapMode: Text.Wrap
                                }
                                // 1. where the request goes - a card that folds to one line once it is set up (2026-11-11: the
                                // connection rows took the top of the window and pushed the gesture part below the fold)
                                Rectangle {
                                    id: llmSetup
                                    objectName: "llmSetup"
                                    Layout.fillWidth: true
                                    radius: 8
                                    color: "#FFFFFF"
                                    border.color: window.line
                                    property bool userOpen: false
                                    // no model or no key yet: always open, there is nothing to fold
                                    readonly property bool ready: (llmPanel.cfg.modelShown || "") !== "" && !!llmPanel.cfg.hasKey
                                    readonly property bool open: userOpen || !ready
                                    readonly property string providerLabel: {
                                        var ps = dashboard.llmProviders
                                        for (var i = 0; i < ps.length; i++) if (ps[i].id === llmPanel.cfg.provider) return ps[i].label
                                        return llmPanel.cfg.provider || ""
                                    }
                                    implicitHeight: setupCol.implicitHeight + 16
                                    ColumnLayout {
                                        id: setupCol
                                        anchors.left: parent.left
                                        anchors.right: parent.right
                                        anchors.top: parent.top
                                        anchors.margins: 8
                                        spacing: 8
                                        RowLayout {
                                            Layout.fillWidth: true
                                            spacing: 8
                                            Text {
                                                text: llmSetup.open ? "▾" : "▸"
                                                font.pixelSize: 14
                                                color: window.muted
                                            }
                                            Text {
                                                objectName: "llmSetupSummary"
                                                Layout.fillWidth: true
                                                text: "AI 연결  ·  " + llmSetup.providerLabel
                                                      + "  ·  " + ((llmPanel.cfg.modelShown || "") !== "" ? llmPanel.cfg.modelShown : "모델 미정")
                                                      + (llmPanel.cfg.needsKey ? "  ·  " + (llmPanel.cfg.hasKey ? "🔑 " + llmPanel.cfg.keySource : "⚠ 키 없음") : "")
                                                font.pixelSize: 13
                                                font.bold: true
                                                color: llmSetup.ready ? window.ink : "#B3261E"
                                                elide: Text.ElideRight
                                            }
                                            CompactButton {
                                                objectName: "llmSetupToggle"
                                                visible: llmSetup.ready
                                                text: llmSetup.open ? "접기" : "연결 설정"
                                                onClicked: llmSetup.userOpen = !llmSetup.userOpen
                                            }
                                        }
                                        ColumnLayout {
                                            Layout.fillWidth: true
                                            spacing: 8
                                            visible: llmSetup.open
                                            RowLayout {
                                                Layout.fillWidth: true
                                                spacing: 6
                                                FormLabel { text: "AI 연결" }
                                                Flow {
                                                    Layout.fillWidth: true
                                                    spacing: 6
                                                    Repeater {
                                                        model: dashboard.llmProviders
                                                        delegate: CompactButton {
                                                            required property var modelData
                                                            text: modelData.label
                                                            accent: llmPanel.cfg.provider === modelData.id
                                                            enabled: !dashboard.llmBusy
                                                            onClicked: dashboard.setLlmProvider(modelData.id)
                                                        }
                                                    }
                                                }
                                            }
                                            TextLabel {
                                                Layout.fillWidth: true
                                                Layout.leftMargin: 90
                                                text: {
                                                    var ps = dashboard.llmProviders
                                                    for (var i = 0; i < ps.length; i++) if (ps[i].id === llmPanel.cfg.provider) return ps[i].note
                                                    return ""
                                                }
                                                color: window.muted
                                                font.pixelSize: 12
                                                wrapMode: Text.Wrap
                                            }
                                            RowLayout {
                                                Layout.fillWidth: true
                                                spacing: 6
                                                FormLabel { text: "모델" }
                                                TextField {
                                                    id: llmModelField
                                                    Layout.fillWidth: true
                                                    text: llmPanel.cfg.model || ""
                                                    placeholderText: llmPanel.cfg.modelShown ? ("기본: " + llmPanel.cfg.modelShown) : "모델 이름 (목록에서 고르거나 직접 입력)"
                                                    font.pixelSize: 13
                                                    onEditingFinished: dashboard.setLlmModel(text)
                                                }
                                                StyledComboBox {
                                                    visible: dashboard.llmModels.length > 0
                                                    Layout.preferredWidth: 240
                                                    model: dashboard.llmModels
                                                    onActivated: function (i) { dashboard.setLlmModel(dashboard.llmModels[i]); llmModelField.text = dashboard.llmModels[i] }
                                                }
                                                CompactButton {
                                                    text: "모델 목록 불러오기"
                                                    enabled: !dashboard.llmBusy
                                                    onClicked: dashboard.loadLlmModels()
                                                }
                                            }
                                            RowLayout {
                                                Layout.fillWidth: true
                                                spacing: 6
                                                visible: llmPanel.cfg.needsKey
                                                FormLabel { text: "API 키" }
                                                TextField {
                                                    id: llmKeyField
                                                    Layout.fillWidth: true
                                                    echoMode: TextInput.Password
                                                    placeholderText: llmPanel.cfg.keySource + " · 새 키를 붙여 넣고 [키 저장]"
                                                    font.pixelSize: 13
                                                }
                                                CompactButton {
                                                    text: "키 저장"
                                                    enabled: llmKeyField.text.length > 0
                                                    onClicked: { dashboard.saveLlmKey(llmKeyField.text); llmKeyField.text = "" }
                                                }
                                                CompactButton {
                                                    text: "키 지우기"
                                                    visible: llmPanel.cfg.keySaved
                                                    onClicked: dashboard.clearLlmKey()
                                                }
                                            }
                                            RowLayout {
                                                Layout.fillWidth: true
                                                spacing: 6
                                                FormLabel { text: "주소 (고급)" }
                                                TextField {
                                                    Layout.fillWidth: true
                                                    text: llmPanel.cfg.baseUrl || ""
                                                    placeholderText: llmPanel.cfg.defaultBase ? ("기본: " + llmPanel.cfg.defaultBase) : "기본 주소 사용"
                                                    font.pixelSize: 12
                                                    onEditingFinished: dashboard.setLlmBaseUrl(text)
                                                }
                                            }
                                        }
                                    }
                                    TapHandler {
                                        // a tap anywhere on the folded card opens it
                                        enabled: llmSetup.ready && !llmSetup.open
                                        onTapped: llmSetup.userOpen = true
                                    }
                                }
                                Divider {}

                                // 2. the request, typed or spoken (Windows voice typing writes into this box)
                                // what 이/저 point to: a hand shape shown to the camera, a key combination pressed
                                TextLabel {
                                    Layout.fillWidth: true
                                    text: "\"이 손모양이면 저렇게 해줘\"처럼 말하려면 먼저 가리켜 두세요 (선택)"
                                    font.bold: true
                                    wrapMode: Text.Wrap
                                }
                                RowLayout {
                                    Layout.fillWidth: true
                                    spacing: 6
                                    readonly property var pose: dashboard.llmContext.pose || {}
                                    id: poseRow
                                    ActionButton {
                                        objectName: "poseProbeButton"
                                        text: "✋ 손 모양·움직임 보여주기"
                                        enabled: poseRow.pose.state !== "countdown" && poseRow.pose.state !== "holding"
                                        onClicked: dashboard.startPoseProbe()
                                    }
                                    // 2026-11-11: what was looked at (the user's own hand, joints drawn) -> what it was told as
                                    Rectangle {
                                        objectName: "poseProbeShot"
                                        visible: poseRow.pose.state === "done" && (dashboard.llmContext.shot || "") !== ""
                                        Layout.preferredWidth: 112
                                        Layout.preferredHeight: 112
                                        radius: 6
                                        clip: true
                                        color: "#111"
                                        // the look replayed like a GIF (memory only, src/pose_probe.PoseProbe.clip); one
                                        // picture when there is a single frame
                                        id: poseShot
                                        property int frame: 0
                                        readonly property int frames: dashboard.llmContext.shotFrames || 0
                                        onVisibleChanged: frame = 0
                                        onFramesChanged: frame = 0
                                        Timer {
                                            interval: 66
                                            repeat: true
                                            running: poseShot.visible && poseShot.frames > 1
                                            onTriggered: poseShot.frame = (poseShot.frame + 1) % poseShot.frames
                                        }
                                        Image {
                                            anchors.fill: parent
                                            source: !poseShot.visible ? ""
                                                  : poseShot.frames > 1 ? (dashboard.llmContext.shot + "/" + poseShot.frame)
                                                  : dashboard.llmContext.shot
                                            fillMode: Image.PreserveAspectFit
                                            cache: false
                                            smooth: true
                                        }
                                    }
                                    // 2026-11-11: the hand emoji that stood here (🖐 ✌ …) is gone - often wrong, and the photo beside it shows the hand anyway.
                                    // The arrow of a movement / turn stays: the photo does not show which way the hand went.
                                    Text {
                                        objectName: "poseProbeArrow"
                                        readonly property var arrows: ({"left": "←", "right": "→", "up": "↑", "down": "↓",
                                            "diag_up_left": "↖", "diag_up_right": "↗", "diag_down_left": "↙", "diag_down_right": "↘",
                                            "rotate_cw": "↻", "rotate_ccw": "↺"})
                                        visible: poseRow.pose.state === "done" && text !== ""
                                        text: poseRow.pose.kind === "motion" ? (arrows[poseRow.pose.direction] || "")
                                            : poseRow.pose.kind === "rotate" ? (arrows[poseRow.pose.rotate] || "") : ""
                                        font.pixelSize: 32
                                        color: Theme.Studio.mintDark
                                    }
                                    TextLabel {
                                        Layout.fillWidth: true
                                        wrapMode: Text.Wrap
                                        font.pixelSize: 13
                                        // an approximate answer (the nearest known shape / movement) says so
                                        readonly property string approxText: poseRow.pose.approx ? " · 가장 가까운 것으로 봤어요" : ""
                                        readonly property var teach: dashboard.llmContext.teach || {}
                                        color: poseRow.pose.state === "failed" || (poseRow.pose.unknown && !teach.adding) ? Theme.Studio.danger
                                             : poseRow.pose.state === "done" ? Theme.Studio.mintDark : window.muted
                                        font.bold: poseRow.pose.state === "countdown" || poseRow.pose.state === "done"
                                        text: poseRow.pose.state === "countdown"
                                                ? ((teach.adding ? "'" + teach.focusName + "' 모양으로 " : "") + "손을 준비하세요… " + poseRow.pose.seconds)
                                            // [한 번 더 보여주기]: this look is one more example of the shape being taught
                                            : poseRow.pose.state === "done" && teach.adding ? ("'" + teach.focusName + "' 견본으로 추가하는 중…")
                                            : poseRow.pose.state === "done" && !poseRow.pose.kind && poseRow.pose.taught
                                                ? ("✓ '" + poseRow.pose.name + "' 견본으로 저장했어요"
                                                   + (String(poseRow.pose.posture).indexOf("custom_") === 0 ? " · [학습] → [적용] 뒤부터 앱이 알아봐요" : ""))
                                            : poseRow.pose.state === "holding" ? ("그대로 유지! " + Math.round(poseRow.pose.progress * 100) + "%")
                                            // [새 동작 등록]: whatever the app took the look for, it is to be named
                                            : poseRow.pose.state === "done" && !poseRow.pose.kind && teach.naming
                                                ? ((poseRow.pose.unknown ? "목록에 없는 손 모양이에요."
                                                    : "앱은 '" + poseRow.pose.name + "'(으)로 봤어요. 다른 모양이면")
                                                   + " 아래에 새 이름을 지어 저장해 주세요.")
                                            // 2026-11-11: no listed shape / movement is said so, not forced into the nearest one
                                            : poseRow.pose.state === "done" && poseRow.pose.kind === "unknown_move" ? poseRow.pose.message
                                            : poseRow.pose.state === "done" && poseRow.pose.unknown
                                                ? "목록에 없는 손 모양이에요. 아래에 이름을 지어 새 손 모양으로 저장해 주세요."
                                            : poseRow.pose.state === "done" && poseRow.pose.kind === "rotate"
                                                ? ("이 움직임 = " + poseRow.pose.name + " 모양으로 " + poseRow.pose.rotate_name + approxText)
                                            : poseRow.pose.state === "done" && poseRow.pose.kind === "drawn"
                                                ? ("이 움직임 = " + poseRow.pose.shape_name + " 그리기 (" + Math.round(poseRow.pose.score * 100)
                                                   + "%) · 그리기 모드에서 검지로 그리면 실행돼요")
                                            : poseRow.pose.state === "done" && poseRow.pose.kind === "motion"
                                                ? ("이 움직임 = " + poseRow.pose.name + " 모양으로 " + poseRow.pose.direction_name + approxText)
                                            : poseRow.pose.state === "done" ? ("이 손모양 = " + poseRow.pose.name + approxText
                                                                               + (poseRow.pose.gesture_key ? "" : " · 아직 연결 없음 (연결하면 새 동작이 돼요)"))
                                            : poseRow.pose.state === "failed" ? poseRow.pose.message
                                            : "3초 뒤 2초 동안 카메라로 봅니다 · 가만히 = 손 모양, 한 모양으로 한 방향 움직이기 = 움직임"
                                    }
                                    CompactButton {
                                        visible: poseRow.pose.state === "done" || poseRow.pose.state === "failed"
                                        text: "지우기"
                                        onClicked: dashboard.clearPoseProbe()
                                    }
                                }
                                // 2026-11-12: this look is read as another gesture's hand too (src/gesture_overlap.py)
                                TextLabel {
                                    objectName: "llmOverlapNote"
                                    visible: text.length > 0
                                    Layout.fillWidth: true
                                    text: dashboard.llmContext.overlap ? "⚠ " + dashboard.llmContext.overlap : ""
                                    color: "#B45309"
                                    font.pixelSize: 12
                                    wrapMode: Text.Wrap
                                }
                                // 2026-11-11: teach the shown hand shape to a small MLP (src/posture_teach.py)
                                RowLayout {
                                    id: teachSaveRow
                                    Layout.fillWidth: true
                                    spacing: 6
                                    readonly property var teach: dashboard.llmContext.teach || {}
                                    visible: poseRow.pose.state === "done" && !poseRow.pose.kind && !poseRow.pose.taught && !teach.adding
                                    // the shape being taught: one press adds this look to it, whatever the rules called it
                                    ActionButton {
                                        objectName: "poseTeachAddFocus"
                                        visible: !poseRow.pose.taught && (teachSaveRow.teach.focus || "") !== ""
                                        text: "➕ '" + (teachSaveRow.teach.focusName || "") + "' 견본으로 추가"
                                        onClicked: dashboard.poseTeachSave(teachSaveRow.teach.focus)
                                    }
                                    // a look that is no listed shape (or a listed one that should be its own): name it
                                    TextField {
                                        id: teachNewName
                                        objectName: "poseTeachNewName"
                                        Layout.preferredWidth: 130
                                        visible: !poseRow.pose.taught
                                        placeholderText: "새 손 모양 이름"
                                        onVisibleChanged: if (visible && teachSaveRow.teach.naming) forceActiveFocus()
                                        onAccepted: if (text.trim() !== "") { dashboard.poseTeachSaveNew(text); text = "" }
                                        maximumLength: 20
                                        font.pixelSize: 12
                                    }
                                    CompactButton {
                                        objectName: "poseTeachSaveNew"
                                        visible: !poseRow.pose.taught
                                        text: "새 손 모양으로 저장"
                                        enabled: teachNewName.text.trim() !== ""
                                        onClicked: { dashboard.poseTeachSaveNew(teachNewName.text); teachNewName.text = "" }
                                    }
                                    TextLabel {
                                        visible: poseRow.pose.taught || (teachSaveRow.teach.focus || "") === ""
                                        text: poseRow.pose.taught ? "✓ 견본 저장됨" : "또는 목록의 이 모양:"
                                        font.pixelSize: 12
                                        color: poseRow.pose.taught ? Theme.Studio.mintDark : window.muted
                                    }
                                    StyledComboBox {
                                        id: teachChoice
                                        objectName: "poseTeachChoice"
                                        Layout.preferredWidth: 190
                                        model: dashboard.postureChoices
                                        textRole: "name"
                                        currentIndex: {
                                            var c = dashboard.postureChoices
                                            for (var i = 0; i < c.length; i++) if (c[i].key === poseRow.pose.posture) return i
                                            return poseRow.pose.unknown ? -1 : 0
                                        }
                                    }
                                    CompactButton {
                                        objectName: "poseTeachSave"
                                        text: "이 이름으로 견본 저장"
                                        enabled: !poseRow.pose.taught && teachChoice.currentIndex >= 0
                                        onClicked: dashboard.poseTeachSave(dashboard.postureChoices[teachChoice.currentIndex].key)
                                    }
                                }
                                RowLayout {
                                    Layout.fillWidth: true
                                    spacing: 6
                                    readonly property var teach: dashboard.llmContext.teach || {}
                                    id: teachRow
                                    visible: teach.hasExamples || teach.active !== "" || teach.text !== ""
                                    CompactButton {
                                        objectName: "poseTeachTrain"
                                        text: teachRow.teach.state === "training" ? "학습 중…"
                                            : teachRow.teach.focus ? ("🧠 '" + teachRow.teach.focusName + "' 학습") : "🧠 가르친 손 모양 학습 (MLP)"
                                        enabled: teachRow.teach.hasExamples && teachRow.teach.state !== "training"
                                        onClicked: dashboard.poseTeachTrain()
                                    }
                                    TextLabel {
                                        Layout.fillWidth: true
                                        wrapMode: Text.Wrap
                                        font.pixelSize: 12
                                        color: teachRow.teach.state === "error" ? Theme.Studio.danger
                                             : teachRow.teach.state === "ready" ? (teachRow.teach.canApply ? Theme.Studio.mintDark : Theme.Studio.danger)
                                             : window.muted
                                        objectName: "poseTeachGuide"
                                        // the shape being taught now, step by step - nothing about the other taught shapes
                                        text: [teachRow.teach.steps || "", teachRow.teach.text || "", teachRow.teach.summary || ""]
                                              .filter(function (t) { return t !== "" }).join("\n")
                                    }
                                    ActionButton {
                                        objectName: "poseTeachAgain"
                                        visible: (teachRow.teach.focus || "") !== "" && teachRow.teach.state !== "training"
                                                 && poseRow.pose.state !== "countdown" && poseRow.pose.state !== "holding"
                                        text: "✋ 한 번 더 보여주기"
                                        onClicked: dashboard.poseTeachAgain()
                                    }
                                    CompactButton {
                                        visible: teachRow.teach.state === "ready" && teachRow.teach.canApply
                                        text: "적용"
                                        onClicked: dashboard.poseTeachApply()
                                    }
                                    CompactButton {
                                        visible: teachRow.teach.state === "ready"
                                        text: "버리기"
                                        onClicked: dashboard.poseTeachDiscard()
                                    }
                                    CompactButton {
                                        visible: teachRow.teach.active !== "" && teachRow.teach.state !== "ready"
                                        text: "끄기"
                                        onClicked: dashboard.poseTeachOff()
                                    }
                                }
                                RowLayout {
                                    Layout.fillWidth: true
                                    spacing: 6
                                    ActionButton {
                                        objectName: "keyCaptureButton"
                                        text: dashboard.llmContext.capturing ? "키를 누르세요…" : "⌨ 키 기억하기"
                                        enabled: !dashboard.llmContext.capturing
                                        onClicked: dashboard.captureKey()
                                    }
                                    TextLabel {
                                        Layout.fillWidth: true
                                        wrapMode: Text.Wrap
                                        font.pixelSize: 13
                                        font.bold: dashboard.llmContext.key !== ""
                                        color: dashboard.llmContext.key !== "" ? Theme.Studio.mintDark : window.muted
                                        text: dashboard.llmContext.key !== "" ? ("저렇게 = " + dashboard.llmContext.key)
                                            : "누른 뒤 8초 안에 원하는 키 조합을 직접 누르면 그 조합 하나만 기억해요"
                                    }
                                    CompactButton {
                                        visible: dashboard.llmContext.key !== ""
                                        text: "지우기"
                                        onClicked: dashboard.clearCapturedKey()
                                    }
                                }
                                TextLabel { text: "무엇을 연결할까요?"; font.bold: true }
                                Rectangle {
                                    Layout.fillWidth: true
                                    implicitHeight: 96
                                    radius: 8
                                    color: Theme.Studio.paper
                                    border.color: llmRequest.activeFocus ? Theme.Studio.mintDark : window.line
                                    border.width: llmRequest.activeFocus ? 2 : 1
                                    ScrollView {
                                        anchors.fill: parent
                                        anchors.margins: 4
                                        TextArea {
                                            id: llmRequest
                                            objectName: "llmRequest"
                                            wrapMode: TextEdit.Wrap
                                            font.pixelSize: 14
                                            placeholderText: "예) 유튜브에서는 엄지+약지로 자막 켜고 끄기\n예) 크롬에서 엄지+중지는 새 탭, 다른 곳에서는 그대로\n예) V 사인으로 화면 캡처 (Win+Shift+S)"
                                            background: null
                                        }
                                    }
                                }
                                RowLayout {
                                    Layout.fillWidth: true
                                    spacing: 6
                                    ActionButton {
                                        text: "🎤 말로 입력"
                                        enabled: !dashboard.llmBusy
                                        onClicked: { llmRequest.forceActiveFocus(); llmRequest.cursorPosition = llmRequest.length; dashboard.startVoiceTyping() }
                                    }
                                    ActionButton {
                                        objectName: "llmAskButton"
                                        text: dashboard.llmBusy ? "묻는 중…" : "제안 받기"
                                        primary: true
                                        enabled: !dashboard.llmBusy && llmRequest.text.trim().length > 0 && llmPanel.cfg.hasKey
                                        onClicked: dashboard.askLlm(llmRequest.text)
                                    }
                                    BusySpinner { active: dashboard.llmBusy }
                                    TextLabel {
                                        Layout.fillWidth: true
                                        text: llmPanel.cfg.privacy
                                        color: window.muted
                                        font.pixelSize: 11
                                        wrapMode: Text.Wrap
                                    }
                                }
                                TextLabel {
                                    Layout.fillWidth: true
                                    visible: text !== ""
                                    text: dashboard.llmMessage
                                    color: "#0369A1"
                                    font.bold: true
                                    wrapMode: Text.Wrap
                                }

                                // 3. the proposals: checked against the real catalogue, ticked by the user, then saved
                                TextLabel {
                                    Layout.fillWidth: true
                                    visible: (llmPanel.result.summary || "") !== ""
                                    text: "AI 요약: " + (llmPanel.result.summary || "")
                                    wrapMode: Text.Wrap
                                }
                                Repeater {
                                    model: llmPanel.result.questions || []
                                    delegate: Chip { required property var modelData; warn: true; text: "질문: " + modelData; Layout.fillWidth: true; Layout.preferredWidth: -1 }
                                }
                                Repeater {
                                    model: llmPanel.proposals
                                    delegate: Rectangle {
                                        id: proposalCard
                                        required property var modelData
                                        required property int index
                                        Layout.fillWidth: true
                                        implicitHeight: proposalCol.implicitHeight + 16
                                        radius: 8
                                        color: !modelData.ok ? "#FDECEE" : (modelData.risky ? Theme.Studio.amberWash : Theme.Studio.paper)
                                        border.color: modelData.checked ? Theme.Studio.mintDark : window.line
                                        RowLayout {
                                            anchors.fill: parent
                                            anchors.margins: 8
                                            spacing: 8
                                            CheckBox {
                                                enabled: proposalCard.modelData.ok
                                                checked: proposalCard.modelData.checked
                                                onToggled: dashboard.setLlmProposalChecked(proposalCard.index, checked)
                                            }
                                            ColumnLayout {
                                                id: proposalCol
                                                Layout.fillWidth: true
                                                spacing: 2
                                                TextLabel {
                                                    Layout.fillWidth: true
                                                    text: proposalCard.modelData.gesture_name
                                                          + (proposalCard.modelData.mode_name ? "  ·  " + proposalCard.modelData.mode_name
                                                                 + (proposalCard.modelData.mode === "all" ? "" : " 전용") : "")
                                                          + (proposalCard.modelData.app_match ? "  ·  " + proposalCard.modelData.app_match + "에서만" : "  ·  모든 프로그램")
                                                    font.bold: true
                                                    wrapMode: Text.Wrap
                                                }
                                                TextLabel {
                                                    Layout.fillWidth: true
                                                    visible: proposalCard.modelData.ok
                                                    text: proposalCard.modelData.before + "  →  "
                                                          + ((proposalCard.modelData.steps || []).length ? "여러 단계" : proposalCard.modelData.after)
                                                    font.pixelSize: 13
                                                    wrapMode: Text.Wrap
                                                }
                                                Repeater {
                                                    model: proposalCard.modelData.steps || []
                                                    delegate: TextLabel {
                                                        required property var modelData
                                                        required property int index
                                                        Layout.fillWidth: true
                                                        Layout.leftMargin: 12
                                                        text: (index + 1) + ". " + window.stepText(modelData)
                                                        font.pixelSize: 13
                                                        wrapMode: Text.Wrap
                                                    }
                                                }
                                                TextLabel {
                                                    Layout.fillWidth: true
                                                    visible: proposalCard.modelData.risky && proposalCard.modelData.ok
                                                    text: "⚠ " + (proposalCard.modelData.warning || "")
                                                    color: Theme.Studio.amber
                                                    font.pixelSize: 12
                                                    wrapMode: Text.Wrap
                                                }
                                                TextLabel {
                                                    Layout.fillWidth: true
                                                    visible: !proposalCard.modelData.ok
                                                    text: "적용 불가: " + proposalCard.modelData.problem + " (" + proposalCard.modelData.action_type + " " + proposalCard.modelData.action_value + ")"
                                                    color: Theme.Studio.danger
                                                    font.pixelSize: 12
                                                    wrapMode: Text.Wrap
                                                }
                                                TextLabel {
                                                    Layout.fillWidth: true
                                                    visible: proposalCard.modelData.reason !== ""
                                                    text: proposalCard.modelData.reason
                                                    color: window.muted
                                                    font.pixelSize: 12
                                                    wrapMode: Text.Wrap
                                                }
                                            }
                                        }
                                    }
                                }
                                RowLayout {
                                    visible: llmPanel.proposals.length > 0
                                    spacing: 6
                                    ActionButton {
                                        objectName: "llmApplyButton"
                                        text: "선택한 연결 적용"
                                        primary: true
                                        onClicked: dashboard.applyLlmProposals()
                                    }
                                    ActionButton { text: "버리기"; onClicked: dashboard.clearLlmResult() }
                                }

                                // the hand shapes the user named (src/custom_postures.py): a wrong name can be deleted
                                Divider { Layout.topMargin: 6; visible: dashboard.customPostures.length > 0 }
                                SectionLabel {
                                    visible: dashboard.customPostures.length > 0
                                    text: "내가 이름 지은 손 모양 (" + dashboard.customPostures.length + ")"
                                }
                                Repeater {
                                    model: dashboard.customPostures
                                    delegate: Rectangle {
                                        id: customCard
                                        objectName: "customPostureCard"
                                        required property var modelData
                                        Layout.fillWidth: true
                                        implicitHeight: customRow.implicitHeight + 16
                                        radius: 8
                                        color: Theme.Studio.paper
                                        border.color: window.line
                                        RowLayout {
                                            id: customRow
                                            anchors.fill: parent
                                            anchors.margins: 8
                                            spacing: 8
                                            TextLabel { text: customCard.modelData.name; font.bold: true }
                                            TextLabel {
                                                Layout.fillWidth: true
                                                wrapMode: Text.Wrap
                                                color: window.muted
                                                font.pixelSize: 12
                                                text: "견본 " + customCard.modelData.examples + "개 · "
                                                      + (customCard.modelData.uses ? "연결한 동작: " + customCard.modelData.usesText : "연결한 동작 없음")
                                            }
                                            CompactButton {
                                                text: "삭제"
                                                danger: true
                                                onClicked: confirmDialog.ask("손 모양 삭제",
                                                    "'" + customCard.modelData.name + "' 손 모양을 지웁니다. 견본 " + customCard.modelData.examples + "개"
                                                    + (customCard.modelData.uses ? "와 이 모양에 연결한 동작(" + customCard.modelData.usesText + ")" : "")
                                                    + "도 함께 지워지고 되돌릴 수 없어요.",
                                                    "삭제", function () { dashboard.removeCustomPosture(customCard.modelData.key) })
                                            }
                                        }
                                    }
                                }

                            }
                        }
                        // 2026-11-11: the AI connections in their own column on the right (the window had room to spare)
                        Rectangle {
                            id: llmListPane
                            objectName: "llmListPane"
                            anchors.top: parent.top
                            anchors.bottom: parent.bottom
                            anchors.right: parent.right
                            anchors.margins: 12
                            width: Math.max(340, Math.min(560, parent.width * 0.4))
                            radius: 8
                            color: "#FFFFFF"
                            border.color: window.line
                            ScrollView {
                                id: llmListScroll
                                anchors.fill: parent
                                anchors.margins: 10
                                clip: true
                                contentWidth: availableWidth
                                ColumnLayout {
                                    width: llmListScroll.availableWidth
                                    spacing: 8
                                RowLayout {
                                    Layout.fillWidth: true
                                    SectionLabel { text: "AI로 연결한 명령 (" + dashboard.llmHistory.length + ")" }
                                    Item { Layout.fillWidth: true }
                                    CheckBox { id: historyAll; text: "바뀐 것도 보기"; checked: false }
                                }
                                TextLabel {
                                    visible: dashboard.llmHistory.length === 0
                                    text: "아직 없어요. 왼쪽에서 제안을 받아 적용하면 여기에 쌓여요."
                                    color: window.muted
                                    font.pixelSize: 12
                                }
                                Repeater {
                                    model: dashboard.llmHistory
                                    delegate: Rectangle {
                                        id: historyCard
                                        objectName: "llmHistoryCard"
                                        required property var modelData
                                        // 2026-11-11: the command and the hold time can be changed later by hand
                                        property bool editing: false
                                        property string editType: "hotkey"
                                        property string editValue: ""
                                        property real editHold: -1
                                        readonly property bool hasHold: modelData.hold_seconds !== undefined
                                        function startEdit() {
                                            editType = String(modelData.action_type || "hotkey")
                                            editValue = editType === "macro" ? "" : String(modelData.action_value || "")
                                            if (editType === "macro") editType = "hotkey"     // a macro is re-made through the AI
                                            editHold = hasHold ? Number(modelData.hold_seconds) : -1
                                            editing = true
                                        }
                                        visible: modelData.current || historyAll.checked
                                        Layout.fillWidth: true
                                        implicitHeight: visible ? Math.max(historyCol.implicitHeight, historyButtons.implicitHeight,
                                                                           handPic.visible ? handPic.implicitHeight : 0) + 16 : 0
                                        radius: 8
                                        color: modelData.current ? Theme.Studio.paper : Theme.Studio.surface
                                        border.color: window.line
                                        // 2026-11-11: which hand this command was registered with, from that gesture's own saved
                                        // joints (src/gesture_preview.py), looping like a short clip
                                        readonly property var preview: dashboard.gesturePreview(String(modelData.gesture_key || ""))
                                        RowLayout {
                                            anchors.left: parent.left
                                            anchors.right: parent.right
                                            anchors.top: parent.top
                                            anchors.margins: 8
                                            spacing: 8
                                            ColumnLayout {
                                                id: handPic
                                                objectName: "llmHistoryHand"
                                                readonly property var frames: historyCard.preview.frames || []
                                                visible: frames.length > 0
                                                Layout.alignment: Qt.AlignTop
                                                Layout.preferredWidth: 96
                                                spacing: 2
                                                Rectangle {
                                                    Layout.preferredWidth: 96
                                                    Layout.preferredHeight: 96
                                                    radius: 8
                                                    color: "#0E1B26"
                                                    Canvas {
                                                        id: handCanvas
                                                        anchors.fill: parent
                                                        property int frame: 0
                                                        onFrameChanged: requestPaint()
                                                        onAvailableChanged: if (available) requestPaint()
                                                        Timer {
                                                            interval: 1000 / Math.max(1, historyCard.preview.fps || 15)
                                                            repeat: true
                                                            running: handPic.visible && historyCard.visible && handPic.frames.length > 1
                                                            onTriggered: handCanvas.frame = (handCanvas.frame + 1) % handPic.frames.length
                                                        }
                                                        onPaint: {
                                                            if (!available) return
                                                            let c = getContext("2d"); c.reset()
                                                            let fs = handPic.frames
                                                            if (!fs.length) return
                                                            let p = fs[Math.min(frame, fs.length - 1)]
                                                            let W = width, H = height
                                                            let chains = [[0,1,2,3,4],[0,5,6,7,8],[0,9,10,11,12],[0,13,14,15,16],[0,17,18,19,20],[5,9,13,17]]
                                                            c.lineCap = "round"; c.lineJoin = "round"
                                                            for (let pass = 0; pass < 2; pass++) {
                                                                c.strokeStyle = pass === 0 ? "rgba(0,0,0,0.55)" : Theme.Studio.mint
                                                                c.lineWidth = pass === 0 ? 4 : 2
                                                                for (let chain of chains) {
                                                                    c.beginPath()
                                                                    for (let i = 0; i < chain.length; i++) {
                                                                        let v = p[chain[i]]
                                                                        if (i === 0) c.moveTo(v[0] * W, v[1] * H); else c.lineTo(v[0] * W, v[1] * H)
                                                                    }
                                                                    c.stroke()
                                                                }
                                                            }
                                                            c.fillStyle = "#FFFFFF"
                                                            for (let i of [4, 8, 12, 16, 20]) {
                                                                c.beginPath(); c.arc(p[i][0] * W, p[i][1] * H, 2.4, 0, Math.PI * 2); c.fill()
                                                            }
                                                            // the movement: an arrow for a direction, a word for the rest
                                                            let m = historyCard.preview.move || ""
                                                            let dirs = {"left": [-1, 0], "right": [1, 0], "up": [0, -1], "down": [0, 1],
                                                                        "diag_up_left": [-.7, -.7], "diag_up_right": [.7, -.7],
                                                                        "diag_down_left": [-.7, .7], "diag_down_right": [.7, .7]}
                                                            if (dirs[m]) {
                                                                let d = dirs[m], cx = W - 18, cy = 18, r = 11
                                                                let x0 = cx - d[0] * r, y0 = cy - d[1] * r, x1 = cx + d[0] * r, y1 = cy + d[1] * r
                                                                c.strokeStyle = "#F2B544"; c.fillStyle = "#F2B544"; c.lineWidth = 2.5
                                                                c.beginPath(); c.moveTo(x0, y0); c.lineTo(x1, y1); c.stroke()
                                                                let a = Math.atan2(y1 - y0, x1 - x0)
                                                                c.beginPath(); c.moveTo(x1, y1)
                                                                c.lineTo(x1 - 7 * Math.cos(a - .5), y1 - 7 * Math.sin(a - .5))
                                                                c.lineTo(x1 - 7 * Math.cos(a + .5), y1 - 7 * Math.sin(a + .5))
                                                                c.closePath(); c.fill()
                                                            } else if (m) {
                                                                let label = m === "double_pinch" ? "두 번 집기" : m.indexOf("draw_") === 0 ? "그리기"
                                                                          : m === "sequence" ? "" : ""
                                                                if (m === "sequence") {
                                                                    let st = historyCard.preview.steps || [], n = 0
                                                                    for (let i = 0; i < st.length; i++) if (frame >= st[i]) n = i + 1
                                                                    label = n + " / " + st.length
                                                                }
                                                                if (label) {
                                                                    c.font = "bold 11px sans-serif"; c.fillStyle = "#F2B544"
                                                                    c.fillText(label, 6, 14)
                                                                }
                                                            }
                                                        }
                                                    }
                                                }
                                                Text {
                                                    Layout.preferredWidth: 96
                                                    text: historyCard.preview.source || ""
                                                    font.pixelSize: 10
                                                    color: window.muted
                                                    wrapMode: Text.Wrap
                                                    horizontalAlignment: Text.AlignHCenter
                                                }
                                            }
                                            ColumnLayout {
                                                id: historyCol
                                                Layout.fillWidth: true
                                                spacing: 2
                                                // the name on its own line, wrapping: a long name used to push the marks and the
                                                // buttons out of the card (2026-11-11, seen when the "motion mode only" mark was added)
                                                TextLabel {
                                                    Layout.fillWidth: true
                                                    text: historyCard.modelData.gesture_name
                                                          + (historyCard.modelData.app_match ? "  ·  " + historyCard.modelData.app_match + "에서만" : "")
                                                    font.bold: true
                                                    wrapMode: Text.Wrap
                                                }
                                                RowLayout {
                                                    Layout.fillWidth: true
                                                    spacing: 6
                                                    Chip {
                                                        text: historyCard.modelData.current ? "적용 중" : "이후 바뀜"
                                                        warn: !historyCard.modelData.current
                                                    }
                                                    // which world the gesture lives in (2026-11-12): the two hand modes are separate
                                                    Chip {
                                                        objectName: "llmModeChip"
                                                        visible: !!historyCard.modelData.mode_name && historyCard.modelData.mode !== "motion"
                                                        text: historyCard.modelData.mode_works === false
                                                              ? historyCard.modelData.mode_name + " 전용 · 지금 방식에서는 안 쓰임"
                                                              : historyCard.modelData.mode === "all" ? "모든 손 모드" : historyCard.modelData.mode_name + " 전용"
                                                        warn: historyCard.modelData.mode_works === false
                                                    }
                                                    Chip {
                                                        visible: historyCard.hasHold
                                                        text: "유지 " + Number(historyCard.modelData.hold_seconds || 0).toFixed(1) + "초"
                                                    }
                                                    Chip {
                                                        objectName: "llmMotionOnlyChip"
                                                        visible: historyCard.modelData.motion_only === true
                                                        text: "모션 모드에서만"
                                                    }
                                                    Item { Layout.fillWidth: true }
                                                }
                                                TextLabel {
                                                    Layout.fillWidth: true
                                                    text: (historyCard.modelData.before_text || "") + "  →  "
                                                          + ((historyCard.modelData.steps || []).length ? "여러 단계" : historyCard.modelData.after)
                                                    font.pixelSize: 13
                                                    wrapMode: Text.Wrap
                                                }
                                                Repeater {
                                                    model: historyCard.modelData.steps || []
                                                    delegate: TextLabel {
                                                        required property var modelData
                                                        required property int index
                                                        Layout.fillWidth: true
                                                        Layout.leftMargin: 12
                                                        text: (index + 1) + ". " + window.stepText(modelData)
                                                        font.pixelSize: 13
                                                        wrapMode: Text.Wrap
                                                    }
                                                }
                                                TextLabel {
                                                    // 2026-11-12: a gesture registered without an AI history line (older app, copied
                                                    // config) is listed too, so it can be seen, changed and deleted here
                                                    objectName: "llmAdoptedNote"
                                                    Layout.fillWidth: true
                                                    visible: historyCard.modelData.adopted === true
                                                    text: "AI 기록 없이 등록된 동작 · 목록에 " + historyCard.modelData.time + " 추가"
                                                    color: window.muted
                                                    font.pixelSize: 11
                                                    wrapMode: Text.Wrap
                                                }
                                                TextLabel {
                                                    Layout.fillWidth: true
                                                    visible: (historyCard.modelData.request || "") !== ""
                                                    text: "요청: " + historyCard.modelData.request + "  ·  " + historyCard.modelData.time
                                                          + (historyCard.modelData.edited ? "  ·  직접 고침 " + historyCard.modelData.edited : "")
                                                    color: window.muted
                                                    font.pixelSize: 11
                                                    wrapMode: Text.Wrap
                                                }
                                                // ---- one more look at this command's hand shape, started from its editor
                                                // (poseTeachMore): what is going on stays on the card, because the list is
                                                // built again with every step and the editor closes
                                                TextLabel {
                                                    id: teachLine
                                                    objectName: "llmHistoryTeachLine"
                                                    readonly property var teach: dashboard.llmContext.teach || {}
                                                    readonly property var pose: dashboard.llmContext.pose || {}
                                                    readonly property bool mine: !!historyCard.modelData.teach_posture
                                                                                 && teach.focus === historyCard.modelData.teach_posture
                                                    visible: mine && text.length > 0
                                                    Layout.fillWidth: true
                                                    Layout.topMargin: 4
                                                    text: !mine ? ""
                                                        : teach.adding && pose.state === "countdown" ? ("'" + teach.focusName + "' 모양으로 손을 준비하세요… " + pose.seconds)
                                                        : teach.adding && pose.state === "holding" ? ("그대로 유지! " + Math.round(pose.progress * 100) + "%")
                                                        : teach.adding ? ("'" + teach.focusName + "' 견본으로 추가하는 중…")
                                                        : (teach.text || "")
                                                    color: teach.state === "error" ? Theme.Studio.danger : Theme.Studio.mintDark
                                                    font.pixelSize: 12
                                                    font.bold: true
                                                    wrapMode: Text.Wrap
                                                }
                                                // ---- the editor: hold time (hold gestures) and command
                                                ColumnLayout {
                                                    objectName: "llmHistoryEditor"
                                                    visible: historyCard.editing
                                                    Layout.fillWidth: true
                                                    Layout.topMargin: 6
                                                    spacing: 6
                                                    RowLayout {
                                                        visible: historyCard.hasHold
                                                        Layout.fillWidth: true
                                                        spacing: 6
                                                        TextLabel { text: "발동까지 유지"; font.pixelSize: 12; font.bold: true }
                                                        Slider {
                                                            id: holdSlider
                                                            objectName: "llmHoldSlider"
                                                            Layout.fillWidth: true
                                                            from: historyCard.modelData.hold_min || 0.4
                                                            to: historyCard.modelData.hold_max || 3.0
                                                            stepSize: 0.1
                                                            snapMode: Slider.SnapAlways
                                                            value: historyCard.editHold
                                                            onMoved: historyCard.editHold = Math.round(value * 10) / 10
                                                        }
                                                        TextLabel {
                                                            text: historyCard.editHold.toFixed(1) + "초"
                                                                  + (historyCard.editHold <= (historyCard.modelData.hold_min || 0.4) + 0.001 ? " (최소)" : "")
                                                            font.pixelSize: 12
                                                        }
                                                        CompactButton {
                                                            text: "최소로"
                                                            enabled: historyCard.editHold > (historyCard.modelData.hold_min || 0.4) + 0.001
                                                            onClicked: historyCard.editHold = historyCard.modelData.hold_min || 0.4
                                                        }
                                                    }
                                                    TextLabel {
                                                        visible: historyCard.hasHold
                                                        Layout.fillWidth: true
                                                        text: (historyCard.modelData.hold_min || 0.4) >= 1.0
                                                              ? "평소 조작 중에도 자주 하는 손 모양이라 최소 1초예요. 잘못 실행되면 늘려 보세요."
                                                              : "짧을수록 빨리 실행되고, 지나가던 손 모양에 잘못 실행되면 늘려 보세요."
                                                        color: window.muted
                                                        font.pixelSize: 11
                                                        wrapMode: Text.Wrap
                                                    }
                                                    // 2026-11-12 request ("수정 메뉴에 mlp 추가 학습시키기 옵션도"): the hand shape of
                                                    // this command shown once more = one more example for the taught model
                                                    TextLabel {
                                                        visible: !!historyCard.modelData.teach_posture
                                                        text: "손 모양 인식 추가 학습 (MLP)"
                                                        font.pixelSize: 12
                                                        font.bold: true
                                                    }
                                                    ColumnLayout {
                                                        visible: !!historyCard.modelData.teach_posture
                                                        Layout.fillWidth: true
                                                        spacing: 4
                                                        TextLabel {
                                                            readonly property var teach: dashboard.llmContext.teach || {}
                                                            readonly property int n: (teach.counts || {})[historyCard.modelData.teach_posture] || 0
                                                            Layout.fillWidth: true
                                                            text: "이 손 모양을 한 번 더 보여 주면 견본으로 저장하고 다시 학습해요 (지금 견본 " + n + "개"
                                                                  + (n < 1 ? ", 2개부터 학습" : "") + "). 누르면 3초 뒤 2초 동안 손을 봐요. "
                                                                  + "잘 안 걸리는 각도·거리로 보여 주면 좋아요."
                                                            color: window.muted
                                                            font.pixelSize: 11
                                                            wrapMode: Text.Wrap
                                                        }
                                                        CompactButton {
                                                            objectName: "llmEditTeach"
                                                            Layout.alignment: Qt.AlignRight
                                                            text: "✋ 보여 주고 추가 학습"
                                                            enabled: (dashboard.llmContext.teach || {}).state !== "training"
                                                            onClicked: dashboard.poseTeachMore(historyCard.modelData.teach_posture)
                                                        }
                                                    }
                                                    TextLabel { text: "실행할 명령"; font.pixelSize: 12; font.bold: true }
                                                    Flow {
                                                        Layout.fillWidth: true
                                                        spacing: 6
                                                        Repeater {
                                                            model: [["hotkey", "단축키"], ["youtube_key", "유튜브·미디어 키"],
                                                                    ["launch_app", "프로그램·폴더·웹사이트"], ["mouse_action", "마우스·시스템"]]
                                                            delegate: CompactButton {
                                                                required property var modelData
                                                                text: modelData[1]
                                                                accent: historyCard.editType === modelData[0]
                                                                onClicked: {
                                                                    if (historyCard.editType !== modelData[0]) historyCard.editValue = ""
                                                                    historyCard.editType = modelData[0]
                                                                }
                                                            }
                                                        }
                                                    }
                                                    TextLabel {
                                                        visible: historyCard.modelData.action_type === "macro"
                                                        Layout.fillWidth: true
                                                        text: "지금은 여러 단계(매크로)예요. 여기서 고르면 한 가지 명령으로 바뀌어요. 단계를 바꾸려면 AI에게 다시 부탁해 주세요."
                                                        color: window.muted
                                                        font.pixelSize: 11
                                                        wrapMode: Text.Wrap
                                                    }
                                                    TextField {
                                                        objectName: "llmEditValue"
                                                        visible: historyCard.editType !== "mouse_action"
                                                        Layout.fillWidth: true
                                                        text: historyCard.editValue
                                                        placeholderText: historyCard.editType === "hotkey" ? "예: ctrl+shift+t, win+d, f5"
                                                                       : historyCard.editType === "youtube_key" ? "예: k (재생/정지), f (전체 화면), m (음소거)"
                                                                       : "예: chrome.exe --incognito https://www.youtube.com 또는 %USERPROFILE%\\Desktop\\폴더"
                                                        font.pixelSize: 13
                                                        onTextEdited: historyCard.editValue = text
                                                    }
                                                    StyledComboBox {
                                                        visible: historyCard.editType === "mouse_action"
                                                        Layout.fillWidth: true
                                                        model: dashboard.mouseActionPresets
                                                        textRole: "label"
                                                        currentIndex: {
                                                            var ps = dashboard.mouseActionPresets
                                                            for (var i = 0; i < ps.length; i++) if (ps[i].value === historyCard.editValue) return i
                                                            return -1
                                                        }
                                                        onActivated: function (i) { historyCard.editValue = dashboard.mouseActionPresets[i].value }
                                                    }
                                                    RowLayout {
                                                        Layout.fillWidth: true
                                                        spacing: 6
                                                        Item { Layout.fillWidth: true }
                                                        CompactButton {
                                                            text: "취소"
                                                            onClicked: historyCard.editing = false
                                                        }
                                                        CompactButton {
                                                            objectName: "llmEditSave"
                                                            text: "저장"
                                                            accent: true
                                                            enabled: historyCard.editValue.trim().length > 0
                                                            onClicked: {
                                                                if (dashboard.editLlmConnection(historyCard.modelData.index, historyCard.editType,
                                                                                                historyCard.editValue.trim(), historyCard.hasHold ? historyCard.editHold : -1))
                                                                    historyCard.editing = false
                                                            }
                                                        }
                                                    }
                                                }
                                            }
                                            ColumnLayout {
                                                id: historyButtons
                                                Layout.alignment: Qt.AlignTop
                                                Layout.minimumWidth: implicitWidth      // as wide as its widest button (a fixed 118 px let the labels spill out, 2026-11-11)
                                                spacing: 4
                                                CompactButton {
                                                    objectName: "llmEditButton"
                                                    visible: historyCard.modelData.editable === true && !historyCard.editing
                                                    Layout.fillWidth: true
                                                    text: "수정"                       // the editor below says what can change (time, command)
                                                    onClicked: historyCard.startEdit()
                                                }
                                                CompactButton {
                                                    // 2026-11-11: the gesture counts only while motion mode is on (press again: everywhere)
                                                    objectName: "llmMotionOnlyButton"
                                                    visible: historyCard.modelData.mode_option === true && !historyCard.editing
                                                    Layout.fillWidth: true
                                                    text: historyCard.modelData.motion_only ? "평소에도 쓰기" : "모션 모드에서만"
                                                    onClicked: dashboard.setLlmMotionOnly(historyCard.modelData.index, !historyCard.modelData.motion_only)
                                                }
                                                CompactButton {
                                                    // back one step: what was there just before this AI change
                                                    visible: historyCard.modelData.current && !historyCard.modelData.created
                                                    Layout.fillWidth: true
                                                    text: "되돌리기"
                                                    onClicked: confirmDialog.ask("AI 연결 되돌리기",
                                                        "'" + historyCard.modelData.gesture_name + "'을(를) " + (historyCard.modelData.before_text || "이전 연결") + "(으)로 되돌립니다.",
                                                        "되돌리기", function () { dashboard.undoLlmConnection(historyCard.modelData.index) })
                                                }
                                                CompactButton {
                                                    // the connection itself goes: a created gesture is deleted, an existing one gets its built-in command
                                                    visible: historyCard.modelData.current
                                                    Layout.fillWidth: true
                                                    text: "삭제"
                                                    danger: true
                                                    onClicked: confirmDialog.ask("AI 연결 삭제",
                                                        (historyCard.modelData.created || historyCard.modelData.custom) && !historyCard.modelData.app_match
                                                            ? "'" + historyCard.modelData.gesture_name + "' 동작을 지웁니다. 지운 뒤에는 그 손짓에 아무 명령도 실행되지 않아요. (목록 아래 '지운 동작'에서 되살릴 수 있어요)"
                                                            : historyCard.modelData.app_match
                                                                ? "'" + historyCard.modelData.gesture_name + "'의 " + historyCard.modelData.app_match + " 전용 명령을 지웁니다."
                                                                : "'" + historyCard.modelData.gesture_name + "'에 AI가 연결한 명령을 지우고 기본 명령으로 돌립니다.",
                                                        "삭제", function () { dashboard.deleteLlmConnection(historyCard.modelData.index) })
                                                }
                                                CompactButton {
                                                    visible: !historyCard.modelData.current
                                                    text: "목록에서 지우기"
                                                    onClicked: dashboard.forgetLlmConnection(historyCard.modelData.index)
                                                }
                                            }
                                        }
                                    }
                                }
                                // 2026-11-12 ("손바닥 폈을때 바탕화면 보기 명령어 어디갔냐?"): a deleted gesture is kept and
                                // can be brought back (src/llm_binding.History.restore)
                                RowLayout {
                                    Layout.fillWidth: true
                                    Layout.topMargin: 6
                                    visible: dashboard.llmDeleted.length > 0
                                    SectionLabel { text: "지운 동작 (" + dashboard.llmDeleted.length + ")" }
                                    Item { Layout.fillWidth: true }
                                    CheckBox { id: deletedShown; objectName: "llmDeletedShown"; text: "보기"; checked: false }
                                }
                                Repeater {
                                    model: deletedShown.checked ? dashboard.llmDeleted : []
                                    delegate: Rectangle {
                                        objectName: "llmDeletedCard"
                                        required property var modelData
                                        Layout.fillWidth: true
                                        implicitHeight: deletedRow.implicitHeight + 14
                                        radius: 8
                                        color: Theme.Studio.surface
                                        border.color: window.line
                                        RowLayout {
                                            id: deletedRow
                                            anchors.left: parent.left
                                            anchors.right: parent.right
                                            anchors.verticalCenter: parent.verticalCenter
                                            anchors.margins: 8
                                            spacing: 8
                                            ColumnLayout {
                                                Layout.fillWidth: true
                                                spacing: 2
                                                TextLabel {
                                                    Layout.fillWidth: true
                                                    text: modelData.name + "  →  " + (modelData.after || "")
                                                    font.pixelSize: 13
                                                    wrapMode: Text.Wrap
                                                }
                                                TextLabel {
                                                    Layout.fillWidth: true
                                                    text: "지운 때 " + modelData.time
                                                    color: window.muted
                                                    font.pixelSize: 11
                                                }
                                            }
                                            CompactButton {
                                                objectName: "llmRestoreButton"
                                                text: "되살리기"
                                                onClicked: dashboard.restoreDeletedGesture(modelData.trash_index)
                                            }
                                        }
                                    }
                                }
                                }
                            }
                        }
                    }

        }
    }

    // Profiles (2026-11-11): pick, make, rename, reset, delete, export, import (qt_dashboard.py "profiles").
    // A profile keeps only what differs from the default state; none, or an untouched one, is the default state.
    Dialog {
        id: profileManager
        objectName: "profileManager"
        property string renaming: ""        // the profile whose name is being edited
        anchors.centerIn: parent
        width: Math.min(660, window.width - 48)
        height: Math.min(window.height - 48, implicitHeight)
        modal: true
        title: "프로필"
        padding: 18
        background: Rectangle { radius: 14; color: "white"; border.color: window.line }
        header: TextLabel {
            text: profileManager.title
            font.pixelSize: 17
            font.bold: true
            leftPadding: 18; rightPadding: 18; topPadding: 16
        }
        onClosed: renaming = ""
        contentItem: ScrollView {
            id: profileScroll
            clip: true
            contentWidth: availableWidth
            implicitHeight: profileCol.implicitHeight
            ColumnLayout {
                id: profileCol
                width: profileScroll.availableWidth
                spacing: 8
                TextLabel {
                    Layout.fillWidth: true
                    wrapMode: Text.Wrap
                    font.pixelSize: 12
                    color: window.muted
                    text: "프로필은 기본 상태에서 바꾼 것만 기억해요: 엔진 설정, 동작 연결(복합 동작·모션 포함), 화면 옵션. "
                          + "프로필이 없거나 아무것도 바꾸지 않은 프로필은 앱의 기본 상태 그대로입니다."
                }
                Repeater {
                    model: dashboard.profileRows
                    delegate: Rectangle {
                        id: pRow
                        required property var modelData
                        readonly property string name: modelData.name
                        objectName: "profileRow"
                        Layout.fillWidth: true
                        implicitHeight: pRowCol.implicitHeight + 18
                        radius: 10
                        color: modelData.active ? "#E6F8F3" : "white"
                        border.color: modelData.active ? "#46E5BD" : window.line
                        border.width: modelData.active ? 2 : 1
                        ColumnLayout {
                            id: pRowCol
                            anchors.fill: parent
                            anchors.margins: 9
                            spacing: 6
                            RowLayout {
                                Layout.fillWidth: true
                                spacing: 8
                                ColumnLayout {
                                    Layout.fillWidth: true
                                    Layout.minimumWidth: 0
                                    spacing: 1
                                    TextLabel {
                                        Layout.fillWidth: true
                                        text: pRow.modelData.title + (pRow.modelData.active ? "  ·  사용 중" : "")
                                        font.bold: true
                                        font.pixelSize: 14
                                        elide: Text.ElideRight
                                    }
                                    TextLabel {
                                        Layout.fillWidth: true
                                        text: pRow.modelData.note
                                        font.pixelSize: 12
                                        color: window.muted
                                        wrapMode: Text.Wrap
                                    }
                                }
                                CompactButton {
                                    visible: !pRow.modelData.active
                                    primary: true
                                    implicitHeight: 32
                                    leftPadding: 12; rightPadding: 12
                                    enabled: !dashboard.calibratingPointer && !dashboard.trackingActive
                                    text: pRow.name === "" ? "프로필 끄기" : "이 프로필 쓰기"
                                    onClicked: dashboard.selectProfile(pRow.name)
                                }
                            }
                            RowLayout {
                                visible: pRow.name !== "" && profileManager.renaming === pRow.name
                                Layout.fillWidth: true
                                spacing: 6
                                TextField {
                                    id: renameField
                                    Layout.fillWidth: true
                                    implicitHeight: 32
                                    font.pixelSize: 13
                                    text: pRow.name
                                    selectByMouse: true
                                    onAccepted: if (dashboard.renameProfile(pRow.name, text)) profileManager.renaming = ""
                                }
                                CompactButton {
                                    text: "바꾸기"
                                    primary: true
                                    implicitHeight: 32
                                    enabled: renameField.text.trim() !== "" && renameField.text.trim() !== pRow.name
                                    onClicked: if (dashboard.renameProfile(pRow.name, renameField.text)) profileManager.renaming = ""
                                }
                                CompactButton { text: "취소"; implicitHeight: 32; onClicked: profileManager.renaming = "" }
                            }
                            RowLayout {
                                visible: pRow.name !== "" && profileManager.renaming !== pRow.name
                                Layout.fillWidth: true
                                spacing: 6
                                CompactButton { text: "이름 바꾸기"; onClicked: profileManager.renaming = pRow.name }
                                CompactButton { text: "내보내기"; onClicked: dashboard.exportProfile(pRow.name) }
                                CompactButton {
                                    text: "기본 상태로 되돌리기"
                                    enabled: pRow.modelData.changed > 0
                                    onClicked: confirmDialog.ask("기본 상태로 되돌리기",
                                        "「" + pRow.name + "」 프로필에서 바꾼 설정·동작 연결·화면 옵션을 모두 지우고 기본 상태로 되돌립니다. 프로필 자체는 남아요.",
                                        "되돌리기", function () { dashboard.resetProfile(pRow.name) })
                                }
                                Item { Layout.fillWidth: true }
                                CompactButton {
                                    text: "삭제"
                                    danger: true
                                    onClicked: confirmDialog.ask("프로필 삭제",
                                        "「" + pRow.name + "」 프로필과 그 안에서 바꾼 것을 모두 지웁니다. 되돌릴 수 없어요. 남기려면 먼저 [내보내기]를 하세요.",
                                        "삭제", function () { dashboard.deleteProfile(pRow.name) })
                                }
                            }
                        }
                    }
                }
                Divider {}
                RowLayout {
                    Layout.fillWidth: true
                    spacing: 6
                    TextField {
                        id: newProfileField
                        objectName: "newProfileField"
                        Layout.fillWidth: true
                        implicitHeight: 34
                        font.pixelSize: 13
                        placeholderText: "새 프로필 이름 (예: 집 PC, 민수)"
                        selectByMouse: true
                        onAccepted: if (text.trim() !== "" && dashboard.createProfile(text)) text = ""
                    }
                    CompactButton {
                        text: "새 프로필 만들기"
                        primary: true
                        implicitHeight: 34
                        leftPadding: 12; rightPadding: 12
                        enabled: newProfileField.text.trim() !== ""
                        onClicked: if (dashboard.createProfile(newProfileField.text)) newProfileField.text = ""
                    }
                    CompactButton {
                        text: "파일에서 가져오기"
                        implicitHeight: 34
                        leftPadding: 12; rightPadding: 12
                        onClicked: dashboard.importProfile()
                    }
                }
                RowLayout {
                    Layout.fillWidth: true
                    spacing: 8
                    TextLabel {
                        objectName: "profileMessage"
                        Layout.fillWidth: true
                        text: dashboard.profileMessage
                        font.pixelSize: 12
                        font.bold: true
                        color: "#0369A1"
                        wrapMode: Text.Wrap
                    }
                    CompactButton {
                        text: "닫기"
                        implicitHeight: 34
                        leftPadding: 16; rightPadding: 16
                        onClicked: profileManager.close()
                    }
                }
            }
        }
    }

    // Palm (Dan) mode settings: what used to sit on the main screen's side panel, plus the engine sliders (Tk window)
    Dialog {
        id: palmSettings
        objectName: "palmSettings"
        anchors.centerIn: parent
        width: Math.min(680, window.width - 48)
        height: Math.min(window.height - 48, implicitHeight)
        modal: true
        title: "설정"
        standardButtons: Dialog.Close
        contentItem: ScrollView {
            id: palmSettingsScroll
            clip: true
            contentWidth: availableWidth
            implicitHeight: palmSettingsCol.implicitHeight
            ColumnLayout {
                id: palmSettingsCol
                width: palmSettingsScroll.availableWidth
                spacing: 10
                SectionLabel { text: "모션 모드" }
                ActionButton {
                    objectName: "settingsMotionButton"
                    Layout.fillWidth: true
                    enabled: !dashboard.calibratingPointer && !dashboard.trackingActive
                    text: dashboard.motionLabel
                    accent: dashboard.motionLabel.indexOf("켜짐") >= 0
                    onClicked: dashboard.toggleMotion()
                }
                // the other hand as a motion hand (src/other_hand_motion.py, 2026-11-12)
                ActionButton {
                    objectName: "settingsOtherMotion"
                    Layout.fillWidth: true
                    text: dashboard.otherMotionOn ? "다른 손으로 모션 · 켜짐 (눌러서 끄기)" : "다른 손으로 모션 · 꺼짐 (눌러서 켜기)"
                    accent: dashboard.otherMotionOn
                    onClicked: dashboard.setOtherMotion(!dashboard.otherMotionOn)
                }
                TextLabel {
                    Layout.fillWidth: true
                    text: "조작하지 않는 손(오른손으로 조작하면 왼손)을 펴서 0.3초 들고 있으면 그 손으로 모션 명령을 보내요. 손 펴고 왼쪽/오른쪽 = 다음/이전 탭, 검지만 펴고 왼쪽/오른쪽 = 앞으로/뒤로. "
                          + "손을 내리면 끝나고, 조작하는 손은 그동안에도 커서를 움직여요. 두 손이 다 카메라에 보여야 하고, [손 자르기]가 켜져 있으면 안 보여요."
                    color: window.muted
                    font.pixelSize: 12
                    wrapMode: Text.Wrap
                }
                Divider {}
                // ---------------------------------------------------------------- the skeletons' look (src/skeleton_style.py)
                SectionLabel { text: "스켈레톤 표시" }
                ColumnLayout {
                    id: skelBox
                    objectName: "skeletonStyleBox"
                    Layout.fillWidth: true
                    spacing: 6
                    readonly property var values: dashboard.skeletonStyle.values || {}
                    readonly property var presets: dashboard.skeletonStyle.presets || []
                    readonly property var ranges: dashboard.skeletonStyle.ranges || {}
                    Repeater {
                        // [key, label]
                        model: [["main", "카메라 화면 · 조작하는 손"], ["other", "카메라 화면 · 다른 손 (모션)"],
                                ["vh_line", "바탕화면 가상 손 · 선"], ["vh_joint", "바탕화면 가상 손 · 관절"]]
                        delegate: ColumnLayout {
                            required property var modelData
                            readonly property string key: modelData[0]
                            readonly property string current: skelBox.values[key] || ""
                            Layout.fillWidth: true
                            spacing: 3
                            TextLabel { text: modelData[1]; font.pixelSize: 12 }
                            Flow {
                                Layout.fillWidth: true
                                spacing: 5
                                Repeater {
                                    model: skelBox.presets
                                    delegate: Rectangle {
                                        required property var modelData
                                        objectName: "skelSwatch_" + parent.parent.key + "_" + modelData
                                        width: 24; height: 24; radius: 12
                                        color: modelData
                                        border.width: parent.parent.current === modelData ? 3 : 1
                                        border.color: parent.parent.current === modelData ? window.ink : window.line
                                        MouseArea {
                                            anchors.fill: parent
                                            cursorShape: Qt.PointingHandCursor
                                            onClicked: dashboard.setSkeletonStyle(parent.parent.parent.key, parent.modelData)
                                        }
                                    }
                                }
                                // any other colour as #RRGGBB
                                TextField {
                                    objectName: "skelHex_" + parent.parent.key
                                    width: 92; height: 26
                                    font.pixelSize: 12
                                    text: parent.parent.current
                                    placeholderText: "#RRGGBB"
                                    onEditingFinished: if (!dashboard.setSkeletonStyle(parent.parent.key, text)) text = parent.parent.current
                                }
                            }
                        }
                    }
                    Repeater {
                        // [key, label, scale shown, unit]
                        model: [["preview_alpha", "카메라 화면 스켈레톤 불투명도", 100, "%"], ["vh_alpha", "바탕화면 가상 손 불투명도", 100, "%"],
                                ["width", "선 굵기", 1, "배"]]
                        delegate: RowLayout {
                            required property var modelData
                            readonly property string key: modelData[0]
                            readonly property var range: skelBox.ranges[key] || [0, 1]
                            Layout.fillWidth: true
                            spacing: 6
                            TextLabel { text: modelData[1]; font.pixelSize: 12; Layout.preferredWidth: 190 }
                            Slider {
                                objectName: "skelSetting_" + parent.key
                                Layout.fillWidth: true
                                from: parent.range[0]
                                to: parent.range[1]
                                stepSize: 0.05
                                snapMode: Slider.SnapAlways
                                value: skelBox.values[parent.key] !== undefined ? skelBox.values[parent.key] : 1
                                onPressedChanged: if (!pressed) dashboard.setSkeletonStyle(parent.key, value)
                            }
                            TextLabel {
                                Layout.preferredWidth: 70
                                horizontalAlignment: Text.AlignRight
                                text: modelData[2] === 100 ? Math.round((skelBox.values[parent.key] || 1) * 100) + " %"
                                                           : Number(skelBox.values[parent.key] || 1).toFixed(2) + " 배"
                                font.pixelSize: 12
                                color: window.muted
                            }
                        }
                    }
                    RowLayout {
                        Layout.fillWidth: true
                        TextLabel {
                            Layout.fillWidth: true
                            text: "집기 선(노랑·초록·빨강)과 주먹 스크롤 중 주황은 신호라 색이 바뀌지 않아요."
                            color: window.muted
                            font.pixelSize: 11
                            wrapMode: Text.Wrap
                        }
                        CompactButton {
                            objectName: "skeletonStyleReset"
                            text: "기본값으로"
                            onClicked: dashboard.resetSkeletonStyle()
                        }
                    }
                }
                Divider {}
                SectionLabel { text: "커서 방향 보정" }
                TextLabel {
                    Layout.fillWidth: true
                    text: dashboard.palmCalibrated ? "보정이 저장되어 있어요." : "아직 보정하지 않았어요."
                    color: window.muted
                    font.pixelSize: 12
                    wrapMode: Text.Wrap
                }
                RowLayout {
                    Layout.fillWidth: true
                    spacing: 6
                    ActionButton {
                        objectName: "settingsPalmCalibrate"
                        Layout.fillWidth: true
                        enabled: !dashboard.palmCalibrating && !dashboard.trackingActive
                        text: dashboard.palmCalibrated ? "커서 방향 보정 다시" : "커서 방향 보정"
                        onClicked: { palmSettings.close(); dashboard.beginPalmCalibration() }
                    }
                    ActionButton {
                        visible: dashboard.palmCalibrated && !dashboard.palmCalibrating
                        text: "초기화"
                        onClicked: confirmDialog.ask("커서 방향 보정 초기화", "저장한 커서 방향 보정을 지웁니다.", "초기화",
                                                     function () { dashboard.resetPalmCalibration() })
                    }
                }
                Divider {}
                // ---------------------------------------------------------------- pointing mode (src/point_mode.py)
                SectionLabel { text: "포인팅 모드" }
                ActionButton {
                    objectName: "pointModeButton"
                    Layout.fillWidth: true
                    text: dashboard.pointModeOn ? "포인팅 모드 · 켜짐 (눌러서 끄기)" : "포인팅 모드 · 꺼짐 (눌러서 켜기)"
                    accent: dashboard.pointModeOn
                    onClicked: dashboard.setPointMode(!dashboard.pointModeOn)
                }
                TextLabel {
                    Layout.fillWidth: true
                    text: "따로 켤 필요 없이 손 모양만으로 바뀌어요. 엄지를 위로 펴고 검지를 비스듬히 펴면(권총 모양) 검지 끝으로 커서가 움직이고, "
                          + "파일·폴더 위에서 1초 멈추면 더블클릭해요. 검지·중지를 붙여 함께 펴면(엄지도 위로) 같은 방법으로 우클릭. "
                          + "파일·폴더가 아닌 곳에서는 멈춰도 클릭하지 않아요."
                    color: window.muted
                    font.pixelSize: 12
                    wrapMode: Text.Wrap
                }
                // the details (2026-11-11 request: "포인팅 모드도 설정 안에서 상세 설정") - src/point_mode.SETTINGS
                ColumnLayout {
                    objectName: "pointSettingsBox"
                    visible: dashboard.pointModeOn
                    Layout.fillWidth: true
                    spacing: 4
                    readonly property var values: dashboard.pointSettings.values || {}
                    readonly property var ranges: dashboard.pointSettings.ranges || {}
                    id: pointBox
                    Repeater {
                        // [name, label, unit, step, how the value is written]
                        model: [["dwell", "발동 대기 시간", "초", 0.1, 1],
                                ["area_px", "손가락 끝 주변 파일 인정 범위", "px", 5, 0],
                                ["tilt_min", "손가락 기울기 · 최소", "°", 5, 0],
                                ["tilt_max", "손가락 기울기 · 최대", "°", 5, 0],
                                ["enter_frames", "모드 진입 · 모양 유지 프레임", "프레임", 1, 0],
                                ["leave", "손 모양을 놓쳐도 유지", "초", 0.05, 2],
                                ["speed", "커서 속도 배율", "배", 0.1, 1]]
                        delegate: RowLayout {
                            required property var modelData
                            readonly property string key: modelData[0]
                            readonly property var range: pointBox.ranges[key] || [0, 0, 1]
                            Layout.fillWidth: true
                            spacing: 6
                            TextLabel {
                                text: modelData[1]
                                font.pixelSize: 12
                                Layout.preferredWidth: 190
                            }
                            Slider {
                                objectName: "pointSetting_" + parent.key
                                Layout.fillWidth: true
                                from: parent.range[1]
                                to: parent.range[2]
                                stepSize: modelData[3]
                                snapMode: Slider.SnapAlways
                                value: pointBox.values[parent.key] !== undefined ? pointBox.values[parent.key] : parent.range[0]
                                onPressedChanged: if (!pressed) dashboard.setPointSetting(parent.key, value)
                            }
                            TextLabel {
                                Layout.preferredWidth: 70
                                horizontalAlignment: Text.AlignRight
                                text: Number(pointBox.values[parent.key] !== undefined ? pointBox.values[parent.key] : parent.range[0]).toFixed(modelData[4])
                                      + " " + modelData[2]
                                      + (Math.abs((pointBox.values[parent.key] || 0) - parent.range[0]) < 1e-6 ? " (기본)" : "")
                                font.pixelSize: 12
                                color: window.muted
                            }
                        }
                    }
                    RowLayout {
                        Layout.fillWidth: true
                        CheckBox {
                            objectName: "pointSettingRight"
                            text: "검지·중지를 붙인 모양으로 우클릭"
                            checked: pointBox.values.right_click !== false
                            onToggled: dashboard.setPointSetting("right_click", checked)
                        }
                        Item { Layout.fillWidth: true }
                        CompactButton {
                            objectName: "pointSettingsReset"
                            text: "기본값으로"
                            onClicked: dashboard.resetPointSettings()
                        }
                    }
                    TextLabel {
                        Layout.fillWidth: true
                        text: "대기 시간이 짧을수록 빨리 열리지만 지나가다 열릴 수 있어요. 인정 범위가 넓을수록 손끝이 조금 빗나가도 파일이 잡혀요. "
                              + "기울기 범위를 넓히면 손가락을 똑바로 세우거나 눕혀도 포인팅으로 읽어요 (다른 손 모양과 헷갈릴 수 있음). "
                              + "진입 프레임을 늘리면 모드가 늦게 켜지지만 잘못 켜지는 일이 줄어요."
                        color: window.muted
                        font.pixelSize: 11
                        wrapMode: Text.Wrap
                    }
                }                Divider {}
                // ---------------------------------------------------------------- the words beside the drawn hand
                SectionLabel { text: "신호 글자 표시" }
                ActionButton {
                    objectName: "signalTextButton"
                    Layout.fillWidth: true
                    text: dashboard.signalTextOn ? "가상 손 옆 신호 글자 · 켜짐 (눌러서 끄기)" : "가상 손 옆 신호 글자 · 꺼짐 (눌러서 켜기)"
                    accent: dashboard.signalTextOn
                    onClicked: dashboard.setSignalText(!dashboard.signalTextOn)
                }
                TextLabel {
                    Layout.fillWidth: true
                    text: "화면에 그린 손 옆에 '더블클릭', '우클릭' 같은 신호 이름을 글자로 보여 줘요. 마우스 제어가 꺼져 있을 때는 "
                          + "아무것도 실행하지 않고, 손이 낸 신호(클릭·끌기, 연결한 동작과 그 명령, 포인팅 모양, 지금 보이는 손 모양)를 "
                          + "초록 글자로 보여 줘서 손짓을 미리 확인할 수 있어요."
                    color: window.muted
                    font.pixelSize: 12
                    wrapMode: Text.Wrap
                }
                Divider {}
                // ---------------------------------------------------------------- drawing mode (src/draw_mode.py)
                SectionLabel { text: "그리기 모드" }
                ActionButton {
                    objectName: "drawModeButton"
                    Layout.fillWidth: true
                    text: dashboard.drawOn ? "그리기 모드 · 켜짐 (눌러서 끄기)" : "그리기 모드 · 꺼짐 (눌러서 켜기)"
                    accent: dashboard.drawOn
                    onClicked: dashboard.toggleDrawMode()
                }
                TextLabel {
                    Layout.fillWidth: true
                    text: "켜면 모니터에 펜이 나타나요. 검지만 펴서 가리키면 펜이 내려가고(검지 끝이 펜), 손을 펴거나 쥐면 그린 모양을 알아보고 연결한 명령을 실행해요. "
                          + "여러 모양을 이어서 그려도 됩니다. 손을 움직이는 영역 = 카메라 화면의 가상 손 박스. 켜져 있는 동안 다른 손 조작은 쉬어요."
                    color: window.muted
                    font.pixelSize: 12
                    wrapMode: Text.Wrap
                }
                RowLayout {
                    Layout.fillWidth: true
                    TextLabel { text: "인식 기준"; font.pixelSize: 12; font.bold: true }
                    Slider {
                        id: drawThresholdSlider
                        Layout.fillWidth: true
                        from: .6; to: .95; stepSize: .01
                        value: dashboard.drawThreshold
                        onPressedChanged: if (!pressed) dashboard.setDrawThreshold(value)
                    }
                    TextLabel { text: Math.round(drawThresholdSlider.value * 100) + "% (높을수록 엄격)"; font.pixelSize: 12; color: window.muted }
                }

                // the shapes and their commands
                Item {
                    id: drawEdit
                    property string key: ""          // the shape whose command is being edited
                    property string type: "hotkey"
                    property string value: ""
                    property string padMode: "test"  // test | new | example
                    property string exampleKey: ""
                    property var strokes: []          // new shape: the examples drawn so far
                    function edit(row) { key = row.key; type = row.action_type; value = row.action_value === "none" ? "" : row.action_value }
                    Connections {
                        target: dashboard
                        function onLlmChanged() {
                            if (drawEdit.key !== "" && drawEdit.type === "hotkey" && dashboard.llmContext.key !== "" && !dashboard.llmContext.capturing)
                                drawEdit.value = dashboard.llmContext.key
                        }
                    }
                }
                Repeater {
                    model: dashboard.drawShapes
                    delegate: Rectangle {
                        id: shapeCard
                        required property var modelData
                        Layout.fillWidth: true
                        implicitHeight: shapeCol.implicitHeight + 16
                        radius: 8
                        color: Theme.Studio.paper
                        border.color: drawEdit.key === modelData.key ? Theme.Studio.mintDark : window.line
                        opacity: modelData.enabled ? 1 : 0.6
                        ColumnLayout {
                            id: shapeCol
                            anchors { left: parent.left; right: parent.right; top: parent.top; margins: 8 }
                            spacing: 6
                            RowLayout {
                                Layout.fillWidth: true
                                spacing: 8
                                Canvas {
                                    implicitWidth: 40; implicitHeight: 40
                                    property var pts: shapeCard.modelData.preview
                                    onPtsChanged: requestPaint()
                                    onPaint: {
                                        var c = getContext("2d"); c.reset()
                                        c.strokeStyle = "#147D68"; c.lineWidth = 2.5; c.lineCap = "round"; c.lineJoin = "round"
                                        c.beginPath()
                                        for (var i = 0; i < pts.length; i++) {
                                            var x = 4 + pts[i][0] * 32, y = 4 + pts[i][1] * 32
                                            if (i === 0) c.moveTo(x, y); else c.lineTo(x, y)
                                        }
                                        c.stroke()
                                        if (pts.length) { c.fillStyle = "#E5484D"; c.beginPath(); c.arc(4 + pts[0][0] * 32, 4 + pts[0][1] * 32, 3, 0, 2 * Math.PI); c.fill() }
                                    }
                                }
                                ColumnLayout {
                                    Layout.fillWidth: true
                                    spacing: 0
                                    TextLabel {
                                        text: shapeCard.modelData.name + (shapeCard.modelData.builtin ? "  (기본)" : "  · 예시 " + shapeCard.modelData.examples + "개")
                                        font.bold: true
                                    }
                                    TextLabel { text: "→ " + shapeCard.modelData.badge; font.pixelSize: 12; color: window.muted }
                                }
                                Item { Layout.fillWidth: true }
                                CheckBox {
                                    checked: shapeCard.modelData.enabled
                                    text: "사용"
                                    onToggled: dashboard.setDrawShapeEnabled(shapeCard.modelData.key, checked)
                                }
                                CompactButton {
                                    text: drawEdit.key === shapeCard.modelData.key ? "닫기" : "명령"
                                    onClicked: drawEdit.key === shapeCard.modelData.key ? drawEdit.key = "" : drawEdit.edit(shapeCard.modelData)
                                }
                                CompactButton {
                                    visible: !shapeCard.modelData.builtin
                                    text: "예시 더하기"
                                    onClicked: { drawEdit.padMode = "example"; drawEdit.exampleKey = shapeCard.modelData.key }
                                }
                                CompactButton {
                                    visible: !shapeCard.modelData.builtin
                                    text: "삭제"
                                    danger: true
                                    onClicked: confirmDialog.ask("그림 삭제", "'" + shapeCard.modelData.name + "' 그림을 지웁니다.", "삭제",
                                                                 function () { dashboard.removeDrawShape(shapeCard.modelData.key) })
                                }
                            }
                            // the command editor for this shape
                            ColumnLayout {
                                visible: drawEdit.key === shapeCard.modelData.key
                                Layout.fillWidth: true
                                spacing: 6
                                Segmented {
                                    options: [["hotkey", "단축키"], ["youtube_key", "유튜브·미디어"], ["mouse_action", "마우스·시스템"], ["launch_app", "프로그램 실행"]]
                                    current: drawEdit.type
                                    onPicked: function (v) { drawEdit.type = v; drawEdit.value = "" }
                                }
                                RowLayout {
                                    Layout.fillWidth: true
                                    spacing: 6
                                    visible: drawEdit.type === "hotkey" || drawEdit.type === "launch_app"
                                    TextField {
                                        Layout.fillWidth: true
                                        text: drawEdit.value
                                        placeholderText: drawEdit.type === "hotkey" ? "예: ctrl+shift+t, win+d, f5" : "예: calc.exe 또는 https://..."
                                        onTextEdited: drawEdit.value = text
                                    }
                                    CompactButton {
                                        visible: drawEdit.type === "hotkey"
                                        text: dashboard.llmContext.capturing ? "키를 누르세요…" : "⌨ 키 기억하기"
                                        enabled: !dashboard.llmContext.capturing
                                        onClicked: dashboard.captureKey()
                                    }
                                }
                                StyledComboBox {
                                    visible: drawEdit.type === "mouse_action" || drawEdit.type === "youtube_key"
                                    Layout.fillWidth: true
                                    readonly property var items: drawEdit.type === "mouse_action" ? dashboard.mouseActionPresets : dashboard.youtubeKeyPresets
                                    model: items
                                    textRole: "label"
                                    currentIndex: {
                                        for (var i = 0; i < items.length; i++) if (items[i].value === drawEdit.value) return i
                                        return -1
                                    }
                                    displayText: currentIndex < 0 ? "골라 주세요" : currentText
                                    onActivated: function (i) { drawEdit.value = items[i].value }
                                }
                                RowLayout {
                                    ActionButton {
                                        text: "명령 저장"
                                        primary: true
                                        enabled: drawEdit.value !== ""
                                        onClicked: if (dashboard.setDrawBinding(drawEdit.key, drawEdit.type, drawEdit.value)) drawEdit.key = ""
                                    }
                                    TextLabel {
                                        visible: drawEdit.type === "launch_app"
                                        text: "⚠ 그림이 인식될 때마다 이 프로그램을 실행해요"
                                        color: Theme.Studio.amber
                                        font.pixelSize: 12
                                    }
                                }
                            }
                        }
                    }
                }

                // the drawing pad: register a new shape, add an example, or test what a stroke is recognised as
                RowLayout {
                    Layout.fillWidth: true
                    spacing: 6
                    Segmented {
                        Layout.fillWidth: true
                        options: [["test", "시험해 보기"], ["new", "새 그림 등록"]]
                        current: drawEdit.padMode === "example" ? "" : drawEdit.padMode
                        onPicked: function (v) { drawEdit.padMode = v; drawEdit.strokes = []; drawPad.clear() }
                    }
                }
                TextLabel {
                    Layout.fillWidth: true
                    wrapMode: Text.Wrap
                    font.pixelSize: 12
                    color: window.muted
                    text: drawEdit.padMode === "new" ? "이름을 적고 아래 칸에 마우스로 한 획으로 그리세요. 2~3번 조금씩 다르게 그리면 더 잘 알아봐요."
                        : drawEdit.padMode === "example" ? "'" + drawEdit.exampleKey + "' 그림을 한 번 더 그리세요 (예시가 늘면 더 잘 알아봐요)."
                        : "아래 칸에 마우스로 그려 보면 어떤 그림으로 알아보는지 보여 줘요."
                }
                RowLayout {
                    visible: drawEdit.padMode === "new"
                    Layout.fillWidth: true
                    spacing: 6
                    TextField { id: newShapeName; Layout.fillWidth: true; placeholderText: "그림 이름 (예: 별, 하트, 위 화살표)"; maximumLength: 30 }
                    TextLabel { text: "그린 횟수 " + drawEdit.strokes.length; font.pixelSize: 12 }
                    CompactButton { text: "다시 그리기"; onClicked: { drawEdit.strokes = []; drawPad.clear() } }
                    CompactButton {
                        text: "등록"
                        primary: true
                        enabled: newShapeName.text.trim() !== "" && drawEdit.strokes.length > 0
                        onClicked: if (dashboard.addDrawShape(newShapeName.text.trim(), drawEdit.strokes)) {
                            drawEdit.strokes = []; newShapeName.text = ""; drawPad.clear(); drawEdit.padMode = "test"
                        }
                    }
                }
                Rectangle {
                    Layout.fillWidth: true
                    implicitHeight: 220
                    radius: 8
                    color: Theme.Studio.stage
                    Canvas {
                        id: drawPad
                        objectName: "drawPad"
                        anchors.fill: parent
                        property var current: []
                        property var done: []
                        function clear() { current = []; done = []; requestPaint() }
                        onPaint: {
                            var c = getContext("2d"); c.reset()
                            c.lineCap = "round"; c.lineJoin = "round"
                            function line(pts, color, width) {
                                c.strokeStyle = color; c.lineWidth = width; c.beginPath()
                                for (var i = 0; i < pts.length; i++) { if (i === 0) c.moveTo(pts[i][0], pts[i][1]); else c.lineTo(pts[i][0], pts[i][1]) }
                                c.stroke()
                            }
                            for (var k = 0; k < done.length; k++) line(done[k], "rgba(70,229,189,0.35)", 3)
                            line(current, "#46E5BD", 4)
                        }
                        MouseArea {
                            anchors.fill: parent
                            cursorShape: Qt.CrossCursor
                            onPressed: function (m) { drawPad.current = [[m.x, m.y]]; drawPad.requestPaint() }
                            onPositionChanged: function (m) { var c = drawPad.current; c.push([m.x, m.y]); drawPad.current = c; drawPad.requestPaint() }
                            onReleased: {
                                var stroke = drawPad.current
                                if (stroke.length < 8) { drawPad.current = []; drawPad.requestPaint(); return }
                                if (drawEdit.padMode === "new") {
                                    var all = drawEdit.strokes.slice(); all.push(stroke); drawEdit.strokes = all
                                    var d = drawPad.done.slice(); d.push(stroke); drawPad.done = d
                                    drawPad.current = []
                                } else if (drawEdit.padMode === "example") {
                                    dashboard.addDrawExample(drawEdit.exampleKey, stroke)
                                    drawEdit.padMode = "test"
                                } else {
                                    dashboard.testDrawStroke(stroke)
                                }
                                drawPad.requestPaint()
                            }
                        }
                    }
                    Label {
                        visible: drawEdit.padMode === "test" && dashboard.drawTest.key !== undefined
                        anchors { left: parent.left; top: parent.top; margins: 10 }
                        text: dashboard.drawTest.ok ? ("✓ " + dashboard.drawTest.name + " (" + Math.round(dashboard.drawTest.score * 100) + "%)")
                              : ("✕ " + (dashboard.drawTest.why || "") + (dashboard.drawTest.name ? " · 가장 비슷한 것: " + dashboard.drawTest.name
                                 + " " + Math.round(dashboard.drawTest.score * 100) + "%" : ""))
                        color: dashboard.drawTest.ok ? "#46E5BD" : "#FF8A8F"
                        font.pixelSize: 14; font.bold: true; font.family: Theme.Studio.font
                    }
                }
                TextLabel {
                    Layout.fillWidth: true
                    visible: dashboard.drawMessage !== ""
                    text: dashboard.drawMessage
                    color: "#0369A1"
                    font.bold: true
                    wrapMode: Text.Wrap
                }
                Divider {}
                // ---------------------------------------------------------------- gesture sequences (src/sequence.py)
                SectionLabel { text: "동작 이어 하기 · 손 모양으로 그리기" }
                TextLabel {
                    Layout.fillWidth: true
                    text: "손 모양 2~3개를 차례로 하면(각각 잠깐 유지, 다음 모양은 1초 안에) 명령이 실행돼요. 실수로 실행되면 곤란한 명령에 좋아요. "
                          + "손 모양을 유지한 채 손바닥으로 원·Z 같은 모양을 그려도 실행할 수 있어요(그리기 모드 없이). "
                          + "새로 만들기는 위쪽 [말·글로 연결 (AI)]에서 \"V 사인 다음 주먹이면 창 닫기\", \"주먹으로 원 그리면 새로고침\"처럼 말하면 돼요."
                    color: window.muted
                    font.pixelSize: 12
                    wrapMode: Text.Wrap
                }
                TextLabel {
                    visible: dashboard.sequenceRows.length === 0
                    text: "아직 없어요."
                    color: window.muted
                    font.pixelSize: 12
                }
                Repeater {
                    model: dashboard.sequenceRows
                    delegate: Rectangle {
                        id: seqCard
                        required property var modelData
                        Layout.fillWidth: true
                        implicitHeight: seqRow.implicitHeight + 16
                        radius: 8
                        color: Theme.Studio.paper
                        border.color: window.line
                        opacity: modelData.enabled ? 1 : 0.6
                        RowLayout {
                            id: seqRow
                            anchors { left: parent.left; right: parent.right; verticalCenter: parent.verticalCenter; margins: 8 }
                            spacing: 8
                            ColumnLayout {
                                Layout.fillWidth: true
                                spacing: 0
                                TextLabel { text: seqCard.modelData.name; font.bold: true }
                                TextLabel { Layout.fillWidth: true; text: seqCard.modelData.steps_text; font.pixelSize: 12; wrapMode: Text.Wrap }
                                TextLabel { Layout.fillWidth: true; text: "→ " + seqCard.modelData.badge; font.pixelSize: 12; color: window.muted; wrapMode: Text.Wrap }
                            }
                            CheckBox {
                                checked: seqCard.modelData.enabled
                                text: "사용"
                                onToggled: dashboard.setSequenceEnabled(seqCard.modelData.key, checked)
                            }
                            CompactButton {
                                text: "삭제"
                                danger: true
                                onClicked: confirmDialog.ask("이어 하기 삭제", "'" + seqCard.modelData.name + "'을(를) 지웁니다.", "삭제",
                                                             function () { dashboard.removeSequence(seqCard.modelData.key) })
                            }
                        }
                    }
                }
                Divider {}
                SectionLabel { text: "세부 값" }
                ActionButton {
                    Layout.fillWidth: true
                    text: "엔진 세부 값 (슬라이더 창)"
                    onClicked: { palmSettings.close(); dashboard.command(111) }
                }
            }
        }
    }

    Dialog {
        id: pointerSettings
        anchors.centerIn: parent
        width: Math.min(400, window.width - 48)
        modal: true
        title: "검지 포인터 설정"
        standardButtons: Dialog.Close
        onClosed: dashboard.persistPointerSettings()
        contentItem: ColumnLayout {
            spacing: 10
            TextLabel { text: "커서 감도 · " + dashboard.pointerSensitivity + "%"; font.bold: true }
            Slider {
                Layout.fillWidth: true
                from: 50
                to: 150
                stepSize: 5
                snapMode: Slider.SnapAlways
                value: dashboard.pointerSensitivity
                onMoved: dashboard.setPointerSensitivity(Math.round(value))
            }
            RowLayout {
                Layout.fillWidth: true
                TextLabel { text: "느리게"; color: window.muted }
                Item { Layout.fillWidth: true }
                TextLabel { text: "빠르게"; color: window.muted }
            }
            ActionButton { text: "기본값 복원"; onClicked: dashboard.setPointerSensitivity(100) }
            ActionButton {
                text: "엔진 설정"
                onClicked: {
                    pointerSettings.close()
                    dashboard.command(111)
                }
            }
        }
    }

    // Online learning: after F, what was the last moment really? (only this answer makes it training data)
    Popup {
        id: correctionPopup
        anchors.centerIn: parent
        width: Math.min(620, window.width - 48)
        padding: 20
        modal: true
        focus: true
        closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside
        onClosed: dashboard.dismissCorrection()
        background: Rectangle { radius: 14; color: "#FFFFFF"; border.color: window.line }
        Connections {
            target: dashboard
            function onCorrectionChanged() {
                if (dashboard.correctionVisible) correctionPopup.open()
                else correctionPopup.close()
            }
        }
        contentItem: ColumnLayout {
            spacing: 12
            focus: true
            Keys.onPressed: function (event) {
                var index = event.key === Qt.Key_0 ? 9 : event.key - Qt.Key_1
                if (index >= 0 && index < dashboard.correctionChoices.length) {
                    dashboard.answerCorrection(dashboard.correctionChoices[index].label)
                    event.accepted = true
                }
            }
            TextLabel { text: "방금 동작은 무엇이었나요?"; font.pixelSize: 18; font.bold: true }
            TextLabel {
                Layout.fillWidth: true
                wrapMode: Text.WordWrap
                color: window.muted
                text: (dashboard.correctionGuess ? "앱은 '" + dashboard.correctionGuess + "'(으)로 봤어요. " : "")
                      + "고르면 직전 3초를 학습 데이터로 저장해요."
            }
            GridLayout {
                Layout.fillWidth: true
                columns: 2
                columnSpacing: 8
                rowSpacing: 8
                Repeater {
                    model: dashboard.correctionChoices
                    ActionButton {
                        required property var modelData
                        required property int index
                        Layout.fillWidth: true
                        Layout.preferredWidth: 1
                        text: (index < 9 ? (index + 1) + ". " : (index === 9 ? "0. " : "")) + modelData.name
                        onClicked: dashboard.answerCorrection(modelData.label)
                    }
                }
            }
            RowLayout {
                Layout.fillWidth: true
                TextLabel { text: "숫자 키로 고를 수 있어요"; font.pixelSize: 12; color: window.muted }
                Item { Layout.fillWidth: true }
                ActionButton { text: "저장 안 함 (Esc)"; onClicked: dashboard.dismissCorrection() }
            }
        }
    }

    // Online learning: which command a registered gesture runs. Two clicks, or press the keys.
    Popup {
        id: commandPopup
        objectName: "commandPopup"
        property string label: ""
        property bool listening: false
        property bool withWin: false        // Windows keeps Win combinations from the app: this adds Win to the next key
        function openFor(name) {
            label = name
            listening = false
            withWin = false
            dashboard.clearCommandMessage()
            open()
            commandKeys.forceActiveFocus()
        }
        // Qt key -> the app's key name
        function keyName(event) {
            var k = event.key
            if (k >= Qt.Key_A && k <= Qt.Key_Z) return String.fromCharCode(k).toLowerCase()
            if (k >= Qt.Key_0 && k <= Qt.Key_9) return String.fromCharCode(k)
            if (k >= Qt.Key_F1 && k <= Qt.Key_F12) return "f" + (k - Qt.Key_F1 + 1)
            var names = {}
            names[Qt.Key_Return] = "enter"; names[Qt.Key_Enter] = "enter"; names[Qt.Key_Space] = "space"; names[Qt.Key_Tab] = "tab"
            names[Qt.Key_Backspace] = "backspace"; names[Qt.Key_Delete] = "delete"; names[Qt.Key_Left] = "left"; names[Qt.Key_Right] = "right"
            names[Qt.Key_Up] = "up"; names[Qt.Key_Down] = "down"; names[Qt.Key_Home] = "home"; names[Qt.Key_End] = "end"
            names[Qt.Key_PageUp] = "pageup"; names[Qt.Key_PageDown] = "pagedown"
            return names[k] || ""
        }
        anchors.centerIn: parent
        width: Math.min(460, window.width - 48)
        padding: 20
        modal: true
        closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside
        background: Rectangle { radius: 14; color: "#FFFFFF"; border.color: window.line }
        contentItem: ColumnLayout {
            spacing: 12
            Item {
                id: commandKeys
                width: 0; height: 0
                focus: true
                // While listening, a letter is the key being chosen, not the window's shortcut (Q would quit the app)
                Keys.onShortcutOverride: function (event) { event.accepted = commandPopup.listening }
                Keys.onPressed: function (event) {
                    if (!commandPopup.listening) return
                    if (event.key === Qt.Key_Escape) { commandPopup.listening = false; event.accepted = true; return }
                    var name = commandPopup.keyName(event)
                    if (name === "") { event.accepted = true; return }    // a modifier alone, or a key with no name: keep listening
                    var combo = []
                    if (event.modifiers & Qt.ControlModifier) combo.push("ctrl")
                    if (event.modifiers & Qt.AltModifier) combo.push("alt")
                    if (event.modifiers & Qt.ShiftModifier) combo.push("shift")
                    if ((event.modifiers & Qt.MetaModifier) || commandPopup.withWin) combo.push("win")
                    combo.push(name)
                    commandPopup.listening = false
                    commandPopup.withWin = false
                    event.accepted = true
                    if (dashboard.setGestureCommand(commandPopup.label, combo.join("+"))) commandPopup.close()
                }
            }
            TextLabel { Layout.fillWidth: true; wrapMode: Text.WordWrap; text: "'" + commandPopup.label + "' 하면 무엇을 실행할까요?"; font.pixelSize: 18; font.bold: true }
            GridLayout {
                Layout.fillWidth: true
                columns: 2
                columnSpacing: 8
                rowSpacing: 8
                Repeater {
                    model: dashboard.commandChoices
                    ActionButton {
                        required property var modelData
                        Layout.fillWidth: true
                        Layout.preferredWidth: 1
                        text: modelData.label
                        onClicked: if (dashboard.setGestureCommand(commandPopup.label, modelData.value)) commandPopup.close()
                    }
                }
            }
            RowLayout {
                Layout.fillWidth: true
                spacing: 8
                ActionButton {
                    Layout.fillWidth: true
                    accent: commandPopup.listening
                    text: commandPopup.listening
                          ? (commandPopup.withWin ? "Win + 지금 키를 누르세요 (예: D) · Esc 취소" : "지금 키를 누르세요 (예: Ctrl+B) · Esc 취소")
                          : "다른 키 직접 입력"
                    onClicked: { commandPopup.listening = true; commandKeys.forceActiveFocus() }
                }
                // Win+key cannot be pressed here (Windows acts on it first): switch Win on, then press only the key
                ActionButton {
                    objectName: "commandWinToggle"
                    accent: commandPopup.withWin
                    text: commandPopup.withWin ? "Win 켜짐" : "Win 같이"
                    onClicked: {
                        commandPopup.withWin = !commandPopup.withWin
                        commandPopup.listening = true
                        commandKeys.forceActiveFocus()
                    }
                }
            }
            TextLabel {
                Layout.fillWidth: true
                wrapMode: Text.WordWrap
                visible: dashboard.commandMessage !== ""
                color: window.muted
                font.pixelSize: 12
                text: dashboard.commandMessage
            }
            TextLabel {
                Layout.fillWidth: true
                wrapMode: Text.WordWrap
                color: window.muted
                font.pixelSize: 12
                text: "제어 시작 상태에서 동작을 0.5초 유지하면 실행돼요. 한 번 유지에 한 번만 실행해요."
            }
            RowLayout {
                Layout.fillWidth: true
                spacing: 8
                ActionButton {
                    danger: true
                    text: "동작 삭제"
                    onClicked: confirmDialog.ask("동작 삭제", "'" + commandPopup.label + "' 동작과 시연 기록을 지웁니다. 되돌릴 수 없습니다.", "삭제", function () {
                        dashboard.deleteMyGesture(commandPopup.label)
                        commandPopup.close()
                    })
                }
                Item { Layout.fillWidth: true }
                ActionButton {
                    text: "표시만"
                    onClicked: if (dashboard.setGestureCommand(commandPopup.label, "")) commandPopup.close()
                }
                ActionButton { text: "닫기"; onClicked: commandPopup.close() }
            }
        }
    }

    // Online learning: add a new gesture from a few demonstrations. Not modal: the person watches the preview meanwhile.
    Popup {
        id: registerPopup
        objectName: "registerPopup"
        x: window.width - width - 28
        y: 86
        width: Math.min(400, window.width - 48)
        padding: 20
        modal: false
        closePolicy: Popup.NoAutoClose
        background: Rectangle { radius: 14; color: "#FFFFFF"; border.color: window.line; border.width: 1 }
        readonly property var view: dashboard.registration
        readonly property string state: view.state || ""
        readonly property bool running: state === "prep" || state === "do" || state === "rest"
        onOpened: dashboard.refreshMyGestures()
        contentItem: ColumnLayout {
            spacing: 12
            TextLabel { text: "새 동작 등록"; font.pixelSize: 18; font.bold: true }
            // the gestures already registered, each with its command
            Repeater {
                model: registerPopup.state === "" || registerPopup.state === "failed" ? dashboard.myGestures : []
                RowLayout {
                    required property var modelData
                    Layout.fillWidth: true
                    spacing: 8
                    TextLabel { text: modelData.label; font.bold: true; elide: Text.ElideRight; Layout.maximumWidth: 150 }
                    TextLabel { Layout.fillWidth: true; text: modelData.text; color: window.muted; font.pixelSize: 12; elide: Text.ElideRight }
                    CompactButton { text: "명령 바꾸기"; onClicked: commandPopup.openFor(modelData.label) }
                }
            }
            // name
            TextLabel {
                visible: registerPopup.state === "" || registerPopup.state === "failed"
                Layout.fillWidth: true
                wrapMode: Text.WordWrap
                color: registerPopup.state === "failed" ? window.dangerRed : window.muted
                text: registerPopup.state === "failed" ? registerPopup.view.message
                      : "이름을 정하고 5번 시연해요. 동작마다 조금씩 다르게 해 보세요. 마우스는 움직이지 않아요."
            }
            TextField {
                id: registerName
                visible: registerPopup.state === "" || registerPopup.state === "failed"
                Layout.fillWidth: true
                placeholderText: "동작 이름 (예: 주먹 쥐기)"
                maximumLength: 30
                selectByMouse: true
                onAccepted: if (text.trim().length) dashboard.startRegistration(text)
            }
            // demonstrations
            TextLabel {
                visible: registerPopup.running
                Layout.fillWidth: true
                horizontalAlignment: Text.AlignHCenter
                font.pixelSize: 26
                font.bold: true
                color: registerPopup.state === "do" ? "#16846E" : window.navy
                text: registerPopup.state === "do" ? "지금 동작하세요" : (registerPopup.state === "prep" ? "준비하세요" : "손을 풀어 주세요")
            }
            TextLabel {
                visible: registerPopup.running
                Layout.fillWidth: true
                horizontalAlignment: Text.AlignHCenter
                color: registerPopup.view.hand === false ? window.dangerRed : window.muted
                text: registerPopup.view.hand === false ? "손이 보이지 않아요. 시간이 멈춰 있어요"
                      : (registerPopup.view.demo + " / " + registerPopup.view.demos + "번째 · " + registerPopup.view.seconds + "초")
            }
            // the result
            TextLabel {
                visible: registerPopup.state === "review"
                Layout.fillWidth: true
                wrapMode: Text.WordWrap
                font.bold: true
                text: registerPopup.view.report ? "시연 " + registerPopup.view.report.demos + "번 중 "
                      + registerPopup.view.report.recognised + "번을 알아봤어요" : ""
            }
            TextLabel {
                visible: registerPopup.state === "review"
                Layout.fillWidth: true
                wrapMode: Text.WordWrap
                color: registerPopup.view.report && registerPopup.view.report.reliable ? window.muted : window.dangerRed
                text: dashboard.registrationAdvice
            }
            TextLabel {
                visible: registerPopup.state === "done"
                Layout.fillWidth: true
                wrapMode: Text.WordWrap
                text: "'" + registerPopup.view.name + "'을(를) 등록했어요. 이제 이 동작으로 실행할 명령을 골라 주세요."
            }
            RowLayout {
                Layout.fillWidth: true
                spacing: 8
                Item { Layout.fillWidth: true }
                ActionButton {
                    text: registerPopup.state === "review" || registerPopup.running ? "취소" : "닫기"
                    onClicked: {
                        dashboard.cancelRegistration()
                        if (!registerPopup.running) registerPopup.close()
                    }
                }
                ActionButton {
                    visible: registerPopup.state === "" || registerPopup.state === "failed"
                    primary: true
                    enabled: registerName.text.trim().length > 0
                    text: "시연 시작"
                    onClicked: dashboard.startRegistration(registerName.text)
                }
                ActionButton {
                    visible: registerPopup.state === "review"
                    primary: true
                    text: "등록"
                    onClicked: dashboard.approveRegistration()
                }
                ActionButton {
                    visible: registerPopup.state === "done"
                    primary: true
                    text: "명령 고르기"
                    onClicked: commandPopup.openFor(registerPopup.view.name)
                }
            }
        }
    }

    // Cursor reference picker: click joints on a hand skeleton; the cursor follows their centre
    Popup {
        id: anchorPicker
        property var picked: []          // working copy, applied with [적용]
        readonly property var stable: dashboard.stableAnchorJoints
        // Schematic right hand, palm toward the camera (as in the mirrored preview), 0..1 box
        readonly property var joints: [
            [0.50, 0.94],
            [0.35, 0.84], [0.24, 0.72], [0.16, 0.60], [0.10, 0.49],
            [0.36, 0.53], [0.33, 0.37], [0.31, 0.26], [0.30, 0.15],
            [0.49, 0.50], [0.49, 0.33], [0.49, 0.21], [0.49, 0.09],
            [0.61, 0.52], [0.63, 0.36], [0.64, 0.26], [0.65, 0.16],
            [0.71, 0.58], [0.75, 0.46], [0.78, 0.38], [0.80, 0.30]
        ]
        readonly property var bones: [
            [0,1],[1,2],[2,3],[3,4], [0,5],[5,6],[6,7],[7,8], [5,9],[9,10],[10,11],[11,12],
            [9,13],[13,14],[14,15],[15,16], [13,17],[17,18],[18,19],[19,20], [0,17]
        ]
        readonly property var presets: [
            ["손바닥 중심 (기본)", []], ["손목", [0]], ["손가락 뿌리 4곳", [5, 9, 13, 17]],
            ["손바닥 전체", [0, 5, 9, 13, 17]], ["검지 뿌리", [5]], ["중지 뿌리", [9]], ["검지 끝", [8]]
        ]
        // [] means the default (centre of wrist and middle-finger base): shown as 0 + 9
        readonly property var shown: picked.length === 0 ? [0, 9] : picked
        readonly property bool unstable: {
            for (var i = 0; i < picked.length; i++)
                if (stable.indexOf(picked[i]) < 0) return true
            return false
        }
        function openWith(current) {
            picked = current ? current.slice() : []
            open()
        }
        function toggle(j) {
            var base = picked.length === 0 ? [0, 9] : picked.slice()
            var at = base.indexOf(j)
            if (at >= 0) base.splice(at, 1); else base.push(j)
            base.sort(function (a, b) { return a - b })
            // back to exactly 0 + 9 = the default
            picked = (base.length === 2 && base[0] === 0 && base[1] === 9) ? [] : base
        }
        function samePicks(a, b) {
            if (a.length !== b.length) return false
            for (var i = 0; i < a.length; i++) if (a[i] !== b[i]) return false
            return true
        }
        function centre() {
            var x = 0, y = 0, js = shown
            for (var i = 0; i < js.length; i++) { x += joints[js[i]][0]; y += joints[js[i]][1] }
            return js.length ? [x / js.length, y / js.length] : [0.5, 0.7]
        }
        anchors.centerIn: Overlay.overlay
        width: Math.min(720, window.width - 40)
        height: Math.min(560, window.height - 40)
        modal: true
        focus: true
        z: 900
        padding: 18
        closePolicy: Popup.CloseOnEscape
        background: Rectangle { radius: 16; color: "white"; border.color: window.line }
        onPickedChanged: anchorSkelCanvas.requestPaint()
        contentItem: ColumnLayout {
            spacing: 10
            TextLabel { text: "커서 기준점 정하기"; font.pixelSize: 19; font.bold: true }
            TextLabel {
                Layout.fillWidth: true
                wrapMode: Text.Wrap
                color: window.muted
                font.pixelSize: 13
                text: "손 그림에서 관절을 눌러 고르세요. 여러 곳을 고르면 그 가운데(＋)를 커서가 따라갑니다. 다시 누르면 빠집니다."
            }
            RowLayout {
                Layout.fillWidth: true
                Layout.fillHeight: true
                spacing: 16
                Rectangle {
                    id: anchorSkelBox
                    Layout.preferredWidth: Math.min(330, anchorPicker.availableWidth * 0.5)
                    Layout.fillHeight: true
                    radius: 12
                    color: "#F4F7F9"
                    border.color: window.line
                    Item {
                        id: anchorSkelArea
                        anchors.fill: parent
                        anchors.margins: 14
                        Canvas {
                            id: anchorSkelCanvas
                            anchors.fill: parent
                            onWidthChanged: requestPaint()
                            onHeightChanged: requestPaint()
                            onPaint: {
                                var ctx = getContext("2d")
                                ctx.reset()
                                var J = anchorPicker.joints, B = anchorPicker.bones
                                ctx.strokeStyle = "#AEBBC6"
                                ctx.lineWidth = 3
                                ctx.lineCap = "round"
                                for (var i = 0; i < B.length; i++) {
                                    ctx.beginPath()
                                    ctx.moveTo(J[B[i][0]][0] * width, J[B[i][0]][1] * height)
                                    ctx.lineTo(J[B[i][1]][0] * width, J[B[i][1]][1] * height)
                                    ctx.stroke()
                                }
                                var c = anchorPicker.centre(), sh = anchorPicker.shown
                                ctx.strokeStyle = "rgba(29, 78, 216, 0.35)"
                                ctx.lineWidth = 1.5
                                for (var k = 0; k < sh.length && sh.length > 1; k++) {
                                    ctx.beginPath()
                                    ctx.moveTo(J[sh[k]][0] * width, J[sh[k]][1] * height)
                                    ctx.lineTo(c[0] * width, c[1] * height)
                                    ctx.stroke()
                                }
                            }
                        }
                        Repeater {
                            model: 21
                            delegate: Rectangle {
                                id: anchorJointDot
                                required property int index
                                readonly property bool on: anchorPicker.shown.indexOf(index) >= 0
                                readonly property bool fingertip: [4, 8, 12, 16, 20].indexOf(index) >= 0
                                width: on ? 20 : 16
                                height: width
                                radius: width / 2
                                x: anchorPicker.joints[index][0] * anchorSkelArea.width - width / 2
                                y: anchorPicker.joints[index][1] * anchorSkelArea.height - height / 2
                                color: on ? window.primaryBlue : (anchorJointHover.containsMouse ? "#DCE7F5" : "white")
                                border.color: on ? window.primaryBlueDark : (anchorPicker.stable.indexOf(index) >= 0 ? "#16846E" : "#8A9AA8")
                                border.width: 2
                                MouseArea {
                                    id: anchorJointHover
                                    anchors.fill: parent
                                    anchors.margins: -6
                                    hoverEnabled: true
                                    cursorShape: Qt.PointingHandCursor
                                    onClicked: anchorPicker.toggle(anchorJointDot.index)
                                }
                                ToolTip.visible: anchorJointHover.containsMouse
                                ToolTip.delay: 250
                                ToolTip.text: anchorJointDot.index + " · " + dashboard.handJointNames[anchorJointDot.index]
                            }
                        }
                        // the point the cursor will follow
                        Item {
                            readonly property var c: anchorPicker.centre()
                            x: c[0] * anchorSkelArea.width - 13
                            y: c[1] * anchorSkelArea.height - 13
                            width: 26; height: 26
                            visible: anchorPicker.shown.length > 1
                            Rectangle { anchors.centerIn: parent; width: 26; height: 3; radius: 1.5; color: "#F97316" }
                            Rectangle { anchors.centerIn: parent; width: 3; height: 26; radius: 1.5; color: "#F97316" }
                        }
                    }
                    TextLabel {
                        anchors.left: parent.left; anchors.bottom: parent.bottom; anchors.margins: 8
                        text: "오른손 · 손바닥이 카메라 쪽"
                        font.pixelSize: 11
                        color: window.muted
                    }
                }
                ColumnLayout {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    spacing: 8
                    SectionLabel { text: "빠른 선택" }
                    Flow {
                        Layout.fillWidth: true
                        spacing: 6
                        Repeater {
                            model: anchorPicker.presets
                            delegate: CompactButton {
                                required property var modelData
                                text: modelData[0]
                                accent: anchorPicker.samePicks(anchorPicker.picked, modelData[1])
                                onClicked: anchorPicker.picked = modelData[1].slice()
                            }
                        }
                    }
                    SectionLabel { text: "고른 관절" }
                    TextLabel {
                        Layout.fillWidth: true
                        wrapMode: Text.Wrap
                        font.pixelSize: 13
                        text: {
                            if (anchorPicker.picked.length === 0)
                                return "손목 + 중지 뿌리의 가운데 (기본 · 손바닥 중심)"
                            var names = []
                            for (var i = 0; i < anchorPicker.picked.length; i++)
                                names.push(dashboard.handJointNames[anchorPicker.picked[i]])
                            return names.join(", ") + (names.length > 1 ? "  → 가운데" : "")
                        }
                    }
                    Rectangle {
                        visible: anchorPicker.unstable
                        Layout.fillWidth: true
                        implicitHeight: anchorUnstableNote.implicitHeight + 16
                        radius: 8
                        color: "#FFF1D6"
                        border.color: "#F2B544"
                        TextLabel {
                            id: anchorUnstableNote
                            anchors.fill: parent
                            anchors.margins: 8
                            wrapMode: Text.Wrap
                            font.pixelSize: 12
                            color: "#7A4A00"
                            text: "손가락 마디·끝은 집거나 오므릴 때 함께 움직여서, 클릭하는 순간 커서가 흔들릴 수 있습니다. 클릭 위치가 중요하면 손목·손가락 뿌리(초록 테두리)를 고르세요."
                        }
                    }
                    TextLabel {
                        Layout.fillWidth: true
                        wrapMode: Text.Wrap
                        font.pixelSize: 12
                        color: window.muted
                        text: dashboard.pointerOnly
                            ? "검지 포인터 모드에서는 [커서 기준점]이 '직접 지정'으로 바뀝니다."
                            : "손바닥(Dan) 모드의 커서 이동에 바로 쓰입니다. 적용하면 입력이 잠시 멈춥니다."
                    }
                    Item { Layout.fillHeight: true }
                    RowLayout {
                        Layout.fillWidth: true
                        spacing: 8
                        Item { Layout.fillWidth: true }
                        ActionButton { text: "취소"; onClicked: anchorPicker.close() }
                        ActionButton {
                            text: "적용"
                            primary: true
                            onClicked: {
                                dashboard.setAnchorJoints(anchorPicker.picked)
                                anchorPicker.close()
                            }
                        }
                    }
                }
            }
        }
    }

    // One confirmation step for actions that cannot be undone (delete a recording, reset a gesture...)
    Dialog {
        id: confirmDialog
        property string message: ""
        property string confirmText: "확인"
        property var onConfirm: null
        function ask(title, message, confirmText, callback) {
            confirmDialog.title = title
            confirmDialog.message = message
            confirmDialog.confirmText = confirmText || "확인"
            confirmDialog.onConfirm = callback
            confirmDialog.open()
        }
        anchors.centerIn: Overlay.overlay
        width: Math.min(440, window.width - 48)
        modal: true
        z: 1000
        padding: 20
        topPadding: 18
        background: Rectangle { radius: 14; color: "white"; border.color: window.line }
        header: TextLabel {
            text: confirmDialog.title
            font.pixelSize: 17
            font.bold: true
            leftPadding: 20; rightPadding: 20; topPadding: 18
            wrapMode: Text.Wrap
        }
        contentItem: ColumnLayout {
            spacing: 18
            TextLabel {
                Layout.fillWidth: true
                text: confirmDialog.message
                wrapMode: Text.Wrap
                lineHeight: 1.25
                color: "#334155"
            }
            RowLayout {
                Layout.fillWidth: true
                spacing: 8
                Item { Layout.fillWidth: true }
                ActionButton { text: "취소"; onClicked: confirmDialog.close() }
                ActionButton {
                    text: confirmDialog.confirmText
                    danger: true
                    onClicked: {
                        var cb = confirmDialog.onConfirm
                        confirmDialog.onConfirm = null
                        confirmDialog.close()
                        if (cb) cb()
                    }
                }
            }
        }
        onClosed: onConfirm = null
    }

    Shortcut { sequence: "Return"; enabled: !dashboard.trackingActive && (dashboard.calibratingPointer); autoRepeat: false; onActivated: dashboard.capturePointerSample() }
    Shortcut { sequence: "Enter"; enabled: !dashboard.trackingActive && (dashboard.calibratingPointer); autoRepeat: false; onActivated: dashboard.capturePointerSample() }
    Shortcut { sequence: "Esc"; enabled: !dashboard.trackingActive; onActivated: dashboard.command(27) }
    Shortcut { sequence: "Space"; enabled: !dashboard.trackingActive && (!pointerSettings.visible); onActivated: dashboard.command(32) }
    Shortcut { sequence: "Q"; enabled: !dashboard.trackingActive; onActivated: dashboard.command(81) }
    Shortcut { sequence: "O"; enabled: !dashboard.trackingActive; onActivated: dashboard.command(111) }
    Shortcut { sequence: "M"; enabled: !dashboard.trackingActive; onActivated: dashboard.command(109) }
    Shortcut { sequence: "N"; enabled: !dashboard.trackingActive; onActivated: dashboard.command(110) }
    Shortcut { sequence: "F"; enabled: !dashboard.trackingActive; onActivated: dashboard.markFailure() }
    Shortcut { sequence: "C"; enabled: !dashboard.trackingActive; onActivated: dashboard.command(99) }
    Shortcut { sequence: "P"; enabled: !dashboard.trackingActive; onActivated: dashboard.command(112) }

    Timer { interval: 700; running: dashboard.stage === "splash"; onTriggered: dashboard.finishSplash() }

    Rectangle {
        anchors.fill: parent
        visible: dashboard.stage !== "main"
        color: "#F4F6F8"
        ColumnLayout {
            anchors.centerIn: parent
            width: Math.min(parent.width - 64, 670)
            spacing: 16
            Image {
                Layout.alignment: Qt.AlignHCenter
                Layout.preferredWidth: dashboard.stage === "splash" ? 260 : 110
                Layout.preferredHeight: dashboard.stage === "splash" ? 96 : 38
                source: "assets/manux.svg"
                fillMode: Image.PreserveAspectFit
            }
            TextLabel {
                visible: dashboard.stage !== "splash"
                Layout.fillWidth: true
                horizontalAlignment: Text.AlignHCenter
                text: dashboard.stage === "welcome" ? "안녕하세요" : "어느 손으로 조작할까요?"
                font.pixelSize: 38
                font.bold: true
            }
            TextLabel {
                visible: dashboard.stage !== "splash"
                Layout.fillWidth: true
                horizontalAlignment: Text.AlignHCenter
                wrapMode: Text.Wrap
                color: window.muted
                text: dashboard.stage === "welcome"
                    ? "편하게 쓸 손을 한 번 정하면, 다음부터 바로 시작할 수 있어요."
                    : "카메라에 사용할 손과 움직일 공간을 보여주세요.\n한 손만 5초 동안 보여주면 자동으로 시작합니다."
            }
            ActionButton {
                visible: dashboard.stage === "welcome"
                Layout.alignment: Qt.AlignHCenter
                text: "시작하기"
                primary: true
                onClicked: dashboard.beginHandSetup()
            }
            Rectangle {
                visible: dashboard.stage === "capture"
                Layout.fillWidth: true
                Layout.preferredHeight: Math.min(300, window.height * .45)
                radius: 16
                color: window.navy
                Image {
                    id: setupPreview
                    anchors.fill: parent; source: dashboard.previewUrl; cache: false; fillMode: Image.PreserveAspectFit
                    HandSkeleton { anchors.fill: parent; imageWidth: setupPreview.paintedWidth; imageHeight: setupPreview.paintedHeight }
                }
            }
            TextLabel {
                visible: dashboard.stage === "capture"
                Layout.alignment: Qt.AlignHCenter
                text: dashboard.handCandidate ? dashboard.handCandidate + " 감지됨 · " + dashboard.secondsRemaining + "초 남음" : "한 손을 기다리는 중"
                color: dashboard.handCandidate ? "#08775E" : window.muted
                font.bold: true
            }
            RowLayout {
                visible: dashboard.stage === "capture"
                Layout.alignment: Qt.AlignHCenter
                ActionButton {
                    visible: dashboard.chosenHand !== ""
                    text: "취소"
                    onClicked: dashboard.cancelHandSetup()
                }

            }
        }
    }

    component SectionLabel: TextLabel {
        font.pixelSize: 13
        font.bold: true
        Layout.topMargin: 4
    }
    // Fixed-width label in front of a form row, so the rows line up
    component FormLabel: TextLabel {
        Layout.preferredWidth: 84
        Layout.alignment: Qt.AlignTop
        topPadding: 6
        font.pixelSize: 12
        font.bold: true
        color: window.muted
    }
    component Divider: Rectangle {
        Layout.fillWidth: true
        implicitHeight: 1
        color: window.line
    }
    // All choices visible at once; the current one is highlighted (was: one button that cycled)
    component Segmented: RowLayout {
        id: seg
        property var options: []      // [[value, label], ...]
        property string current: ""
        signal picked(string value)
        Layout.fillWidth: true
        spacing: 4
        Repeater {
            model: seg.options
            delegate: Button {
                id: option
                required property var modelData
                readonly property bool selected: seg.current === modelData[0]
                Layout.fillWidth: true
                Layout.preferredWidth: 1
                Layout.minimumWidth: 0
                implicitWidth: 0
                implicitHeight: 34
                leftPadding: 6
                rightPadding: 6
                enabled: seg.enabled
                onClicked: seg.picked(modelData[0])
                contentItem: TextLabel {
                    text: option.modelData[1]
                    font.pixelSize: 12
                    font.bold: option.selected
                    color: option.enabled ? (option.selected ? window.navy : "#3E5262") : "#A9B6C0"
                    horizontalAlignment: Text.AlignHCenter
                    verticalAlignment: Text.AlignVCenter
                    elide: Text.ElideRight
                }
                background: Rectangle {
                    radius: 8
                    color: option.selected ? Theme.Studio.mint : option.down ? "#BCEFE1" : option.hovered ? Theme.Studio.mintWash : Theme.Studio.paper
                    border.color: option.activeFocus ? Theme.Studio.mintDark : option.selected ? "transparent" : Theme.Studio.line
                    border.width: option.activeFocus ? 2 : 1
                }
            }
        }
    }
    component Chip: Rectangle {
        id: chip
        property alias text: chipLabel.text
        property bool warn: false
        implicitWidth: chipLabel.implicitWidth + 18
        implicitHeight: 26
        Layout.minimumWidth: Math.min(implicitWidth, 56)
        Layout.preferredWidth: implicitWidth
        radius: 13
        color: warn ? Theme.Studio.amberWash : Theme.Studio.mintWash
        border.color: warn ? "#F2B544" : "transparent"
        clip: true
        TextLabel {
            id: chipLabel
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.leftMargin: 9
            anchors.rightMargin: 9
            anchors.verticalCenter: parent.verticalCenter
            horizontalAlignment: Text.AlignHCenter
            elide: Text.ElideRight
            font.pixelSize: 12
            color: chip.warn ? Theme.Studio.amber : window.navy
        }
    }

    component StyledComboBox: ComboBox {
        id: scombo
        implicitHeight: 32
        leftPadding: 10
        rightPadding: 28
        font.pixelSize: 12
        contentItem: TextLabel {
            text: scombo.displayText
            font.pixelSize: 12
            color: window.navy
            verticalAlignment: Text.AlignVCenter
            elide: Text.ElideRight
        }
        indicator: TextLabel {
            x: scombo.width - width - 9
            y: (scombo.availableHeight - height) / 2
            text: "▾"
            font.pixelSize: 12
            color: window.muted
        }
        background: Rectangle {
            radius: 7
            color: scombo.down ? Theme.Studio.mintWash : Theme.Studio.paper
            border.color: scombo.activeFocus ? Theme.Studio.mintDark : Theme.Studio.line
            border.width: scombo.activeFocus ? 2 : 1
        }
    }

    component BusySpinner: Item {
        id: spinnerRoot
        property bool active: false
        property color strokeColor: "#1D4ED8"
        implicitWidth: 20
        implicitHeight: 20
        visible: active
        Canvas {
            id: spinnerCanvas
            anchors.fill: parent
            onPaint: {
                var ctx = getContext("2d")
                ctx.reset()
                var cx = width / 2, cy = height / 2
                var r = Math.min(width, height) / 2 - 2.5
                ctx.lineWidth = 2.6
                ctx.lineCap = "round"
                ctx.strokeStyle = "#CBD5E1"
                ctx.beginPath()
                ctx.arc(cx, cy, r, 0, Math.PI * 2)
                ctx.stroke()
                ctx.strokeStyle = spinnerRoot.strokeColor
                ctx.beginPath()
                ctx.arc(cx, cy, r, -Math.PI / 2, Math.PI * 0.85)
                ctx.stroke()
            }
            RotationAnimator on rotation {
                from: 0
                to: 360
                duration: 850
                loops: Animation.Infinite
                running: spinnerRoot.active && spinnerRoot.visible
            }
        }
    }

    component WorkProgressBanner: Rectangle {
        id: workBanner
        property bool showOpenCenterButton: false
        property bool showStopButton: false
        property bool showStatusWhenIdle: false
        readonly property bool hasIdleStatus: showStatusWhenIdle && !dashboard.appWorking && (dashboard.trainingStage !== "" || dashboard.trainingNote !== "")
        visible: dashboard.appWorking || hasIdleStatus || (showStatusWhenIdle && dashboard.trainingResumable)
        Layout.fillWidth: true
        implicitHeight: bannerCol.implicitHeight + 20
        radius: 10
        color: dashboard.appWorking ? (dashboard.trainingRunning ? "#EFF6FF" : "#ECFEFF") : "#F8FAFC"
        border.color: dashboard.appWorking ? (dashboard.trainingRunning ? "#60A5FA" : "#22D3EE") : "#CBD5E1"
        border.width: dashboard.appWorking ? 1.5 : 1

        ColumnLayout {
            id: bannerCol
            anchors.fill: parent
            anchors.margins: 10
            spacing: 6

            RowLayout {
                Layout.fillWidth: true
                spacing: 10

                BusySpinner {
                    active: dashboard.appWorking && workBanner.visible
                    strokeColor: dashboard.trainingRunning ? "#1D4ED8" : "#0891B2"
                }

                ColumnLayout {
                    Layout.fillWidth: true
                    Layout.minimumWidth: 0
                    spacing: 2

                    RowLayout {
                        Layout.fillWidth: true
                        spacing: 8
                        TextLabel {
                            text: dashboard.appWorking
                                ? (dashboard.workTitle !== "" ? dashboard.workTitle : "작업 진행 중…")
                                : (dashboard.trainingStage !== "" ? dashboard.trainingStage : dashboard.trainingNote)
                            font.pixelSize: 13
                            font.bold: true
                            color: dashboard.appWorking ? (dashboard.trainingRunning ? "#1E3A8A" : "#0F172A") : window.navy
                            Layout.fillWidth: true
                            Layout.minimumWidth: 0
                            elide: Text.ElideRight
                        }
                        Rectangle {
                            visible: dashboard.appWorking && dashboard.workElapsedText !== ""
                            radius: 9
                            color: dashboard.trainingRunning ? "#DBEAFE" : "#CFFAFE"
                            implicitWidth: elapsedLbl.implicitWidth + 14
                            implicitHeight: 20
                            TextLabel {
                                id: elapsedLbl
                                anchors.centerIn: parent
                                text: dashboard.workElapsedText
                                font.pixelSize: 12
                                font.bold: true
                                color: dashboard.trainingRunning ? "#1E40AF" : "#155E75"
                            }
                        }
                        Rectangle {
                            visible: dashboard.appWorking && dashboard.workPercentText !== ""
                            radius: 9
                            color: dashboard.trainingRunning ? "#1D4ED8" : "#0891B2"
                            implicitWidth: pctLbl.implicitWidth + 14
                            implicitHeight: 20
                            TextLabel {
                                id: pctLbl
                                anchors.centerIn: parent
                                text: dashboard.workPercentText
                                font.pixelSize: 12
                                font.bold: true
                                color: "white"
                            }
                        }
                    }

                    TextLabel {
                        visible: dashboard.appWorking ? (dashboard.workDetail !== "") : (dashboard.trainingStage !== "" && dashboard.trainingNote !== "")
                        Layout.fillWidth: true
                        Layout.minimumWidth: 0
                        text: dashboard.appWorking
                            ? (dashboard.trainingNote !== "" && dashboard.trainingNote !== dashboard.workDetail && dashboard.workDetail.indexOf(dashboard.trainingNote) === -1
                                ? (dashboard.workDetail + " · " + dashboard.trainingNote)
                                : dashboard.workDetail)
                            : dashboard.trainingNote
                        font.pixelSize: 12
                        color: "#334155"
                        wrapMode: Text.Wrap
                    }
                }

                Canvas {
                    id: bannerLossChart
                    visible: dashboard.appWorking && dashboard.trainingLosses.length > 1
                    Layout.preferredWidth: 150
                    Layout.preferredHeight: 30
                    property var losses: dashboard.trainingLosses
                    onLossesChanged: requestPaint()
                    onPaint: {
                        var ctx = getContext("2d")
                        ctx.reset()
                        var v = losses
                        if (!v || v.length < 2) return
                        var hi = Math.max.apply(null, v), lo = Math.min.apply(null, v)
                        var span = Math.max(1e-6, hi - lo)
                        ctx.strokeStyle = "#16846E"
                        ctx.lineWidth = 2
                        ctx.beginPath()
                        for (var i = 0; i < v.length; i++) {
                            var x = i / (v.length - 1) * (width - 4) + 2
                            var y = 3 + (1 - (v[i] - lo) / span) * (height - 6)
                            if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y)
                        }
                        ctx.stroke()
                    }
                }

                CompactButton {
                    visible: workBanner.showOpenCenterButton && !trainingCenter.visible
                    text: "학습 센터 열기"
                    primary: true
                    onClicked: trainingCenter.open()
                }

                CompactButton {
                    visible: workBanner.showStopButton && dashboard.trainingRunning && !dashboard.trainingPausing
                    text: "일시중지"
                    onClicked: dashboard.pauseTraining()
                }

                CompactButton {
                    visible: workBanner.showStopButton && dashboard.trainingRunning
                    text: "학습 멈춤"
                    danger: true
                    onClicked: dashboard.stopTraining()
                }
            }

            RowLayout {
                visible: workBanner.showStatusWhenIdle && dashboard.trainingResumable
                Layout.fillWidth: true
                spacing: 8
                TextLabel {
                    Layout.fillWidth: true
                    Layout.minimumWidth: 0
                    text: dashboard.trainingResumeText
                    font.pixelSize: 12
                    color: "#334155"
                    wrapMode: Text.Wrap
                }
                CompactButton {
                    text: "이어서 학습"
                    primary: true
                    onClicked: dashboard.resumeTraining()
                }
                CompactButton {
                    text: "버리기"
                    onClicked: dashboard.discardTraining()
                }
            }

            Rectangle {
                id: barTrack
                visible: dashboard.appWorking
                Layout.fillWidth: true
                height: 8
                radius: 4
                color: dashboard.trainingRunning ? "#DBEAFE" : "#CFFAFE"
                clip: true

                Rectangle {
                    id: determinateFill
                    visible: !dashboard.workIndeterminate
                    width: parent.width * Math.max(0.03, Math.min(1.0, dashboard.workProgress))
                    height: parent.height
                    radius: 4
                    color: dashboard.trainingRunning ? "#2563EB" : "#06B6D4"
                    Behavior on width {
                        NumberAnimation { duration: 220; easing.type: Easing.OutCubic }
                    }
                }

                Rectangle {
                    id: indeterminateFill
                    visible: dashboard.workIndeterminate
                    width: Math.max(80, parent.width * 0.32)
                    height: parent.height
                    radius: 4
                    color: dashboard.trainingRunning ? "#3B82F6" : "#06B6D4"
                    property real slidePhase: 0.0
                    x: (parent.width - width) * slidePhase
                    SequentialAnimation on slidePhase {
                        loops: Animation.Infinite
                        running: workBanner.visible && dashboard.appWorking && dashboard.workIndeterminate
                        NumberAnimation { from: 0.0; to: 1.0; duration: 900; easing.type: Easing.InOutQuad }
                        NumberAnimation { from: 1.0; to: 0.0; duration: 900; easing.type: Easing.InOutQuad }
                    }
                }
            }
        }
    }

    ColumnLayout {
        visible: dashboard.stage === "main"
        anchors.fill: parent
        spacing: 0
        Rectangle {
            color: "white"
            Layout.fillWidth: true
            Layout.preferredHeight: 72
            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: 24
                anchors.rightMargin: 24
                spacing: 12
                TextLabel { text: dashboard.appName; font.pixelSize: 26; font.bold: true }
                TextLabel { text: "INPUT STUDIO"; font.pixelSize: 12; font.letterSpacing: 1.4; color: window.muted }
                Item { Layout.fillWidth: true }
                ActionButton {
                    text: dashboard.appWorking
                        ? ("학습 센터 · " + dashboard.workPercentText)
                        : "학습 센터"
                    accent: dashboard.appWorking
                    onClicked: trainingCenter.open()
                }
                ActionButton {
                    objectName: "llmTopButton"
                    text: "말·글로 연결 (AI)"
                    onClicked: llmDialog.open()
                }
                ActionButton {
                    text: dashboard.chosenHand ? dashboard.chosenHand + " · 다시 설정" : "사용할 손 설정"
                    onClicked: dashboard.beginHandSetup()
                }
                ActionButton {
                    text: "설정"
                    enabled: !dashboard.calibratingPointer
                    onClicked: {
                        if (dashboard.pointerOnly) {
                            dashboard.command(27)
                            pointerSettings.open()
                        } else {
                            palmSettings.open()
                        }
                    }
                }
                ActionButton {
                    // Start = the one primary action on screen; while running it turns into the mint "on" state
                    text: dashboard.controlLabel
                    primary: dashboard.controlLabel.indexOf("시작") >= 0
                    accent: !primary
                    onClicked: dashboard.command(32)
                }
            }
        }
        // learning while using (docs/use-log.md): what the app is doing by itself with the taught gestures' uses.
        // 2026-11-11: one card per gesture (it was one long sentence), each with its own [사례 보기] = those collected uses
        Rectangle {
            objectName: "learnBanner"
            visible: dashboard.learnItems.length > 0 || dashboard.learnAutoLine !== ""
                     || dashboard.onnxCandidate.ready === true || dashboard.onnxCandidate.can_rollback === true
            Layout.fillWidth: true
            Layout.leftMargin: 20
            Layout.rightMargin: 20
            Layout.topMargin: 12
            implicitHeight: learnCol.implicitHeight + 20
            radius: 10
            color: "#F2FAF6"
            border.color: "#BFE5D3"
            ColumnLayout {
                id: learnCol
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.top: parent.top
                anchors.margins: 10
                spacing: 8
                RowLayout {
                    Layout.fillWidth: true
                    spacing: 10
                    Text {
                        text: "쓰면서 배우는 중"
                        font.pixelSize: 13
                        font.bold: true
                        color: "#17603F"
                    }
                    Text {
                        Layout.fillWidth: true
                        text: dashboard.learnAutoLine !== "" ? "자동 학습 · " + dashboard.learnAutoLine
                                                            : "가르친 동작을 쓸 때마다 앞뒤 손 움직임을 모아 TCN을 자동으로 학습해요"
                        font.pixelSize: 12
                        color: dashboard.learnAutoLine !== "" ? "#17603F" : window.muted
                        elide: Text.ElideRight
                    }
                    CompactButton {
                        // 2026-11-12: a candidate of the exported gesture model, trained by the app from the collected
                        // uses, waits for the person's look (it replaces nothing by itself)
                        objectName: "onnxCandidateButton"
                        visible: dashboard.onnxCandidate.ready === true || dashboard.onnxCandidate.can_rollback === true
                        accent: dashboard.onnxCandidate.ready === true
                        text: dashboard.onnxCandidate.ready === true ? "새 모델 확인" : "손짓 모델 되돌리기"
                        onClicked: onnxDialog.open()
                    }
                }
                Flow {
                    Layout.fillWidth: true
                    spacing: 8
                    Repeater {
                        model: dashboard.learnItems
                        delegate: Rectangle {
                            id: learnCard
                            objectName: "learnCard"
                            required property var modelData
                            readonly property bool counting: modelData.need > 0
                            width: 300
                            height: learnCardCol.implicitHeight + 16
                            radius: 8
                            color: "#FFFFFF"
                            border.color: modelData.state === "ready" || modelData.state === "learned" ? "#6CCB9F"
                                          : modelData.state === "review" ? "#F0A070" : "#D5E7DE"
                            ColumnLayout {
                                id: learnCardCol
                                anchors.left: parent.left
                                anchors.right: parent.right
                                anchors.top: parent.top
                                anchors.margins: 8
                                spacing: 5
                                RowLayout {
                                    Layout.fillWidth: true
                                    spacing: 6
                                    Text {
                                        Layout.fillWidth: true
                                        text: learnCard.modelData.name
                                        font.pixelSize: 13
                                        font.bold: true
                                        color: window.ink
                                        elide: Text.ElideRight
                                    }
                                    Rectangle {
                                        radius: 9
                                        implicitWidth: stateText.implicitWidth + 14
                                        implicitHeight: 18
                                        color: ({collecting: "#E8F0FE", ready: "#DCFCE7", waiting: "#FEF3C7", learned: "#D1FAE5", review: "#FDE8D8", nobase: "#FEF3C7", candidate: "#FDE8D8"})[learnCard.modelData.state] || "#EEE"
                                        Text {
                                            id: stateText
                                            anchors.centerIn: parent
                                            text: ({collecting: "모으는 중", ready: "곧 학습", waiting: "다른 날 기다림", learned: "학습됨", review: "검토 필요", nobase: "기본 모델 필요", candidate: "확인 필요"})[learnCard.modelData.state] || ""
                                            font.pixelSize: 11
                                            font.bold: true
                                            color: ({collecting: "#1D4ED8", ready: "#15803D", waiting: "#B45309", learned: "#047857", review: "#C2410C", nobase: "#B45309", candidate: "#C2410C"})[learnCard.modelData.state] || window.muted
                                        }
                                    }
                                }
                                RowLayout {
                                    visible: learnCard.counting
                                    Layout.fillWidth: true
                                    spacing: 8
                                    Rectangle {
                                        Layout.fillWidth: true
                                        implicitHeight: 8
                                        radius: 4
                                        color: "#E5EFEA"
                                        Rectangle {
                                            width: parent.width * Math.min(1, learnCard.modelData.n / Math.max(1, learnCard.modelData.need))
                                            height: parent.height
                                            radius: 4
                                            color: "#10B981"
                                        }
                                    }
                                    Text {
                                        text: learnCard.modelData.n + " / " + learnCard.modelData.need
                                        font.pixelSize: 12
                                        font.bold: true
                                        color: window.ink
                                    }
                                }
                                Text {
                                    visible: !learnCard.counting && learnCard.modelData.n > 0
                                    text: "사용 사례 " + learnCard.modelData.n + "개 저장됨"
                                    font.pixelSize: 12
                                    font.bold: true
                                    color: window.ink
                                }
                                RowLayout {
                                    Layout.fillWidth: true
                                    spacing: 6
                                    Text {
                                        Layout.fillWidth: true
                                        text: learnCard.modelData.text + (learnCard.modelData.hint ? " · " + learnCard.modelData.hint : "")
                                        font.pixelSize: 11
                                        color: window.muted
                                        wrapMode: Text.Wrap
                                    }
                                    CompactButton {
                                        // enough uses were collected: the person judges them before anything is learned
                                        objectName: "learnCardReview"
                                        visible: learnCard.modelData.state === "review"
                                        accent: true
                                        text: "검토하기"
                                        onClicked: {
                                            dashboard.openUseReview(learnCard.modelData.key, learnCard.modelData.name)
                                            useCasesDialog.open()
                                        }
                                    }
                                    CompactButton {
                                        // the exported gesture model's card: its candidate is looked at, not single uses
                                        objectName: "learnCardCandidate"
                                        visible: learnCard.modelData.key === "__onnx__" && learnCard.modelData.state === "candidate"
                                        accent: true
                                        text: "새 모델 확인"
                                        onClicked: onnxDialog.open()
                                    }
                                    CompactButton {
                                        objectName: "learnCardCases"
                                        visible: learnCard.modelData.state !== "review" && learnCard.modelData.key !== "__onnx__"
                                        text: "사례 보기"
                                        onClicked: {
                                            dashboard.openUseCases(learnCard.modelData.key, learnCard.modelData.name)
                                            useCasesDialog.open()
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }        Item {
            visible: dashboard.appWorking
            Layout.fillWidth: true
            Layout.leftMargin: 20
            Layout.rightMargin: 20
            Layout.topMargin: 12
            implicitHeight: mainWorkBanner.implicitHeight
            WorkProgressBanner {
                id: mainWorkBanner
                anchors.fill: parent
                showOpenCenterButton: true
                showStopButton: true
            }
        }
        RowLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            Layout.margins: 20
            spacing: 16
            Rectangle {
                Layout.preferredWidth: 312
                Layout.minimumWidth: 298
                Layout.maximumWidth: 328
                Layout.fillHeight: true
                radius: 16
                color: "white"
                border.color: window.line
                ColumnLayout {
                    anchors.fill: parent
                    anchors.margins: 12
                    spacing: 8
                    ScrollView {
                        id: sideScroll
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        clip: true
                        contentWidth: availableWidth
                        ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
                        Item {
                            width: Math.max(180, sideScroll.availableWidth - 10)
                            implicitHeight: sideCol.implicitHeight
                            ColumnLayout {
                                id: sideCol
                                anchors.left: parent.left
                                anchors.right: parent.right
                                spacing: 8
                                TextLabel { text: "포인터"; font.pixelSize: 20; font.bold: true }
                                Segmented {
                                    enabled: !dashboard.calibratingPointer && !dashboard.trackingActive
                                    options: [["index", "검지 포인터"], ["palm", "손바닥 (Dan)"]]
                                    current: dashboard.pointerOnly ? "index" : "palm"
                                    onPicked: function (value) { dashboard.setPointerPreset(value === "index") }
                                }
                                // motion mode and the cursor direction calibration: in [설정] (palmSettings), 2026-11-10
                                ActionButton {
                                    Layout.fillWidth: true
                                    Layout.minimumWidth: 0
                                    implicitWidth: 0
                                    leftPadding: 10; rightPadding: 10
                                    enabled: !dashboard.calibratingPointer && !dashboard.trackingActive
                                    objectName: "profileButton"
                                    text: dashboard.profileLabel + "  · 관리"
                                    onClicked: profileManager.open()
                                }
                                ActionButton {
                                    visible: !dashboard.pointerOnly
                                    Layout.fillWidth: true
                                    Layout.minimumWidth: 0
                                    implicitWidth: 0
                                    leftPadding: 10; rightPadding: 10
                                    enabled: !dashboard.palmCalibrating && !dashboard.trackingActive
                                    text: "커서 기준점 · " + dashboard.anchorJointsLabel
                                    onClicked: anchorPicker.openWith(dashboard.anchorJoints)
                                }
                                // (2026-11-11: [새 동작 등록], [학습하기]·[되돌리기] and their line were here - removed, the AI window and the
                                // training center do the same; the summary they read is still loaded for the rest of the screen)
                                Item { Component.onCompleted: dashboard.refreshOnlineSummary() }
                                SectionLabel { visible: !dashboard.pointerOnly; text: "화면에 가상 손" }
                                Segmented {
                                    visible: !dashboard.pointerOnly
                                    options: [["off", "끔"], ["on", "켬"]]
                                    current: dashboard.virtualHandOn ? "on" : "off"
                                    onPicked: function (value) { dashboard.setVirtualHand(value === "on") }
                                }
                                ActionButton {
                                    visible: !dashboard.pointerOnly && dashboard.virtualHandOn
                                    Layout.fillWidth: true
                                    Layout.minimumWidth: 0
                                    implicitWidth: 0
                                    accent: dashboard.boxEditing
                                    text: dashboard.boxEditing && !dashboard.boxEditingOther ? "그리는 중 · 누르면 취소" : "손 움직일 영역 다시 그리기"
                                    onClicked: dashboard.setBoxEditing(!(dashboard.boxEditing && !dashboard.boxEditingOther))
                                }
                                // the other hand's own box (2026-11-12, "왼손 모니터 박스를 별도로"): the whole image until drawn
                                RowLayout {
                                    visible: !dashboard.pointerOnly && dashboard.virtualHandOn && dashboard.otherMotionOn
                                    Layout.fillWidth: true
                                    spacing: 6
                                    ActionButton {
                                        objectName: "otherBoxButton"
                                        Layout.fillWidth: true
                                        Layout.minimumWidth: 0
                                        implicitWidth: 0
                                        accent: dashboard.boxEditingOther
                                        text: dashboard.boxEditingOther ? "그리는 중 · 누르면 취소"
                                              : (dashboard.otherBoxDrawn ? "다른 손 영역 다시 그리기" : "다른 손 영역 그리기")
                                        onClicked: dashboard.setOtherBoxEditing(!dashboard.boxEditingOther)
                                    }
                                    ActionButton {
                                        visible: dashboard.otherBoxDrawn && !dashboard.boxEditingOther
                                        text: "전체 화면"
                                        onClicked: dashboard.resetOtherBox()
                                    }
                                }
                                SectionLabel { visible: !(dashboard.virtualHandOn && !dashboard.pointerOnly); text: "커서 옆 손가락 표시" }
                                Segmented {
                                    visible: !(dashboard.virtualHandOn && !dashboard.pointerOnly)
                                    options: [["off", "끔"], ["on", "켬"]]
                                    current: dashboard.fingerOverlay ? "on" : "off"
                                    onPicked: function (value) { dashboard.setFingerOverlay(value === "on") }
                                }
                                SectionLabel { visible: !dashboard.pointerOnly; text: "손 주변 확대 (시험)" }
                                Segmented {
                                    visible: !dashboard.pointerOnly
                                    enabled: !dashboard.palmCalibrating && !dashboard.trackingActive
                                    options: [["off", "끔"], ["on", "켬"]]
                                    current: dashboard.handCrop ? "on" : "off"
                                    onPicked: function (value) { dashboard.setHandCrop(value === "on") }
                                }
                                SectionLabel { visible: !dashboard.pointerOnly && dashboard.tcnAvailable; text: "손짓 확인 (TCN: 학습된 동작)" }
                                Segmented {
                                    visible: !dashboard.pointerOnly && dashboard.tcnAvailable
                                    options: [["off", "끔"], ["on", "켬"]]
                                    current: dashboard.tcnGate ? "on" : "off"
                                    onPicked: function (value) { dashboard.setTcnGate(value === "on") }
                                }
                                ColumnLayout {
                                    visible: !dashboard.pointerOnly && dashboard.tcnAvailable && dashboard.tcnGate
                                    Layout.fillWidth: true
                                    spacing: 2
                                    TextLabel {
                                        Layout.fillWidth: true
                                        text: dashboard.gateCalibratedConfidenceText
                                        font.pixelSize: 12
                                        color: window.muted
                                        wrapMode: Text.WordWrap
                                    }
                                    Segmented {
                                        visible: dashboard.onlineReady && dashboard.learnCanUse
                                        enabled: !dashboard.palmCalibrating && !dashboard.trackingActive
                                        options: [["tcn", "기존 모델"], ["online", "내 모델"]]
                                        current: dashboard.gateModel
                                        onPicked: function (value) { dashboard.setGateModel(value) }
                                    }
                                    TextLabel {
                                        Layout.fillWidth: true
                                        text: dashboard.gateRejectionReasonText
                                        font.pixelSize: 12
                                        color: window.muted
                                        wrapMode: Text.WordWrap
                                    }
                                }
                                SectionLabel { visible: !dashboard.pointerOnly; text: "학습 데이터 녹화" }
                                Segmented {
                                    visible: !dashboard.pointerOnly
                                    enabled: !dashboard.palmCalibrating && !dashboard.trackingActive
                                    options: [["off", "끔"], ["guided", "안내 녹화"], ["free", "평소 녹화"]]
                                    current: dashboard.recMode
                                    onPicked: function (value) {
                                        if (value === "guided") {
                                            if (dashboard.focusRecord("")) capturePlan.open()
                                        } else { dashboard.setRecMode(value) }
                                    }
                                }
                                ColumnLayout {
                                    visible: dashboard.pointerOnly
                                    Layout.fillWidth: true
                                    spacing: 8
                                    SectionLabel { text: "클릭" }
                                    Segmented {
                                        enabled: !dashboard.calibratingPointer && !dashboard.trackingActive
                                        options: [["pinch", "핀치"], ["trigger", "방아쇠"], ["off", "끔"]]
                                        current: dashboard.clickStyle
                                        onPicked: function (value) { dashboard.setClickStyle(value) }
                                    }
                                    SectionLabel { text: "커서 기준점" }
                                    Segmented {
                                        enabled: !dashboard.calibratingPointer && !dashboard.trackingActive
                                        options: [["index", "검지 끝"], ["palm", "직접 지정"]]
                                        current: dashboard.pointerAnchor
                                        onPicked: function (value) { dashboard.setAnchor(value) }
                                    }
                                    ActionButton {
                                        visible: dashboard.pointerAnchor === "palm"
                                        Layout.fillWidth: true
                                        Layout.minimumWidth: 0
                                        implicitWidth: 0
                                        leftPadding: 10; rightPadding: 10
                                        enabled: !dashboard.calibratingPointer && !dashboard.trackingActive
                                        text: "기준점 · " + dashboard.anchorJointsLabel + "  · 바꾸기"
                                        onClicked: anchorPicker.openWith(dashboard.anchorJoints)
                                    }
                                    SectionLabel { text: "손 주변 확대 (시험)" }
                                    Segmented {
                                        enabled: !dashboard.calibratingPointer && !dashboard.trackingActive
                                        options: [["off", "끔"], ["on", "켬"]]
                                        current: dashboard.handCrop ? "on" : "off"
                                        onPicked: function (value) { dashboard.setHandCrop(value === "on") }
                                    }
                                    RowLayout {
                                        Layout.fillWidth: true
                                        spacing: 6
                                        ActionButton {
                                            Layout.fillWidth: true
                                            Layout.minimumWidth: 0
                                            implicitWidth: 0
                                            leftPadding: 10; rightPadding: 10
                                            enabled: !dashboard.calibratingPointer
                                            text: dashboard.pointerCalibrated ? "방향 보정 다시" : "방향 보정"
                                            onClicked: dashboard.beginPointerCalibration()
                                        }
                                        ActionButton {
                                            visible: dashboard.pointerCalibrated && !dashboard.calibratingPointer
                                            leftPadding: 10; rightPadding: 10
                                            text: "초기화"
                                            onClicked: dashboard.resetPointerCalibration()
                                        }
                                    }
                                }
                                TextLabel {
                                    Layout.fillWidth: true
                                    text: "설정을 바꾸면 입력이 멈춥니다. 다시 제어 시작을 누르세요."
                                    color: window.muted
                                    wrapMode: Text.Wrap
                                    font.pixelSize: 12
                                }
                                Divider {}
                                RowLayout {
                                    Layout.fillWidth: true
                                    spacing: 4
                                    SectionLabel {
                                        text: "동작 · 단축키 매핑"
                                        Layout.fillWidth: true
                                        Layout.minimumWidth: 0
                                        elide: Text.ElideRight
                                    }
                                    CompactButton {
                                        visible: !dashboard.pointerOnly
                                        text: "단축키·모션 설정"
                                        implicitHeight: 24
                                        leftPadding: 7; rightPadding: 7
                                        onClicked: {
                                            trainingCenter.centerTab = "bindings"
                                            trainingCenter.open()
                                        }
                                    }
                                }
                                Repeater {
                                    visible: dashboard.pointerOnly
                                    model: dashboard.pointerOnly ? (dashboard.clickOff
                                        ? [[dashboard.pointerAnchor === "palm" ? (dashboard.anchorJointsLabel + " 따라가기") : "검지 끝 따라가기", "포인터 이동"], ["클릭", "꺼짐"]]
                                        : dashboard.triggerClick
                                        ? [["검지만 펴기", "포인터 이동"], ["엄지로 검지 옆 짧게", "좌클릭"],
                                           ["누른 채 가만히", "우클릭"], ["누른 채 움직이기", "드래그"]]
                                        : [["검지만 펴기", "포인터 이동"], ["엄지 + 중지", "좌클릭"], ["엄지 + 약지", "우클릭"]]) : []
                                    delegate: RowLayout {
                                        required property var modelData
                                        Layout.fillWidth: true
                                        TextLabel { text: modelData[0]; font.pixelSize: 12; font.bold: true; Layout.fillWidth: true; Layout.minimumWidth: 0; elide: Text.ElideRight }
                                        TextLabel { text: modelData[1]; font.pixelSize: 12; color: window.muted }
                                    }
                                }
                                Repeater {
                                    visible: !dashboard.pointerOnly
                                    model: !dashboard.pointerOnly ? dashboard.sidebarGestureMappings : []
                                    delegate: RowLayout {
                                        required property var modelData
                                        Layout.fillWidth: true
                                        spacing: 4
                                        Rectangle {
                                            radius: 4
                                            color: modelData.track === "motion" ? "#EDE9FE" : (modelData.track === "composite" ? "#FEF3C7" : "#E6F8F3")
                                            border.color: modelData.track === "motion" ? "#C4B5FD" : (modelData.track === "composite" ? "#FCD34D" : "#8CE0CA")
                                            implicitWidth: sideTrackLbl.implicitWidth + 6
                                            implicitHeight: 17
                                            TextLabel {
                                                id: sideTrackLbl
                                                anchors.centerIn: parent
                                                text: modelData.track === "motion" ? "모션" : (modelData.track === "composite" ? "복합" : "정지")
                                                font.pixelSize: 11
                                                font.bold: true
                                                color: modelData.track === "motion" ? "#5B21B6" : (modelData.track === "composite" ? "#92400E" : "#0F6E5B")
                                            }
                                        }
                                        TextLabel {
                                            text: modelData.gesture
                                            font.pixelSize: 12
                                            font.bold: true
                                            elide: Text.ElideRight
                                            Layout.fillWidth: true
                                            Layout.minimumWidth: 0
                                        }
                                        TextLabel {
                                            text: modelData.badge
                                            font.pixelSize: 12
                                            color: modelData.track === "motion" ? "#4C1D95" : "#0F6E5B"
                                            font.bold: true
                                            elide: Text.ElideRight
                                            horizontalAlignment: Text.AlignRight
                                            Layout.maximumWidth: 118
                                            Layout.minimumWidth: 0
                                        }
                                    }
                                }
                                TextLabel {
                                    visible: dashboard.pointerOnly
                                    Layout.fillWidth: true
                                    text: dashboard.clickOff
                                        ? "클릭을 판정하지 않습니다. 손이 보이면 손 모양과 관계없이 커서가 따라갑니다."
                                        : dashboard.triggerClick
                                        ? "엄지가 검지 옆에 다가오면 커서가 고정되고, 누르기 직전 위치에서 클릭합니다."
                                        : "검지를 움직이는 동안에는 클릭하지 않습니다. 멈춘 뒤 엄지를 뗐다가 중지·약지에 대면 클릭합니다."
                                    color: window.muted
                                    wrapMode: Text.Wrap
                                    font.pixelSize: 12
                                }
                                TextLabel {
                                    visible: dashboard.pointerOnly && diagnostics.visible
                                    Layout.fillWidth: true
                                    text: "0 엄지 · 1 검지 · 2 중지 · 3 약지 · 4 새끼\n조합: " + (dashboard.detectedContacts || "—")
                                    wrapMode: Text.Wrap
                                    color: window.muted
                                    font.pixelSize: 12
                                }
                                Divider { visible: dashboard.pointerOnly }
                                SectionLabel { visible: dashboard.pointerOnly; text: "트래킹 측정" }
                                ActionButton {
                                    visible: dashboard.pointerOnly
                                    enabled: !dashboard.calibratingPointer && !dashboard.trackingActive
                                    Layout.fillWidth: true
                                    text: "측정 시작 (클릭 없음)"
                                    onClicked: dashboard.beginTrackingTest()
                                }
                                TextLabel {
                                    visible: dashboard.pointerOnly && dashboard.recentResults.length === 0
                                    Layout.fillWidth: true
                                    text: "아직 측정 기록이 없습니다. 설정을 바꿔 가며 측정해 비교하세요."
                                    color: window.muted
                                    wrapMode: Text.Wrap
                                    font.pixelSize: 12
                                }
                                Repeater {
                                    model: dashboard.pointerOnly ? dashboard.recentResults : []
                                    delegate: TextLabel {
                                        required property string modelData
                                        required property int index
                                        Layout.fillWidth: true
                                        text: modelData
                                        wrapMode: Text.Wrap
                                        font.pixelSize: 12
                                        font.bold: index === 0
                                        color: index === 0 ? window.navy : window.muted
                                    }
                                }
                                Divider { visible: dashboard.pointerOnly }
                                SectionLabel { visible: dashboard.pointerOnly; text: "실패 기록" }
                                TextLabel {
                                    visible: dashboard.pointerOnly
                                    Layout.fillWidth: true
                                    text: dashboard.failureSummary + (dashboard.failureLast ? "\n최근: " + dashboard.failureLast : "")
                                        + "\n손을 놓치면 앞뒤 3초의 관절 좌표를 logs/failures에 저장합니다(영상 없음)."
                                    color: window.muted
                                    wrapMode: Text.Wrap
                                    font.pixelSize: 12
                                }
                                ActionButton {
                                    visible: dashboard.pointerOnly
                                    Layout.fillWidth: true
                                    text: "방금 이상했어요 (F)"
                                    onClicked: dashboard.markFailure()
                                }
                            }
                        }
                    }
                    Divider {}
                    TextLabel {
                        Layout.fillWidth: true
                        text: "Space 시작/정지 · Esc 정지 · N 다음 모니터 · F 실패 표시 · F8 잘못된 클릭 표시 (어느 창에서든)"
                        font.pixelSize: 12
                        color: window.muted
                        wrapMode: Text.Wrap
                    }
                }
            }
            Rectangle {
                Layout.fillWidth: true
                Layout.fillHeight: true
                radius: 16
                color: "white"
                border.color: window.line
                ColumnLayout {
                    anchors.fill: parent
                    anchors.margins: 18
                    spacing: 12
                    RowLayout {
                        Layout.fillWidth: true
                        spacing: 8
                        TextLabel { text: "카메라"; font.pixelSize: 20; font.bold: true }
                        Item { Layout.fillWidth: true }
                        Chip { visible: dashboard.cameraMode !== ""; text: dashboard.cameraMode }
                        Chip {
                            visible: dashboard.brightness >= 0
                            warn: dashboard.lowLight
                            text: (dashboard.lowLight ? "어두움 " : "밝기 ") + Math.round(dashboard.brightness / 2.55) + "%"
                        }
                        Chip { text: dashboard.tracking }
                    }
                    Rectangle {
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        radius: 10
                        color: window.navy
                        clip: true
                        Image {
                            id: capturePreview
                            anchors.fill: parent
                            source: dashboard.previewUrl
                            cache: false
                            fillMode: Image.PreserveAspectFit
                            HandSkeleton { anchors.fill: parent; imageWidth: capturePreview.paintedWidth; imageHeight: capturePreview.paintedHeight }
                        }
                        // The box for the hand on the screen: its inside is the whole monitor. Drag on the image to draw it.
                        Item {
                            id: boxLayer
                            objectName: "boxLayer"
                            visible: !dashboard.pointerOnly && dashboard.virtualHandOn
                            x: capturePreview.x + (capturePreview.width - capturePreview.paintedWidth) / 2
                            y: capturePreview.y + (capturePreview.height - capturePreview.paintedHeight) / 2
                            width: capturePreview.paintedWidth
                            height: capturePreview.paintedHeight
                            property point start
                            property point end
                            property bool dragging: false
                            readonly property var box: dashboard.virtualBox
                            readonly property bool drawingOther: dashboard.boxEditingOther
                            readonly property color otherColour: (dashboard.skeletonStyle && dashboard.skeletonStyle.values
                                                                  && dashboard.skeletonStyle.values.other) || "#D946EF"
                            // the other hand's box, in its colour (only once drawn: the whole image needs no frame)
                            Rectangle {
                                objectName: "otherBoxFrame"
                                readonly property var b: dashboard.otherBox
                                visible: dashboard.otherMotionOn && dashboard.otherBoxDrawn && !boxLayer.drawingOther
                                x: b[0] * boxLayer.width; y: b[1] * boxLayer.height
                                width: (b[2] - b[0]) * boxLayer.width; height: (b[3] - b[1]) * boxLayer.height
                                color: "transparent"
                                border.color: boxLayer.otherColour
                                border.width: 2
                                radius: 4
                            }
                            Rectangle {
                                visible: !boxLayer.drawingOther || boxLayer.dragging
                                x: (boxLayer.dragging ? Math.min(boxLayer.start.x, boxLayer.end.x) : boxLayer.box[0] * boxLayer.width)
                                y: (boxLayer.dragging ? Math.min(boxLayer.start.y, boxLayer.end.y) : boxLayer.box[1] * boxLayer.height)
                                width: boxLayer.dragging ? Math.abs(boxLayer.end.x - boxLayer.start.x) : (boxLayer.box[2] - boxLayer.box[0]) * boxLayer.width
                                height: boxLayer.dragging ? Math.abs(boxLayer.end.y - boxLayer.start.y) : (boxLayer.box[3] - boxLayer.box[1]) * boxLayer.height
                                color: dashboard.boxEditing ? Qt.rgba(0.27, 0.9, 0.74, 0.12) : "transparent"
                                border.color: boxLayer.drawingOther ? boxLayer.otherColour : window.mint
                                border.width: dashboard.boxEditing ? 3 : 2
                                radius: 4
                            }
                            Rectangle {
                                visible: dashboard.boxEditing
                                anchors.top: parent.top
                                anchors.horizontalCenter: parent.horizontalCenter
                                anchors.topMargin: 12
                                width: boxHint.implicitWidth + 28
                                height: boxHint.implicitHeight + 12
                                radius: height / 2
                                color: Qt.rgba(0.06, 0.09, 0.16, 0.72)
                                Text {
                                    id: boxHint
                                    anchors.centerIn: parent
                                    text: boxLayer.drawingOther ? "다른 손을 움직일 영역을 끌어서 그리세요 · 이 영역이 모니터 전체가 돼요"
                                                                : "손을 움직일 영역을 끌어서 그리세요 · 이 영역이 모니터 전체가 돼요"
                                    color: "#F5F7F8"
                                    font.pixelSize: 14
                                    font.family: Theme.Studio.font
                                }
                            }
                            MouseArea {
                                anchors.fill: parent
                                enabled: dashboard.boxEditing
                                cursorShape: dashboard.boxEditing ? Qt.CrossCursor : Qt.ArrowCursor
                                onPressed: function (mouse) { boxLayer.start = Qt.point(mouse.x, mouse.y); boxLayer.end = boxLayer.start; boxLayer.dragging = true }
                                onPositionChanged: function (mouse) {
                                    boxLayer.end = Qt.point(Math.max(0, Math.min(boxLayer.width, mouse.x)), Math.max(0, Math.min(boxLayer.height, mouse.y)))
                                }
                                onReleased: {
                                    boxLayer.dragging = false
                                    dashboard.setVirtualBox(boxLayer.start.x / boxLayer.width, boxLayer.start.y / boxLayer.height,
                                                            boxLayer.end.x / boxLayer.width, boxLayer.end.y / boxLayer.height)
                                }
                            }
                        }
                        // Read from 3 m away, but quietly: a translucent dark pill with the word (or the countdown number) in the colour of
                        // what to do now - teal = go, amber = get ready, blue = rest, red = timer stopped. Fades in and out.
                        Rectangle {
                            id: bigCue
                            readonly property bool shown: dashboard.recActive && dashboard.recBig !== ""
                            readonly property color accent: dashboard.recBigKind === "do" ? "#45E0B4"
                                                          : dashboard.recBigKind === "prep" ? "#F2B544"
                                                          : dashboard.recBigKind === "rest" ? "#7DB4FF"
                                                          : dashboard.recBigKind === "hold" ? "#FF8A8F" : "#EEF2F6"
                            visible: opacity > 0.01
                            opacity: shown ? 1.0 : 0.0
                            Behavior on opacity { NumberAnimation { duration: 180 } }
                            anchors.centerIn: parent
                            width: Math.min(parent.width * 0.7, bigCueText.implicitWidth + 64)
                            height: bigCueText.implicitHeight + 24
                            radius: 22
                            color: Qt.rgba(0.06, 0.09, 0.16, 0.55)
                            border.width: 2
                            border.color: Qt.rgba(accent.r, accent.g, accent.b, 0.75)
                            Text {
                                id: bigCueText
                                anchors.centerIn: parent
                                text: dashboard.recBig
                                color: bigCue.accent
                                font.bold: true
                                font.pixelSize: Math.max(48, Math.min(capturePreview.paintedHeight, capturePreview.paintedWidth) * (text.length <= 2 ? 0.34 : 0.18))
                            }
                        }
                        // A registered gesture recognised right now (shown only, it sends nothing to the mouse)
                        Rectangle {
                            objectName: "liveGesturePill"
                            opacity: dashboard.liveGesture !== "" ? 1.0 : 0.0
                            visible: opacity > 0.01
                            Behavior on opacity { NumberAnimation { duration: 120 } }
                            anchors.top: parent.top
                            anchors.horizontalCenter: parent.horizontalCenter
                            anchors.topMargin: 14
                            z: 5
                            width: Math.min(liveGestureText.implicitWidth + 40, parent.width - 24)
                            height: liveGestureText.implicitHeight + 16
                            radius: height / 2
                            color: Qt.rgba(0.06, 0.09, 0.16, 0.72)
                            border.width: 2
                            border.color: window.mint
                            Text {
                                id: liveGestureText
                                anchors.centerIn: parent
                                width: Math.min(implicitWidth, parent.width - 24)
                                elide: Text.ElideRight
                                text: dashboard.liveGesture
                                color: window.mint
                                font.pixelSize: 20
                                font.bold: true
                            }
                        }
                        // Hand lost: a thin soft red frame and a small pill at the top
                        Rectangle {
                            id: handLostFrame
                            opacity: dashboard.handLost ? 1.0 : 0.0
                            visible: opacity > 0.01
                            Behavior on opacity { NumberAnimation { duration: 180 } }
                            anchors.fill: parent
                            color: "transparent"
                            border.width: 4
                            border.color: Qt.rgba(0.90, 0.28, 0.30, 0.55)
                            Rectangle {
                                anchors.top: parent.top
                                anchors.horizontalCenter: parent.horizontalCenter
                                anchors.topMargin: 14
                                width: handLostText.implicitWidth + 36
                                height: handLostText.implicitHeight + 14
                                radius: height / 2
                                color: Qt.rgba(0.06, 0.09, 0.16, 0.6)
                                border.width: 2
                                border.color: Qt.rgba(1.0, 0.54, 0.56, 0.8)
                                Text {
                                    id: handLostText
                                    anchors.centerIn: parent
                                    text: "손을 놓쳤어요"
                                    color: "#FF8A8F"
                                    font.bold: true
                                    font.pixelSize: Math.max(22, capturePreview.paintedHeight * 0.06)
                                }
                            }
                        }
                        // An admin window (Task Manager) is in front: Windows drops this app's cursor and clicks there unless the
                        // app itself runs as administrator. Says so, with a button that restarts the app as administrator.
                        Rectangle {
                            id: adminBlockedPill
                            opacity: dashboard.adminBlocked ? 1.0 : 0.0
                            visible: opacity > 0.01
                            Behavior on opacity { NumberAnimation { duration: 180 } }
                            anchors.horizontalCenter: parent.horizontalCenter
                            anchors.verticalCenter: parent.verticalCenter
                            anchors.verticalCenterOffset: parent.height * 0.25
                            width: Math.min(parent.width * 0.9, adminBlockedRow.implicitWidth + 36)
                            height: adminBlockedRow.implicitHeight + 20
                            radius: 14
                            color: Qt.rgba(0.06, 0.09, 0.16, 0.7)
                            border.width: 2
                            border.color: Qt.rgba(0.95, 0.71, 0.27, 0.85)
                            RowLayout {
                                id: adminBlockedRow
                                anchors.centerIn: parent
                                spacing: 12
                                Text {
                                    text: "관리자 권한 창(작업 관리자 등)에서는 손으로 조작할 수 없어요"
                                    color: "#F2B544"
                                    font.bold: true
                                    font.pixelSize: Math.max(16, capturePreview.paintedHeight * 0.04)
                                }
                                ActionButton {
                                    text: "관리자 권한으로 다시 시작"
                                    primary: true
                                    onClicked: dashboard.restartAsAdmin()
                                }
                            }
                        }
                        // Arm lost (Pose): smaller, amber, at the bottom
                        Rectangle {
                            opacity: (dashboard.armLost && !dashboard.handLost) ? 1.0 : 0.0
                            visible: opacity > 0.01
                            Behavior on opacity { NumberAnimation { duration: 180 } }
                            anchors.bottom: parent.bottom
                            anchors.horizontalCenter: parent.horizontalCenter
                            anchors.bottomMargin: 14
                            width: armLostText.implicitWidth + 32
                            height: armLostText.implicitHeight + 12
                            radius: height / 2
                            color: Qt.rgba(0.06, 0.09, 0.16, 0.6)
                            border.width: 2
                            border.color: Qt.rgba(0.95, 0.71, 0.27, 0.8)
                            Text {
                                id: armLostText
                                anchors.centerIn: parent
                                text: "팔을 놓쳤어요"
                                color: "#F2B544"
                                font.bold: true
                                font.pixelSize: Math.max(18, capturePreview.paintedHeight * 0.045)
                            }
                        }
                        Item {
                            visible: dashboard.recMode !== "off"
                            x: (parent.width - capturePreview.paintedWidth) / 2
                            y: (parent.height - capturePreview.paintedHeight) / 2
                            width: capturePreview.paintedWidth
                            height: capturePreview.paintedHeight

                            Canvas {
                                id: liveRecSprayCanvas
                                anchors.fill: parent
                                onPaint: {
                                    var ctx = getContext("2d")
                                    var w = width
                                    var h = height
                                    ctx.clearRect(0, 0, w, h)
                                    var cells = dashboard.spatialSprayCells || []
                                    var baseR = Math.max(24, Math.min(w, h) * 0.13)
                                    for (var i = 0; i < cells.length; i++) {
                                        var cell = cells[i]
                                        var d = cell.density || 0
                                        if (d <= 0.01) continue
                                        var cx = cell.x * w
                                        var cy = cell.y * h
                                        var rad = baseR * (0.65 + 0.65 * Math.sqrt(d))
                                        var q = (cell.quality !== undefined) ? cell.quality : 0.85
                                        var rCol = q >= 0.72 ? 40 : (q >= 0.45 ? 242 : 229)
                                        var gCol = q >= 0.72 ? 229 : (q >= 0.45 ? 181 : 72)
                                        var bCol = q >= 0.72 ? 175 : (q >= 0.45 ? 68 : 77)
                                        var alpha = Math.min(0.42, 0.08 + d * 0.34)
                                        var grad = ctx.createRadialGradient(cx, cy, 0, cx, cy, rad)
                                        grad.addColorStop(0.0, "rgba(" + rCol + "," + gCol + "," + bCol + "," + alpha.toFixed(3) + ")")
                                        grad.addColorStop(0.55, "rgba(" + rCol + "," + gCol + "," + bCol + "," + (alpha * 0.45).toFixed(3) + ")")
                                        grad.addColorStop(1.0, "rgba(" + rCol + "," + gCol + "," + bCol + ",0.0)")
                                        ctx.fillStyle = grad
                                        ctx.beginPath()
                                        ctx.arc(cx, cy, rad, 0, Math.PI * 2)
                                        ctx.fill()

                                        // Spray stipple dots for visual concentration texture
                                        var dots = Math.min(18, Math.max(3, Math.round(d * 18)))
                                        ctx.fillStyle = "rgba(" + rCol + "," + gCol + "," + bCol + "," + Math.min(0.65, 0.18 + d * 0.45).toFixed(3) + ")"
                                        for (var k = 0; k < dots; k++) {
                                            var ang = ((cell.gx * 31 + cell.gy * 17 + k * 53) % 360) * (Math.PI / 180.0)
                                            var dist = (((cell.gx * 13 + cell.gy * 29 + k * 37) % 100) / 100.0) * (rad * 0.72)
                                            var dx = cx + Math.cos(ang) * dist
                                            var dy = cy + Math.sin(ang) * dist
                                            ctx.fillRect(dx - 1, dy - 1, 2.2, 2.2)
                                        }
                                    }
                                }
                                Connections {
                                    target: dashboard
                                    // The cells only change with the training state. Repainting on stateChanged redrew every cell
                                    // 30 times a second while recording (stateChanged fires with each frame).
                                    function onTrainingChanged() { liveRecSprayCanvas.requestPaint() }
                                }
                            }

                            Rectangle {
                                anchors.top: parent.top
                                anchors.left: parent.left
                                anchors.right: parent.right
                                anchors.margins: 10
                                implicitHeight: sprayGuideRow.implicitHeight + 12
                                radius: 8
                                color: "#B80D1B26"
                                border.color: "#8046E5BD"
                                RowLayout {
                                    id: sprayGuideRow
                                    anchors.fill: parent
                                    anchors.leftMargin: 12
                                    anchors.rightMargin: 12
                                    spacing: 8
                                    Rectangle { width: 10; height: 10; radius: 5; color: "#46E5BD" }
                                    Label {
                                        Layout.fillWidth: true
                                        text: "전체 화면 대상 녹화 · 초록 스프레이 음영 = AI 모델이 이미 학습된 영역 (음영이 옅거나 빈 영역 위주로 손을 자유롭게 움직이며 녹화하세요 · Space 키로 시작/일시정지)"
                                        color: "#EEFCF8"
                                        font.pixelSize: 12
                                        font.bold: true
                                        wrapMode: Text.Wrap
                                    }
                                }
                            }
                        }
                        Rectangle {
                            visible: dashboard.lowLight
                            anchors.left: parent.left
                            anchors.right: parent.right
                            anchors.bottom: parent.bottom
                            anchors.margins: 12
                            implicitHeight: lowLightText.implicitHeight + 16
                            radius: 8
                            color: "#F2B544"
                            TextLabel {
                                id: lowLightText
                                anchors.fill: parent
                                anchors.margins: 8
                                text: "어두워요. 움직일 때 손을 놓치기 쉽습니다. 조명을 켜거나 모니터를 밝게 하고, 손을 카메라에 조금 더 가까이 두세요."
                                wrapMode: Text.Wrap
                                font.pixelSize: 12
                                verticalAlignment: Text.AlignVCenter
                            }
                        }
                    }
                    RowLayout {
                        visible: dashboard.calibratingPointer
                        Layout.fillWidth: true
                        TextLabel {
                            Layout.fillWidth: true
                            text: dashboard.calibrationHint
                            wrapMode: Text.Wrap
                        }
                        ActionButton { text: "취소"; onClicked: dashboard.cancelPointerCalibration() }
                    }
                    RowLayout {
                        visible: dashboard.recActive
                        Layout.fillWidth: true
                        spacing: 10
                        ColumnLayout {
                            Layout.fillWidth: true
                            spacing: 4
                            TextLabel {
                                Layout.fillWidth: true
                                visible: dashboard.recCondition !== ""
                                text: dashboard.recCondition
                                font.pixelSize: 12
                                color: "#16846E"
                                wrapMode: Text.Wrap
                            }
                            TextLabel {
                                Layout.fillWidth: true
                                // A fixed height: when the prompt changed from one line to three, the panel grew and the camera
                                // preview above (it fills the rest) shrank and jumped on every change.
                                Layout.preferredHeight: 48
                                visible: dashboard.recPrompt !== ""
                                text: dashboard.recPrompt
                                font.pixelSize: 16
                                font.bold: true
                                wrapMode: Text.Wrap
                                maximumLineCount: 2
                                elide: Text.ElideRight
                            }
                            Rectangle {
                                visible: dashboard.recMode === "guided" && dashboard.recPrompt !== ""
                                Layout.fillWidth: true
                                height: 6
                                radius: 3
                                color: "#E3E9EE"
                                Rectangle {
                                    width: parent.width * Math.max(0, Math.min(1, dashboard.recProgress))
                                    height: parent.height
                                    radius: 3
                                    color: "#45E0B4"
                                }
                            }
                            TextLabel {
                                Layout.fillWidth: true
                                Layout.preferredHeight: 32
                                text: dashboard.recSub
                                font.pixelSize: 12
                                color: window.muted
                                wrapMode: Text.Wrap
                                maximumLineCount: 2
                                elide: Text.ElideRight
                            }
                        }
                        ActionButton { visible: dashboard.recWaiting; text: "시작 (Space)"; primary: true; onClicked: dashboard.recStart() }
                        ActionButton {
                            visible: (dashboard.recMode === "guided" && !dashboard.recWaiting) || dashboard.recMode === "free"
                            text: dashboard.recPaused ? "녹화 시작/계속 (Space)" : "일시정지 (Space)"
                            accent: dashboard.recPaused
                            primary: dashboard.recPaused && dashboard.recMode === "free"
                            onClicked: dashboard.toggleRecordingPause()
                        }
                        ActionButton { visible: dashboard.recMode !== "off"; text: "녹화 끝 (저장)"; primary: true; onClicked: dashboard.setRecMode("off") }
                        ActionButton { visible: dashboard.recMode !== "off"; text: "녹화 취소 (버리기)"; danger: true; onClicked: confirmDialog.ask("녹화 취소", "지금까지 녹화한 내용을 저장하지 않고 버립니다.", "버리기", function () { dashboard.discardRecording() }) }
                    }
                    Rectangle {
                        visible: dashboard.hasRecReview && dashboard.recMode === "off"
                        Layout.fillWidth: true
                        implicitHeight: recReviewCol.implicitHeight + 20
                        radius: 10
                        color: dashboard.recReviewStatus === "fail" ? "#FFF1F0" : (dashboard.recReviewStatus === "warning" ? "#FFF8EA" : "#EEFCF8")
                        border.color: dashboard.recReviewStatus === "fail" ? "#E5484D" : (dashboard.recReviewStatus === "warning" ? "#F2B544" : "#45E0B4")
                        ColumnLayout {
                            id: recReviewCol
                            anchors.fill: parent
                            anchors.margins: 10
                            spacing: 6
                            RowLayout {
                                Layout.fillWidth: true
                                spacing: 8
                                Chip {
                                    warn: dashboard.recReviewStatus !== "pass"
                                    text: dashboard.recReviewStatus === "pending" ? "품질 검사 중…" : (dashboard.recReviewStatus === "fail" ? "품질 미달 (자동 제외됨)" : (dashboard.recReviewStatus === "warning" ? "품질 주의" : "녹화 완료"))
                                }
                                TextLabel {
                                    Layout.fillWidth: true
                                    text: "방금 끝난 녹화: " + dashboard.recReviewFile + " — 학습 데이터에 반영할까요?"
                                    font.bold: true
                                    font.pixelSize: 13
                                    wrapMode: Text.Wrap
                                }
                            }
                            TextLabel {
                                Layout.fillWidth: true
                                text: dashboard.recReviewMessage
                                font.pixelSize: 12
                                color: window.muted
                                wrapMode: Text.Wrap
                            }
                            RowLayout {
                                Layout.fillWidth: true
                                spacing: 8
                                ActionButton {
                                    text: "학습에 포함"
                                    primary: dashboard.recReviewStatus !== "fail"
                                    enabled: dashboard.recReviewStatus !== "pending"      // the check is still running
                                    onClicked: dashboard.keepLastRecording(false)
                                }
                                ActionButton {
                                    text: "포함 후 바로 학습"
                                    primary: true
                                    enabled: !dashboard.trainingRunning && dashboard.recReviewStatus !== "pending"
                                    onClicked: dashboard.keepLastRecording(true)
                                }
                                ActionButton {
                                    text: "학습에서 제외 (파일 보관)"
                                    onClicked: dashboard.excludeLastRecording()
                                }
                                ActionButton {
                                    text: "녹화 파일 삭제"
                                    danger: true
                                    enabled: dashboard.recReviewStatus !== "pending"
                                    onClicked: confirmDialog.ask("녹화 파일 삭제", "'" + dashboard.recReviewFile + "' 파일을 디스크에서 지웁니다. 되돌릴 수 없습니다.", "삭제", function () { dashboard.deleteLastRecording() })
                                }
                            }
                        }
                    }
                    RowLayout {
                        visible: dashboard.palmCalibrating || (dashboard.palmAxesHint !== "" && !dashboard.calibratingPointer)
                        Layout.fillWidth: true
                        TextLabel {
                            Layout.fillWidth: true
                            text: dashboard.palmAxesHint
                            wrapMode: Text.Wrap
                        }
                        ActionButton { visible: dashboard.palmCalibrating; text: "취소"; onClicked: dashboard.cancelPalmCalibration() }
                    }
                    RowLayout {
                        visible: !dashboard.calibratingPointer && !dashboard.palmCalibrating
                        Layout.fillWidth: true
                        ColumnLayout {
                            Layout.fillWidth: true
                            TextLabel { text: dashboard.inputState; font.bold: true }
                            TextLabel { Layout.fillWidth: true; text: dashboard.currentAction; color: window.muted; wrapMode: Text.Wrap }
                        }
                        ActionButton { text: diagnostics.visible ? "상세 닫기" : "상세 정보"; onClicked: diagnostics.visible = !diagnostics.visible }
                    }
                    TextLabel {
                        id: diagnostics
                        visible: false
                        onVisibleChanged: dashboard.showFingertips(visible)
                        Layout.fillWidth: true
                        text: dashboard.details
                        color: window.muted
                        wrapMode: Text.Wrap
                        font.pixelSize: 12
                    }
                }
            }
        }
    }

    // Training center (src/training_center.py): data per gesture, scores, focused recording, training, export
    Popup {
        id: trainingCenter
        objectName: "trainingCenterPopup"
        property string centerTab: "gestures"
        property string selectedSimFile: ""
        property bool showImprovementReport: false
        property string bindingsSubTab: "shortcuts"
        property string selectedBindingKey: ""
        // What is chosen here is kept per profile (dashboard.centerPref): read at the start and when the profile changes
        property bool prefsLoading: true
        function loadPrefs() {
            prefsLoading = true
            var tab = dashboard.centerPref("centerTab", "gestures")
            centerTab = ["gestures", "recordings", "simulator", "diagnostics", "bindings"].indexOf(tab) >= 0 ? tab : "gestures"
            var sub = dashboard.centerPref("bindingsSubTab", "shortcuts")
            bindingsSubTab = ["shortcuts", "motions", "composites"].indexOf(sub) >= 0 ? sub : "shortcuts"
            simTabRoot.loadPrefs()
            bindingsTabRoot.loadPrefs()
            prefsLoading = false
        }
        function savePref(name, value) {
            if (!prefsLoading)
                dashboard.setCenterPref(name, value)
        }
        onCenterTabChanged: savePref("centerTab", centerTab)
        onBindingsSubTabChanged: savePref("bindingsSubTab", bindingsSubTab)
        Component.onCompleted: loadPrefs()
        anchors.centerIn: parent
        width: Math.min(1256, window.width - 20)
        height: Math.min(836, window.height - 20)
        modal: true
        focus: true
        closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside
        onOpened: {
            dashboard.openTraining()
            if (centerTab === "diagnostics" && dashboard.diagnosticsChecks.length === 0)
                dashboard.runDiagnostics()      // the tab left open last time: fill it as its button would
        }
        onClosed: dashboard.closeTraining()
        padding: 14
        background: Rectangle { radius: 16; color: "white"; border.color: window.line; clip: true }
        contentItem: Item {
            width: trainingCenter.availableWidth
            height: trainingCenter.availableHeight
            clip: true
            ColumnLayout {
                anchors.fill: parent
                spacing: 6
            RowLayout {
                Layout.fillWidth: true
                spacing: 8
                ColumnLayout {
                    Layout.fillWidth: true
                    Layout.minimumWidth: 0
                    spacing: 1
                    TextLabel {
                        Layout.fillWidth: true
                        Layout.minimumWidth: 0
                        elide: Text.ElideRight
                        text: "학습 센터"
                        font.pixelSize: 19
                        font.bold: true
                    }
                    TextLabel {
                        Layout.fillWidth: true
                        Layout.minimumWidth: 0
                        elide: Text.ElideRight
                        objectName: "centerSubtitle"
                        text: "녹화 고르기 → 학습 → 시뮬레이터로 확인 → 동작 연결  ·  여기서 바꾼 옵션은 「"
                              + dashboard.centerProfileName + "」에 저장돼요"
                        font.pixelSize: 12
                        color: window.muted
                    }
                }
                CompactButton { text: "새로고침"; implicitHeight: 34; leftPadding: 14; rightPadding: 14; enabled: dashboard.trainingBusy === ""; onClicked: dashboard.refreshTraining() }
                CompactButton { text: "닫기"; implicitHeight: 34; leftPadding: 14; rightPadding: 14; onClicked: trainingCenter.close() }
            }
            RowLayout {
                Layout.fillWidth: true
                spacing: 6
                Chip {
                    text: dashboard.trainingData !== "" ? dashboard.trainingData : "녹화 읽는 중…"
                }
                Chip {
                    text: dashboard.trainingModel !== "" ? dashboard.trainingModel : "모델 확인 중…"
                }
                Chip {
                    visible: dashboard.trainingStorage !== "" && !dashboard.trainingStorageWarn
                    text: dashboard.trainingStorage
                }
                Chip {
                    warn: !dashboard.hubHasToken
                    Layout.fillWidth: true
                    Layout.maximumWidth: 360
                    text: "원격 허브 · " + dashboard.hubSummaryLabel
                }
                Item { Layout.fillWidth: true; Layout.minimumWidth: 0 }
            }
            WorkProgressBanner {
                showStopButton: true
                showStatusWhenIdle: true
            }
            Rectangle {
                visible: dashboard.trainingStorageWarn
                Layout.fillWidth: true
                implicitHeight: storageWarn.implicitHeight + 12
                radius: 8
                color: "#FFF1D6"
                border.color: "#F2B544"
                TextLabel {
                    id: storageWarn
                    anchors.fill: parent
                    anchors.margins: 6
                    text: dashboard.trainingStorage
                    font.pixelSize: 12
                    color: "#8A5A00"
                    wrapMode: Text.Wrap
                }
            }
            // Top tab navigation for Training Center
            RowLayout {
                Layout.fillWidth: true
                spacing: 6
                ActionButton {
                    implicitHeight: 36
                    text: "1. 동작별 학습"
                    accent: trainingCenter.centerTab === "gestures"
                    onClicked: trainingCenter.centerTab = "gestures"
                }
                ActionButton {
                    implicitHeight: 36
                    text: "2. 녹화 (" + dashboard.trainingFiles.length + ")"
                    accent: trainingCenter.centerTab === "recordings"
                    onClicked: trainingCenter.centerTab = "recordings"
                }
                ActionButton {
                    implicitHeight: 36
                    text: "3. 시뮬레이터"
                    accent: trainingCenter.centerTab === "simulator"
                    onClicked: {
                        trainingCenter.centerTab = "simulator"
                        var targetFile = trainingCenter.selectedSimFile || dashboard.selectedSimFile || (dashboard.trainingFiles.length > 0 ? dashboard.trainingFiles[0].file : "")
                        if (targetFile !== "" && dashboard.simulationResult.file !== targetFile) {
                            dashboard.runSimulation(targetFile, true)
                        }
                    }
                }
                ActionButton {
                    implicitHeight: 36
                    text: "4. 모델 복원 · 진단"
                    accent: trainingCenter.centerTab === "diagnostics"
                    onClicked: {
                        trainingCenter.centerTab = "diagnostics"
                        if (dashboard.diagnosticsChecks.length === 0) {
                            dashboard.runDiagnostics()
                        }
                    }
                }
                ActionButton {
                    implicitHeight: 36
                    text: "5. 동작 연결"
                    accent: trainingCenter.centerTab === "bindings"
                    onClicked: trainingCenter.centerTab = "bindings"
                }
                Item { Layout.fillWidth: true }
            }

            // =========================================================================
            // TAB 1: 동작별 학습 · 초기화
            // =========================================================================
            ColumnLayout {
                visible: trainingCenter.centerTab === "gestures"
                Layout.fillWidth: true
                Layout.fillHeight: true
                spacing: 8
                // Before-vs-After Training Improvement Report Toggle & Collapsible Card
                RowLayout {
                    visible: Boolean(dashboard.trainingImprovement.available) && dashboard.trainingImprovementItems.length > 0
                    Layout.fillWidth: true
                    spacing: 8
                    Rectangle {
                        radius: 8
                        color: dashboard.trainingImprovement.overall_status === "warn" ? "#FFF5E5" : "#EEFBF6"
                        border.color: dashboard.trainingImprovement.overall_status === "warn" ? "#F2B544" : "#3BC49A"
                        implicitWidth: impToggleRow.implicitWidth + 20
                        implicitHeight: 32
                        RowLayout {
                            id: impToggleRow
                            anchors.centerIn: parent
                            spacing: 8
                            Rectangle {
                                width: 8; height: 8; radius: 4
                                color: dashboard.trainingImprovement.overall_status === "warn" ? "#D97706" : "#15805C"
                            }
                            TextLabel {
                                text: (dashboard.trainingImprovement.has_before_model ? "전후 비교 리포트" : "학습 성과 리포트")
                                    + (trainingCenter.showImprovementReport ? " 접기 ▲" : " 보기 ▼")
                                font.pixelSize: 12
                                font.bold: true
                                color: dashboard.trainingImprovement.overall_status === "warn" ? "#8A4B00" : "#0F5E43"
                            }
                        }
                        MouseArea {
                            anchors.fill: parent
                            cursorShape: Qt.PointingHandCursor
                            onClicked: trainingCenter.showImprovementReport = !trainingCenter.showImprovementReport
                        }
                    }
                    TextLabel {
                        visible: !trainingCenter.showImprovementReport && !Boolean(dashboard.trainingImprovement.dismissed)
                        Layout.fillWidth: true
                        Layout.minimumWidth: 0
                        elide: Text.ElideRight
                        text: dashboard.trainingImprovementHeadline
                        font.pixelSize: 12
                        color: dashboard.trainingImprovement.overall_status === "warn" ? "#8A4B00" : "#12352A"
                    }
                    Item {
                        visible: trainingCenter.showImprovementReport || Boolean(dashboard.trainingImprovement.dismissed)
                        Layout.fillWidth: true
                    }
                }
                Rectangle {
                    visible: trainingCenter.showImprovementReport && Boolean(dashboard.trainingImprovement.available) && dashboard.trainingImprovementItems.length > 0
                    Layout.fillWidth: true
                    implicitHeight: impCol.implicitHeight + 20
                    radius: 10
                    color: dashboard.trainingImprovement.overall_status === "warn" ? "#FFF5E5" : "#EEFBF6"
                    border.color: dashboard.trainingImprovement.overall_status === "warn" ? "#F2B544" : "#3BC49A"
                    ColumnLayout {
                        id: impCol
                        anchors.fill: parent
                        anchors.margins: 10
                        spacing: 6
                        RowLayout {
                            Layout.fillWidth: true
                            spacing: 8
                            Rectangle {
                                radius: 5
                                color: dashboard.trainingImprovement.overall_status === "warn" ? "#F2B544" : "#15805C"
                                implicitWidth: impTagLbl.implicitWidth + 12
                                implicitHeight: 22
                                TextLabel {
                                    id: impTagLbl
                                    anchors.centerIn: parent
                                    text: dashboard.trainingImprovement.has_before_model ? "전후 비교 리포트" : "학습 성과 리포트"
                                    font.pixelSize: 12
                                    font.bold: true
                                    color: "#FFFFFF"
                                }
                            }
                            TextLabel {
                                Layout.fillWidth: true
                                Layout.minimumWidth: 0
                                text: dashboard.trainingImprovementHeadline
                                font.pixelSize: 13
                                font.bold: true
                                color: "#12352A"
                                wrapMode: Text.Wrap
                            }
                            CompactButton {
                                visible: Boolean(dashboard.trainingImprovement.can_rollback) && String(dashboard.trainingImprovement.backup_id || "") !== ""
                                text: "직전 모델로 되돌리기"
                                danger: Number(dashboard.trainingImprovement.regressed_count || 0) > 0
                                enabled: !dashboard.trainingRunning && !dashboard.recActive && dashboard.trainingBusy === ""
                                onClicked: dashboard.restoreModelBackup(String(dashboard.trainingImprovement.backup_id))
                            }
                            CompactButton {
                                text: "닫기"
                                onClicked: {
                                    trainingCenter.showImprovementReport = false
                                    dashboard.dismissTrainingImprovement()
                                }
                            }
                        }
                        Flow {
                            Layout.fillWidth: true
                            spacing: 6
                            Repeater {
                                model: dashboard.trainingImprovementItems
                                delegate: Rectangle {
                                    required property var modelData
                                    radius: 7
                                    color: "#FFFFFF"
                                    border.color: modelData.status === "improved" || modelData.status === "new"
                                        ? "#6AD6B3"
                                        : (modelData.status === "regressed" ? "#F2B544" : window.line)
                                    implicitWidth: String(modelData.diagnosis_summary || "") !== ""
                                        ? Math.max(260, trainScroll.availableWidth - 24)
                                        : Math.min(trainScroll.availableWidth - 24, impItemCol.implicitWidth + 16)
                                    implicitHeight: impItemCol.implicitHeight + 12
                                    ColumnLayout {
                                        id: impItemCol
                                        anchors.fill: parent
                                        anchors.margins: 6
                                        spacing: 4
                                        RowLayout {
                                            id: impItemRow
                                            Layout.fillWidth: true
                                            spacing: 6
                                            TextLabel {
                                                text: modelData.name
                                                font.pixelSize: 12
                                                font.bold: true
                                            }
                                            Rectangle {
                                                radius: 4
                                                color: modelData.status === "improved" || modelData.status === "new"
                                                    ? "#DDF7EE"
                                                    : (modelData.status === "regressed" ? "#FFF0D4" : "#EEF2F5")
                                                implicitWidth: impBadgeTxt.implicitWidth + 10
                                                implicitHeight: 19
                                                TextLabel {
                                                    id: impBadgeTxt
                                                    anchors.centerIn: parent
                                                    text: modelData.badge
                                                    font.pixelSize: 12
                                                    font.bold: true
                                                    color: modelData.status === "improved" || modelData.status === "new"
                                                        ? "#0F6E4F"
                                                        : (modelData.status === "regressed" ? "#945800" : window.muted)
                                                }
                                            }
                                            TextLabel {
                                                text: modelData.detail
                                                font.pixelSize: 12
                                                color: window.muted
                                                Layout.fillWidth: true
                                                elide: Text.ElideRight
                                            }
                                        }
                                        TextLabel {
                                            visible: String(modelData.diagnosis_summary || "") !== ""
                                            Layout.fillWidth: true
                                            Layout.minimumWidth: 0
                                            text: "💡 " + String(modelData.diagnosis_summary || "")
                                            font.pixelSize: 12
                                            color: modelData.status === "regressed" ? "#8A4B00" : "#155E4B"
                                            wrapMode: Text.Wrap
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
                TextLabel {
                    Layout.fillWidth: true
                    Layout.minimumWidth: 0
                    text: "인식 = 학습에 쓰지 않은 자세에서 맞힌 비율 (실전 실력) · 특정 동작 학습이 잘못된 경우 [학습 초기화]로 해당 동작만 즉시 규칙 모드로 되돌릴 수 있습니다."
                    font.pixelSize: 12; color: window.muted; wrapMode: Text.Wrap
                }
                RowLayout {
                    Layout.fillWidth: true
                    spacing: 6
                    Repeater {
                        model: dashboard.trainingCategories
                        CompactButton {
                            required property string modelData
                            implicitHeight: 32
                            leftPadding: 14
                            rightPadding: 14
                            text: modelData
                            accent: dashboard.trainingFilter === modelData
                            onClicked: dashboard.setTrainingFilter(modelData)
                        }
                    }
                    Item { Layout.fillWidth: true }
                    TextLabel { text: dashboard.trainingCatalog; font.pixelSize: 12; color: window.muted }
                }
                ScrollView {
                    id: trainScroll
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    clip: true
                    contentWidth: availableWidth
                    ScrollBar.vertical.policy: ScrollBar.AlwaysOn
                    ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
                    ColumnLayout {
                        width: trainScroll.availableWidth
                        spacing: 7
                        Repeater {
                            model: dashboard.trainingRows
                            delegate: Rectangle {
                                id: row
                                required property var modelData
                                Layout.fillWidth: true
                                implicitHeight: rowBody.implicitHeight + 18
                                radius: 10
                                color: modelData.level === "need" ? "#FFF8EA" : "#F7FAFB"
                                border.color: modelData.level === "need" ? "#F2B544" : window.line
                                ColumnLayout {
                                    id: rowBody
                                    anchors.fill: parent
                                    anchors.margins: 9
                                    spacing: 6

                                    // Row 1: Gesture Title + Status Badges (Left) | Horizontal Action Buttons Toolbar (Right)
                                    RowLayout {
                                        Layout.fillWidth: true
                                        spacing: 8
                                        TextLabel {
                                            text: row.modelData.name
                                            font.pixelSize: 15
                                            font.bold: true
                                        }
                                        Chip {
                                            warn: row.modelData.level === "need"
                                            text: row.modelData.level === "ok" ? "좋아요" : row.modelData.level === "need" ? "더 녹화" : "다시 학습"
                                        }
                                        Rectangle {
                                            radius: 5
                                            color: row.modelData.track === "motion" ? "#EDE9FE" : (row.modelData.track === "static" ? "#E6F8F3" : "#EEF2F5")
                                            border.color: row.modelData.track === "motion" ? "#C4B5FD" : (row.modelData.track === "static" ? "#8CE0CA" : window.line)
                                            implicitWidth: trackFmtTxt.implicitWidth + 10
                                            implicitHeight: 22
                                            TextLabel {
                                                id: trackFmtTxt
                                                anchors.centerIn: parent
                                                text: row.modelData.track === "motion" ? "시계열 모션 트랙" : (row.modelData.track === "static" ? "정지·핀치 트랙" : "연속 배경")
                                                font.pixelSize: 11
                                                font.bold: true
                                                color: row.modelData.track === "motion" ? "#5B21B6" : (row.modelData.track === "static" ? "#0F6E5B" : window.muted)
                                            }
                                        }
                                        Rectangle {
                                            visible: String(row.modelData.shortcut_badge || "") !== ""
                                            radius: 5
                                            color: "#F0F9FF"
                                            border.color: "#7DD3FC"
                                            implicitWidth: scBadgeTxt.implicitWidth + 12
                                            implicitHeight: 22
                                            TextLabel {
                                                id: scBadgeTxt
                                                anchors.centerIn: parent
                                                text: {
                                                    var sb = String(row.modelData.shortcut_badge || "")
                                                    return sb.indexOf("단축키:") === 0 ? sb : ("단축키: " + sb)
                                                }
                                                font.pixelSize: 12
                                                font.bold: true
                                                color: "#0369A1"
                                            }
                                            MouseArea {
                                                anchors.fill: parent
                                                cursorShape: Qt.PointingHandCursor
                                                onClicked: {
                                                    if (row.modelData.can_train) {
                                                        trainingCenter.selectedBindingKey = row.modelData.key
                                                        trainingCenter.bindingsSubTab = "shortcuts"
                                                        trainingCenter.centerTab = "bindings"
                                                    }
                                                }
                                            }
                                        }
                                        Chip {
                                            visible: Boolean(row.modelData.is_disabled)
                                            warn: true
                                            text: "초기화됨 (규칙 동작)"
                                        }
                                        Rectangle {
                                            visible: String(row.modelData.delta_badge || "") !== ""
                                            radius: 6
                                            color: row.modelData.delta_status === "improved" || row.modelData.delta_status === "new"
                                                ? "#DDF7EE"
                                                : (row.modelData.delta_status === "regressed" ? "#FFF0D4" : "#EEF2F5")
                                            border.color: row.modelData.delta_status === "improved" || row.modelData.delta_status === "new"
                                                ? "#6AD6B3"
                                                : (row.modelData.delta_status === "regressed" ? "#F2B544" : window.line)
                                            implicitWidth: rowDeltaTxt.implicitWidth + 12
                                            implicitHeight: 22
                                            TextLabel {
                                                id: rowDeltaTxt
                                                anchors.centerIn: parent
                                                text: String(row.modelData.delta_badge || "")
                                                font.pixelSize: 12
                                                font.bold: true
                                                color: row.modelData.delta_status === "improved" || row.modelData.delta_status === "new"
                                                    ? "#0F6E4F"
                                                    : (row.modelData.delta_status === "regressed" ? "#945800" : window.muted)
                                            }
                                        }
                                        Item { Layout.fillWidth: true; Layout.minimumWidth: 0 }
                                        RowLayout {
                                            spacing: 5
                                            TextLabel {
                                                visible: !row.modelData.can_train
                                                text: "공통 오답 자료"
                                                font.pixelSize: 12
                                                color: window.muted
                                            }
                                            CompactButton {
                                                text: "집중 녹화"
                                                implicitHeight: 32
                                                leftPadding: 11; rightPadding: 11
                                                enabled: !dashboard.trainingRunning && dashboard.recMode === "off"
                                                onClicked: {
                                                    if (dashboard.focusRecord(row.modelData.key)) {
                                                        trainingCenter.close()
                                                        capturePlan.open()
                                                    }
                                                }
                                            }
                                            CompactButton {
                                                text: row.modelData.track === "motion" ? "모션 학습" : "이 동작만 학습"
                                                implicitHeight: 32
                                                leftPadding: 12; rightPadding: 12
                                                visible: row.modelData.can_train
                                                primary: true
                                                enabled: !dashboard.trainingRunning && !dashboard.recActive && dashboard.trainingBusy === ""
                                                onClicked: {
                                                    if (row.modelData.track === "motion") {
                                                        dashboard.trainMotionTemplatesSlot(row.modelData.key)
                                                    } else {
                                                        dashboard.trainSelectedGesture(row.modelData.key)
                                                    }
                                                }
                                            }
                                            CompactButton {
                                                id: rowMoreButton
                                                text: "더보기 ▾"
                                                implicitHeight: 32
                                                leftPadding: 10; rightPadding: 10
                                                visible: row.modelData.can_train || String(row.modelData.latest_file || "") !== ""
                                                onClicked: rowMoreMenu.popup(rowMoreButton, rowMoreButton.width - rowMoreMenu.width, rowMoreButton.height + 2)
                                                Menu {
                                                    id: rowMoreMenu
                                                    readonly property bool idle: !dashboard.trainingRunning && dashboard.trainingBusy === ""
                                                    MenuItem {
                                                        text: "단축키 변경"
                                                        visible: row.modelData.can_train
                                                        height: visible ? implicitHeight : 0
                                                        onTriggered: {
                                                            trainingCenter.selectedBindingKey = row.modelData.key
                                                            trainingCenter.bindingsSubTab = "shortcuts"
                                                            trainingCenter.centerTab = "bindings"
                                                        }
                                                    }
                                                    MenuItem {
                                                        text: "판정 검증 (최근 녹화로)"
                                                        visible: Boolean(row.modelData.can_train && String(row.modelData.latest_file || "") !== "")
                                                        height: visible ? implicitHeight : 0
                                                        enabled: rowMoreMenu.idle && !dashboard.recActive
                                                        onTriggered: dashboard.testGestureJudgment(row.modelData.key)
                                                    }
                                                    MenuItem {
                                                        text: "시뮬레이터에서 재생"
                                                        visible: String(row.modelData.latest_file || "") !== ""
                                                        height: visible ? implicitHeight : 0
                                                        enabled: rowMoreMenu.idle
                                                        onTriggered: {
                                                            var targetFile = String(row.modelData.latest_file || "")
                                                            if (targetFile !== "") {
                                                                trainingCenter.selectedSimFile = targetFile
                                                                dashboard.setSelectedSimFile(targetFile)
                                                                trainingCenter.centerTab = "simulator"
                                                                dashboard.runSimulation(targetFile, true)
                                                            }
                                                        }
                                                    }
                                                    MenuSeparator {
                                                        visible: Boolean(row.modelData.can_train && row.modelData.is_trained)
                                                        height: visible ? implicitHeight : 0
                                                    }
                                                    MenuItem {
                                                        text: "학습 초기화…"
                                                        visible: Boolean(row.modelData.can_train && row.modelData.is_trained)
                                                        height: visible ? implicitHeight : 0
                                                        enabled: rowMoreMenu.idle && !dashboard.recActive
                                                        onTriggered: {
                                                            var key = row.modelData.key
                                                            confirmDialog.ask(
                                                                "'" + row.modelData.name + "' 학습 초기화",
                                                                "이 동작의 학습 모델을 끄고 규칙 판정으로 되돌립니다.\n현재 모델은 자동 백업되며 [4. 모델 버전 복원]에서 되살릴 수 있습니다.",
                                                                "초기화",
                                                                function () { dashboard.resetGestureTraining(key) })
                                                        }
                                                    }
                                                }
                                            }
                                        }
                                    }

                                    // Row 1b: what to do for this gesture (was squeezed into row 1 and cut off)
                                    TextLabel {
                                        visible: String(row.modelData.instruction || "") !== ""
                                        Layout.fillWidth: true
                                        Layout.minimumWidth: 0
                                        text: row.modelData.instruction
                                        font.pixelSize: 12
                                        color: window.muted
                                        elide: Text.ElideRight
                                    }

                                    // Row 2: Full-width Data Progress + Recognition Score + Fit + Model Info
                                    RowLayout {
                                        Layout.fillWidth: true
                                        spacing: 12
                                        RowLayout {
                                            spacing: 6
                                            TextLabel { text: "데이터"; font.pixelSize: 12; font.bold: true; color: window.muted }
                                            Rectangle {
                                                width: 150
                                                height: 8; radius: 4; color: "#E3E9EE"
                                                Rectangle {
                                                    width: parent.width * Math.max(0, Math.min(1, row.modelData.data_ratio))
                                                    height: parent.height; radius: 4
                                                    color: row.modelData.data_ratio >= 1 ? "#45E0B4" : "#F2B544"
                                                }
                                            }
                                            TextLabel { text: row.modelData.data_text; font.pixelSize: 12; font.bold: true }
                                        }
                                        Rectangle { width: 1; height: 14; color: window.line }
                                        TextLabel { text: row.modelData.score_text; font.pixelSize: 12; font.bold: true; color: "#0F6E5B" }
                                        TextLabel { text: row.modelData.fit_text; font.pixelSize: 12; color: window.muted }
                                        Rectangle { width: 1; height: 14; color: window.line }
                                        TextLabel {
                                            text: String(row.modelData.training_format_badge || "") + "  ·  " + row.modelData.model_text
                                                + (String(row.modelData.motion_metrics_text || "") !== "" ? ("  [" + row.modelData.motion_metrics_text + "]") : "")
                                            font.pixelSize: 12
                                            color: row.modelData.track === "motion" ? "#4C1D95" : window.muted
                                            elide: Text.ElideRight
                                            Layout.fillWidth: true
                                            Layout.minimumWidth: 0
                                        }
                                    }

                                    // Row 3: Advice + Shared Model Note + Optional Delta/Diagnosis/Test Result
                                    RowLayout {
                                        Layout.fillWidth: true
                                        spacing: 10
                                        TextLabel {
                                            Layout.fillWidth: true
                                            Layout.minimumWidth: 0
                                            text: "→ " + row.modelData.advice
                                                + (row.modelData.label === "thumb_middle" ? "  (좌클릭과 중지 유지 드래그가 같은 모델을 공유합니다)" : "")
                                            font.pixelSize: 12
                                            color: row.modelData.level === "need" ? "#8A5A00" : window.muted
                                            elide: Text.ElideRight
                                        }
                                        TextLabel {
                                            visible: String(row.modelData.delta_detail || "") !== ""
                                            text: "개선 평가: " + String(row.modelData.delta_detail || "")
                                            font.pixelSize: 12
                                            font.bold: true
                                            color: row.modelData.delta_status === "improved" || row.modelData.delta_status === "new"
                                                ? "#0F6E4F"
                                                : (row.modelData.delta_status === "regressed" ? "#945800" : window.muted)
                                        }
                                    }
                                    Rectangle {
                                        visible: String(row.modelData.diagnosis_summary || "") !== ""
                                        Layout.fillWidth: true
                                        radius: 6
                                        color: row.modelData.delta_status === "regressed" ? "#FFF7E6" : "#EFFAF5"
                                        border.color: row.modelData.delta_status === "regressed" ? "#F2C97D" : "#A7E3CB"
                                        implicitHeight: rowDiagTxt.implicitHeight + 8
                                        TextLabel {
                                            id: rowDiagTxt
                                            anchors.fill: parent
                                            anchors.margins: 4
                                            text: "💡 " + String(row.modelData.diagnosis_summary || "")
                                            font.pixelSize: 12
                                            color: row.modelData.delta_status === "regressed" ? "#7A4300" : "#135D47"
                                            wrapMode: Text.Wrap
                                        }
                                    }
                                    Rectangle {
                                        visible: Boolean(dashboard.gestureTestResults[row.modelData.key])
                                        Layout.fillWidth: true
                                        radius: 6
                                        color: "#EEF8F6"
                                        border.color: "#7BD6BD"
                                        implicitHeight: testResCol.implicitHeight + 8
                                        ColumnLayout {
                                            id: testResCol
                                            anchors.fill: parent
                                            anchors.margins: 4
                                            spacing: 2
                                            TextLabel {
                                                Layout.fillWidth: true
                                                Layout.minimumWidth: 0
                                                text: dashboard.gestureTestResults[row.modelData.key]
                                                    ? String(dashboard.gestureTestResults[row.modelData.key].summary || "")
                                                    : ""
                                                font.pixelSize: 12
                                                font.bold: true
                                                color: "#0D5944"
                                                wrapMode: Text.Wrap
                                            }
                                            TextLabel {
                                                visible: Boolean(dashboard.gestureTestResults[row.modelData.key] && dashboard.gestureTestResults[row.modelData.key].detail)
                                                Layout.fillWidth: true
                                                Layout.minimumWidth: 0
                                                text: dashboard.gestureTestResults[row.modelData.key]
                                                    ? String(dashboard.gestureTestResults[row.modelData.key].detail || "")
                                                    : ""
                                                font.pixelSize: 12
                                                color: window.muted
                                                wrapMode: Text.Wrap
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }

            // =========================================================================
            // TAB 2: 녹화 데이터 품질 평가 및 선별
            // =========================================================================
            ColumnLayout {
                visible: trainingCenter.centerTab === "recordings"
                Layout.fillWidth: true
                Layout.fillHeight: true
                spacing: 8
                RowLayout {
                    Layout.fillWidth: true
                    spacing: 8
                    TextLabel {
                        Layout.fillWidth: true
                        Layout.minimumWidth: 0
                        text: "녹화별 품질 점수(손 유실률·프레임 떨림·동작 구간 유효성)를 평가하고, 학습에 사용할 녹화만 체크하여 선별할 수 있습니다."
                        font.pixelSize: 12; color: window.muted; wrapMode: Text.Wrap
                    }
                    ActionButton {
                        text: "전체 품질 재검사"
                        enabled: dashboard.trainingBusy === "" && !dashboard.trainingRunning
                        onClicked: dashboard.evaluateAllRecordings(false)
                    }
                    ActionButton {
                        text: "불량 녹화 자동 제외"
                        enabled: dashboard.trainingBusy === "" && !dashboard.trainingRunning
                        onClicked: dashboard.evaluateAllRecordings(true)
                    }
                }
                ScrollView {
                    id: filesScroll
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    clip: true
                    contentWidth: availableWidth
                    ScrollBar.vertical.policy: ScrollBar.AlwaysOn
                    ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
                    ColumnLayout {
                        width: filesScroll.availableWidth
                        spacing: 8
                        Repeater {
                            model: dashboard.trainingFiles
                            delegate: Rectangle {
                                id: fileRow
                                required property var modelData
                                Layout.fillWidth: true
                                implicitHeight: fileRowBody.implicitHeight + 22
                                radius: 10
                                color: !modelData.selected ? "#F2F4F6" : (modelData.quality_status === "fail" ? "#FFF1F0" : (modelData.quality_status === "warning" ? "#FFF8EA" : "#F7FAFB"))
                                border.color: !modelData.selected ? window.line : (modelData.quality_status === "fail" ? "#E5484D" : (modelData.quality_status === "warning" ? "#F2B544" : window.line))
                                RowLayout {
                                    id: fileRowBody
                                    anchors.fill: parent
                                    anchors.margins: 11
                                    spacing: 12
                                    ColumnLayout {
                                        Layout.fillWidth: true
                                        Layout.minimumWidth: 0
                                        spacing: 4
                                        RowLayout {
                                            Layout.fillWidth: true
                                            spacing: 8
                                            Chip {
                                                warn: !fileRow.modelData.selected
                                                text: fileRow.modelData.selected ? "학습 포함" : "학습 제외됨"
                                            }
                                            Chip {
                                                warn: fileRow.modelData.quality_status !== "pass"
                                                text: fileRow.modelData.quality_status === "pass" ? "품질 양호" : (fileRow.modelData.quality_status === "warning" ? "품질 주의" : "품질 불량")
                                            }
                                            Chip {
                                                text: fileRow.modelData.recorded_mode_label || "가이드 녹화"
                                            }
                                            TextLabel {
                                                text: fileRow.modelData.file
                                                font.bold: true
                                                font.pixelSize: 14
                                                Layout.fillWidth: true
                                                Layout.minimumWidth: 0
                                                elide: Text.ElideMiddle
                                            }
                                        }
                                        TextLabel {
                                            Layout.fillWidth: true
                                            Layout.minimumWidth: 0
                                            text: "녹화 목표 동작: " + (fileRow.modelData.target_gestures_text || "지정된 동작 없음")
                                                + (fileRow.modelData.target_conditions_text ? ("  |  촬영 자세: " + fileRow.modelData.target_conditions_text) : "")
                                            font.bold: true
                                            font.pixelSize: 12
                                            color: "#0F6E5B"
                                            wrapMode: Text.Wrap
                                        }
                                        TextLabel {
                                            Layout.fillWidth: true
                                            Layout.minimumWidth: 0
                                            text: fileRow.modelData.detail_text
                                            font.pixelSize: 12
                                            color: window.muted
                                            wrapMode: Text.Wrap
                                        }
                                        TextLabel {
                                            Layout.fillWidth: true
                                            Layout.minimumWidth: 0
                                            text: fileRow.modelData.quality_text
                                            font.pixelSize: 12
                                            color: fileRow.modelData.quality_status === "fail" ? "#C62828" : window.muted
                                            wrapMode: Text.Wrap
                                        }
                                    }
                                    RowLayout {
                                        spacing: 6
                                        ActionButton {
                                            text: fileRow.modelData.selected ? "학습 포함됨" : "학습 포함하기"
                                            accent: Boolean(fileRow.modelData.selected)
                                            enabled: !dashboard.trainingRunning && dashboard.trainingBusy === ""
                                            onClicked: dashboard.setRecordingSelected(fileRow.modelData.file, !fileRow.modelData.selected)
                                        }
                                        ActionButton {
                                            text: "시뮬레이터 검증"
                                            enabled: dashboard.trainingBusy === ""
                                            onClicked: {
                                                trainingCenter.selectedSimFile = fileRow.modelData.file
                                                dashboard.setSelectedSimFile(fileRow.modelData.file)
                                                trainingCenter.centerTab = "simulator"
                                                dashboard.runSimulation(fileRow.modelData.file, true)
                                            }
                                        }
                                        ActionButton {
                                            text: "삭제"
                                            enabled: !dashboard.trainingRunning && dashboard.trainingBusy === ""
                                            onClicked: {
                                                var f = fileRow.modelData.file
                                                confirmDialog.ask("녹화 파일 삭제", "'" + f + "' 파일을 디스크에서 지웁니다. 되돌릴 수 없습니다.\n학습에서만 빼려면 [학습 포함됨]을 눌러 제외하세요.", "삭제", function () { dashboard.deleteRecording(f) })
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }

            // =========================================================================
            // TAB 3: 학습 데이터 · 모델 시뮬레이터 (데이터 평가 · 보정 · 증강 설정 포함)
            // =========================================================================
            ColumnLayout {
                id: simTabRoot
                visible: trainingCenter.centerTab === "simulator"
                Layout.fillWidth: true
                Layout.fillHeight: true
                spacing: 6
                property int calibInterpGap: 3
                property real calibJointJump: 0.38
                property int playFrameIdx: 0
                property bool isPlaying: false
                property real playSpeed: 1.0
                property bool expandSkeleton: false
                property bool showArmPose: true
                property bool fullScreenCoordMode: true
                property bool showSpatialSpray: true

                readonly property int totalFrames: dashboard.simPlaybackCount
                property var curFrame: null

                function refreshCurFrame() {
                    if (totalFrames > 0 && playFrameIdx >= 0 && playFrameIdx < totalFrames) {
                        curFrame = dashboard.getSimPlaybackFrame(playFrameIdx)
                    } else {
                        curFrame = null
                    }
                    skeletonCanvas.requestPaint()
                }

                onTotalFramesChanged: {
                    if (playFrameIdx >= totalFrames)
                        playFrameIdx = 0
                    refreshCurFrame()
                }
                onPlayFrameIdxChanged: refreshCurFrame()
                onExpandSkeletonChanged: { skeletonCanvas.requestPaint(); trainingCenter.savePref("sim.expandSkeleton", expandSkeleton) }
                onShowArmPoseChanged: { skeletonCanvas.requestPaint(); trainingCenter.savePref("sim.showArmPose", showArmPose) }
                onFullScreenCoordModeChanged: { skeletonCanvas.requestPaint(); trainingCenter.savePref("sim.fullScreenCoordMode", fullScreenCoordMode) }
                onShowSpatialSprayChanged: { skeletonCanvas.requestPaint(); trainingCenter.savePref("sim.showSpatialSpray", showSpatialSpray) }
                onCalibInterpGapChanged: trainingCenter.savePref("sim.calibInterpGap", calibInterpGap)
                onCalibJointJumpChanged: trainingCenter.savePref("sim.calibJointJump", calibJointJump)
                onPlaySpeedChanged: trainingCenter.savePref("sim.playSpeed", playSpeed)
                function loadPrefs() {
                    calibInterpGap = dashboard.centerPref("sim.calibInterpGap", 3)
                    calibJointJump = dashboard.centerPref("sim.calibJointJump", 0.38)
                    playSpeed = dashboard.centerPref("sim.playSpeed", 1.0)
                    expandSkeleton = dashboard.centerPref("sim.expandSkeleton", false)
                    showArmPose = dashboard.centerPref("sim.showArmPose", true)
                    fullScreenCoordMode = dashboard.centerPref("sim.fullScreenCoordMode", true)
                    showSpatialSpray = dashboard.centerPref("sim.showSpatialSpray", true)
                }

                Connections {
                    target: dashboard
                    function onCenterPrefsChanged() { trainingCenter.loadPrefs() }
                    function onTrainingChanged() {
                        if (dashboard.selectedSimFile !== "" && trainingCenter.selectedSimFile !== dashboard.selectedSimFile) {
                            trainingCenter.selectedSimFile = dashboard.selectedSimFile
                        }
                        simTabRoot.refreshCurFrame()
                    }
                }

                function currentSimFilename() {
                    // while the collected uses are shown ("use:..."), the recording buttons act on the recording the combo shows
                    if (dashboard.selectedSimFile !== "" && dashboard.selectedSimFile.indexOf("use:") !== 0)
                        return dashboard.selectedSimFile
                    if (trainingCenter.selectedSimFile !== "" && trainingCenter.selectedSimFile.indexOf("use:") !== 0)
                        return trainingCenter.selectedSimFile
                    var idx = simFileCombo.currentIndex
                    if (idx >= 0 && idx < dashboard.trainingFiles.length)
                        return dashboard.trainingFiles[idx].file
                    return dashboard.trainingFiles.length > 0 ? dashboard.trainingFiles[0].file : ""
                }

                function seekFrame(targetIdx) {
                    if (totalFrames <= 0) {
                        playFrameIdx = 0
                        return
                    }
                    playFrameIdx = Math.max(0, Math.min(totalFrames - 1, Math.round(targetIdx)))
                }

                function jumpToNextEvent() {
                    if (totalFrames <= 0)
                        return
                    playFrameIdx = dashboard.findNextSimEventFrame(playFrameIdx)
                }

                Timer {
                    id: simPlayTimer
                    interval: Math.max(12, Math.round(33 / Math.max(0.25, simTabRoot.playSpeed)))
                    repeat: true
                    running: simTabRoot.visible && simTabRoot.isPlaying && simTabRoot.totalFrames > 0
                    onTriggered: {
                        var step = simTabRoot.playSpeed >= 3.5 ? 2 : 1
                        if (simTabRoot.playFrameIdx + step < simTabRoot.totalFrames) {
                            simTabRoot.playFrameIdx += step
                        } else {
                            simTabRoot.playFrameIdx = 0
                            simTabRoot.isPlaying = false
                        }
                    }
                }

                // Top selector & simulation trigger row inside a properly sized background Rectangle
                Rectangle {
                    Layout.fillWidth: true
                    implicitHeight: topSelectorRow.implicitHeight + 12
                    radius: 10
                    color: "#F7FAFB"
                    border.color: window.line
                    RowLayout {
                        id: topSelectorRow
                        anchors.fill: parent
                        anchors.margins: 6
                        spacing: 8
                        TextLabel { text: "대상 녹화:"; font.bold: true; font.pixelSize: 13 }
                        StyledComboBox {
                            id: simFileCombo
                            Layout.fillWidth: true
                            Layout.minimumWidth: 180
                            implicitHeight: 32
                            model: dashboard.trainingFiles
                            textRole: "combo_label"
                            currentIndex: {
                                var list = dashboard.trainingFiles || []
                                var target = dashboard.selectedSimFile || trainingCenter.selectedSimFile || (dashboard.simulationResult && dashboard.simulationResult.file) || ""
                                for (var i = 0; i < list.length; i++) {
                                    if (list[i].file === target) return i
                                }
                                return list.length > 0 ? 0 : -1
                            }
                            onActivated: function(idx) {
                                if (idx >= 0 && idx < dashboard.trainingFiles.length) {
                                    var f = dashboard.trainingFiles[idx].file
                                    trainingCenter.selectedSimFile = f
                                    dashboard.setSelectedSimFile(f)
                                    simTabRoot.isPlaying = false
                                    simTabRoot.playFrameIdx = 0
                                    dashboard.runSimulation(f, true)
                                }
                            }
                        }
                        CompactButton {
                            text: "데이터 평가"
                            implicitHeight: 32
                            leftPadding: 12; rightPadding: 12
                            enabled: dashboard.trainingBusy === "" && dashboard.trainingFiles.length > 0
                            onClicked: dashboard.evaluateSimRecording(simTabRoot.currentSimFilename())
                        }
                        CompactButton {
                            text: "시뮬레이션 실행 (보정본)"
                            implicitHeight: 32
                            leftPadding: 12; rightPadding: 12
                            primary: true
                            enabled: dashboard.trainingBusy === "" && dashboard.trainingFiles.length > 0
                            onClicked: {
                                simTabRoot.isPlaying = false
                                simTabRoot.playFrameIdx = 0
                                dashboard.runSimulation(simTabRoot.currentSimFilename(), true)
                            }
                        }
                        CompactButton {
                            text: "원본 시뮬레이션"
                            implicitHeight: 32
                            leftPadding: 12; rightPadding: 12
                            enabled: dashboard.trainingBusy === "" && dashboard.trainingFiles.length > 0
                            onClicked: {
                                simTabRoot.isPlaying = false
                                simTabRoot.playFrameIdx = 0
                                dashboard.runSimulation(simTabRoot.currentSimFilename(), false)
                            }
                        }
                        Chip {
                            visible: dashboard.simulationResult.file !== undefined && dashboard.simulationResult.file !== ""
                            text: dashboard.simulationResult.using_cleaned ? "현재: 보정본 재생" : "현재: 원본 재생"
                        }
                    }
                }

                // The uses the app collects by itself while a taught gesture is used (src/use_log.py), played like a recording
                // (src/use_sim.py). Nothing here is a recording file: it is read from the use log and never trained from this tab.
                Rectangle {
                    objectName: "useSimRow"
                    Layout.fillWidth: true
                    implicitHeight: useSimRow.implicitHeight + 12
                    radius: 10
                    color: "#EAF7F1"
                    border.color: "#BFE5D3"
                    onVisibleChanged: if (visible) dashboard.refreshUseGestures()
                    Component.onCompleted: dashboard.refreshUseGestures()
                    RowLayout {
                        id: useSimRow
                        anchors.fill: parent
                        anchors.margins: 6
                        spacing: 8
                        TextLabel { text: "쓰면서 모은 자료:"; font.bold: true; font.pixelSize: 13; color: "#17603F" }
                        StyledComboBox {
                            id: useGestureCombo
                            Layout.fillWidth: true
                            Layout.minimumWidth: 180
                            implicitHeight: 32
                            enabled: dashboard.useGestures.length > 0
                            model: dashboard.useGestures
                            textRole: "combo_label"
                            displayText: dashboard.useGestures.length > 0 ? currentText : "아직 모은 사용 사례가 없어요 (가르친 자세를 쓰면 자동으로 쌓여요)"
                            currentIndex: {
                                var list = dashboard.useGestures || []
                                for (var i = 0; i < list.length; i++) {
                                    if (list[i].file === dashboard.selectedSimFile) return i
                                }
                                return list.length > 0 ? 0 : -1
                            }
                        }
                        CompactButton {
                            objectName: "useSimPlay"
                            text: "시뮬레이터에서 보기"
                            implicitHeight: 32
                            leftPadding: 12; rightPadding: 12
                            primary: true
                            enabled: dashboard.trainingBusy === "" && dashboard.useGestures.length > 0
                            onClicked: {
                                var list = dashboard.useGestures || []
                                var idx = useGestureCombo.currentIndex
                                if (idx >= 0 && idx < list.length) {
                                    simTabRoot.isPlaying = false
                                    simTabRoot.playFrameIdx = 0
                                    trainingCenter.selectedSimFile = list[idx].file
                                    dashboard.runUseSimulation(list[idx].key)
                                }
                            }
                        }
                        CompactButton {
                            text: "새로 고침"
                            implicitHeight: 32
                            leftPadding: 12; rightPadding: 12
                            onClicked: dashboard.refreshUseGestures()
                        }
                        Chip {
                            visible: dashboard.simulationResult.use_view === true
                            text: "현재: 자동 수집 자료 재생 (녹화 파일 아님)"
                        }
                    }
                }

                // ONNX Model Selector + Load/Use + Train + Spatial Spray Filter Bar
                Rectangle {
                    Layout.fillWidth: true
                    implicitHeight: onnxSelectRow.implicitHeight + 12
                    radius: 10
                    color: "#EEF8F6"
                    border.color: "#8CE0CA"
                    RowLayout {
                        id: onnxSelectRow
                        anchors.fill: parent
                        anchors.margins: 6
                        spacing: 8
                        TextLabel { text: "ONNX 모델 선택:"; font.bold: true; font.pixelSize: 13; color: "#0B4F40" }
                        StyledComboBox {
                            id: onnxModelCombo
                            Layout.fillWidth: true
                            Layout.minimumWidth: 180
                            implicitHeight: 32
                            model: dashboard.onnxModels
                            textRole: "combo_label"
                            currentIndex: {
                                var list = dashboard.onnxModels || []
                                var selId = dashboard.selectedOnnxModelId
                                for (var i = 0; i < list.length; i++) {
                                    if (list[i].id === selId) return i
                                }
                                return list.length > 0 ? 0 : -1
                            }
                            onActivated: function(idx) {
                                var list = dashboard.onnxModels || []
                                if (idx >= 0 && idx < list.length) {
                                    var mid = list[idx].id
                                    dashboard.selectOnnxModel(mid)
                                    var f = simTabRoot.currentSimFilename()
                                    if (f !== "") {
                                        dashboard.runSimulation(f, true)
                                    }
                                }
                            }
                        }
                        Chip {
                            warn: !(dashboard.selectedOnnxModel && dashboard.selectedOnnxModel.active)
                            text: (dashboard.selectedOnnxModel && dashboard.selectedOnnxModel.active)
                                ? "현재 실사용 적용됨"
                                : "시뮬레이터 미리보기 중"
                        }
                        CompactButton {
                            text: "이 ONNX 불러와 실사용"
                            primary: !(dashboard.selectedOnnxModel && dashboard.selectedOnnxModel.active)
                            accent: Boolean(dashboard.selectedOnnxModel && dashboard.selectedOnnxModel.active)
                            enabled: dashboard.trainingBusy === "" && !dashboard.trainingRunning && dashboard.recMode === "off"
                            onClicked: dashboard.activateOnnxModel(dashboard.selectedOnnxModelId)
                        }
                        CompactButton {
                            text: (dashboard.selectedOnnxModel && dashboard.selectedOnnxModel.trainable_key && dashboard.selectedOnnxModel.trainable_key !== "all")
                                ? "이 동작 ONNX 재학습"
                                : "통합 ONNX 재학습"
                            primary: true
                            enabled: dashboard.trainingBusy === "" && !dashboard.trainingRunning && dashboard.recMode === "off" && Boolean(dashboard.trainingCanStart)
                            onClicked: dashboard.trainSelectedOnnxModel(dashboard.selectedOnnxModelId)
                        }
                        TextLabel { text: "스프레이 동작 필터:"; font.bold: true; font.pixelSize: 12; color: "#0B4F40" }
                        StyledComboBox {
                            id: sprayFilterCombo
                            Layout.preferredWidth: 165
                            implicitHeight: 30
                            model: dashboard.spatialSprayFilterOptions
                            textRole: "name"
                            currentIndex: {
                                var opts = dashboard.spatialSprayFilterOptions || []
                                var cur = dashboard.sprayGestureFilter
                                for (var i = 0; i < opts.length; i++) {
                                    if (opts[i].key === cur) return i
                                }
                                return 0
                            }
                            onActivated: function(idx) {
                                var opts = dashboard.spatialSprayFilterOptions || []
                                if (idx >= 0 && idx < opts.length) {
                                    dashboard.setSprayGestureFilter(opts[idx].key)
                                }
                            }
                        }
                    }
                }

                ScrollView {
                    id: simScroll
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    clip: true
                    contentWidth: availableWidth
                    ScrollBar.vertical.policy: ScrollBar.AlwaysOn
                    ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
                    ColumnLayout {
                        width: simScroll.availableWidth
                        spacing: 8

                // 3) 팔·어깨(Pose) + 21관절 손 스켈레톤 & 카메라 화면 영역(3x3) 시각화 재생기 (화면 확대 지원)
                Rectangle {
                    Layout.fillWidth: true
                    implicitHeight: simTabRoot.expandSkeleton ? 420 : 244
                    radius: 10
                    color: "#F7FAFB"
                    border.color: window.line
                    RowLayout {
                        anchors.fill: parent
                        anchors.margins: 8
                        spacing: 10

                        // Left: Expandable Arm/Shoulder + 21-Joint Hand Skeleton & 3x3 Camera Screen Zone Visualizer Canvas
                        Rectangle {
                            Layout.preferredWidth: simTabRoot.expandSkeleton ? 460 : 320
                            Layout.fillHeight: true
                            radius: 10
                            color: "#0D1B26"
                            border.color: (simTabRoot.curFrame && simTabRoot.curFrame.event_kind === "pinch") ? "#46E5BD"
                                : ((simTabRoot.curFrame && simTabRoot.curFrame.event_kind === "swipe") ? "#FF9F1C"
                                : ((simTabRoot.curFrame && simTabRoot.curFrame.event_kind === "sign") ? "#5BC0EB" : "#22384A"))
                            border.width: (simTabRoot.curFrame && simTabRoot.curFrame.event_kind !== "none") ? 2 : 1
                            clip: true

                            Canvas {
                                id: skeletonCanvas
                                anchors.fill: parent
                                onPaint: {
                                    var ctx = getContext("2d")
                                    var w = width
                                    var h = height
                                    ctx.clearRect(0, 0, w, h)

                                    var f = simTabRoot.curFrame
                                    var padX = 18
                                    var padY = 28
                                    var drawW = Math.max(40, w - padX * 2)
                                    var drawH = Math.max(40, h - padY * 2)

                                    // 0-A. 2D Spatial Spray / Concentration Shading Overlay (shows where on screen the model is trained & how well it recognizes)
                                    if (simTabRoot.showSpatialSpray && simTabRoot.fullScreenCoordMode) {
                                        var sprayCells = dashboard.spatialSprayCells || []
                                        var baseRad = Math.max(18, Math.min(drawW, drawH) * 0.14)
                                        for (var scIdx = 0; scIdx < sprayCells.length; scIdx++) {
                                            var sc = sprayCells[scIdx]
                                            var dens = sc.density || 0
                                            if (dens <= 0.01) continue
                                            var scx = padX + sc.x * drawW
                                            var scy = padY + sc.y * drawH
                                            var sRad = baseRad * (0.62 + 0.68 * Math.sqrt(dens))
                                            var qual = (sc.quality !== undefined) ? sc.quality : 0.85
                                            var sr = qual >= 0.72 ? 46 : (qual >= 0.45 ? 242 : 229)
                                            var sg = qual >= 0.72 ? 229 : (qual >= 0.45 ? 181 : 72)
                                            var sb = qual >= 0.72 ? 180 : (qual >= 0.45 ? 68 : 77)
                                            var sAlpha = Math.min(0.48, 0.09 + dens * 0.38)
                                            var sGrad = ctx.createRadialGradient(scx, scy, 0, scx, scy, sRad)
                                            sGrad.addColorStop(0.0, "rgba(" + sr + "," + sg + "," + sb + "," + sAlpha.toFixed(3) + ")")
                                            sGrad.addColorStop(0.55, "rgba(" + sr + "," + sg + "," + sb + "," + (sAlpha * 0.45).toFixed(3) + ")")
                                            sGrad.addColorStop(1.0, "rgba(" + sr + "," + sg + "," + sb + ",0.0)")
                                            ctx.fillStyle = sGrad
                                            ctx.beginPath()
                                            ctx.arc(scx, scy, sRad, 0, Math.PI * 2)
                                            ctx.fill()

                                            // Spray stipple particles showing concentration & distribution
                                            var nDots = Math.min(20, Math.max(3, Math.round(dens * 20)))
                                            ctx.fillStyle = "rgba(" + sr + "," + sg + "," + sb + "," + Math.min(0.78, 0.22 + dens * 0.52).toFixed(3) + ")"
                                            for (var dk = 0; dk < nDots; dk++) {
                                                var dAng = ((sc.gx * 37 + sc.gy * 19 + dk * 53) % 360) * (Math.PI / 180.0)
                                                var dDist = (((sc.gx * 13 + sc.gy * 29 + dk * 41) % 100) / 100.0) * (sRad * 0.74)
                                                var dpx = scx + Math.cos(dAng) * dDist
                                                var dpy = scy + Math.sin(dAng) * dDist
                                                ctx.fillRect(dpx - 1, dpy - 1, 2.0, 2.0)
                                            }
                                        }
                                    }

                                    // 3x3 Camera Screen Region Grid (subtle reference grid over the full screen)
                                    var zoneLabels = [
                                        ["왼쪽 위", "위", "오른쪽 위"],
                                        ["왼쪽", "중앙", "오른쪽"],
                                        ["왼쪽 아래", "아래", "오른쪽 아래"]
                                    ]
                                    var activeZone = (f && f.screen_zone) ? f.screen_zone : ""
                                    for (var r = 0; r < 3; r++) {
                                        for (var c = 0; c < 3; c++) {
                                            var zx = padX + (drawW * c) / 3.0
                                            var zy = padY + (drawH * r) / 3.0
                                            var zw = drawW / 3.0
                                            var zh = drawH / 3.0
                                            var zName = zoneLabels[r][c]
                                            if (simTabRoot.fullScreenCoordMode && activeZone === zName) {
                                                ctx.fillStyle = "rgba(70, 229, 189, 0.09)"
                                                ctx.fillRect(zx, zy, zw, zh)
                                            }
                                            ctx.strokeStyle = "rgba(255, 255, 255, 0.08)"
                                            ctx.lineWidth = 1
                                            ctx.strokeRect(zx, zy, zw, zh)
                                            if (simTabRoot.fullScreenCoordMode) {
                                                ctx.fillStyle = activeZone === zName ? "rgba(70, 229, 189, 0.78)" : "rgba(255, 255, 255, 0.20)"
                                                ctx.font = (activeZone === zName ? "bold " : "") + "10px 'Noto Sans KR'"
                                                ctx.textAlign = "left"
                                                ctx.fillText(zName, zx + 5, zy + 13)
                                            }
                                        }
                                    }

                                    var hasHand = Boolean(f && f.hand_present && f.lm && f.lm.length >= 21)
                                    var arm = (f && f.active_arm) ? f.active_arm : null
                                    if (!hasHand && !arm) {
                                        ctx.fillStyle = "rgba(255, 255, 255, 0.82)"
                                        ctx.font = "bold 11px 'Noto Sans KR'"
                                        ctx.textAlign = "center"
                                        if (simTabRoot.totalFrames > 0) {
                                            ctx.fillText("이 프레임에는 손/팔이 감지되지 않았습니다", w / 2, h / 2 - 8)
                                            ctx.fillText("(배경 = 학습 스프레이 음영)", w / 2, h / 2 + 8)
                                        } else {
                                            ctx.fillText("배경 스프레이 음영 = 현재 모델이 학습된 화면 위치 분포·인식 품질", w / 2, h - 22)
                                            ctx.fillText("[시뮬레이션 실행]을 누르면 팔·어깨 + 손 스켈레톤이 함께 재생됩니다", w / 2, h - 8)
                                        }
                                        return
                                    }

                                    // Compute bounding box across hand (and arm if shown) or map directly to full camera screen [0..1]
                                    var minX = 1.0, maxX = 0.0, minY = 1.0, maxY = 0.0
                                    function includePt(px, py) {
                                        if (px < minX) minX = px
                                        if (px > maxX) maxX = px
                                        if (py < minY) minY = py
                                        if (py > maxY) maxY = py
                                    }
                                    if (hasHand) {
                                        for (var i = 0; i < 21; i++) {
                                            includePt(f.lm[i][0], f.lm[i][1])
                                        }
                                    }
                                    if (simTabRoot.showArmPose && arm) {
                                        if (arm.shoulder) includePt(arm.shoulder[0], arm.shoulder[1])
                                        if (arm.elbow) includePt(arm.elbow[0], arm.elbow[1])
                                        if (arm.wrist) includePt(arm.wrist[0], arm.wrist[1])
                                        if (arm.other_shoulder && simTabRoot.expandSkeleton) {
                                            includePt(arm.other_shoulder[0], arm.other_shoulder[1])
                                        }
                                    }

                                    var spanX = Math.max(maxX - minX, 0.22)
                                    var spanY = Math.max(maxY - minY, 0.22)
                                    var cx = (minX + maxX) * 0.5
                                    var cy = (minY + maxY) * 0.5
                                    var zoomScale = Math.min(drawW / spanX, drawH / spanY) * 0.78

                                    function mapX(nx) {
                                        if (simTabRoot.fullScreenCoordMode) {
                                            return padX + Math.max(-0.08, Math.min(1.08, nx)) * drawW
                                        }
                                        return w * 0.5 + (nx - cx) * zoomScale
                                    }
                                    function mapY(ny) {
                                        if (simTabRoot.fullScreenCoordMode) {
                                            return padY + Math.max(-0.08, Math.min(1.08, ny)) * drawH
                                        }
                                        return h * 0.52 + (ny - cy) * zoomScale
                                    }

                                    // 0. Draw Arm & Shoulder Skeleton (Clavicle -> Shoulder -> Elbow -> Wrist)
                                    if (simTabRoot.showArmPose && arm && arm.shoulder && arm.elbow) {
                                        var sx = mapX(arm.shoulder[0]), sy = mapY(arm.shoulder[1])
                                        var ex = mapX(arm.elbow[0]), ey = mapY(arm.elbow[1])
                                        var wx = hasHand ? mapX(f.lm[0][0]) : mapX(arm.wrist[0])
                                        var wy = hasHand ? mapY(f.lm[0][1]) : mapY(arm.wrist[1])
                                        var isRealPose = (arm.source === "pose")

                                        // Clavicle line across shoulders if opposite shoulder is available
                                        if (arm.other_shoulder) {
                                            var osx = mapX(arm.other_shoulder[0]), osy = mapY(arm.other_shoulder[1])
                                            ctx.beginPath()
                                            ctx.moveTo(osx, osy)
                                            ctx.lineTo(sx, sy)
                                            ctx.strokeStyle = "rgba(148, 163, 184, 0.50)"
                                            ctx.lineWidth = 3.0
                                            ctx.stroke()

                                            ctx.beginPath()
                                            ctx.arc(osx, osy, 5.0, 0, Math.PI * 2)
                                            ctx.fillStyle = "#94A3B8"
                                            ctx.fill()
                                        }

                                        // Upper arm (Shoulder -> Elbow) and Forearm (Elbow -> Wrist)
                                        ctx.beginPath()
                                        ctx.moveTo(sx, sy)
                                        ctx.lineTo(ex, ey)
                                        ctx.lineTo(wx, wy)
                                        ctx.strokeStyle = isRealPose ? "#38BDF8" : "rgba(56, 189, 248, 0.68)"
                                        ctx.lineWidth = simTabRoot.expandSkeleton ? 5.0 : 4.0
                                        ctx.stroke()

                                        // Shoulder joint node
                                        ctx.beginPath()
                                        ctx.arc(sx, sy, simTabRoot.expandSkeleton ? 7.5 : 6.0, 0, Math.PI * 2)
                                        ctx.fillStyle = "#F59E0B"
                                        ctx.fill()
                                        ctx.strokeStyle = "#0D1B26"
                                        ctx.lineWidth = 1.5
                                        ctx.stroke()

                                        // Elbow joint node
                                        ctx.beginPath()
                                        ctx.arc(ex, ey, simTabRoot.expandSkeleton ? 7.0 : 5.5, 0, Math.PI * 2)
                                        ctx.fillStyle = "#38BDF8"
                                        ctx.fill()
                                        ctx.strokeStyle = "#0D1B26"
                                        ctx.lineWidth = 1.5
                                        ctx.stroke()

                                        // Labels for Shoulder & Elbow + Angle
                                        ctx.fillStyle = "#FDE68A"
                                        ctx.font = "bold 10px 'Noto Sans KR'"
                                        ctx.textAlign = "left"
                                        ctx.fillText((arm.side_ko || "팔") + " 어깨", sx + 8, sy + 4)
                                        ctx.fillStyle = "#BAE6FD"
                                        var degTxt = arm.elbow_deg !== null && arm.elbow_deg !== undefined ? (" " + Math.round(arm.elbow_deg) + "°") : ""
                                        ctx.fillText("팔꿈치" + degTxt + (isRealPose ? "" : " (추정)"), ex + 8, ey + 4)
                                    }

                                    if (!hasHand) {
                                        return
                                    }

                                    var lm = f.lm

                                    // 1. Draw recent palm trajectory trail (last 14 frames) for swipe / screen motion visualization
                                    var trail = f.trail || []
                                    ctx.beginPath()
                                    var started = false
                                    for (var ti = 0; ti < trail.length; ti++) {
                                        var tp = trail[ti]
                                        if (tp && tp.length === 2) {
                                            var tx = mapX(tp[0])
                                            var ty = mapY(tp[1])
                                            if (!started) {
                                                ctx.moveTo(tx, ty)
                                                started = true
                                            } else {
                                                ctx.lineTo(tx, ty)
                                            }
                                        }
                                    }
                                    if (started) {
                                        ctx.strokeStyle = f.event_kind === "swipe" ? "rgba(255, 159, 28, 0.88)" : "rgba(70, 229, 189, 0.45)"
                                        ctx.lineWidth = f.event_kind === "swipe" ? 3.5 : 2.2
                                        ctx.stroke()
                                    }

                                    // 2. Draw anatomical hand bone chains
                                    var chains = [
                                        { pts: [0, 1, 2, 3, 4], color: "#FF6B6B" },     // Thumb
                                        { pts: [0, 5, 6, 7, 8], color: "#46E5BD" },     // Index
                                        { pts: [0, 9, 10, 11, 12], color: "#FFD166" },  // Middle
                                        { pts: [0, 13, 14, 15, 16], color: "#5BC0EB" }, // Ring
                                        { pts: [0, 17, 18, 19, 20], color: "#C792EA" }, // Pinky
                                        { pts: [5, 9, 13, 17], color: "rgba(255,255,255,0.40)" } // Palm arch
                                    ]
                                    for (var c2 = 0; c2 < chains.length; c2++) {
                                        var ch = chains[c2]
                                        ctx.beginPath()
                                        for (var k = 0; k < ch.pts.length; k++) {
                                            var jIdx = ch.pts[k]
                                            var jx = mapX(lm[jIdx][0])
                                            var jy = mapY(lm[jIdx][1])
                                            if (k === 0) ctx.moveTo(jx, jy)
                                            else ctx.lineTo(jx, jy)
                                        }
                                        ctx.strokeStyle = ch.color
                                        ctx.lineWidth = simTabRoot.expandSkeleton ? 3.0 : 2.4
                                        ctx.stroke()
                                    }

                                    // 3. Draw 21 joint nodes
                                    var pinchArr = f.pinch_joints || []
                                    var signArr = f.sign_joints || []
                                    for (var j = 0; j < 21; j++) {
                                        var x = mapX(lm[j][0])
                                        var y = mapY(lm[j][1])
                                        var isPinchJoint = pinchArr.indexOf(j) !== -1
                                        var isSignJoint = signArr.indexOf(j) !== -1
                                        var isTip = (j === 4 || j === 8 || j === 12 || j === 16 || j === 20)
                                        ctx.beginPath()
                                        ctx.arc(x, y, isPinchJoint ? 6.5 : (isSignJoint ? 6.0 : (isTip ? 4.0 : 2.8)), 0, Math.PI * 2)
                                        ctx.fillStyle = isPinchJoint ? "#46E5BD" : (isSignJoint ? "#5BC0EB" : (j === 0 ? "#FFFFFF" : "#E2EDF5"))
                                        ctx.fill()
                                        if (isPinchJoint || isSignJoint) {
                                            ctx.beginPath()
                                            ctx.arc(x, y, 10.5, 0, Math.PI * 2)
                                            ctx.strokeStyle = isPinchJoint ? "rgba(70, 229, 189, 0.85)" : "rgba(91, 192, 235, 0.85)"
                                            ctx.lineWidth = 2
                                            ctx.stroke()
                                        }
                                    }

                                    // 4. Visual PINCH connector & burst ring between thumb(4) and active finger(s)
                                    if (pinchArr.length >= 2) {
                                        var tx0 = mapX(lm[pinchArr[0]][0])
                                        var ty0 = mapY(lm[pinchArr[0]][1])
                                        var mx = tx0, my = ty0
                                        for (var pi = 1; pi < pinchArr.length; pi++) {
                                            var tx1 = mapX(lm[pinchArr[pi]][0])
                                            var ty1 = mapY(lm[pinchArr[pi]][1])
                                            mx += tx1
                                            my += ty1
                                            ctx.beginPath()
                                            ctx.moveTo(tx0, ty0)
                                            ctx.lineTo(tx1, ty1)
                                            ctx.strokeStyle = "#46E5BD"
                                            ctx.lineWidth = 3
                                            ctx.stroke()
                                        }
                                        mx /= pinchArr.length
                                        my /= pinchArr.length
                                        ctx.beginPath()
                                        ctx.arc(mx, my, 15, 0, Math.PI * 2)
                                        ctx.fillStyle = "rgba(70, 229, 189, 0.24)"
                                        ctx.fill()
                                        ctx.strokeStyle = "#46E5BD"
                                        ctx.lineWidth = 2
                                        ctx.stroke()
                                    }

                                    // 5. Visual SWIPE direction arrow overlay
                                    if (f.swipe_dir && f.swipe_dir !== "") {
                                        var ax0 = w * 0.5, ay0 = h - 22
                                        var ax1 = ax0, ay1 = ay0
                                        if (f.swipe_dir === "left") { ax0 = w * 0.68; ax1 = w * 0.32 }
                                        else if (f.swipe_dir === "right") { ax0 = w * 0.32; ax1 = w * 0.68 }
                                        else if (f.swipe_dir === "down") { ay0 = h * 0.28; ay1 = h * 0.72; ax0 = w - 26; ax1 = w - 26 }

                                        ctx.beginPath()
                                        ctx.moveTo(ax0, ay0)
                                        ctx.lineTo(ax1, ay1)
                                        ctx.strokeStyle = "#FF9F1C"
                                        ctx.lineWidth = 4
                                        ctx.stroke()

                                        var ang = Math.atan2(ay1 - ay0, ax1 - ax0)
                                        ctx.beginPath()
                                        ctx.moveTo(ax1, ay1)
                                        ctx.lineTo(ax1 - 10 * Math.cos(ang - 0.5), ay1 - 10 * Math.sin(ang - 0.5))
                                        ctx.lineTo(ax1 - 10 * Math.cos(ang + 0.5), ay1 - 10 * Math.sin(ang + 0.5))
                                        ctx.closePath()
                                        ctx.fillStyle = "#FF9F1C"
                                        ctx.fill()
                                    }
                                }
                            }

                            // Top-left time / frame HUD
                            Rectangle {
                                anchors.top: parent.top
                                anchors.left: parent.left
                                anchors.margins: 6
                                radius: 5
                                color: "#C80B151E"
                                width: frameHudText.implicitWidth + 12
                                height: 22
                                TextLabel {
                                    id: frameHudText
                                    anchors.centerIn: parent
                                    color: "#E2EDF5"
                                    font.pixelSize: 12
                                    font.bold: true
                                    text: simTabRoot.curFrame
                                        ? (simTabRoot.curFrame.t.toFixed(2) + "s · #" + (simTabRoot.playFrameIdx + 1) + "/" + simTabRoot.totalFrames + " · " + simTabRoot.curFrame.handedness)
                                        : "0.00s · 0/0"
                                }
                            }

                            // Top-right active Event Badge (판정 구간 vs 전환 과정)
                            Rectangle {
                                visible: simTabRoot.curFrame !== null
                                anchors.top: parent.top
                                anchors.right: parent.right
                                anchors.margins: 6
                                radius: 5
                                color: !simTabRoot.curFrame ? "#334E68"
                                    : (simTabRoot.curFrame.event_kind === "pinch" ? "#16846E"
                                    : (simTabRoot.curFrame.event_kind === "swipe" ? "#D97706"
                                    : (simTabRoot.curFrame.event_kind === "sign" ? "#0284C7"
                                    : (simTabRoot.curFrame.event_kind === "transition" ? "#475569" : "#243B4A"))))
                                width: evBadgeText.implicitWidth + 12
                                height: 22
                                TextLabel {
                                    id: evBadgeText
                                    anchors.centerIn: parent
                                    color: "white"
                                    font.pixelSize: 12
                                    font.bold: true
                                    text: simTabRoot.curFrame ? simTabRoot.curFrame.event_text : "대기"
                                }
                            }

                            // Bottom-left Screen Position & Arm Pose Status HUD
                            Rectangle {
                                visible: simTabRoot.curFrame !== null
                                anchors.bottom: parent.bottom
                                anchors.left: parent.left
                                anchors.margins: 6
                                radius: 5
                                color: "#C80B151E"
                                width: Math.min(posHudText.implicitWidth + 12, parent.width - 12)
                                height: 22
                                TextLabel {
                                    id: posHudText
                                    anchors.verticalCenter: parent.verticalCenter
                                    anchors.left: parent.left
                                    anchors.leftMargin: 6
                                    width: parent.width - 12
                                    elide: Text.ElideRight
                                    color: "#8CE0CA"
                                    font.pixelSize: 12
                                    font.bold: true
                                    text: {
                                        var f = simTabRoot.curFrame
                                        if (!f) return ""
                                        var z = f.screen_zone ? ("화면영역: " + f.screen_zone) : "화면영역: -"
                                        if (f.palm_xy_pct && f.palm_xy_pct.length === 2) {
                                            z += " (" + f.palm_xy_pct[0] + "%, " + f.palm_xy_pct[1] + "%)"
                                        }
                                        if (f.target_position && f.target_position !== "") {
                                            z += " · 목표위치: " + f.target_position
                                        }
                                        if (f.cursor && f.cursor.length === 2) {
                                            z += " · 커서(" + f.cursor[0] + "," + f.cursor[1] + ")"
                                        }
                                        return z
                                    }
                                }
                            }
                        }

                        // Right: Frame Event Inspector + Interactive Timeline + Media Player Controls + Visualizer Mode Controls
                        ColumnLayout {
                            Layout.fillWidth: true
                            Layout.fillHeight: true
                            Layout.minimumWidth: 0
                            spacing: 6

                            // Summary Banner + Skeleton View Mode Controls
                            RowLayout {
                                Layout.fillWidth: true
                                spacing: 4
                                Rectangle {
                                    Layout.fillWidth: true
                                    Layout.minimumWidth: 0
                                    implicitHeight: 28
                                    radius: 7
                                    color: "#EEFCF8"
                                    border.color: "#45E0B4"
                                    TextLabel {
                                        anchors.fill: parent
                                        anchors.leftMargin: 8
                                        anchors.rightMargin: 8
                                        verticalAlignment: Text.AlignVCenter
                                        text: dashboard.simulationSummary
                                        font.bold: true
                                        font.pixelSize: 12
                                        elide: Text.ElideRight
                                    }
                                }
                                CompactButton {
                                    implicitHeight: 28
                                    leftPadding: 8; rightPadding: 8
                                    text: simTabRoot.showSpatialSpray ? "스프레이 켜짐" : "스프레이 꺼짐"
                                    accent: simTabRoot.showSpatialSpray
                                    onClicked: simTabRoot.showSpatialSpray = !simTabRoot.showSpatialSpray
                                }
                                CompactButton {
                                    implicitHeight: 28
                                    leftPadding: 8; rightPadding: 8
                                    text: simTabRoot.showArmPose ? "팔·어깨 켜짐" : "팔·어깨 꺼짐"
                                    accent: simTabRoot.showArmPose
                                    onClicked: simTabRoot.showArmPose = !simTabRoot.showArmPose
                                }
                                CompactButton {
                                    implicitHeight: 28
                                    leftPadding: 8; rightPadding: 8
                                    text: simTabRoot.fullScreenCoordMode ? "전체화면 좌표" : "손 확대"
                                    accent: simTabRoot.fullScreenCoordMode
                                    onClicked: simTabRoot.fullScreenCoordMode = !simTabRoot.fullScreenCoordMode
                                }
                                CompactButton {
                                    implicitHeight: 28
                                    leftPadding: 8; rightPadding: 8
                                    text: simTabRoot.expandSkeleton ? "화면 축소 ⤡" : "화면 크게 ⤢"
                                    accent: simTabRoot.expandSkeleton
                                    onClicked: simTabRoot.expandSkeleton = !simTabRoot.expandSkeleton
                                }
                            }

                            // 3-Box Live Frame Inspector (목표 동작+화면영역 / 모델 판정 / 규칙·팔어깨 각도)
                            RowLayout {
                                Layout.fillWidth: true
                                spacing: 6
                                Rectangle {
                                    Layout.fillWidth: true
                                    Layout.preferredWidth: 1
                                    Layout.minimumWidth: 0
                                    implicitHeight: 42
                                    radius: 7
                                    color: (simTabRoot.curFrame && simTabRoot.curFrame.zone === "judgment") ? "#E6F8F3"
                                        : ((simTabRoot.curFrame && simTabRoot.curFrame.zone === "transition") ? "#F8FAFC" : "white")
                                    border.color: (simTabRoot.curFrame && simTabRoot.curFrame.zone === "judgment") ? "#16846E"
                                        : ((simTabRoot.curFrame && simTabRoot.curFrame.zone === "transition") ? "#94A3B8" : window.line)
                                    ColumnLayout {
                                        anchors.fill: parent
                                        anchors.leftMargin: 8
                                        anchors.rightMargin: 8
                                        spacing: 0
                                        TextLabel { text: "구간 상태 (판정 구간 vs 전환 과정) · 화면 위치"; font.pixelSize: 11; color: window.muted; elide: Text.ElideRight; Layout.fillWidth: true; Layout.minimumWidth: 0 }
                                        TextLabel {
                                            text: simTabRoot.curFrame
                                                ? (simTabRoot.curFrame.target_name
                                                    + (simTabRoot.curFrame.zone === "judgment" ? " [판정 구간]"
                                                        : ((simTabRoot.curFrame.zone === "waiting" || simTabRoot.curFrame.phase === "waiting" || simTabRoot.curFrame.phase === "paused" || simTabRoot.curFrame.target === "idle") ? " [세트 대기]" : " [전환 과정]"))
                                                    + (simTabRoot.curFrame.screen_zone ? (" · " + simTabRoot.curFrame.screen_zone) : ""))
                                                : "-"
                                            font.bold: true
                                            font.pixelSize: 12
                                            color: (simTabRoot.curFrame && simTabRoot.curFrame.zone === "judgment") ? "#0F6E5B" : window.navy
                                            elide: Text.ElideRight
                                            Layout.fillWidth: true
                                            Layout.minimumWidth: 0
                                        }
                                    }
                                }
                                Rectangle {
                                    Layout.fillWidth: true
                                    Layout.preferredWidth: 1
                                    Layout.minimumWidth: 0
                                    implicitHeight: 42
                                    radius: 7
                                    color: (simTabRoot.curFrame && simTabRoot.curFrame.model_hit) ? "#E6F8F3" : "white"
                                    border.color: (simTabRoot.curFrame && simTabRoot.curFrame.model_hit) ? "#16846E" : window.line
                                    ColumnLayout {
                                        anchors.fill: parent
                                        anchors.leftMargin: 8
                                        anchors.rightMargin: 8
                                        spacing: 0
                                        TextLabel { text: "TCN 모델 실시간 예측"; font.pixelSize: 11; color: window.muted; elide: Text.ElideRight; Layout.fillWidth: true; Layout.minimumWidth: 0 }
                                        TextLabel {
                                            text: simTabRoot.curFrame
                                                ? (simTabRoot.curFrame.model_name + " · 확신도 " + Math.round(simTabRoot.curFrame.model_prob * 100) + "%" + (simTabRoot.curFrame.model_hit ? " (발동)" : ""))
                                                : "-"
                                            font.bold: true
                                            font.pixelSize: 12
                                            color: (simTabRoot.curFrame && simTabRoot.curFrame.model_hit) ? "#0F6E5B" : window.navy
                                            elide: Text.ElideRight
                                            Layout.fillWidth: true
                                            Layout.minimumWidth: 0
                                        }
                                    }
                                }
                                Rectangle {
                                    Layout.fillWidth: true
                                    Layout.preferredWidth: 1
                                    Layout.minimumWidth: 0
                                    implicitHeight: 42
                                    radius: 7
                                    color: (simTabRoot.curFrame && simTabRoot.curFrame.issue_text !== "") ? "#FFF1F0" : "white"
                                    border.color: (simTabRoot.curFrame && simTabRoot.curFrame.issue_text !== "") ? "#E5484D" : window.line
                                    ColumnLayout {
                                        anchors.fill: parent
                                        anchors.leftMargin: 8
                                        anchors.rightMargin: 8
                                        spacing: 0
                                        TextLabel { text: "팔·어깨 각도 / 프레임 품질"; font.pixelSize: 11; color: window.muted; elide: Text.ElideRight; Layout.fillWidth: true; Layout.minimumWidth: 0 }
                                        TextLabel {
                                            text: !simTabRoot.curFrame ? "-"
                                                : (simTabRoot.curFrame.issue_text !== ""
                                                    ? ("⚠ " + simTabRoot.curFrame.issue_text)
                                                    : ((simTabRoot.curFrame.active_arm && simTabRoot.curFrame.active_arm.elbow_deg !== null)
                                                        ? (simTabRoot.curFrame.active_arm.side_ko + " 팔꿈치 " + Math.round(simTabRoot.curFrame.active_arm.elbow_deg) + "° · vx=" + simTabRoot.curFrame.vx + ", vy=" + simTabRoot.curFrame.vy)
                                                        : ("속도 vx=" + simTabRoot.curFrame.vx + ", vy=" + simTabRoot.curFrame.vy)))
                                            font.bold: true
                                            font.pixelSize: 12
                                            color: (simTabRoot.curFrame && simTabRoot.curFrame.issue_text !== "") ? "#C62828" : window.navy
                                            elide: Text.ElideRight
                                            Layout.fillWidth: true
                                            Layout.minimumWidth: 0
                                        }
                                    }
                                }
                            }

                            // Interactive Probability Timeline + Playhead Scrubber
                            Rectangle {
                                Layout.fillWidth: true
                                Layout.fillHeight: true
                                implicitHeight: 64
                                radius: 8
                                color: "white"
                                border.color: window.line
                                ColumnLayout {
                                    anchors.fill: parent
                                    anchors.margins: 6
                                    spacing: 2
                                    RowLayout {
                                        Layout.fillWidth: true
                                        TextLabel {
                                            text: "시간축 판정 구간 & 전환 과정 프레임 바 (클릭·드래그 탐색 · 초록=판정 구간[목표 인식], 주황=판정 구간[미달], 청회색=전환 과정)"
                                            font.pixelSize: 11
                                            color: window.muted
                                            elide: Text.ElideRight
                                            Layout.fillWidth: true
                                        }
                                    }
                                    Item {
                                        id: timelineTrack
                                        Layout.fillWidth: true
                                        Layout.fillHeight: true
                                        RowLayout {
                                            anchors.fill: parent
                                            spacing: 1
                                            Repeater {
                                                model: dashboard.simulationTimeline
                                                delegate: Item {
                                                    required property var modelData
                                                    Layout.fillWidth: true
                                                    Layout.fillHeight: true
                                                    property string binZone: modelData.zone ? modelData.zone : (modelData.target === "idle" ? "waiting" : (modelData.target !== "none" ? "judgment" : "transition"))
                                                    // Zone background tint so 판정 구간 vs 전환 과정 spans are immediately visible
                                                    Rectangle {
                                                        anchors.fill: parent
                                                        radius: 1
                                                        color: binZone === "judgment"
                                                            ? "#E2F7F0"
                                                            : (binZone === "transition" ? "#F1F5F9" : "#F8FAFC")
                                                    }
                                                    // Top marker band highlighting 판정 구간
                                                    Rectangle {
                                                        visible: binZone === "judgment"
                                                        anchors.top: parent.top
                                                        width: parent.width
                                                        height: 3
                                                        color: modelData.confirmed ? "#16846E" : "#D97706"
                                                    }
                                                    // Target confidence / interval bar
                                                    Rectangle {
                                                        anchors.bottom: parent.bottom
                                                        width: parent.width
                                                        height: binZone === "judgment"
                                                            ? Math.max(parent.height * 0.42, parent.height * Math.min(1.0, modelData.prob))
                                                            : Math.max(4, parent.height * Math.min(0.65, modelData.prob * 0.65))
                                                        radius: 1
                                                        color: binZone === "waiting"
                                                            ? "#CBD5E1"
                                                            : (binZone === "judgment"
                                                                ? (modelData.confirmed ? "#16846E" : "#F2B544")
                                                                : "#94A3B8")
                                                    }
                                                }
                                            }
                                        }
                                        // Playhead indicator line
                                        Rectangle {
                                            visible: simTabRoot.totalFrames > 0
                                            width: 3
                                            height: parent.height
                                            radius: 1
                                            color: "#112331"
                                            x: simTabRoot.totalFrames > 1
                                                ? Math.min(parent.width - 3, Math.max(0, (simTabRoot.playFrameIdx / (simTabRoot.totalFrames - 1)) * (parent.width - 3)))
                                                : 0
                                        }
                                        MouseArea {
                                            anchors.fill: parent
                                            enabled: simTabRoot.totalFrames > 0
                                            onPressed: function(mouse) {
                                                simTabRoot.isPlaying = false
                                                var ratio = Math.max(0, Math.min(1, mouse.x / Math.max(1, width)))
                                                simTabRoot.seekFrame(ratio * (simTabRoot.totalFrames - 1))
                                            }
                                            onPositionChanged: function(mouse) {
                                                if (pressed) {
                                                    var ratio = Math.max(0, Math.min(1, mouse.x / Math.max(1, width)))
                                                    simTabRoot.seekFrame(ratio * (simTabRoot.totalFrames - 1))
                                                }
                                            }
                                        }
                                    }
                                }
                            }

                            // Media Player Transport Controls (여유 있게 배치 + 재생 중일 때만 연두색 선택 표시)
                            RowLayout {
                                Layout.fillWidth: true
                                spacing: 3
                                CompactButton {
                                    text: "⏮"
                                    implicitHeight: 28
                                    leftPadding: 7; rightPadding: 7
                                    enabled: simTabRoot.totalFrames > 0
                                    onClicked: {
                                        simTabRoot.isPlaying = false
                                        simTabRoot.seekFrame(0)
                                    }
                                }
                                CompactButton {
                                    text: "-10F"
                                    implicitHeight: 28
                                    leftPadding: 7; rightPadding: 7
                                    enabled: simTabRoot.totalFrames > 0
                                    onClicked: {
                                        simTabRoot.isPlaying = false
                                        simTabRoot.seekFrame(simTabRoot.playFrameIdx - 10)
                                    }
                                }
                                CompactButton {
                                    text: "-1F"
                                    implicitHeight: 28
                                    leftPadding: 7; rightPadding: 7
                                    enabled: simTabRoot.totalFrames > 0
                                    onClicked: {
                                        simTabRoot.isPlaying = false
                                        simTabRoot.seekFrame(simTabRoot.playFrameIdx - 1)
                                    }
                                }
                                CompactButton {
                                    text: simTabRoot.isPlaying ? "⏸ 일시정지" : "▶ 재생"
                                    implicitHeight: 28
                                    leftPadding: 9; rightPadding: 9
                                    accent: simTabRoot.isPlaying
                                    primary: !simTabRoot.isPlaying
                                    enabled: simTabRoot.totalFrames > 0
                                    onClicked: {
                                        if (!simTabRoot.isPlaying && simTabRoot.playFrameIdx >= simTabRoot.totalFrames - 1)
                                            simTabRoot.playFrameIdx = 0
                                        simTabRoot.isPlaying = !simTabRoot.isPlaying
                                    }
                                }
                                CompactButton {
                                    text: "⏹"
                                    implicitHeight: 28
                                    leftPadding: 7; rightPadding: 7
                                    enabled: simTabRoot.totalFrames > 0
                                    onClicked: {
                                        simTabRoot.isPlaying = false
                                        simTabRoot.seekFrame(0)
                                    }
                                }
                                CompactButton {
                                    text: "+1F"
                                    implicitHeight: 28
                                    leftPadding: 7; rightPadding: 7
                                    enabled: simTabRoot.totalFrames > 0
                                    onClicked: {
                                        simTabRoot.isPlaying = false
                                        simTabRoot.seekFrame(simTabRoot.playFrameIdx + 1)
                                    }
                                }
                                CompactButton {
                                    text: "+10F"
                                    implicitHeight: 28
                                    leftPadding: 7; rightPadding: 7
                                    enabled: simTabRoot.totalFrames > 0
                                    onClicked: {
                                        simTabRoot.isPlaying = false
                                        simTabRoot.seekFrame(simTabRoot.playFrameIdx + 10)
                                    }
                                }
                                CompactButton {
                                    text: "다음 이벤트 ⏭"
                                    implicitHeight: 28
                                    leftPadding: 8; rightPadding: 8
                                    enabled: simTabRoot.totalFrames > 0
                                    onClicked: {
                                        simTabRoot.isPlaying = false
                                        simTabRoot.jumpToNextEvent()
                                    }
                                }
                                Item { Layout.fillWidth: true; Layout.minimumWidth: 0 }
                                TextLabel { text: "배속:"; font.pixelSize: 12; color: window.muted }
                                Repeater {
                                    model: [0.25, 0.5, 1.0, 2.0, 4.0]
                                    delegate: CompactButton {
                                        required property real modelData
                                        implicitHeight: 28
                                        leftPadding: 6; rightPadding: 6
                                        text: modelData + "x"
                                        accent: Math.abs(simTabRoot.playSpeed - modelData) < 0.01
                                        onClicked: simTabRoot.playSpeed = modelData
                                    }
                                }
                            }
                        }
                    }
                }

                        // Selected ONNX Model Per-Gesture Recognition Rates & Spatial Spray Distribution Card
                        Rectangle {
                            Layout.fillWidth: true
                            implicitHeight: onnxProfileCol.implicitHeight + 16
                            radius: 10
                            color: "#F7FAFB"
                            border.color: window.line
                            ColumnLayout {
                                id: onnxProfileCol
                                anchors.fill: parent
                                anchors.margins: 8
                                spacing: 6
                                RowLayout {
                                    Layout.fillWidth: true
                                    spacing: 8
                                    TextLabel {
                                        text: "모델별 포착 동작 인식률 · 화면 영역 학습 분포(스프레이): "
                                            + (dashboard.selectedOnnxModel.title || "통합 하이브리드 모델")
                                        font.bold: true
                                        font.pixelSize: 13
                                    }
                                    Chip {
                                        text: "전체 인식률 " + Math.round(((dashboard.selectedOnnxModel.overall_rate || 0) * 100)) + "%"
                                    }
                                    Item { Layout.fillWidth: true; Layout.minimumWidth: 0 }
                                    RowLayout {
                                        spacing: 6
                                        Rectangle { width: 10; height: 10; radius: 5; color: "#2EE5B4" }
                                        TextLabel { text: "높은 인식·학습 밀집"; font.pixelSize: 11; color: window.muted }
                                        Rectangle { width: 10; height: 10; radius: 5; color: "#F2B544" }
                                        TextLabel { text: "보통/중간"; font.pixelSize: 11; color: window.muted }
                                        Rectangle { width: 10; height: 10; radius: 5; color: "#E5484D" }
                                        TextLabel { text: "인식 부족"; font.pixelSize: 11; color: window.muted }
                                    }
                                }
                                TextLabel {
                                    Layout.fillWidth: true
                                    Layout.minimumWidth: 0
                                    text: dashboard.spatialSprayHeadline
                                        + (dashboard.selectedOnnxModel.description ? ("   |   " + dashboard.selectedOnnxModel.description) : "")
                                    font.pixelSize: 12
                                    color: window.muted
                                    wrapMode: Text.Wrap
                                }
                                Flow {
                                    Layout.fillWidth: true
                                    spacing: 6
                                    Repeater {
                                        model: dashboard.selectedOnnxGestureRates
                                        delegate: Rectangle {
                                            id: gRateChip
                                            required property var modelData
                                            width: 222
                                            height: 44
                                            radius: 8
                                            color: dashboard.sprayGestureFilter === gRateChip.modelData.key ? "#E6F8F3" : "white"
                                            border.color: dashboard.sprayGestureFilter === gRateChip.modelData.key ? "#16846E" : window.line
                                            border.width: dashboard.sprayGestureFilter === gRateChip.modelData.key ? 2 : 1
                                            ColumnLayout {
                                                anchors.fill: parent
                                                anchors.margins: 6
                                                spacing: 3
                                                RowLayout {
                                                    Layout.fillWidth: true
                                                    spacing: 4
                                                    TextLabel {
                                                        text: gRateChip.modelData.name
                                                        font.bold: true
                                                        font.pixelSize: 12
                                                        Layout.fillWidth: true
                                                        elide: Text.ElideRight
                                                    }
                                                    TextLabel {
                                                        text: Math.round((gRateChip.modelData.rate || 0) * 100) + "% (" + (gRateChip.modelData.hits || 0) + "/" + (gRateChip.modelData.reps || 0) + ")"
                                                        font.bold: true
                                                        font.pixelSize: 12
                                                        color: (gRateChip.modelData.rate || 0) >= 0.72 ? "#0F6E5B" : ((gRateChip.modelData.rate || 0) >= 0.45 ? "#B45309" : "#C62828")
                                                    }
                                                }
                                                Rectangle {
                                                    Layout.fillWidth: true
                                                    height: 6
                                                    radius: 3
                                                    color: "#E2E8F0"
                                                    Rectangle {
                                                        width: parent.width * Math.max(0.0, Math.min(1.0, gRateChip.modelData.rate || 0))
                                                        height: parent.height
                                                        radius: 3
                                                        color: (gRateChip.modelData.rate || 0) >= 0.72 ? "#16846E" : ((gRateChip.modelData.rate || 0) >= 0.45 ? "#F2B544" : "#E5484D")
                                                    }
                                                }
                                            }
                                            MouseArea {
                                                anchors.fill: parent
                                                cursorShape: Qt.PointingHandCursor
                                                onClicked: {
                                                    var nextKey = (dashboard.sprayGestureFilter === gRateChip.modelData.key) ? "all" : gRateChip.modelData.key
                                                    dashboard.setSprayGestureFilter(nextKey)
                                                }
                                            }
                                        }
                                    }
                                }
                            }
                        }

                        // Explicit Recording Target Intent & Screen Region Coverage Banner
                        Rectangle {
                            Layout.fillWidth: true
                            implicitHeight: recIntentCol.implicitHeight + 14
                            radius: 10
                            color: "#EEF8F6"
                            border.color: "#8CE0CA"
                            ColumnLayout {
                                id: recIntentCol
                                anchors.fill: parent
                                anchors.margins: 7
                                spacing: 3
                                RowLayout {
                                    Layout.fillWidth: true
                                    spacing: 8
                                    Chip {
                                        text: dashboard.simRecordedModeLabel
                                    }
                                    TextLabel {
                                        Layout.fillWidth: true
                                        Layout.minimumWidth: 0
                                        text: "녹화 목표 동작: " + dashboard.simTargetGesturesText
                                        font.bold: true
                                        font.pixelSize: 13
                                        color: "#0B4F40"
                                        wrapMode: Text.Wrap
                                    }
                                    Chip {
                                        warn: dashboard.simPoseCoveragePct === 0
                                        text: dashboard.simPoseCoveragePct > 0
                                            ? ("팔·어깨 스켈레톤(Pose) " + dashboard.simPoseCoveragePct + "% 수록")
                                            : "팔·어깨 스켈레톤 추정 모드"
                                    }
                                }
                                TextLabel {
                                    Layout.fillWidth: true
                                    Layout.minimumWidth: 0
                                    text: "촬영 자세 조건: " + dashboard.simTargetConditionsText
                                        + "   |   화면 영역 기록 분포: " + dashboard.simScreenZonesText
                                        + (dashboard.simTargetInstructionText !== "" ? ("   |   수행 방법: " + dashboard.simTargetInstructionText) : "")
                                    font.pixelSize: 12
                                    color: "#235347"
                                    wrapMode: Text.Wrap
                                }
                            }
                        }
                        // 2-Column Enlarged Cards: Left = 데이터 평가·보정, Right = 데이터 증강 설정
                        RowLayout {
                            Layout.fillWidth: true
                            spacing: 10

                            // 1) 데이터 평가 및 보정 카드
                            Rectangle {
                                Layout.fillWidth: true
                                Layout.preferredWidth: 1
                                Layout.minimumWidth: 0
                                implicitHeight: Math.max(evalCalibCol.implicitHeight, augCol.implicitHeight) + 20
                                radius: 10
                                color: dashboard.simQualityStatus === "fail" ? "#FFF1F0" : (dashboard.simQualityStatus === "warning" ? "#FFF8EA" : "#F7FAFB")
                                border.color: dashboard.simQualityStatus === "fail" ? "#E5484D" : (dashboard.simQualityStatus === "warning" ? "#F2B544" : window.line)
                                ColumnLayout {
                                    id: evalCalibCol
                                    anchors.fill: parent
                                    anchors.margins: 10
                                    spacing: 6
                                    RowLayout {
                                        Layout.fillWidth: true
                                        spacing: 6
                                        TextLabel { text: "데이터 품질 평가 · 보정"; font.bold: true; font.pixelSize: 13 }
                                        Chip {
                                            warn: dashboard.simQualityStatus !== "pass"
                                            text: dashboard.simCleanedExists ? "보정본 적용 중" : "원본 상태"
                                        }
                                        Item { Layout.fillWidth: true; Layout.minimumWidth: 0 }
                                        CompactButton {
                                            text: "데이터 보정 실행"
                                            primary: true
                                            enabled: dashboard.trainingBusy === "" && !dashboard.trainingRunning && dashboard.trainingFiles.length > 0
                                            onClicked: dashboard.calibrateSimRecording(
                                                simTabRoot.currentSimFilename(),
                                                simTabRoot.calibInterpGap,
                                                simTabRoot.calibJointJump,
                                                4
                                            )
                                        }
                                        CompactButton {
                                            text: "원본 복구"
                                            enabled: dashboard.trainingBusy === "" && !dashboard.trainingRunning && dashboard.simCleanedExists
                                            onClicked: dashboard.resetCalibratedSimRecording(simTabRoot.currentSimFilename())
                                        }
                                    }
                                    TextLabel {
                                        Layout.fillWidth: true
                                        Layout.minimumWidth: 0
                                        text: dashboard.simQualityHeadline
                                        font.pixelSize: 12
                                        color: window.ink
                                        wrapMode: Text.Wrap
                                    }
                                    RowLayout {
                                        Layout.fillWidth: true
                                        spacing: 6
                                        TextLabel { text: "손끊김 결측 보간:"; font.pixelSize: 12; color: window.muted; Layout.preferredWidth: 96 }
                                        Repeater {
                                            model: [
                                                { label: "1프레임", val: 1 },
                                                { label: "3프레임 (권장)", val: 3 },
                                                { label: "5프레임", val: 5 }
                                            ]
                                            delegate: CompactButton {
                                                required property var modelData
                                                text: modelData.label
                                                accent: simTabRoot.calibInterpGap === modelData.val
                                                onClicked: simTabRoot.calibInterpGap = modelData.val
                                            }
                                        }
                                        Item { Layout.fillWidth: true }
                                    }
                                    RowLayout {
                                        Layout.fillWidth: true
                                        spacing: 6
                                        TextLabel { text: "관절 점프 억제:"; font.pixelSize: 12; color: window.muted; Layout.preferredWidth: 96 }
                                        Repeater {
                                            model: [
                                                { label: "엄격 (0.25)", val: 0.25 },
                                                { label: "표준 (0.38)", val: 0.38 },
                                                { label: "완화 (0.50)", val: 0.50 }
                                            ]
                                            delegate: CompactButton {
                                                required property var modelData
                                                text: modelData.label
                                                accent: Math.abs(simTabRoot.calibJointJump - modelData.val) < 0.01
                                                onClicked: simTabRoot.calibJointJump = modelData.val
                                            }
                                        }
                                        Item { Layout.fillWidth: true }
                                    }
                                }
                            }

                            // 2) 데이터 증강 설정 카드
                            Rectangle {
                                Layout.fillWidth: true
                                Layout.preferredWidth: 1
                                Layout.minimumWidth: 0
                                implicitHeight: Math.max(evalCalibCol.implicitHeight, augCol.implicitHeight) + 20
                                radius: 10
                                color: "#F7FAFB"
                                border.color: window.line
                                ColumnLayout {
                                    id: augCol
                                    anchors.fill: parent
                                    anchors.margins: 10
                                    spacing: 6
                                    RowLayout {
                                        Layout.fillWidth: true
                                        spacing: 6
                                        TextLabel { text: "데이터 증강 설정"; font.bold: true; font.pixelSize: 13 }
                                        CompactButton {
                                            text: dashboard.augEnabled ? "증강 사용 중 (ON)" : "증강 꺼짐 (OFF)"
                                            accent: dashboard.augEnabled
                                            enabled: dashboard.trainingBusy === "" && !dashboard.trainingRunning
                                            onClicked: dashboard.setAugmentationConfig(!dashboard.augEnabled, dashboard.augStrength, dashboard.augFactor)
                                        }
                                        Item { Layout.fillWidth: true; Layout.minimumWidth: 0 }
                                        CompactButton {
                                            text: dashboard.augEnabled ? "이 녹화 증강" : "이 녹화 삭제"
                                            primary: dashboard.augEnabled
                                            enabled: dashboard.trainingBusy === "" && !dashboard.trainingRunning && dashboard.trainingFiles.length > 0
                                            onClicked: dashboard.applySimAugmentation(
                                                simTabRoot.currentSimFilename(),
                                                dashboard.augEnabled,
                                                dashboard.augStrength,
                                                dashboard.augFactor
                                            )
                                        }
                                        CompactButton {
                                            text: dashboard.augEnabled ? "전체 녹화 증강" : "전체 증강 정리"
                                            enabled: dashboard.trainingBusy === "" && !dashboard.trainingRunning && dashboard.trainingFiles.length > 0
                                            onClicked: dashboard.applySimAugmentation(
                                                "__all__",
                                                dashboard.augEnabled,
                                                dashboard.augStrength,
                                                dashboard.augFactor
                                            )
                                        }
                                    }
                                    TextLabel {
                                        Layout.fillWidth: true
                                        Layout.minimumWidth: 0
                                        text: dashboard.augSummary
                                        font.pixelSize: 12
                                        color: window.ink
                                        wrapMode: Text.Wrap
                                    }
                                    RowLayout {
                                        Layout.fillWidth: true
                                        spacing: 6
                                        TextLabel { text: "회전·노이즈 강도:"; font.pixelSize: 12; color: window.muted; Layout.preferredWidth: 96 }
                                        Repeater {
                                            model: [
                                                { key: "light", label: "약 (±20°)" },
                                                { key: "normal", label: "보통 (±35°)" },
                                                { key: "strong", label: "강 (±50°)" }
                                            ]
                                            delegate: CompactButton {
                                                required property var modelData
                                                text: modelData.label
                                                accent: dashboard.augStrength === modelData.key
                                                enabled: dashboard.augEnabled && dashboard.trainingBusy === "" && !dashboard.trainingRunning
                                                onClicked: dashboard.setAugmentationConfig(dashboard.augEnabled, modelData.key, dashboard.augFactor)
                                            }
                                        }
                                        Item { Layout.fillWidth: true }
                                    }
                                    RowLayout {
                                        Layout.fillWidth: true
                                        spacing: 6
                                        TextLabel { text: "녹화당 증강 배수:"; font.pixelSize: 12; color: window.muted; Layout.preferredWidth: 96 }
                                        Repeater {
                                            model: [1, 2, 4, 6]
                                            delegate: CompactButton {
                                                required property int modelData
                                                text: modelData + "배 생성"
                                                accent: dashboard.augFactor === modelData
                                                enabled: dashboard.augEnabled && dashboard.trainingBusy === "" && !dashboard.trainingRunning
                                                onClicked: dashboard.setAugmentationConfig(dashboard.augEnabled, dashboard.augStrength, modelData)
                                            }
                                        }
                                        Item { Layout.fillWidth: true }
                                    }
                                }
                            }
                        }

                        TextLabel {
                            visible: dashboard.simQualityIssues.length > 0
                            text: "감지된 데이터 이상 구간 (" + dashboard.simQualityIssues.length + "건 · 항목 클릭 시 해당 프레임으로 이동)"
                            font.bold: true
                            font.pixelSize: 12
                        }
                        Repeater {
                            model: dashboard.simQualityIssues
                            delegate: Rectangle {
                                id: issRow
                                required property var modelData
                                Layout.fillWidth: true
                                implicitHeight: 30
                                radius: 8
                                color: issRow.modelData.severity === "fail" ? "#FFF1F0" : "#FFF8EA"
                                border.color: issRow.modelData.severity === "fail" ? "#E5484D" : "#F2B544"
                                RowLayout {
                                    anchors.fill: parent
                                    anchors.leftMargin: 10
                                    anchors.rightMargin: 10
                                    spacing: 8
                                    Chip {
                                        warn: true
                                        text: issRow.modelData.severity === "fail" ? "치명" : "주의"
                                    }
                                    TextLabel {
                                        text: issRow.modelData.start_t + "s ~ " + issRow.modelData.end_t + "s (프레임 " + issRow.modelData.start_frame + "~" + issRow.modelData.end_frame + ")"
                                        font.bold: true
                                        font.pixelSize: 12
                                        Layout.preferredWidth: 185
                                    }
                                    TextLabel {
                                        text: issRow.modelData.message
                                        font.pixelSize: 12
                                        Layout.fillWidth: true
                                        Layout.minimumWidth: 0
                                        elide: Text.ElideRight
                                    }
                                    CompactButton {
                                        text: "이동 ▶"
                                        onClicked: {
                                            simTabRoot.isPlaying = false
                                            simTabRoot.seekFrame(issRow.modelData.start_frame || 0)
                                        }
                                    }
                                }
                            }
                        }
                        TextLabel {
                            visible: dashboard.simulationGestures.length > 0
                            text: "동작별 모델 vs 규칙 비교"
                            font.bold: true
                            font.pixelSize: 13
                        }
                        Repeater {
                            model: dashboard.simulationGestures
                            delegate: Rectangle {
                                id: simRow
                                required property var modelData
                                Layout.fillWidth: true
                                implicitHeight: simRowCol.implicitHeight + 12
                                radius: 8
                                color: "#F7FAFB"
                                border.color: window.line
                                RowLayout {
                                    id: simRowCol
                                    anchors.fill: parent
                                    anchors.margins: 6
                                    spacing: 10
                                    TextLabel {
                                        text: simRow.modelData.name
                                        font.bold: true
                                        font.pixelSize: 12
                                        Layout.preferredWidth: 150
                                        elide: Text.ElideRight
                                    }
                                    Chip {
                                        warn: !simRow.modelData.trained
                                        text: simRow.modelData.trained ? "학습됨" : "미학습"
                                    }
                                    TextLabel {
                                        text: simRow.modelData.reps > 0
                                            ? ("반복 " + simRow.modelData.reps + "회 중 모델 " + simRow.modelData.model_hits + "회 (" + Math.round((simRow.modelData.model_rate || 0) * 100) + "%) · 규칙 " + simRow.modelData.rule_hits + "회 (" + Math.round((simRow.modelData.rule_rate || 0) * 100) + "%)")
                                            : "이 녹화에 목표 반복 없음"
                                        font.pixelSize: 12
                                        Layout.fillWidth: true
                                        Layout.minimumWidth: 0
                                        elide: Text.ElideRight
                                    }
                                    TextLabel {
                                        text: "최고 확신도 " + Math.round(simRow.modelData.max_prob * 100) + "% · 중립 오작동 " + simRow.modelData.false_fires + "회"
                                        font.pixelSize: 12
                                        color: simRow.modelData.false_fires > 0 ? "#C62828" : window.muted
                                    }
                                }
                            }
                        }
                        TextLabel {
                            visible: dashboard.simulationReps.length > 0
                            text: "회차별 상세 판정 기록 (" + dashboard.simulationReps.length + "회 · 클릭 시 해당 구간 재생)"
                            font.bold: true
                            font.pixelSize: 13
                        }
                        Repeater {
                            model: dashboard.simulationReps
                            delegate: Rectangle {
                                id: repRow
                                required property var modelData
                                Layout.fillWidth: true
                                implicitHeight: 32
                                radius: 8
                                color: repRow.modelData.model_ok ? "#F2FBF9" : "#FFF8EA"
                                border.color: repRow.modelData.model_ok ? "#B2DFDB" : "#F2B544"
                                RowLayout {
                                    anchors.fill: parent
                                    anchors.leftMargin: 10
                                    anchors.rightMargin: 10
                                    spacing: 8
                                    TextLabel { text: "#" + repRow.modelData.rep + " (" + repRow.modelData.time_s + "초)"; font.bold: true; font.pixelSize: 12; Layout.preferredWidth: 85 }
                                    TextLabel { text: repRow.modelData.name; font.pixelSize: 12; Layout.preferredWidth: 150; elide: Text.ElideRight }
                                    TextLabel { text: "최고 확률 " + Math.round(repRow.modelData.peak_prob * 100) + "% (평균 " + Math.round(repRow.modelData.mean_prob * 100) + "%)"; font.pixelSize: 12; Layout.fillWidth: true; Layout.minimumWidth: 0; elide: Text.ElideRight }
                                    // a collected use (src/use_sim.py) says what happened to it instead of "rule passed"
                                    Chip {
                                        warn: !repRow.modelData.model_ok && repRow.modelData.no_model !== true
                                        text: repRow.modelData.no_model === true ? "확인 모델 없음" : (repRow.modelData.model_ok ? "모델 통과" : "모델 미달")
                                    }
                                    Chip {
                                        warn: !repRow.modelData.rule_ok
                                        text: repRow.modelData.use === true
                                            ? (repRow.modelData.rule_ok ? "실행됨" : "원하지 않음 표시")
                                            : (repRow.modelData.rule_ok ? "규칙 통과" : "규칙 미달")
                                    }
                                    CompactButton {
                                        text: "구간 재생 ▶"
                                        onClicked: {
                                            simTabRoot.seekFrame(repRow.modelData.start_frame || 0)
                                            simTabRoot.isPlaying = true
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }

            // =========================================================================
            // TAB 4: 모델 버전 복원(롤백) · 앱 자가 진단
            // =========================================================================
            ColumnLayout {
                visible: trainingCenter.centerTab === "diagnostics"
                Layout.fillWidth: true
                Layout.fillHeight: true
                spacing: 10
                RowLayout {
                    Layout.fillWidth: true
                    spacing: 8
                    TextLabel {
                        text: "앱 자가 진단 및 버그 탐지"
                        font.bold: true
                        font.pixelSize: 16
                    }
                    TextLabel {
                        Layout.fillWidth: true
                        Layout.minimumWidth: 0
                        elide: Text.ElideRight
                        text: dashboard.diagnosticsSummary
                        font.pixelSize: 12
                        color: window.muted
                    }
                    ActionButton {
                        text: "자가 진단 다시 실행"
                        enabled: dashboard.trainingBusy === ""
                        onClicked: dashboard.runDiagnostics()
                    }
                }
                ScrollView {
                    id: diagScroll
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    clip: true
                    contentWidth: availableWidth
                    ScrollBar.vertical.policy: ScrollBar.AlwaysOn
                    ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
                    ColumnLayout {
                        width: diagScroll.availableWidth
                        spacing: 8
                        Repeater {
                            model: dashboard.diagnosticsChecks
                            delegate: Rectangle {
                                id: chkRow
                                required property var modelData
                                Layout.fillWidth: true
                                implicitHeight: chkBody.implicitHeight + 16
                                radius: 10
                                color: chkRow.modelData.status === "fail" ? "#FFF1F0" : (chkRow.modelData.status === "warn" ? "#FFF8EA" : "#F7FAFB")
                                border.color: chkRow.modelData.status === "fail" ? "#E5484D" : (chkRow.modelData.status === "warn" ? "#F2B544" : window.line)
                                RowLayout {
                                    id: chkBody
                                    anchors.fill: parent
                                    anchors.margins: 8
                                    spacing: 10
                                    Chip {
                                        warn: chkRow.modelData.status !== "ok"
                                        text: chkRow.modelData.status === "ok" ? "정상" : (chkRow.modelData.status === "warn" ? "주의" : "오류")
                                    }
                                    TextLabel {
                                        text: chkRow.modelData.name
                                        font.bold: true
                                        font.pixelSize: 13
                                        Layout.preferredWidth: 210
                                        elide: Text.ElideRight
                                    }
                                    TextLabel {
                                        text: chkRow.modelData.detail
                                        font.pixelSize: 12
                                        color: window.muted
                                        Layout.fillWidth: true
                                        Layout.minimumWidth: 0
                                        wrapMode: Text.Wrap
                                    }
                                }
                            }
                        }
                        Rectangle { Layout.fillWidth: true; height: 1; color: window.line }
                        TextLabel {
                            text: "이전 모델 버전으로 되돌리기 (자동 백업 및 내보내기 스냅샷)"
                            font.bold: true
                            font.pixelSize: 16
                        }
                        TextLabel {
                            Layout.fillWidth: true
                            Layout.minimumWidth: 0
                            text: "새로 학습한 모델이 마음에 들지 않을 때, 학습 직전 자동 백업본이나 이전에 내보낸 모델 버전으로 즉시 복원합니다."
                            font.pixelSize: 12
                            color: window.muted
                            wrapMode: Text.Wrap
                        }
                        TextLabel {
                            visible: dashboard.modelBackups.length === 0
                            Layout.fillWidth: true
                            Layout.minimumWidth: 0
                            wrapMode: Text.Wrap
                            text: "아직 저장된 이전 모델 백업이 없습니다. (다음 학습이나 동작 초기화 시 자동으로 백업됩니다)"
                            font.pixelSize: 12
                            color: window.muted
                        }
                        Repeater {
                            model: dashboard.modelBackups
                            delegate: Rectangle {
                                id: bakRow
                                required property var modelData
                                Layout.fillWidth: true
                                implicitHeight: bakBody.implicitHeight + 18
                                radius: 10
                                color: "#F7FAFB"
                                border.color: window.line
                                RowLayout {
                                    id: bakBody
                                    anchors.fill: parent
                                    anchors.margins: 10
                                    spacing: 12
                                    ColumnLayout {
                                        Layout.fillWidth: true
                                        Layout.minimumWidth: 0
                                        spacing: 3
                                        RowLayout {
                                            Layout.fillWidth: true
                                            spacing: 8
                                            Chip {
                                                text: bakRow.modelData.source === "export" ? "내보내기 본" : "자동 백업"
                                            }
                                            TextLabel {
                                                Layout.fillWidth: true
                                                Layout.minimumWidth: 0
                                                elide: Text.ElideRight
                                                text: bakRow.modelData.name
                                                font.bold: true
                                                font.pixelSize: 13
                                            }
                                        }
                                        TextLabel {
                                            Layout.fillWidth: true
                                            Layout.minimumWidth: 0
                                            text: bakRow.modelData.summary
                                            font.pixelSize: 12
                                            color: window.muted
                                            wrapMode: Text.Wrap
                                        }
                                    }
                                    ActionButton {
                                        text: "이 버전으로 복원"
                                        enabled: !dashboard.trainingRunning && !dashboard.recActive && dashboard.trainingBusy === ""
                                        onClicked: dashboard.restoreModelBackup(bakRow.modelData.id)
                                    }
                                }
                            }
                        }
                    }
                }
            }

            // Tab 5: Shortcut Mapping · Composite Gestures · Dedicated Time-Series Motion Learning
            Item {
                id: bindingsTabRoot
                objectName: "bindingsTabRoot"
                visible: trainingCenter.centerTab === "bindings"
                Layout.fillWidth: true
                Layout.fillHeight: true

                // dashboard.bindingRows: what each hand signal runs in the hand mode in use (qt_dashboard._binding_rows)
                property var selectedRowObj: {
                    var rows = dashboard.bindingRows || []
                    var first = null
                    for (var i = 0; i < rows.length; i++) {
                        if (rows[i].key === trainingCenter.selectedBindingKey) {
                            return rows[i]
                        }
                        if (rows[i].editable && (first === null || (!first.active && rows[i].active)))
                            first = rows[i]          // the first one that can be changed and is in use now
                    }
                    return first !== null ? first : (rows.length > 0 ? rows[0] : null)
                }
                readonly property bool selEditable: selectedRowObj !== null && Boolean(selectedRowObj.editable)
                function loadPrefs() {
                    var groups = dashboard.hotkeyGroups || []
                    var g = dashboard.centerPref("bind.hotkeyGroup", "브라우저")
                    hotkeyGroup = groups.indexOf(g) >= 0 ? g : "브라우저"
                    var recipes = dashboard.recipeGroups || []
                    g = dashboard.centerPref("bind.motionRecipeGroup", "브라우저")
                    motionRecipeGroup = recipes.indexOf(g) >= 0 ? g : "브라우저"
                    g = dashboard.centerPref("bind.compRecipeGroup", "미디어")
                    compRecipeGroup = recipes.indexOf(g) >= 0 ? g : "미디어"
                }
                onHotkeyGroupChanged: trainingCenter.savePref("bind.hotkeyGroup", hotkeyGroup)
                onMotionRecipeGroupChanged: trainingCenter.savePref("bind.motionRecipeGroup", motionRecipeGroup)
                onCompRecipeGroupChanged: trainingCenter.savePref("bind.compRecipeGroup", compRecipeGroup)
                property string editActionType: selectedRowObj ? String(selectedRowObj.action_type || "hotkey") : "hotkey"
                property string editActionValue: selectedRowObj ? String(selectedRowObj.action_value || "") : ""
                property bool editBindingEnabled: selectedRowObj ? Boolean(selectedRowObj.binding_enabled) : true

                property string appMatchInput: ""
                property string appActionTypeInput: "youtube_key"
                property string appActionValueInput: "k"

                property string newMotionName: ""
                property string newMotionKey: ""
                property string newMotionPosture: "open_hand"
                property string newMotionDir: "up"
                property string newMotionActType: "hotkey"
                property string newMotionActVal: "ctrl+t"

                property string newCompName: ""
                property string newCompPosture: "thumb_index"
                property string newCompTrigger: "swipe_up"
                property string newCompActType: "youtube_key"
                property string newCompActVal: "f"
                property string hotkeyGroup: "브라우저"        // which group of ready-made shortcuts is shown
                property string motionRecipeGroup: "브라우저"   // which group of ready-made motions is shown
                property string compRecipeGroup: "미디어"
                property string recipeNote: ""

                // the binding rows are rebuilt on every refresh: reset the edits only when another motion is picked,
                // otherwise an unsaved choice (and the on/off button) snapped back to the saved value at once
                property string editKey: ""
                onSelectedRowObjChanged: {
                    if (selectedRowObj && selectedRowObj.key !== editKey) {
                        editKey = selectedRowObj.key
                        editActionType = String(selectedRowObj.action_type || "hotkey")
                        editActionValue = String(selectedRowObj.action_value || "")
                        editBindingEnabled = Boolean(selectedRowObj.binding_enabled)
                        saveNote = ""
                        saveFailed = false
                    }
                }
                // what [저장] did (a refused command used to leave the screen silent: the list kept the old command)
                property string saveNote: ""
                property bool saveFailed: false
                // the choice on the right differs from what is saved (the list on the left shows the saved one)
                readonly property bool unsaved: selectedRowObj !== null && selEditable
                    && (editActionType !== String(selectedRowObj.action_type || "")
                        || editActionValue !== String(selectedRowObj.action_value || ""))
                // why the picked command cannot be connected to this signal ("" = it can)
                readonly property string refusal: selectedRowObj !== null
                    ? dashboard.bindingRefusal(selectedRowObj.key, editActionType, editActionValue) : ""

                ColumnLayout {
                    anchors.fill: parent
                    spacing: 8

                    // Sub-tab selector bar
                    Rectangle {
                        Layout.fillWidth: true
                        implicitHeight: 44
                        radius: 10
                        color: "#F0F4F8"
                        border.color: window.line
                        RowLayout {
                            anchors.fill: parent
                            anchors.margins: 5
                            spacing: 6
                            CompactButton {
                                implicitHeight: 32
                                leftPadding: 14; rightPadding: 14
                                text: "연결 바꾸기"
                                accent: trainingCenter.bindingsSubTab === "shortcuts"
                                onClicked: trainingCenter.bindingsSubTab = "shortcuts"
                            }
                            CompactButton {
                                implicitHeight: 32
                                leftPadding: 14; rightPadding: 14
                                text: "모션 등록 (" + dashboard.motionTrackRows.length + ")"
                                accent: trainingCenter.bindingsSubTab === "motions"
                                onClicked: trainingCenter.bindingsSubTab = "motions"
                            }
                            CompactButton {
                                implicitHeight: 32
                                leftPadding: 14; rightPadding: 14
                                text: "복합 동작 등록 (" + dashboard.compositeGestureRows.length + ")"
                                accent: trainingCenter.bindingsSubTab === "composites"
                                onClicked: trainingCenter.bindingsSubTab = "composites"
                            }
                            Item { Layout.fillWidth: true }
                        }
                    }

                    // =========================================================================
                    // SUB-TAB 1: SHORTCUT MAPPINGS & PER-APP FOREGROUND OVERRIDES
                    // =========================================================================
                    RowLayout {
                        visible: trainingCenter.bindingsSubTab === "shortcuts"
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        spacing: 10

                        // Left list: all static & motion gestures with their mapped shortcut badges
                        Rectangle {
                            Layout.preferredWidth: 420
                            Layout.fillHeight: true
                            radius: 10
                            color: "#F7FAFB"
                            border.color: window.line
                            ColumnLayout {
                                anchors.fill: parent
                                anchors.margins: 8
                                spacing: 6
                                RowLayout {
                                    Layout.fillWidth: true
                                    spacing: 6
                                    TextLabel {
                                        text: "손 신호 → 실행되는 명령"
                                        font.bold: true
                                        font.pixelSize: 13
                                    }
                                    Item { Layout.fillWidth: true }
                                    Chip { objectName: "bindingProfileChip"; text: dashboard.bindingProfileNote }
                                    Chip { objectName: "handModeChip"; text: "지금 · " + dashboard.handModeName }
                                }
                                ScrollView {
                                    id: bindingListScroll
                                    Layout.fillWidth: true
                                    Layout.fillHeight: true
                                    clip: true
                                    contentWidth: availableWidth
                                    ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
                                    ColumnLayout {
                                        width: bindingListScroll.availableWidth - 12
                                        spacing: 4
                                        Repeater {
                                            model: dashboard.bindingRows
                                            delegate: ColumnLayout {
                                                id: bItem
                                                required property var modelData
                                                required property int index
                                                readonly property bool isSel: bindingsTabRoot.selectedRowObj !== null && bindingsTabRoot.selectedRowObj.key === modelData.key
                                                readonly property bool firstOfSection: index === 0 || dashboard.bindingRows[index - 1].section !== modelData.section
                                                readonly property string note: {
                                                    var parts = []
                                                    if (modelData.why) parts.push(modelData.why)
                                                    if (modelData.how) parts.push(modelData.how)
                                                    if (modelData.changed) parts.push("기본 명령: " + String(modelData.default_badge || ""))
                                                    var n = (modelData.app_overrides || []).length
                                                    if (n > 0) parts.push("앱 전용 " + n + "개")
                                                    return parts.join("  ·  ")
                                                }
                                                Layout.fillWidth: true
                                                spacing: 3
                                                TextLabel {
                                                    visible: bItem.firstOfSection
                                                    Layout.fillWidth: true
                                                    Layout.topMargin: bItem.index === 0 ? 0 : 10
                                                    text: bItem.modelData.section
                                                    font.pixelSize: 11
                                                    font.bold: true
                                                    color: window.muted
                                                    elide: Text.ElideRight
                                                }
                                                Rectangle {
                                                    objectName: "bindingRow"
                                                    Layout.fillWidth: true
                                                    implicitHeight: bItemCol.implicitHeight + 12
                                                    radius: 8
                                                    color: bItem.isSel ? "#E0F2FE" : (bItem.modelData.editable ? "white" : "#F1F5F9")
                                                    border.color: bItem.isSel ? "#0284C7" : window.line
                                                    border.width: bItem.isSel ? 2 : 1
                                                    opacity: bItem.modelData.active ? 1 : 0.6
                                                    ColumnLayout {
                                                        id: bItemCol
                                                        anchors.fill: parent
                                                        anchors.margins: 6
                                                        spacing: 2
                                                        RowLayout {
                                                            Layout.fillWidth: true
                                                            spacing: 8
                                                            TextLabel {
                                                                text: bItem.modelData.name
                                                                font.bold: true
                                                                font.pixelSize: 12
                                                                elide: Text.ElideRight
                                                                Layout.fillWidth: true
                                                                Layout.minimumWidth: 0
                                                            }
                                                            // "기본": a move or sign the app comes with (2026-11-11)
                                                            Rectangle {
                                                                objectName: "bindingDefaultTag"
                                                                visible: Boolean(bItem.modelData.builtin)
                                                                radius: 4
                                                                color: bItem.modelData.changed ? "#FFF0D4" : "#E8EEF4"
                                                                border.color: bItem.modelData.changed ? "#F2B544" : "#C9D6E2"
                                                                implicitWidth: defTagTxt.implicitWidth + 10
                                                                implicitHeight: 18
                                                                TextLabel {
                                                                    id: defTagTxt
                                                                    anchors.centerIn: parent
                                                                    text: !bItem.modelData.editable ? "기본 · 고정"
                                                                          : (bItem.modelData.changed ? "기본 · 바꿈" : "기본")
                                                                    font.pixelSize: 11
                                                                    font.bold: true
                                                                    color: bItem.modelData.changed ? "#945800" : "#475569"
                                                                }
                                                            }
                                                            TextLabel {
                                                                text: "→ " + String(bItem.modelData.shortcut_badge || "")
                                                                font.pixelSize: 12
                                                                font.bold: true
                                                                color: !bItem.modelData.binding_enabled ? window.muted
                                                                       : (bItem.modelData.editable ? "#0369A1" : "#475569")
                                                                elide: Text.ElideRight
                                                                horizontalAlignment: Text.AlignRight
                                                                Layout.maximumWidth: 190
                                                            }
                                                        }
                                                        TextLabel {
                                                            visible: bItem.note !== ""
                                                            Layout.fillWidth: true
                                                            text: bItem.note
                                                            font.pixelSize: 12
                                                            color: bItem.modelData.why ? "#B45309" : window.muted
                                                            wrapMode: Text.Wrap
                                                        }
                                                    }
                                                    MouseArea {
                                                        anchors.fill: parent
                                                        cursorShape: Qt.PointingHandCursor
                                                        onClicked: trainingCenter.selectedBindingKey = bItem.modelData.key
                                                    }
                                                }
                                            }
                                        }
                                    }
                                }
                            }
                        }

                        // Right editor: customize global binding & per-app foreground overrides
                        ScrollView {
                            id: shortcutEditorScroll
                            Layout.fillWidth: true
                            Layout.fillHeight: true
                            clip: true
                            contentWidth: availableWidth
                            ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
                            ColumnLayout {
                                width: Math.max(240, shortcutEditorScroll.availableWidth - 16)
                                spacing: 10

                                Rectangle {
                                    objectName: "bindingFixedNote"
                                    visible: bindingsTabRoot.selectedRowObj !== null && !bindingsTabRoot.selEditable
                                    Layout.fillWidth: true
                                    implicitHeight: fixedNoteCol.implicitHeight + 20
                                    radius: 10
                                    color: "#F7FAFB"
                                    border.color: window.line
                                    ColumnLayout {
                                        id: fixedNoteCol
                                        anchors.fill: parent
                                        anchors.margins: 10
                                        spacing: 6
                                        TextLabel {
                                            Layout.fillWidth: true
                                            text: bindingsTabRoot.selectedRowObj
                                                  ? (bindingsTabRoot.selectedRowObj.name + "  →  " + bindingsTabRoot.selectedRowObj.shortcut_badge) : ""
                                            font.bold: true
                                            font.pixelSize: 14
                                            wrapMode: Text.Wrap
                                        }
                                        TextLabel {
                                            visible: text !== ""
                                            Layout.fillWidth: true
                                            text: bindingsTabRoot.selectedRowObj ? String(bindingsTabRoot.selectedRowObj.how || "") : ""
                                            font.pixelSize: 12
                                            color: window.muted
                                            wrapMode: Text.Wrap
                                        }
                                        TextLabel {
                                            Layout.fillWidth: true
                                            text: "이 조작은 다른 모든 동작의 바탕이 되는 기본 동작이라 다른 명령으로 바꿀 수 없어요. 원하는 명령은 왼쪽 목록의 다른 동작에 연결하세요."
                                            font.pixelSize: 12
                                            wrapMode: Text.Wrap
                                        }
                                    }
                                }

                                Rectangle {
                                    visible: bindingsTabRoot.selEditable
                                    Layout.fillWidth: true
                                    implicitHeight: globalEditCol.implicitHeight + 20
                                    radius: 10
                                    color: "#F7FAFB"
                                    border.color: window.line
                                    ColumnLayout {
                                        id: globalEditCol
                                        anchors.fill: parent
                                        anchors.margins: 10
                                        spacing: 8

                                        RowLayout {
                                            Layout.fillWidth: true
                                            spacing: 8
                                            TextLabel {
                                                text: bindingsTabRoot.selectedRowObj ? (bindingsTabRoot.selectedRowObj.name + "  →  실행할 명령") : ""
                                                font.bold: true
                                                font.pixelSize: 14
                                                wrapMode: Text.Wrap
                                                Layout.fillWidth: true
                                                Layout.minimumWidth: 0
                                            }
                                            Item { Layout.fillWidth: true }
                                            CompactButton {
                                                text: bindingsTabRoot.editBindingEnabled ? "켜짐 · 누르면 끔" : "꺼짐 · 누르면 켬"
                                                accent: bindingsTabRoot.editBindingEnabled
                                                // saved at once with the saved command (it used to change only an unsaved flag)
                                                onClicked: {
                                                    var row = bindingsTabRoot.selectedRowObj
                                                    if (!row) return
                                                    var on = !bindingsTabRoot.editBindingEnabled
                                                    if (dashboard.saveGestureBinding(row.key, String(row.action_type || "mouse_action"),
                                                                                     String(row.action_value || "none"), on))
                                                        bindingsTabRoot.editBindingEnabled = on
                                                }
                                            }
                                        }

                                        TextLabel {
                                            Layout.fillWidth: true
                                            text: bindingsTabRoot.selectedRowObj ? ("지금 연결: " + bindingsTabRoot.selectedRowObj.shortcut_detail + "  ·  " + bindingsTabRoot.selectedRowObj.section) : ""
                                            font.pixelSize: 12
                                            color: "#0369A1"
                                            font.bold: true
                                            wrapMode: Text.Wrap
                                        }
                                        TextLabel {
                                            objectName: "bindingDefaultNote"
                                            visible: bindingsTabRoot.selectedRowObj !== null && Boolean(bindingsTabRoot.selectedRowObj.builtin)
                                            Layout.fillWidth: true
                                            text: bindingsTabRoot.selectedRowObj
                                                  ? ("앱 기본 동작 · 기본 명령: " + String(bindingsTabRoot.selectedRowObj.default_badge || "")
                                                     + (bindingsTabRoot.selectedRowObj.changed ? "  ([기본값 복원]으로 되돌려요)" : "")
                                                     + (String(bindingsTabRoot.selectedRowObj.how || "") !== "" ? "\n" + bindingsTabRoot.selectedRowObj.how : ""))
                                                  : ""
                                            font.pixelSize: 12
                                            color: window.muted
                                            wrapMode: Text.Wrap
                                        }
                                        TextLabel {
                                            objectName: "bindingInactiveNote"
                                            visible: bindingsTabRoot.selectedRowObj !== null && !bindingsTabRoot.selectedRowObj.active
                                            Layout.fillWidth: true
                                            text: bindingsTabRoot.selectedRowObj
                                                  ? ("⚠ " + bindingsTabRoot.selectedRowObj.why + "  ·  연결은 저장되지만 지금 손 방식("
                                                     + dashboard.handModeName + ")에서는 실행되지 않습니다") : ""
                                            font.pixelSize: 12
                                            color: "#B45309"
                                            font.bold: true
                                            wrapMode: Text.Wrap
                                        }
                                        // 2026-11-11: switching this gesture off does not stop another one bound to the same command
                                        TextLabel {
                                            objectName: "bindingSameActionElsewhere"
                                            readonly property var others: bindingsTabRoot.selectedRowObj ? (bindingsTabRoot.selectedRowObj.same_action_elsewhere || []) : []
                                            visible: others.length > 0
                                            Layout.fillWidth: true
                                            text: "⚠ 같은 명령이 다른 동작에도 연결돼 있어요: " + others.join(", ")
                                                  + (bindingsTabRoot.editBindingEnabled ? "" : "  ·  이 동작을 꺼도 그 동작으로는 계속 실행됩니다 (왼쪽 목록에서 그 동작을 골라 끄세요)")
                                            font.pixelSize: 12
                                            color: "#B45309"
                                            font.bold: true
                                            wrapMode: Text.Wrap
                                        }

                                        // Action Category Selector
                                        RowLayout {
                                            Layout.fillWidth: true
                                            spacing: 6
                                            TextLabel { text: "실행 유형:"; font.bold: true; font.pixelSize: 12 }
                                            CompactButton {
                                                text: "1. 윈도우 키보드 단축키"
                                                accent: bindingsTabRoot.editActionType === "hotkey"
                                                onClicked: {
                                                    bindingsTabRoot.editActionType = "hotkey"
                                                    if (bindingsTabRoot.editActionValue === "" || bindingsTabRoot.editActionValue === "left_click") {
                                                        bindingsTabRoot.editActionValue = "ctrl+tab"
                                                    }
                                                }
                                            }
                                            CompactButton {
                                                text: "2. 유튜브 · 미디어 전용 키"
                                                accent: bindingsTabRoot.editActionType === "youtube_key"
                                                onClicked: {
                                                    bindingsTabRoot.editActionType = "youtube_key"
                                                    bindingsTabRoot.editActionValue = "k"
                                                }
                                            }
                                            CompactButton {
                                                text: "3. 특정 프로그램 · 웹사이트 실행"
                                                accent: bindingsTabRoot.editActionType === "launch_app"
                                                onClicked: {
                                                    bindingsTabRoot.editActionType = "launch_app"
                                                    bindingsTabRoot.editActionValue = "notepad.exe"
                                                }
                                            }
                                            CompactButton {
                                                text: "4. 기본 마우스 · 시스템 동작"
                                                accent: bindingsTabRoot.editActionType === "mouse_action"
                                                onClicked: {
                                                    bindingsTabRoot.editActionType = "mouse_action"
                                                    bindingsTabRoot.editActionValue = "left_click"
                                                }
                                            }
                                        }

                                        // Preset Picker for Hotkeys: pick a group, then a shortcut of that group
                                        Flow {
                                            visible: bindingsTabRoot.editActionType === "hotkey"
                                            Layout.fillWidth: true
                                            spacing: 5
                                            Repeater {
                                                model: dashboard.hotkeyGroups
                                                delegate: CompactButton {
                                                    required property string modelData
                                                    implicitHeight: 26
                                                    leftPadding: 8; rightPadding: 8
                                                    text: modelData
                                                    primary: bindingsTabRoot.hotkeyGroup === modelData
                                                    onClicked: bindingsTabRoot.hotkeyGroup = modelData
                                                }
                                            }
                                        }
                                        Flow {
                                            visible: bindingsTabRoot.editActionType === "hotkey"
                                            Layout.fillWidth: true
                                            spacing: 5
                                            Repeater {
                                                model: dashboard.hotkeyPresets
                                                delegate: CompactButton {
                                                    required property var modelData
                                                    visible: modelData.group === bindingsTabRoot.hotkeyGroup
                                                    implicitHeight: 26
                                                    leftPadding: 8; rightPadding: 8
                                                    text: modelData.label
                                                    accent: bindingsTabRoot.editActionValue.toLowerCase() === String(modelData.value).toLowerCase()
                                                    onClicked: bindingsTabRoot.editActionValue = modelData.value
                                                }
                                            }
                                        }

                                        // Preset Picker for YouTube Keys
                                        Flow {
                                            visible: bindingsTabRoot.editActionType === "youtube_key"
                                            Layout.fillWidth: true
                                            spacing: 5
                                            Repeater {
                                                model: dashboard.youtubeKeyPresets
                                                delegate: CompactButton {
                                                    required property var modelData
                                                    implicitHeight: 26
                                                    leftPadding: 8; rightPadding: 8
                                                    text: modelData.label
                                                    accent: bindingsTabRoot.editActionValue === modelData.value
                                                    onClicked: bindingsTabRoot.editActionValue = modelData.value
                                                }
                                            }
                                        }

                                        // Preset Picker for Launch App
                                        Flow {
                                            visible: bindingsTabRoot.editActionType === "launch_app"
                                            Layout.fillWidth: true
                                            spacing: 5
                                            Repeater {
                                                model: [
                                                    {"label": "메모장 (notepad)", "value": "notepad.exe"},
                                                    {"label": "계산기 (calc)", "value": "calc.exe"},
                                                    {"label": "파일 탐색기 (explorer)", "value": "explorer.exe"},
                                                    {"label": "크롬 브라우저", "value": "chrome.exe"},
                                                    {"label": "유튜브 열기", "value": "https://www.youtube.com"},
                                                    {"label": "작업 관리자 (taskmgr)", "value": "taskmgr.exe"}
                                                ]
                                                delegate: CompactButton {
                                                    required property var modelData
                                                    implicitHeight: 26
                                                    leftPadding: 8; rightPadding: 8
                                                    text: modelData.label
                                                    accent: bindingsTabRoot.editActionValue === modelData.value
                                                    onClicked: bindingsTabRoot.editActionValue = modelData.value
                                                }
                                            }
                                        }

                                        // Preset Picker for Mouse Actions
                                        Flow {
                                            visible: bindingsTabRoot.editActionType === "mouse_action"
                                            Layout.fillWidth: true
                                            spacing: 5
                                            Repeater {
                                                model: dashboard.mouseActionPresets
                                                delegate: CompactButton {
                                                    required property var modelData
                                                    implicitHeight: 26
                                                    leftPadding: 8; rightPadding: 8
                                                    text: modelData.label
                                                    accent: bindingsTabRoot.editActionValue === modelData.value
                                                    // a command this signal cannot take (a drag on a pointing click ...) is not offered
                                                    enabled: bindingsTabRoot.selectedRowObj === null
                                                             || dashboard.bindingRefusal(bindingsTabRoot.selectedRowObj.key, "mouse_action", modelData.value) === ""
                                                    onClicked: { bindingsTabRoot.editActionValue = modelData.value; bindingsTabRoot.saveNote = "" }
                                                }
                                            }
                                        }

                                        // Direct Value Input + Save/Reset Buttons
                                        RowLayout {
                                            Layout.fillWidth: true
                                            spacing: 8
                                            TextLabel {
                                                text: bindingsTabRoot.editActionType === "launch_app" ? "실행 경로/명령어:" : "단축키/명령 값:"
                                                font.bold: true
                                                font.pixelSize: 12
                                            }
                                            TextField {
                                                id: customBindingField
                                                Layout.fillWidth: true
                                                implicitHeight: 34
                                                text: bindingsTabRoot.editActionValue
                                                placeholderText: bindingsTabRoot.editActionType === "hotkey"
                                                    ? "예: ctrl+shift+t, alt+left, win+d, space"
                                                    : (bindingsTabRoot.editActionType === "launch_app" ? "예: C:\\Program Files\\...\\app.exe 또는 calc.exe" : "명령 값 입력")
                                                font.pixelSize: 13
                                                onTextEdited: bindingsTabRoot.editActionValue = text
                                            }
                                            CompactButton {
                                                text: "저장"
                                                primary: true
                                                implicitHeight: 34
                                                leftPadding: 14; rightPadding: 14
                                                enabled: bindingsTabRoot.refusal === ""
                                                onClicked: {
                                                    if (bindingsTabRoot.selectedRowObj) {
                                                        var ok = dashboard.saveGestureBinding(
                                                            bindingsTabRoot.selectedRowObj.key,
                                                            bindingsTabRoot.editActionType,
                                                            bindingsTabRoot.editActionValue,
                                                            bindingsTabRoot.editBindingEnabled
                                                        )
                                                        bindingsTabRoot.saveFailed = !ok
                                                        bindingsTabRoot.saveNote = ok ? "저장했어요." : ("저장하지 못했어요: " + dashboard.trainingNote.replace("매핑 저장 실패: ", ""))
                                                    }
                                                }
                                            }
                                            CompactButton {
                                                text: "기본값 복원"
                                                visible: bindingsTabRoot.selectedRowObj !== null && Boolean(bindingsTabRoot.selectedRowObj.can_reset)
                                                implicitHeight: 34
                                                onClicked: {
                                                    if (bindingsTabRoot.selectedRowObj) {
                                                        dashboard.resetGestureBinding(bindingsTabRoot.selectedRowObj.key)
                                                        bindingsTabRoot.editKey = ""         // show the restored command on the right too
                                                        bindingsTabRoot.saveNote = "기본값으로 되돌렸어요."
                                                        bindingsTabRoot.saveFailed = false
                                                    }
                                                }
                                            }
                                        }
                                        TextLabel {
                                            objectName: "bindingSaveNote"
                                            readonly property string say: bindingsTabRoot.refusal !== "" ? ("이 명령은 연결할 수 없어요: " + bindingsTabRoot.refusal)
                                                : bindingsTabRoot.saveNote !== "" ? bindingsTabRoot.saveNote
                                                : bindingsTabRoot.unsaved ? "바꾼 내용이 아직 저장되지 않았어요. [저장]을 눌러야 왼쪽 목록에 반영돼요." : ""
                                            visible: say !== ""
                                            Layout.fillWidth: true
                                            text: say
                                            font.pixelSize: 12
                                            font.bold: true
                                            color: (bindingsTabRoot.refusal !== "" || bindingsTabRoot.saveFailed) ? "#B91C1C"
                                                   : (bindingsTabRoot.saveNote !== "" ? "#0F6E5B" : "#B45309")
                                            wrapMode: Text.Wrap
                                        }
                                    }
                                }

                                // Foreground Program-Specific Override Section
                                Rectangle {
                                    visible: bindingsTabRoot.selEditable
                                    Layout.fillWidth: true
                                    implicitHeight: appOvrCol.implicitHeight + 20
                                    radius: 10
                                    color: "#F5F3FF"
                                    border.color: "#C4B5FD"
                                    ColumnLayout {
                                        id: appOvrCol
                                        anchors.fill: parent
                                        anchors.margins: 10
                                        spacing: 8
                                        TextLabel {
                                            text: "전면 실행 중인 프로그램별 전용 단축키 지정 (Foreground App Override)"
                                            font.bold: true
                                            font.pixelSize: 14
                                            color: "#4C1D95"
                                        }
                                        TextLabel {
                                            Layout.fillWidth: true
                                            text: "특정 프로그램(예: YouTube, chrome.exe, premiere, vlc.exe, powerpnt.exe)이 화면 맨 앞에 켜져 있을 때만 이 손동작을 해당 프로그램 전용 단축키로 자동 전환합니다."
                                            font.pixelSize: 12
                                            color: window.muted
                                            wrapMode: Text.Wrap
                                        }

                                        Flow {
                                            Layout.fillWidth: true
                                            spacing: 5
                                            TextLabel { text: "자주 쓰는 대상 앱:"; font.pixelSize: 12; font.bold: true; color: "#4C1D95" }
                                            Repeater {
                                                model: [
                                                    {"label": "YouTube (창 제목)", "match": "youtube"},
                                                    {"label": "크롬 (chrome.exe)", "match": "chrome.exe"},
                                                    {"label": "엣지 (msedge.exe)", "match": "msedge.exe"},
                                                    {"label": "팟플레이어/VLC", "match": "vlc.exe"},
                                                    {"label": "파워포인트 (powerpnt.exe)", "match": "powerpnt.exe"},
                                                    {"label": "프리미어 (premiere)", "match": "premiere"}
                                                ]
                                                delegate: CompactButton {
                                                    required property var modelData
                                                    implicitHeight: 24
                                                    leftPadding: 7; rightPadding: 7
                                                    text: modelData.label
                                                    accent: bindingsTabRoot.appMatchInput === modelData.match
                                                    onClicked: bindingsTabRoot.appMatchInput = modelData.match
                                                }
                                            }
                                        }

                                        RowLayout {
                                            Layout.fillWidth: true
                                            spacing: 6
                                            TextField {
                                                Layout.preferredWidth: 160
                                                implicitHeight: 32
                                                placeholderText: "대상 앱 (예: youtube, chrome.exe)"
                                                text: bindingsTabRoot.appMatchInput
                                                font.pixelSize: 12
                                                onTextEdited: bindingsTabRoot.appMatchInput = text
                                            }
                                            CompactButton {
                                                text: "유튜브키"
                                                implicitHeight: 30
                                                accent: bindingsTabRoot.appActionTypeInput === "youtube_key"
                                                onClicked: {
                                                    bindingsTabRoot.appActionTypeInput = "youtube_key"
                                                    bindingsTabRoot.appActionValueInput = "k"
                                                }
                                            }
                                            CompactButton {
                                                text: "단축키"
                                                implicitHeight: 30
                                                accent: bindingsTabRoot.appActionTypeInput === "hotkey"
                                                onClicked: {
                                                    bindingsTabRoot.appActionTypeInput = "hotkey"
                                                    bindingsTabRoot.appActionValueInput = "space"
                                                }
                                            }
                                            TextField {
                                                Layout.fillWidth: true
                                                implicitHeight: 32
                                                placeholderText: "실행할 단축키 또는 유튜브 키 (예: k, j, l, f, ctrl+w)"
                                                text: bindingsTabRoot.appActionValueInput
                                                font.pixelSize: 12
                                                onTextEdited: bindingsTabRoot.appActionValueInput = text
                                            }
                                            CompactButton {
                                                text: "앱 전용 단축키 추가"
                                                primary: true
                                                implicitHeight: 32
                                                onClicked: {
                                                    if (bindingsTabRoot.selectedRowObj && bindingsTabRoot.appMatchInput.trim() !== "") {
                                                        dashboard.addAppOverrideSlot(
                                                            bindingsTabRoot.selectedRowObj.key,
                                                            bindingsTabRoot.appMatchInput,
                                                            bindingsTabRoot.appActionTypeInput,
                                                            bindingsTabRoot.appActionValueInput
                                                        )
                                                    }
                                                }
                                            }
                                        }

                                        Repeater {
                                            model: bindingsTabRoot.selectedRowObj ? (bindingsTabRoot.selectedRowObj.app_overrides || []) : []
                                            delegate: Rectangle {
                                                required property var modelData
                                                Layout.fillWidth: true
                                                implicitHeight: 32
                                                radius: 6
                                                color: "white"
                                                border.color: "#DDD6FE"
                                                RowLayout {
                                                    anchors.fill: parent
                                                    anchors.leftMargin: 8; anchors.rightMargin: 8
                                                    spacing: 8
                                                    TextLabel {
                                                        text: "전면 앱 [" + modelData.app_match + "] 활성 시  →  " + String(modelData.badge || modelData.action_value)
                                                        font.pixelSize: 12
                                                        font.bold: true
                                                        color: "#4C1D95"
                                                        Layout.fillWidth: true
                                                    }
                                                    CompactButton {
                                                        text: "삭제"
                                                        danger: true
                                                        implicitHeight: 24
                                                        onClicked: {
                                                            if (bindingsTabRoot.selectedRowObj) {
                                                                dashboard.removeAppOverrideSlot(bindingsTabRoot.selectedRowObj.key, modelData.app_match)
                                                            }
                                                        }
                                                    }
                                                }
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    }

                    // =========================================================================
                    // SUB-TAB 2: DEDICATED TIME-SERIES MOTION LEARNING & NEW MOTION REGISTRATION
                    // =========================================================================
                    ScrollView {
                        id: motionsSubScroll
                        visible: trainingCenter.bindingsSubTab === "motions"
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        clip: true
                        contentWidth: availableWidth
                        ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
                        ColumnLayout {
                            width: Math.max(240, motionsSubScroll.availableWidth - 16)
                            spacing: 10

                            // Architectural Explanation & Batch Motion Trajectory Training Banner
                            Rectangle {
                                Layout.fillWidth: true
                                implicitHeight: motionArchCol.implicitHeight + 18
                                radius: 10
                                color: "#EDE9FE"
                                border.color: "#C4B5FD"
                                ColumnLayout {
                                    id: motionArchCol
                                    anchors.fill: parent
                                    anchors.margins: 9
                                    spacing: 4
                                    RowLayout {
                                        Layout.fillWidth: true
                                        spacing: 8
                                        TextLabel {
                                            text: "시계열 모션 동작 전용 학습 시스템 (정지 동작 96D 공간 MLP와 분리된 16-Step 궤적·속도 프로파일 학습)"
                                            font.bold: true
                                            font.pixelSize: 14
                                            color: "#4C1D95"
                                        }
                                        Item { Layout.fillWidth: true }
                                        CompactButton {
                                            text: "전체 시계열 모션 궤적 일괄 학습"
                                            primary: true
                                            implicitHeight: 32
                                            enabled: !dashboard.trainingRunning && dashboard.trainingBusy === ""
                                            onClicked: dashboard.trainMotionTemplatesSlot("")
                                        }
                                    }
                                    TextLabel {
                                        Layout.fillWidth: true
                                        text: "• 정지 동작(좌클릭·우클릭·핀치)은 단일 프레임 손 모양(96D Spatial MLP)으로 판정하지만, 앞으로·뒤로·이전탭·다음탭 같은 시계열 모션은 [시작 → 가속 피크 → 감속 → 원위치 복귀]의 시간축 흐름을 가집니다.\n• 시계열 모션 전용 학습기는 녹화 데이터에서 16단계 정규화 위치 궤적(dx, dy), 속도 엔벨로프(vx, vy), 진행 방향 일관성을 추출해 전용 템플릿으로 학습하며, 손이 제자리로 돌아오는 역방향 복귀 구간(Return Stroke) 오발화를 자동 차단합니다."
                                        font.pixelSize: 12
                                        color: "#4C1D95"
                                        wrapMode: Text.Wrap
                                    }
                                }
                            }

                            // New Temporal Motion Gesture Registration Form
                            Rectangle {
                                Layout.fillWidth: true
                                implicitHeight: newMotionCol.implicitHeight + 18
                                radius: 10
                                color: "#F7FAFB"
                                border.color: window.line
                                ColumnLayout {
                                    id: newMotionCol
                                    anchors.fill: parent
                                    anchors.margins: 9
                                    spacing: 6
                                    TextLabel {
                                        text: "추천 레시피 (고르면 아래 칸이 채워져요 · 필요하면 고쳐서 등록하세요)"
                                        font.pixelSize: 12
                                        color: window.muted
                                    }
                                    Flow {
                                        Layout.fillWidth: true
                                        spacing: 5
                                        Repeater {
                                            model: dashboard.recipeGroups
                                            delegate: CompactButton {
                                                required property string modelData
                                                implicitHeight: 26
                                                leftPadding: 8; rightPadding: 8
                                                text: modelData
                                                primary: bindingsTabRoot.motionRecipeGroup === modelData
                                                onClicked: bindingsTabRoot.motionRecipeGroup = modelData
                                            }
                                        }
                                    }
                                    Flow {
                                        Layout.fillWidth: true
                                        spacing: 5
                                        Repeater {
                                            model: dashboard.motionRecipes
                                            delegate: CompactButton {
                                                required property var modelData
                                                visible: modelData.group === bindingsTabRoot.motionRecipeGroup
                                                implicitHeight: 26
                                                leftPadding: 8; rightPadding: 8
                                                text: modelData.name + (modelData.note !== "" ? " ⚠" : "")
                                                onClicked: {
                                                    bindingsTabRoot.newMotionName = modelData.name
                                                    bindingsTabRoot.newMotionKey = ""
                                                    bindingsTabRoot.newMotionPosture = modelData.posture
                                                    bindingsTabRoot.newMotionDir = modelData.direction
                                                    bindingsTabRoot.newMotionActType = modelData.action_type
                                                    bindingsTabRoot.newMotionActVal = modelData.action_value
                                                    bindingsTabRoot.recipeNote = modelData.note
                                                }
                                            }
                                        }
                                    }
                                    TextLabel {
                                        Layout.fillWidth: true
                                        visible: bindingsTabRoot.recipeNote !== ""
                                        text: "⚠ " + bindingsTabRoot.recipeNote
                                        font.pixelSize: 12
                                        color: "#B45309"
                                        wrapMode: Text.Wrap
                                    }
                                    TextLabel {
                                        text: "새 시계열 모션 동작 등록 (등록 즉시 녹화 마법사 · 시계열 궤적 학습 · 단축키 매핑에 추가됨)"
                                        font.bold: true
                                        font.pixelSize: 13
                                    }
                                    RowLayout {
                                        Layout.fillWidth: true
                                        spacing: 8
                                        FormLabel { text: "이름" }
                                        TextField {
                                            Layout.fillWidth: true
                                            Layout.preferredWidth: 3
                                            implicitHeight: 32
                                            placeholderText: "새 모션 이름 (비우면 손 모양 · 방향으로 자동)"
                                            text: bindingsTabRoot.newMotionName
                                            font.pixelSize: 13
                                            onTextEdited: bindingsTabRoot.newMotionName = text
                                        }
                                        TextField {
                                            Layout.fillWidth: true
                                            Layout.preferredWidth: 2
                                            implicitHeight: 32
                                            placeholderText: "모션 키 (선택, 예: swipe_up_tab)"
                                            text: bindingsTabRoot.newMotionKey
                                            font.pixelSize: 13
                                            onTextEdited: bindingsTabRoot.newMotionKey = text
                                        }
                                    }
                                    RowLayout {
                                        Layout.fillWidth: true
                                        spacing: 8
                                        FormLabel { text: "손 모양" }
                                        Flow {
                                            Layout.fillWidth: true
                                            spacing: 5
                                            Repeater {
                                                model: dashboard.posturePresets
                                                delegate: CompactButton {
                                                    required property var modelData
                                                    text: modelData.label
                                                    accent: bindingsTabRoot.newMotionPosture === modelData.value
                                                    onClicked: bindingsTabRoot.newMotionPosture = modelData.value
                                                }
                                            }
                                        }
                                    }
                                    RowLayout {
                                        Layout.fillWidth: true
                                        spacing: 8
                                        FormLabel { text: "이동 방향" }
                                        Flow {
                                            Layout.fillWidth: true
                                            spacing: 5
                                            Repeater {
                                                model: dashboard.directionPresets
                                                delegate: CompactButton {
                                                    required property var modelData
                                                    text: modelData.label
                                                    accent: bindingsTabRoot.newMotionDir === modelData.value
                                                    onClicked: bindingsTabRoot.newMotionDir = modelData.value
                                                }
                                            }
                                        }
                                    }
                                    RowLayout {
                                        Layout.fillWidth: true
                                        spacing: 8
                                        FormLabel { text: "실행할 동작" }
                                        CompactButton {
                                            text: "단축키"
                                            accent: bindingsTabRoot.newMotionActType === "hotkey"
                                            onClicked: bindingsTabRoot.newMotionActType = "hotkey"
                                        }
                                        CompactButton {
                                            text: "유튜브 키"
                                            accent: bindingsTabRoot.newMotionActType === "youtube_key"
                                            onClicked: bindingsTabRoot.newMotionActType = "youtube_key"
                                        }
                                        CompactButton {
                                            text: "앱 실행"
                                            accent: bindingsTabRoot.newMotionActType === "launch_app"
                                            onClicked: bindingsTabRoot.newMotionActType = "launch_app"
                                        }
                                        TextField {
                                            Layout.fillWidth: true
                                            Layout.minimumWidth: 120
                                            implicitHeight: 32
                                            placeholderText: "단축키/유튜브키/실행경로 (예: ctrl+t, k, calc.exe)"
                                            text: bindingsTabRoot.newMotionActVal
                                            font.pixelSize: 13
                                            onTextEdited: bindingsTabRoot.newMotionActVal = text
                                        }
                                        CompactButton {
                                            text: "+ 새 모션 등록"
                                            primary: true
                                            implicitHeight: 32
                                            enabled: bindingsTabRoot.newMotionActVal.trim() !== ""
                                            onClicked: {
                                                if (dashboard.registerMotionGestureSlot(
                                                    bindingsTabRoot.newMotionKey,
                                                    bindingsTabRoot.newMotionName,
                                                    bindingsTabRoot.newMotionPosture,
                                                    bindingsTabRoot.newMotionDir,
                                                    bindingsTabRoot.newMotionActType,
                                                    bindingsTabRoot.newMotionActVal,
                                                    0.14,
                                                    0.25
                                                )) {
                                                    bindingsTabRoot.newMotionName = ""
                                                    bindingsTabRoot.newMotionKey = ""
                                                }
                                            }
                                        }
                                    }
                                }
                            }

                            // Dedicated List of Temporal Motion Gestures
                            Repeater {
                                model: dashboard.motionTrackRows
                                delegate: Rectangle {
                                    id: mRow
                                    required property var modelData
                                    Layout.fillWidth: true
                                    implicitHeight: mRowCol.implicitHeight + 16
                                    radius: 10
                                    color: "white"
                                    border.color: mRow.modelData.has_motion_template ? "#8B5CF6" : window.line
                                    ColumnLayout {
                                        id: mRowCol
                                        anchors.fill: parent
                                        anchors.margins: 8
                                        spacing: 4
                                        RowLayout {
                                            Layout.fillWidth: true
                                            spacing: 8
                                            Rectangle {
                                                radius: 4
                                                color: "#EDE9FE"
                                                border.color: "#C4B5FD"
                                                implicitWidth: mBadgeLbl.implicitWidth + 10
                                                implicitHeight: 20
                                                TextLabel {
                                                    id: mBadgeLbl
                                                    anchors.centerIn: parent
                                                    text: mRow.modelData.is_custom_motion ? "사용자 시계열 모션" : "기본 시계열 모션"
                                                    font.pixelSize: 11
                                                    font.bold: true
                                                    color: "#5B21B6"
                                                }
                                            }
                                            TextLabel {
                                                text: mRow.modelData.name
                                                font.bold: true
                                                font.pixelSize: 14
                                            }
                                            Rectangle {
                                                radius: 5
                                                color: "#F0F9FF"
                                                border.color: "#7DD3FC"
                                                implicitWidth: mScTxt.implicitWidth + 10
                                                implicitHeight: 20
                                                TextLabel {
                                                    id: mScTxt
                                                    anchors.centerIn: parent
                                                    text: {
                                                        var sb = String(mRow.modelData.shortcut_badge || "")
                                                        return sb.indexOf("단축키:") === 0 ? sb : ("매핑: " + sb)
                                                    }
                                                    font.pixelSize: 12
                                                    font.bold: true
                                                    color: "#0369A1"
                                                }
                                            }
                                            TextLabel {
                                                text: mRow.modelData.instruction
                                                font.pixelSize: 12
                                                color: window.muted
                                                elide: Text.ElideRight
                                                Layout.fillWidth: true
                                            }
                                            CompactButton {
                                                text: "1. 이 모션 집중 녹화"
                                                implicitHeight: 30
                                                enabled: !dashboard.trainingRunning && dashboard.recMode === "off"
                                                onClicked: {
                                                    if (dashboard.focusRecord(mRow.modelData.key)) {
                                                        trainingCenter.close()
                                                        capturePlan.open()
                                                    }
                                                }
                                            }
                                            CompactButton {
                                                text: "2. 시계열 궤적·속도 학습"
                                                primary: true
                                                implicitHeight: 30
                                                enabled: !dashboard.trainingRunning && dashboard.trainingBusy === ""
                                                onClicked: dashboard.trainMotionTemplatesSlot(mRow.modelData.key)
                                            }
                                            CompactButton {
                                                text: "단축키 변경"
                                                implicitHeight: 30
                                                onClicked: {
                                                    trainingCenter.selectedBindingKey = mRow.modelData.key
                                                    trainingCenter.bindingsSubTab = "shortcuts"
                                                }
                                            }
                                            CompactButton {
                                                visible: Boolean(mRow.modelData.is_custom_motion)
                                                text: "삭제"
                                                danger: true
                                                implicitHeight: 30
                                                onClicked: {
                                                    var k = mRow.modelData.key
                                                    confirmDialog.ask("모션 삭제", "'" + mRow.modelData.name + "' 모션과 단축키 매핑을 지웁니다.", "삭제", function () { dashboard.deleteMotionGestureSlot(k) })
                                                }
                                            }
                                        }
                                        RowLayout {
                                            Layout.fillWidth: true
                                            spacing: 12
                                            TextLabel {
                                                text: "녹화 데이터: " + mRow.modelData.data_text
                                                font.pixelSize: 12
                                                font.bold: true
                                            }
                                            TextLabel {
                                                text: mRow.modelData.motion_metrics_text !== ""
                                                    ? ("시계열 학습 결과: " + mRow.modelData.motion_metrics_text)
                                                    : "시계열 궤적 템플릿 미학습 (모션 녹화 후 [시계열 궤적·속도 학습]을 누르세요)"
                                                font.pixelSize: 12
                                                font.bold: mRow.modelData.motion_metrics_text !== ""
                                                color: mRow.modelData.motion_metrics_text !== "" ? "#4C1D95" : window.muted
                                                Layout.fillWidth: true
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    }

                    // =========================================================================
                    // SUB-TAB 3: COMPOSITE HAND GESTURE MECHANISMS (Pinch+Swipe / Hold / Double-Pinch)
                    // =========================================================================
                    ScrollView {
                        id: compositesSubScroll
                        visible: trainingCenter.bindingsSubTab === "composites"
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        clip: true
                        contentWidth: availableWidth
                        ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
                        ColumnLayout {
                            width: Math.max(240, compositesSubScroll.availableWidth - 16)
                            spacing: 10

                            Rectangle {
                                Layout.fillWidth: true
                                implicitHeight: compBannerCol.implicitHeight + 16
                                radius: 10
                                color: "#FFFBEB"
                                border.color: "#FCD34D"
                                ColumnLayout {
                                    id: compBannerCol
                                    anchors.fill: parent
                                    anchors.margins: 8
                                    spacing: 4
                                    TextLabel {
                                        text: "복합 손동작 메커니즘 (기본 손 모양/핀치 + 이동·유지·연속 핀치 결합)"
                                        font.bold: true
                                        font.pixelSize: 14
                                        color: "#92400E"
                                    }
                                    TextLabel {
                                        Layout.fillWidth: true
                                        text: "별도의 모션 모드 진입 없이도 일반 제어 상태에서 [특정 손가락 핀치 유지 + 상하좌우 스와이프], [핀치 길게 누르기], [더블 핀치]를 조합해 유튜브 제어, 탭 전환, 프로그램 실행 등 원하는 단축키를 즉시 실행합니다."
                                        font.pixelSize: 12
                                        color: "#92400E"
                                        wrapMode: Text.Wrap
                                    }
                                }
                            }

                            // Register New Composite Gesture
                            Rectangle {
                                Layout.fillWidth: true
                                implicitHeight: newCompCol.implicitHeight + 18
                                radius: 10
                                color: "#F7FAFB"
                                border.color: window.line
                                ColumnLayout {
                                    id: newCompCol
                                    anchors.fill: parent
                                    anchors.margins: 9
                                    spacing: 6
                                    TextLabel {
                                        text: "새 복합 손동작 추가"
                                        font.bold: true
                                        font.pixelSize: 13
                                    }
                                    TextLabel {
                                        text: "추천 레시피 (고르면 아래 칸이 채워져요)"
                                        font.pixelSize: 12
                                        color: window.muted
                                    }
                                    Flow {
                                        Layout.fillWidth: true
                                        spacing: 5
                                        Repeater {
                                            model: dashboard.compositeRecipes
                                            delegate: CompactButton {
                                                required property var modelData
                                                implicitHeight: 26
                                                leftPadding: 8; rightPadding: 8
                                                text: modelData.name
                                                onClicked: {
                                                    bindingsTabRoot.newCompName = modelData.name
                                                    bindingsTabRoot.newCompPosture = modelData.posture
                                                    bindingsTabRoot.newCompTrigger = modelData.trigger
                                                    bindingsTabRoot.newCompActType = modelData.action_type
                                                    bindingsTabRoot.newCompActVal = modelData.action_value
                                                }
                                            }
                                        }
                                    }
                                    RowLayout {
                                        Layout.fillWidth: true
                                        spacing: 8
                                        FormLabel { text: "이름" }
                                        TextField {
                                            Layout.fillWidth: true
                                            implicitHeight: 32
                                            placeholderText: "복합 동작 이름 (비우면 자세 + 트리거로 자동)"
                                            text: bindingsTabRoot.newCompName
                                            font.pixelSize: 13
                                            onTextEdited: bindingsTabRoot.newCompName = text
                                        }
                                    }
                                    RowLayout {
                                        Layout.fillWidth: true
                                        spacing: 8
                                        FormLabel { text: "기반 자세" }
                                        Flow {
                                            Layout.fillWidth: true
                                            spacing: 5
                                            Repeater {
                                                model: dashboard.compositePosturePresets
                                                delegate: CompactButton {
                                                    required property var modelData
                                                    text: modelData.label
                                                    accent: bindingsTabRoot.newCompPosture === modelData.value
                                                    onClicked: bindingsTabRoot.newCompPosture = modelData.value
                                                }
                                            }
                                        }
                                    }
                                    RowLayout {
                                        Layout.fillWidth: true
                                        spacing: 8
                                        FormLabel { text: "결합 트리거" }
                                        Flow {
                                            Layout.fillWidth: true
                                            spacing: 5
                                            Repeater {
                                                model: dashboard.compositeTriggerPresets
                                                delegate: CompactButton {
                                                    required property var modelData
                                                    text: modelData.label
                                                    accent: bindingsTabRoot.newCompTrigger === modelData.value
                                                    onClicked: bindingsTabRoot.newCompTrigger = modelData.value
                                                }
                                            }
                                        }
                                    }
                                    RowLayout {
                                        Layout.fillWidth: true
                                        spacing: 8
                                        FormLabel { text: "실행할 동작" }
                                        CompactButton {
                                            text: "단축키"
                                            accent: bindingsTabRoot.newCompActType === "hotkey"
                                            onClicked: {
                                                bindingsTabRoot.newCompActType = "hotkey"
                                                bindingsTabRoot.newCompActVal = "ctrl+tab"
                                            }
                                        }
                                        CompactButton {
                                            text: "유튜브 기능키"
                                            accent: bindingsTabRoot.newCompActType === "youtube_key"
                                            onClicked: {
                                                bindingsTabRoot.newCompActType = "youtube_key"
                                                bindingsTabRoot.newCompActVal = "f"
                                            }
                                        }
                                        CompactButton {
                                            text: "프로그램 실행"
                                            accent: bindingsTabRoot.newCompActType === "launch_app"
                                            onClicked: {
                                                bindingsTabRoot.newCompActType = "launch_app"
                                                bindingsTabRoot.newCompActVal = "calc.exe"
                                            }
                                        }
                                        TextField {
                                            Layout.fillWidth: true
                                            Layout.minimumWidth: 120
                                            implicitHeight: 32
                                            placeholderText: "단축키 / 유튜브키(k,j,l,f,m) / 프로그램 경로"
                                            text: bindingsTabRoot.newCompActVal
                                            font.pixelSize: 13
                                            onTextEdited: bindingsTabRoot.newCompActVal = text
                                        }
                                        CompactButton {
                                            text: "+ 복합 손동작 등록"
                                            primary: true
                                            implicitHeight: 32
                                            enabled: bindingsTabRoot.newCompActVal.trim() !== ""
                                            onClicked: {
                                                if (dashboard.registerCompositeGestureSlot(
                                                    bindingsTabRoot.newCompName,
                                                    bindingsTabRoot.newCompPosture,
                                                    bindingsTabRoot.newCompTrigger,
                                                    bindingsTabRoot.newCompActType,
                                                    bindingsTabRoot.newCompActVal,
                                                    0.08,
                                                    0.55
                                                )) {
                                                    bindingsTabRoot.newCompName = ""
                                                }
                                            }
                                        }
                                    }
                                }
                            }

                            // Active Composite Gestures List
                            Repeater {
                                model: dashboard.compositeGestureRows
                                delegate: Rectangle {
                                    id: cRow
                                    required property var modelData
                                    Layout.fillWidth: true
                                    implicitHeight: 46
                                    radius: 8
                                    color: "white"
                                    border.color: window.line
                                    RowLayout {
                                        anchors.fill: parent
                                        anchors.leftMargin: 10; anchors.rightMargin: 10
                                        spacing: 8
                                        Rectangle {
                                            radius: 4
                                            color: "#FEF3C7"
                                            border.color: "#FCD34D"
                                            implicitWidth: cTagTxt.implicitWidth + 8
                                            implicitHeight: 20
                                            TextLabel {
                                                id: cTagTxt
                                                anchors.centerIn: parent
                                                text: "복합 손동작"
                                                font.pixelSize: 11
                                                font.bold: true
                                                color: "#92400E"
                                            }
                                        }
                                        TextLabel {
                                            text: cRow.modelData.name
                                            font.bold: true
                                            font.pixelSize: 13
                                        }
                                        TextLabel {
                                            text: "[" + cRow.modelData.base_posture_ko + "  +  " + cRow.modelData.trigger_type_ko + "]"
                                            font.pixelSize: 12
                                            color: window.muted
                                        }
                                        TextLabel {
                                            text: "→  " + cRow.modelData.detail
                                            font.pixelSize: 12
                                            font.bold: true
                                            color: "#0369A1"
                                            Layout.fillWidth: true
                                            elide: Text.ElideRight
                                        }
                                        CompactButton {
                                            text: cRow.modelData.enabled ? "활성" : "꺼짐"
                                            accent: cRow.modelData.enabled
                                            implicitHeight: 28
                                            onClicked: dashboard.saveGestureBinding(
                                                cRow.modelData.key,
                                                cRow.modelData.action_type,
                                                cRow.modelData.action_value,
                                                !cRow.modelData.enabled
                                            )
                                        }
                                        CompactButton {
                                            text: "삭제"
                                            danger: true
                                            implicitHeight: 28
                                            onClicked: {
                                                var k = cRow.modelData.key
                                                confirmDialog.ask("복합 손동작 삭제", "'" + cRow.modelData.name + "' 복합 손동작을 지웁니다.", "삭제", function () { dashboard.deleteCompositeGestureSlot(k) })
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }
            Rectangle { Layout.fillWidth: true; height: 1; color: window.line }
            RowLayout {
                Layout.fillWidth: true
                spacing: 6
                TextLabel {
                    text: "학습 모드"
                    font.bold: true
                    font.pixelSize: 12
                }
                CompactButton {
                    implicitHeight: 28
                    leftPadding: 9; rightPadding: 9
                    text: "빠른 학습(권장) · 2회"
                    accent: dashboard.trainingMode === "fast"
                    enabled: !dashboard.trainingRunning && dashboard.trainingBusy === ""
                    onClicked: dashboard.setTrainingMode("fast")
                }
                CompactButton {
                    implicitHeight: 28
                    leftPadding: 9; rightPadding: 9
                    text: "정밀 학습(전체 폴드) · " + dashboard.thoroughRunCount + "회"
                    accent: dashboard.trainingMode === "thorough"
                    enabled: !dashboard.trainingRunning && dashboard.trainingBusy === ""
                    onClicked: dashboard.setTrainingMode("thorough")
                }
                Rectangle { width: 1; height: 16; color: window.line }
                TextLabel {
                    text: "연산 장치"
                    font.bold: true
                    font.pixelSize: 12
                }
                CompactButton {
                    implicitHeight: 28
                    leftPadding: 9; rightPadding: 9
                    text: dashboard.gpuButtonLabel
                    accent: dashboard.gpuAvailable && dashboard.trainingDevice === "gpu"
                    enabled: dashboard.gpuAvailable && !dashboard.trainingRunning && dashboard.trainingBusy === ""
                    onClicked: dashboard.setTrainingDevice("gpu")
                }
                CompactButton {
                    implicitHeight: 28
                    leftPadding: 9; rightPadding: 9
                    text: "CPU 학습"
                    accent: !dashboard.gpuAvailable || dashboard.trainingDevice === "cpu"
                    enabled: !dashboard.trainingRunning && dashboard.trainingBusy === ""
                    onClicked: dashboard.setTrainingDevice("cpu")
                }
                CompactButton {
                    visible: dashboard.canInstallCudaTorch
                    implicitHeight: 28
                    leftPadding: 9; rightPadding: 9
                    text: "GPU 가속 설치"
                    accent: true
                    enabled: !dashboard.trainingRunning && dashboard.trainingBusy === ""
                    onClicked: dashboard.enableGpuAcceleration()
                }
                TextLabel {
                    Layout.fillWidth: true
                    Layout.minimumWidth: 0
                    elide: Text.ElideRight
                    text: dashboard.gpuStatusText + "  ·  " + dashboard.trainingModeRunsText
                    font.pixelSize: 12
                    color: dashboard.gpuAvailable ? "#1B7F5A" : window.muted
                }
            }
            RowLayout {
                Layout.fillWidth: true
                spacing: 8
                TextLabel {
                    Layout.fillWidth: true
                    Layout.minimumWidth: 0
                    elide: Text.ElideRight
                    text: dashboard.trainingMode === "thorough"
                        ? "전체 통합 학습 시: 전체 자세 교차평가 후 최종 통합 모델을 생성합니다"
                        : "전체 통합 학습 시: 대표 자세 빠른 평가 후 최종 통합 모델을 생성합니다 (권장)"
                    font.pixelSize: 12
                    color: window.muted
                }
                ActionButton {
                    implicitHeight: 34
                    text: "전체 통합 학습 (" + (dashboard.trainingDevice === "gpu" ? "GPU" : "CPU") + ")"
                    leftPadding: 13; rightPadding: 13
                    primary: true
                    enabled: !dashboard.trainingRunning && dashboard.trainingBusy === "" && !dashboard.recActive
                    onClicked: dashboard.startTraining()
                }
                ActionButton {
                    implicitHeight: 34
                    text: "내보내기"
                    leftPadding: 13; rightPadding: 13
                    enabled: !dashboard.trainingRunning && dashboard.trainingBusy === ""
                    onClicked: dashboard.exportModel()
                }
                ActionButton {
                    implicitHeight: 34
                    text: "허브 설정 · 동기화"
                    leftPadding: 13; rightPadding: 13
                    accent: hubSyncDialog.visible
                    enabled: !dashboard.trainingRunning && dashboard.trainingBusy === "" && !dashboard.recActive
                    onClicked: hubSyncDialog.openWithMode("sync")
                }
                ActionButton {
                    implicitHeight: 34
                    text: "허브 업로드"
                    leftPadding: 13; rightPadding: 13
                    enabled: !dashboard.trainingRunning && dashboard.trainingBusy === "" && !dashboard.recActive
                    onClicked: {
                        if (!dashboard.hubHasToken || dashboard.hubRepo === "") {
                            hubSyncDialog.openWithMode("push")
                        } else {
                            dashboard.pushToHub()
                        }
                    }
                }
                ActionButton {
                    implicitHeight: 34
                    text: "허브 받기"
                    leftPadding: 13; rightPadding: 13
                    enabled: !dashboard.trainingRunning && dashboard.trainingBusy === "" && !dashboard.recActive
                    onClicked: {
                        if (dashboard.hubRepo === "") {
                            hubSyncDialog.openWithMode("pull")
                        } else {
                            dashboard.pullFromHub()
                        }
                    }
                }
                ActionButton { implicitHeight: 34; text: "폴더 열기"; leftPadding: 13; rightPadding: 13; onClicked: dashboard.openExports() }
            }
            }
        }
    }

    Popup {
        id: hubSyncDialog
        property string selectedProvider: dashboard.hubProvider
        property bool showTokenPlain: false
        property bool includeModels: dashboard.hubIncludeModels
        property string modeHint: "sync"

        function openWithMode(mode) {
            selectedProvider = dashboard.hubProvider
            repoField.text = dashboard.hubRepo
            branchField.text = dashboard.hubBranch
            tokenField.text = ""
            showTokenPlain = false
            includeModels = dashboard.hubIncludeModels
            modeHint = mode || "sync"
            hubSyncDialog.open()
        }

        anchors.centerIn: parent
        width: Math.min(760, window.width - 40)
        modal: true
        focus: true
        closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside
        padding: 20
        background: Rectangle {
            radius: 16
            color: "white"
            border.color: window.line
            border.width: 1
        }
        contentItem: ColumnLayout {
            width: hubSyncDialog.availableWidth
            spacing: 10

            RowLayout {
                Layout.fillWidth: true
                spacing: 10
                ColumnLayout {
                    Layout.fillWidth: true
                    Layout.minimumWidth: 0
                    spacing: 2
                    TextLabel {
                        Layout.fillWidth: true
                        Layout.minimumWidth: 0
                        elide: Text.ElideRight
                        text: "원격 데이터·모델 허브 설정 및 동기화"
                        font.pixelSize: 19
                        font.bold: true
                    }
                    TextLabel {
                        text: "팀 학습 데이터(.jsonl.gz)와 TCN 모델(.onnx/.json)을 업로드하거나 내려받을 원격 저장소와 보안 토큰을 설정합니다."
                        font.pixelSize: 12
                        color: window.muted
                        wrapMode: Text.Wrap
                        Layout.fillWidth: true
                        Layout.minimumWidth: 0
                    }
                }
                ActionButton {
                    text: "닫기"
                    onClicked: hubSyncDialog.close()
                }
            }

            Rectangle {
                Layout.fillWidth: true
                implicitHeight: securityBannerCol.implicitHeight + 16
                radius: 10
                color: "#EEF8F6"
                border.color: "#8CE0CA"
                ColumnLayout {
                    id: securityBannerCol
                    anchors.fill: parent
                    anchors.margins: 8
                    spacing: 3
                    TextLabel {
                        Layout.fillWidth: true
                        Layout.minimumWidth: 0
                        text: "보안 안내 · 토큰 키 암호화 보호"
                        font.bold: true
                        font.pixelSize: 12
                        color: "#0F6E5B"
                    }
                    TextLabel {
                        text: "입력하신 액세스 토큰은 Windows DPAPI(현재 Windows 계정 전용 암호화) 및 로컬 암호화 금고(config/hub_secrets.bin)에 암호화되어 저장됩니다. Git 추적 대상에서 제외되며 화면·로그·오류 메시지에서 자동 마스킹됩니다."
                        font.pixelSize: 12
                        color: "#114B3E"
                        wrapMode: Text.Wrap
                        Layout.fillWidth: true
                        Layout.minimumWidth: 0
                    }
                }
            }

            // 1. Provider Selection
            ColumnLayout {
                Layout.fillWidth: true
                spacing: 6
                TextLabel { text: "1. 원격 허브 플랫폼 선택"; font.bold: true; font.pixelSize: 13 }
                RowLayout {
                    Layout.fillWidth: true
                    spacing: 8
                    ActionButton {
                        text: "Hugging Face Dataset"
                        leftPadding: 14; rightPadding: 14
                        accent: hubSyncDialog.selectedProvider === "huggingface"
                        onClicked: {
                            hubSyncDialog.selectedProvider = "huggingface"
                            if (repoField.text.trim() === "") {
                                repoField.text = "se4nchoi/manux-datasets"
                            }
                        }
                    }
                    ActionButton {
                        text: "GitHub Repository"
                        leftPadding: 14; rightPadding: 14
                        accent: hubSyncDialog.selectedProvider === "github"
                        onClicked: {
                            hubSyncDialog.selectedProvider = "github"
                        }
                    }
                    Item { Layout.fillWidth: true; Layout.minimumWidth: 0 }
                    Chip {
                        Layout.fillWidth: true
                        text: "현재 설정: " + dashboard.hubSummaryLabel
                    }
                }
            }

            // 2. Repository Address & Branch
            RowLayout {
                Layout.fillWidth: true
                spacing: 10
                ColumnLayout {
                    Layout.fillWidth: true
                    Layout.minimumWidth: 0
                    spacing: 4
                    TextLabel {
                        Layout.fillWidth: true
                        Layout.minimumWidth: 0
                        elide: Text.ElideRight
                        text: hubSyncDialog.selectedProvider === "github"
                            ? "2. GitHub 저장소 주소 (owner/repo 또는 전체 URL)"
                            : "2. Hugging Face 데이터셋 저장소 주소 (org/repo 또는 전체 URL)"
                        font.bold: true
                        font.pixelSize: 13
                    }
                    TextField {
                        id: repoField
                        Layout.fillWidth: true
                        Layout.minimumWidth: 0
                        implicitHeight: 38
                        text: dashboard.hubRepo
                        placeholderText: hubSyncDialog.selectedProvider === "github"
                            ? "예: my-org/manux-datasets 또는 https://github.com/my-org/manux-datasets"
                            : "예: se4nchoi/manux-datasets 또는 https://huggingface.co/datasets/se4nchoi/manux-datasets"
                        font.pixelSize: 13
                        selectByMouse: true
                        background: Rectangle {
                            radius: 8
                            color: "#F8FAFC"
                            border.color: repoField.activeFocus ? "#16846E" : window.line
                            border.width: repoField.activeFocus ? 2 : 1
                        }
                    }
                }
                ColumnLayout {
                    Layout.preferredWidth: 130
                    Layout.maximumWidth: 140
                    spacing: 4
                    TextLabel { text: "브랜치 (Branch)"; font.bold: true; font.pixelSize: 13 }
                    TextField {
                        id: branchField
                        Layout.fillWidth: true
                        implicitHeight: 38
                        text: dashboard.hubBranch
                        placeholderText: "main"
                        font.pixelSize: 13
                        selectByMouse: true
                        background: Rectangle {
                            radius: 8
                            color: "#F8FAFC"
                            border.color: branchField.activeFocus ? "#16846E" : window.line
                            border.width: branchField.activeFocus ? 2 : 1
                        }
                    }
                }
            }

            // 3. Access Token (Password masked)
            ColumnLayout {
                Layout.fillWidth: true
                spacing: 4
                RowLayout {
                    Layout.fillWidth: true
                    spacing: 8
                    TextLabel {
                        Layout.fillWidth: true
                        Layout.minimumWidth: 0
                        elide: Text.ElideRight
                        text: hubSyncDialog.selectedProvider === "github"
                            ? "3. GitHub 개인 액세스 토큰 (ghp_... / github_pat_... · 읽기/쓰기 권한)"
                            : "3. Hugging Face 액세스 토큰 (hf_... · Write 권한)"
                        font.bold: true
                        font.pixelSize: 13
                    }
                    Chip {
                        warn: !dashboard.hubHasToken
                        text: dashboard.hubHasToken ? ("암호화 보관 중: " + dashboard.hubTokenMasked) : "저장된 토큰 없음"
                    }
                }
                RowLayout {
                    Layout.fillWidth: true
                    spacing: 8
                    TextField {
                        id: tokenField
                        Layout.fillWidth: true
                        Layout.minimumWidth: 0
                        implicitHeight: 38
                        echoMode: hubSyncDialog.showTokenPlain ? TextInput.Normal : TextInput.Password
                        placeholderText: dashboard.hubHasToken
                            ? "변경하려면 새 토큰을 입력하세요 (비워 두면 기존 암호화 토큰 유지)"
                            : (hubSyncDialog.selectedProvider === "github" ? "ghp_... 또는 github_pat_... 토큰 붙여넣기" : "hf_... 토큰 붙여넣기")
                        font.pixelSize: 13
                        selectByMouse: true
                        background: Rectangle {
                            radius: 8
                            color: "#F8FAFC"
                            border.color: tokenField.activeFocus ? "#16846E" : window.line
                            border.width: tokenField.activeFocus ? 2 : 1
                        }
                    }
                    CompactButton {
                        text: hubSyncDialog.showTokenPlain ? "숨기기" : "보기"
                        onClicked: hubSyncDialog.showTokenPlain = !hubSyncDialog.showTokenPlain
                    }
                    CompactButton {
                        text: "저장된 토큰 삭제"
                        danger: true
                        enabled: dashboard.hubHasToken
                        onClicked: {
                            tokenField.text = ""
                            dashboard.clearHubToken(hubSyncDialog.selectedProvider)
                        }
                    }
                }
            }

            // Options & Status Banner
            RowLayout {
                Layout.fillWidth: true
                spacing: 8
                CheckBox {
                    id: includeModelsCheck
                    Layout.fillWidth: true
                    Layout.minimumWidth: 0
                    checked: hubSyncDialog.includeModels
                    onToggled: hubSyncDialog.includeModels = checked
                    text: "TCN 모델(.onnx + .json 카드)도 함께 동기화"
                }
                CompactButton {
                    text: "설정만 암호화 저장"
                    onClicked: {
                        dashboard.saveHubSettings(
                            hubSyncDialog.selectedProvider,
                            repoField.text,
                            branchField.text,
                            tokenField.text,
                            hubSyncDialog.includeModels
                        )
                        tokenField.text = ""
                    }
                }
                CompactButton {
                    text: "연결 및 저장소 확인"
                    enabled: dashboard.trainingBusy === ""
                    onClicked: {
                        dashboard.testHubConnectionSlot(
                            hubSyncDialog.selectedProvider,
                            repoField.text,
                            branchField.text,
                            tokenField.text
                        )
                        tokenField.text = ""
                    }
                }
            }

            WorkProgressBanner {
            }

            Rectangle {
                visible: dashboard.hubStatusNote !== "" && !dashboard.appWorking
                Layout.fillWidth: true
                implicitHeight: statusNoteText.implicitHeight + 16
                radius: 8
                color: dashboard.hubStatusNote.indexOf("실패") >= 0 || dashboard.hubStatusNote.indexOf("오류") >= 0 ? "#FFF1F0" : "#F7FAFB"
                border.color: dashboard.hubStatusNote.indexOf("실패") >= 0 || dashboard.hubStatusNote.indexOf("오류") >= 0 ? "#E5484D" : window.line
                TextLabel {
                    id: statusNoteText
                    anchors.fill: parent
                    anchors.margins: 8
                    text: dashboard.hubStatusNote
                    font.pixelSize: 12
                    color: dashboard.hubStatusNote.indexOf("실패") >= 0 || dashboard.hubStatusNote.indexOf("오류") >= 0 ? "#C62828" : window.navy
                    wrapMode: Text.Wrap
                }
            }

            Rectangle { Layout.fillWidth: true; height: 1; color: window.line }

            RowLayout {
                Layout.fillWidth: true
                spacing: 10
                TextLabel {
                    text: "저장소 주소와 토큰을 저장한 뒤 바로 업로드하거나 내려받습니다."
                    font.pixelSize: 12
                    color: window.muted
                    Layout.fillWidth: true
                    Layout.minimumWidth: 0
                    wrapMode: Text.Wrap
                }
                ActionButton {
                    text: "허브로 업로드 (Push)"
                    primary: hubSyncDialog.modeHint !== "pull"
                    enabled: !dashboard.trainingRunning && dashboard.trainingBusy === "" && !dashboard.recActive
                    onClicked: {
                        dashboard.pushToHub(
                            hubSyncDialog.selectedProvider,
                            repoField.text,
                            branchField.text,
                            tokenField.text,
                            hubSyncDialog.includeModels
                        )
                        tokenField.text = ""
                    }
                }
                ActionButton {
                    text: "허브에서 받기 (Pull)"
                    primary: hubSyncDialog.modeHint === "pull"
                    enabled: !dashboard.trainingRunning && dashboard.trainingBusy === "" && !dashboard.recActive
                    onClicked: {
                        dashboard.pullFromHub(
                            hubSyncDialog.selectedProvider,
                            repoField.text,
                            branchField.text,
                            tokenField.text,
                            hubSyncDialog.includeModels
                        )
                        tokenField.text = ""
                    }
                }
            }
        }
    }

    RecordingPlanDialog { id: capturePlan; editor: dashboard.recordingPlan }

    // Reception overlay: small click-through pill in a screen corner (tray mode / --overlay)
    Window {
        id: overlay
        title: "MANUX 상태"
        // Independent of the dashboard window: it stays usable while the dashboard is hidden in the tray
        transientParent: null
        visible: dashboard.overlayVisible
        color: "transparent"
        flags: Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool
               | Qt.WindowTransparentForInput | Qt.WindowDoesNotAcceptFocus
        width: pill.implicitWidth
        height: 34
        readonly property var area: dashboard.overlayArea
        readonly property string corner: dashboard.overlayCorner
        x: corner.indexOf("left") >= 0 ? area[0] + 16 : area[0] + area[2] - width - 16
        y: corner.indexOf("top") >= 0 ? area[1] + 16 : area[1] + area[3] - height - 16
        Rectangle {
            id: pill
            anchors.fill: parent
            implicitWidth: pillRow.implicitWidth + 24
            radius: height / 2
            color: "#E6112331"
            Row {
                id: pillRow
                anchors.centerIn: parent
                spacing: 8
                Rectangle {
                    width: 10; height: 10; radius: 5
                    anchors.verticalCenter: parent.verticalCenter
                    color: dashboard.receptionState === "ok" ? "#2FBF8F"
                         : dashboard.receptionState === "weak" ? "#F2B544"
                         : dashboard.receptionState === "none" ? "#8A9AA6" : "#526575"
                }
                Label {
                    text: "MANUX · " + dashboard.receptionText
                    color: "#F5F7F8"
                    font.pixelSize: 13
                    font.family: Theme.Studio.font
                }
            }
        }
    }

    // The other hand drawn on the screen too (src/other_hand_motion.py, 2026-11-12, "왼쪽 스켈레톤도 모니터에 같이"): where it is
    // on the camera image, in the settings window's "다른 손" colour; faint while only seen, full and thick once it swipes.
    Window {
        id: otherHandWindow
        objectName: "otherHandWindow"
        title: "MANUX 다른 손"
        transientParent: null
        readonly property var hand: dashboard.otherHand
        readonly property bool present: hand.pts !== undefined
        readonly property var look: (dashboard.skeletonStyle && dashboard.skeletonStyle.values) || ({})
        visible: dashboard.virtualHandOn && !dashboard.pointerOnly && present
        color: "transparent"
        flags: Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool
               | Qt.WindowTransparentForInput | Qt.WindowDoesNotAcceptFocus
        width: 640
        height: 640
        property var shown: null
        property real shownX: 0
        property real shownY: 0
        function placeAt(px, py) { x = Math.round(px - width / 2); y = Math.round(py - height / 2) }
        onPresentChanged: if (!present) shown = null
        onHandChanged: {
            if (hand.pts !== undefined && (shown === null || shown.length !== hand.pts.length)) {
                shown = hand.pts.slice(); shownX = hand.x; shownY = hand.y
                placeAt(shownX, shownY)
                otherCanvas.requestPaint()
            }
        }
        FrameAnimation {
            running: otherHandWindow.visible && otherHandWindow.shown !== null
            onTriggered: {
                var w = otherHandWindow, h = w.hand
                if (!h.pts || w.shown === null) return
                var k = 1 - Math.exp(-Math.min(frameTime, 0.1) / 0.02)
                var pts = w.shown
                for (var i = 0; i < pts.length; i++) pts[i] += (h.pts[i] - pts[i]) * k
                w.shownX += (h.x - w.shownX) * k
                w.shownY += (h.y - w.shownY) * k
                w.placeAt(w.shownX, w.shownY)
                otherCanvas.requestPaint()
            }
        }
        readonly property var bones: [
            [0,1],[1,2],[2,3],[3,4], [0,5],[5,6],[6,7],[7,8], [5,9],[9,10],[10,11],[11,12],
            [9,13],[13,14],[14,15],[15,16], [13,17],[17,18],[18,19],[19,20], [0,17]
        ]
        Canvas {
            id: otherCanvas
            objectName: "otherHandCanvas"
            anchors.fill: parent
            readonly property real stateAlpha: ({"idle": .55, "arming": .8, "on": 1.0})[otherHandWindow.hand.state] || .55
            opacity: (otherHandWindow.look.vh_alpha || 1.0) * stateAlpha * (otherHandWindow.hand.lost ? 0.45 : 1.0)
            Connections { target: dashboard; function onSkeletonStyleChanged() { otherCanvas.requestPaint() } }
            onPaint: {
                var ctx = getContext("2d")
                ctx.reset()
                var w = otherHandWindow, pts = w.shown
                if (pts === null || !w.hand.pts) return
                var wk = (w.look.width || 1.0) * (w.hand.state === "on" ? 1.4 : 1.0)
                var col = w.look.other || "#D946EF"
                var cx = width / 2, cy = height / 2
                function px(i) { return [cx + pts[2 * i], cy + pts[2 * i + 1]] }
                ctx.lineCap = "round"
                for (var pass = 0; pass < 2; pass++) {
                    ctx.strokeStyle = pass === 0 ? "rgba(17,35,49,0.55)" : col
                    ctx.lineWidth = (pass === 0 ? 7 : 3.5) * wk
                    ctx.beginPath()
                    for (var b = 0; b < w.bones.length; b++) {
                        var a = px(w.bones[b][0]), c = px(w.bones[b][1])
                        ctx.moveTo(a[0], a[1]); ctx.lineTo(c[0], c[1])
                    }
                    ctx.stroke()
                }
                ctx.fillStyle = col
                for (var j = 0; j < 21; j++) {
                    var p = px(j)
                    ctx.beginPath(); ctx.arc(p[0], p[1], (j % 4 === 0 && j > 0 ? 5 : 3.5) * Math.max(.7, wk), 0, 2 * Math.PI); ctx.fill()
                }
                // the speed dial (src/speed_dial.py, 2026-11-12): an arc above the hand, a tick per step, the needle at the
                // hand's turn, the steps taken filled in (green faster, amber slower)
                var dial = w.hand.dial
                if (dial) {
                    var reach = 40                                   // the arc goes round the hand, past its farthest joint
                    for (var q = 0; q < 21; q++) reach = Math.max(reach, Math.hypot(pts[2 * q], pts[2 * q + 1]))
                    var R = Math.min(250, reach + 34), ox = cx, oy = cy
                    var lo = dial.min * dial.step_deg, hi = dial.max * dial.step_deg   // the speeds' range, degrees from 1x
                    // the dial's middle at the hand's 11 o'clock (dial.center, degrees from up): the needle is where the hand points
                    // dial.dir -1: "more" is to the left (counter-clockwise), the easy turn of the left hand
                    function at(deg) { return -Math.PI / 2 + ((dial.center || 0) + (dial.dir || 1) * deg) * Math.PI / 180 }
                    function ring(a0, a1, colour, width) {
                        var s0 = at(a0), s1 = at(a1)
                        ctx.strokeStyle = colour; ctx.lineWidth = width
                        ctx.beginPath(); ctx.arc(ox, oy, R, Math.min(s0, s1), Math.max(s0, s1)); ctx.stroke()
                    }
                    ctx.lineCap = "round"
                    ring(lo, hi, "rgba(17,35,49,0.55)", 14)
                    ring(lo, hi, "rgba(245,247,248,0.85)", 6)
                    var from = (dial.from || 0) * dial.step_deg, done = dial.steps * dial.step_deg   // filled from the start
                    if (dial.steps > (dial.from || 0)) ring(from, done, "#2FBF8F", 8)
                    if (dial.steps < (dial.from || 0)) ring(done, from, "#F2B544", 8)
                    ctx.strokeStyle = "#112331"; ctx.lineWidth = 2
                    for (var k = dial.min; k <= dial.max; k++) {
                        var ang = at(k * dial.step_deg)
                        var r1 = R - (k === 0 ? 14 : 8), r2 = R + (k === 0 ? 14 : 8)
                        ctx.beginPath(); ctx.moveTo(ox + Math.cos(ang) * r1, oy + Math.sin(ang) * r1)
                        ctx.lineTo(ox + Math.cos(ang) * r2, oy + Math.sin(ang) * r2); ctx.stroke()
                    }
                    var needle = at(Math.max(lo - 10, Math.min(hi + 10, dial.turn)))
                    ctx.strokeStyle = col; ctx.lineWidth = 4
                    ctx.beginPath(); ctx.moveTo(ox + Math.cos(needle) * (R - 22), oy + Math.sin(needle) * (R - 22))
                    ctx.lineTo(ox + Math.cos(needle) * (R + 22), oy + Math.sin(needle) * (R + 22)); ctx.stroke()
                    ctx.fillStyle = col
                    ctx.beginPath(); ctx.arc(ox + Math.cos(needle) * R, oy + Math.sin(needle) * R, 8, 0, 2 * Math.PI); ctx.fill()
                    ctx.textAlign = "center"
                    ctx.lineJoin = "round"
                    function say(text, x, y, size) {                  // light text with a dark edge: readable on any page
                        ctx.font = "bold " + size + "px sans-serif"
                        ctx.strokeStyle = "rgba(17,35,49,0.85)"; ctx.lineWidth = 4
                        ctx.strokeText(text, x, y)
                        ctx.fillStyle = "#F5F7F8"; ctx.fillText(text, x, y)
                    }
                    var ends = [[dial.min, dial.lo_text], [dial.max, dial.hi_text]]   // the words come from src/speed_dial.py
                    for (var e = 0; e < 2; e++) {
                        var ea = at(ends[e][0] * dial.step_deg)
                        say(ends[e][1], ox + Math.cos(ea) * (R + 32), oy + Math.sin(ea) * (R + 32) + 5, 13)
                    }
                    say(dial.label, ox, oy - R - 22, 22)
                    say(dial.caption, ox, oy - R - 48, 13)
                }
            }
        }
    }
    // The control hand drawn at the cursor (src/virtual_hand.py): its palm centre is the cursor; a click lands where the pinch meets.
    // Click-through and always on top, like the status pill; it follows the cursor instead of covering the screen.
    Window {
        id: virtualHandWindow
        objectName: "virtualHandWindow"
        title: "MANUX 가상 손"
        transientParent: null
        readonly property var hand: dashboard.virtualHand
        readonly property bool present: hand.pts !== undefined
        visible: dashboard.virtualHandOn && !dashboard.pointerOnly && present
        color: "transparent"
        flags: Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool
               | Qt.WindowTransparentForInput | Qt.WindowDoesNotAcceptFocus
        width: 640
        height: 640
        // Camera frames come ~30 times a second and unevenly: the drawn hand and the window glide toward the newest frame at the
        // screen's own rate (each display frame closes a share of the gap), so the motion is continuous instead of stepping.
        property var shown: null         // the joints as drawn now
        property var shownAnchor: [0, 0] // the drawn anchor (thumb-index point placed on the cursor), glides too
        property real shownX: 0
        property real shownY: 0
        // seconds: time constant of the glide. .015 ("fast", the default) only bridges the camera frames; .04 was 16 ms more lag
        // The runtime sends the glide with each hand (fast while it only moves, smooth while it makes a command).
        readonly property real glide: (hand.glide !== undefined && hand.glide > 0) ? hand.glide
                                      : (dashboard.virtualHandGlide > 0 ? dashboard.virtualHandGlide : 0.015)
        function placeAt(px, py) { x = Math.round(px - width / 2); y = Math.round(py - height / 2) }
        // the hand stays (faded, see VH_LOST_KEEP) through a short loss, so it is never thrown away and re-placed here
        onPresentChanged: if (!present) shown = null
        onHandChanged: {
            if (hand.pts !== undefined && (shown === null || shown.length !== hand.pts.length)) {
                shown = hand.pts.slice(); shownX = hand.x; shownY = hand.y
                shownAnchor = hand.anchor ? hand.anchor.slice() : [0, 0]
                placeAt(shownX, shownY)
                handCanvas.requestPaint()
            }
        }
        FrameAnimation {
            running: virtualHandWindow.visible && virtualHandWindow.shown !== null
            onTriggered: {
                var w = virtualHandWindow, h = w.hand
                if (!h.pts || w.shown === null) return
                var k = 1 - Math.exp(-Math.min(frameTime, 0.1) / w.glide)
                var pts = w.shown
                for (var i = 0; i < pts.length; i++) pts[i] += (h.pts[i] - pts[i]) * k
                var a = w.shownAnchor, ta = h.anchor || [0, 0]
                a[0] += (ta[0] - a[0]) * k; a[1] += (ta[1] - a[1]) * k
                w.shownX += (h.x - w.shownX) * k
                w.shownY += (h.y - w.shownY) * k
                w.placeAt(w.shownX, w.shownY)
                handCanvas.requestPaint()
            }
        }
        readonly property var bones: [
            [0,1],[1,2],[2,3],[3,4], [0,5],[5,6],[6,7],[7,8], [5,9],[9,10],[10,11],[11,12],
            [9,13],[13,14],[14,15],[15,16], [13,17],[17,18],[18,19],[19,20], [0,17]
        ]
        readonly property var tips: ({"index": 8, "middle": 12, "ring": 16, "pinky": 20})
        Canvas {
            id: handCanvas
            anchors.fill: parent
            // the user's look (settings window, src/skeleton_style.py): colours, opacity, thickness
            readonly property var look: (dashboard.skeletonStyle && dashboard.skeletonStyle.values) || ({})
            opacity: (look.vh_alpha || 1.0) * (virtualHandWindow.hand.lost ? 0.35 : (virtualHandWindow.hand.paused ? 0.45 : 1.0))
            Connections { target: dashboard; function onSkeletonStyleChanged() { handCanvas.requestPaint() } }
            onPaint: {
                var ctx = getContext("2d")
                ctx.reset()
                var h = virtualHandWindow.hand
                var wk = look.width || 1.0
                var pts = virtualHandWindow.shown
                if (!h.pts || pts === null) return
                // with an anchor (box mode) the window centre is the cursor and the hand is shifted so its anchor is there
                var anc = h.anchor ? virtualHandWindow.shownAnchor : [0, 0]
                var cx = width / 2 - anc[0], cy = height / 2 - anc[1]
                function px(i) { return [cx + pts[2 * i], cy + pts[2 * i + 1]] }
                ctx.lineCap = "round"
                // a dark outline under a light line: visible on light and dark windows alike
                for (var pass = 0; pass < 2; pass++) {
                    ctx.strokeStyle = pass === 0 ? "rgba(17,35,49,0.55)" : (h.grip ? "#F2B544" : (look.vh_line || "#F5F7F8"))
                    ctx.lineWidth = (pass === 0 ? 7 : 3.5) * wk
                    ctx.beginPath()
                    for (var b = 0; b < virtualHandWindow.bones.length; b++) {
                        var a = px(virtualHandWindow.bones[b][0]), c = px(virtualHandWindow.bones[b][1])
                        ctx.moveTo(a[0], a[1]); ctx.lineTo(c[0], c[1])
                    }
                    ctx.stroke()
                }
                for (var j = 0; j < 21; j++) {
                    var p = px(j)
                    ctx.beginPath(); ctx.arc(p[0], p[1], (j % 4 === 0 && j > 0 ? 5 : 3.5) * Math.max(.7, wk), 0, 2 * Math.PI)
                    ctx.fillStyle = look.vh_joint || "#46E5BD"; ctx.fill()
                }
                // thumb -> finger lines of the pinches the engine sees
                var colors = {"near": "#F2B544", "pinched": "#2FBF8F", "action": "#E5484D"}
                for (var g = 0; g < h.guides.length; g++) {
                    var tip = px(virtualHandWindow.tips[h.guides[g][0]]), thumb = px(4)
                    ctx.strokeStyle = colors[h.guides[g][1]] || "#F2B544"
                    ctx.lineWidth = h.guides[g][1] === "near" ? 3 : 5
                    ctx.beginPath(); ctx.moveTo(thumb[0], thumb[1]); ctx.lineTo(tip[0], tip[1]); ctx.stroke()
                }
                // the palm centre: where the hand is (the cursor while no finger pinches)
                ctx.lineWidth = 2
                ctx.strokeStyle = "rgba(17,35,49,0.55)"
                ctx.beginPath(); ctx.arc(cx, cy, 5, 0, 2 * Math.PI); ctx.stroke()
                // the click point: where the thumb and the pinching finger meet
                if (h.click) {
                    var kx = h.anchor ? width / 2 : cx + h.click[0], ky = h.anchor ? height / 2 : cy + h.click[1]
                    ctx.lineWidth = h.aim ? 2 : 3
                    ctx.strokeStyle = h.action !== "" ? "#E5484D" : (h.aim ? "rgba(17,35,49,0.45)" : "#112331")
                    ctx.beginPath(); ctx.arc(kx, ky, h.aim ? 6 : 9, 0, 2 * Math.PI); ctx.stroke()
                    if (h.action !== "" && h.text !== false) {     // (the words can be switched off in the settings)
                        ctx.font = "bold 16px 'Noto Sans KR'"
                        ctx.lineWidth = 4; ctx.strokeStyle = "rgba(255,255,255,0.9)"
                        ctx.strokeText(h.action, kx + 14, ky - 12)
                        ctx.fillStyle = "#E5484D"
                        ctx.fillText(h.action, kx + 14, ky - 12)
                    }
                }
                // the control is off: what the hand's signal would do, to check a gesture without running it (h.note)
                if (h.action === "" && (h.note || "") !== "" && h.text !== false) {
                    var nx = (h.click ? (h.anchor ? width / 2 : cx + h.click[0]) : cx) + 14
                    var ny = (h.click ? (h.anchor ? height / 2 : cy + h.click[1]) : cy) - 12
                    ctx.font = "bold 15px 'Noto Sans KR'"
                    ctx.lineWidth = 4; ctx.strokeStyle = "rgba(255,255,255,0.9)"
                    ctx.strokeText(h.note, nx, ny)
                    ctx.fillStyle = "#1B6B5A"
                    ctx.fillText(h.note, nx, ny)
                }
            }
        }
    }

    FingerTracker { }
    DrawOverlay { }

    // Pointing mode (src/point_mode.py): a ring at the cursor fills over the 1 s rest on a file / folder. Click-through.
    Window {
        id: pointRing
        objectName: "pointRing"
        title: "MANUX 포인팅"
        transientParent: null
        readonly property var view: dashboard.pointView
        readonly property bool on: view.kind !== undefined
        visible: on
        color: "transparent"
        flags: Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool
               | Qt.WindowTransparentForInput | Qt.WindowDoesNotAcceptFocus
        width: 420
        height: 70
        x: on ? view.cursor[0] + 14 : 0
        y: on ? view.cursor[1] + 14 : 0
        onViewChanged: ringCanvas.requestPaint()
        Canvas {
            id: ringCanvas
            x: 0; y: 0; width: 40; height: 40
            onPaint: {
                var c = getContext("2d"); c.reset()
                var v = pointRing.view
                if (v.kind === undefined) return
                var cx = 20, cy = 20, r = 14
                c.lineWidth = 5
                c.strokeStyle = "rgba(17,35,49,0.55)"
                c.beginPath(); c.arc(cx, cy, r, 0, Math.PI * 2); c.stroke()
                if (v.on_file && v.progress > 0) {
                    c.strokeStyle = v.kind === "right" ? "#3B82F6" : "#10B981"
                    c.beginPath(); c.arc(cx, cy, r, -Math.PI / 2, -Math.PI / 2 + Math.PI * 2 * v.progress); c.stroke()
                }
            }
        }
        Rectangle {
            x: 44; y: 8
            width: pointLabel.implicitWidth + 16
            height: 24
            radius: 12
            color: "#E0112331"
            Label {
                id: pointLabel
                anchors.centerIn: parent
                // the click it would be, and why the ring is (not) filling: the file's name, "not on a file" ...
                text: (pointRing.view.kind === "right" ? "우클릭" : "더블클릭")
                      + (pointRing.view.why ? "  ·  " + pointRing.view.why : "")
                color: pointRing.view.on_file ? (pointRing.view.kind === "right" ? "#93C5FD" : "#6EE7B7") : "#94A3B8"
                font.pixelSize: 12
                font.bold: true
            }
        }
    }
    // Simulation badge (2026-11-11): the mouse control is off - the hand is still read and every gesture, connected command and
    // motion-mode swipe is SHOWN as what it would do, but nothing is sent. Top-right, above the motion badge, so the two states
    // are never confused. Click-through, always on top.
    Window {
        id: simBadge
        objectName: "simBadge"
        title: "MANUX 시뮬레이션"
        transientParent: null
        visible: dashboard.simulating
        color: "transparent"
        flags: Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool
               | Qt.WindowTransparentForInput | Qt.WindowDoesNotAcceptFocus
        width: simPill.implicitWidth
        height: 56
        readonly property var area: dashboard.overlayArea
        x: area[0] + area[2] - width - 16
        y: area[1] + 16 + (dashboard.overlayVisible && dashboard.overlayCorner === "top-right" ? 42 : 0)
        Rectangle {
            id: simPill
            anchors.fill: parent
            implicitWidth: simCol.implicitWidth + 36
            radius: 14
            color: "#E61E3A8A"
            border.width: 2
            border.color: "#93C5FD"
            Row {
                anchors.centerIn: parent
                spacing: 10
                Rectangle {
                    width: 12; height: 12; radius: 6
                    anchors.verticalCenter: parent.verticalCenter
                    color: "#93C5FD"
                }
                Column {
                    id: simCol
                    spacing: 1
                    Label {
                        text: "시뮬레이션 중 · 마우스 제어 꺼짐"
                        color: "#FFFFFF"
                        font.pixelSize: 15
                        font.bold: true
                        font.family: Theme.Studio.font
                    }
                    Label {
                        text: "손짓·모션은 화면에 표시만 하고 실행하지 않아요"
                        color: "#DBEAFE"
                        font.pixelSize: 11
                        font.family: Theme.Studio.font
                    }
                }
            }
        }
    }
    // Motion-mode badge: always on top and click-through, in the top-right corner of the screen, so the user
    // can tell the mode from anywhere (also when this window is hidden or behind others).
    Window {
        id: motionBadge
        title: "MANUX 모션 모드"
        transientParent: null
        visible: dashboard.motionBadgeVisible
        color: "transparent"
        flags: Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool
               | Qt.WindowTransparentForInput | Qt.WindowDoesNotAcceptFocus
        width: badgePill.implicitWidth
        height: 44
        readonly property var area: dashboard.overlayArea
        x: area[0] + area[2] - width - 16
        // below the small reception pill when that one is showing in the same corner
        y: area[1] + 16 + (dashboard.overlayVisible && dashboard.overlayCorner === "top-right" ? 42 : 0)
           + (dashboard.simulating ? 64 : 0)          // under the simulation badge
        Rectangle {
            id: badgePill
            anchors.fill: parent
            implicitWidth: badgeRow.implicitWidth + 32
            radius: height / 2
            color: dashboard.motionBadgeOn ? "#F2B544" : "#E6112331"
            border.width: 2
            border.color: dashboard.motionBadgeOn ? "#FFF3D6" : "#526575"
            Row {
                id: badgeRow
                anchors.centerIn: parent
                spacing: 10
                Rectangle {
                    width: 12; height: 12; radius: 6
                    anchors.verticalCenter: parent.verticalCenter
                    color: dashboard.motionBadgeOn ? "#112331" : "#F2B544"
                }
                Label {
                    text: dashboard.motionBadgeText
                    color: dashboard.motionBadgeOn ? "#112331" : "#F5F7F8"
                    font.pixelSize: 16
                    font.bold: true
                    font.family: Theme.Studio.font
                }
            }
        }
    }

    Window {
        id: trackingWindow
        title: "MANUX 트래킹 측정"
        // Independent of the dashboard window: it stays usable while the dashboard is hidden in the tray
        transientParent: null
        color: "#0E1B26"
        visibility: dashboard.trackingActive ? Window.FullScreen : Window.Hidden
        flags: Qt.Window
        // Take keyboard focus when shown, so Space / Esc reach this window right away
        onVisibilityChanged: function (mode) {
            if (mode === Window.FullScreen) {
                requestActivate()
                keyCatcher.forceActiveFocus()
            }
        }
        screen: {
            const list = Qt.application.screens
            for (let i = 0; i < list.length; i++)
                if (list[i].name === dashboard.trackingScreen) return list[i]
            return list.length ? list[0] : null
        }

        // Keys are read directly here, and the main window's shortcuts are off while the
        // test runs: they also caught keys pressed in this window, and two "Space" shortcuts
        // clashed so neither fired (2026-11-03, Windows: stuck on "Space를 눌러 시작").
        Item {
            id: keyCatcher
            anchors.fill: parent
            focus: true
            Keys.onPressed: function (event) {
                if (event.key === Qt.Key_Space) {
                    dashboard.command(32)
                    event.accepted = true
                } else if (event.key === Qt.Key_Escape) {
                    dashboard.closeTrackingTest()
                    event.accepted = true
                }
            }
        }
        MouseArea {
            // Clicking the window (with the real mouse) also gives it the keyboard back
            anchors.fill: parent
            onPressed: function (mouse) { keyCatcher.forceActiveFocus(); mouse.accepted = false }
        }

        Rectangle {
            id: target
            visible: !dashboard.trackingDone && dashboard.trackingTargetX >= 0
            width: Math.max(6, dashboard.trackingTargetSize * trackingWindow.width)
            height: width
            radius: width / 2
            x: dashboard.trackingTargetX * trackingWindow.width - width / 2
            y: dashboard.trackingTargetY * trackingWindow.height - height / 2
            color: "#46E5BD"
            opacity: .85
        }
        Rectangle {
            // where the controller puts the cursor (also visible in --dry-run)
            width: 16; height: 16; radius: 8
            x: dashboard.trackingCursorX * trackingWindow.width - 8
            y: dashboard.trackingCursorY * trackingWindow.height - 8
            color: "transparent"
            border.color: "#F5F7F8"
            border.width: 2
        }
        Column {
            anchors.horizontalCenter: parent.horizontalCenter
            anchors.top: parent.top
            anchors.topMargin: 24
            spacing: 6
            Label {
                anchors.horizontalCenter: parent.horizontalCenter
                text: dashboard.trackingStatus
                color: "#F5F7F8"
                font.pixelSize: 20
                font.bold: true
            }
            Label {
                anchors.horizontalCenter: parent.horizontalCenter
                text: dashboard.trackingDone ? "Esc 닫기 · 결과는 hand-mouse/logs/tracking-*.csv"
                                             : "Space 제어 시작/일시정지 · Esc 그만두기 · 클릭은 하지 않습니다"
                color: "#9FB3C2"
                font.pixelSize: 14
            }
        }
        Label {
            visible: dashboard.trackingPaused
            anchors.centerIn: parent
            text: "일시정지됨\nSpace를 눌러 시작"
            horizontalAlignment: Text.AlignHCenter
            color: "#F5F7F8"
            font.pixelSize: 40
            font.bold: true
        }
        Button {
            visible: dashboard.trackingDone
            anchors.centerIn: parent
            text: "닫기"
            onClicked: dashboard.closeTrackingTest()
        }
    }
}
