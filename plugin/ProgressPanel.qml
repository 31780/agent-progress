import QtQuick
import QtQuick.Controls
import Quickshell
import Quickshell.Io
import qs.Commons
import qs.Commons as Commons
import qs.Ui
import qs.Ui as Ui

Panel {
    id: root
    moduleName: "nino.codex-progress"
    ipcTarget: "nino.codex-progress"
    property var snapshot: ({tasks: [], active: 0, waiting: 0, unknown: 0})
    property bool healthy: false
    property double lastRead: 0
    property double now: Date.now() / 1000
    property bool showHistory: false
    property int historyPage: 0
    property string actionError: ""
    readonly property int pageSize: 10
    readonly property var currentRows: snapshot.current || []
    readonly property var historyRows: snapshot.history || []
    readonly property string helper: (Quickshell.env("XDG_DATA_HOME") || Quickshell.env("HOME") + "/.local/share") + "/omarchy-agent-progress/progress.py"
    readonly property color fg: bar ? bar.foreground : Commons.Color.foreground
    readonly property color muted: Qt.rgba(fg.r, fg.g, fg.b, 0.62)
    readonly property color accent: Commons.Color.accent
    readonly property color warning: bar ? bar.urgent : Commons.Color.urgent
    readonly property bool connected: healthy && now - lastRead < 10
    readonly property var rows: showHistory ? historyRows.slice(historyPage * pageSize, (historyPage + 1) * pageSize) : currentRows
    readonly property string fontName: bar ? bar.fontFamily : Style.font.family
    implicitWidth: button.implicitWidth
    implicitHeight: button.implicitHeight

    function duration(seconds) {
        var n = Math.max(0, Math.floor(seconds))
        if (n >= 3600) return Math.floor(n / 3600) + "h " + Math.floor(n % 3600 / 60) + "m"
        if (n >= 60) return Math.floor(n / 60) + "m " + (n % 60) + "s"
        return n + "s"
    }
    function refresh() { if (!reader.running) reader.running = true }
    function refreshTitles() { if (!titleReader.running) titleReader.running = true }
    function selectHistory(value) {
        showHistory = value
        historyPage = 0
        scroll.contentY = 0
        actionError = ""
    }
    function dismissJob(job) {
        if (dismissProcess.running || !connected) return
        actionError = ""
        dismissProcess.command = ["/usr/bin/python3", root.helper, "dismiss", "--session", job.id, "--updated", String(job.updated)]
        dismissProcess.running = true
    }
    function stateColor(status) {
        if (status === "waiting_approval" || status === "interrupted") return warning
        if (status === "working") return accent
        return muted
    }
    Component.onCompleted: { refresh(); refreshTitles() }
    onOpenedChanged: if (opened) {
        selectHistory(false)
        refresh()
        refreshTitles()
        Qt.callLater(function() { keys.forceActiveFocus() })
    }
    Timer {
        interval: 2000; running: true; repeat: true
        onTriggered: { root.now = Date.now() / 1000; root.refresh() }
    }
    Timer { interval: 60000; running: true; repeat: true; onTriggered: root.refreshTitles() }
    Process {
        id: reader
        command: ["/usr/bin/python3", root.helper, "snapshot"]
        stdout: StdioCollector {
            onStreamFinished: {
                try {
                    var data = JSON.parse(text)
                    if (data.schemaVersion !== 1 || !Array.isArray(data.tasks)) throw new Error("Invalid data")
                    root.snapshot = data
                    root.historyPage = Math.min(root.historyPage, Math.max(0, Math.ceil(root.historyRows.length / root.pageSize) - 1))
                    root.lastRead = Date.now() / 1000
                    root.healthy = true
                } catch (error) { root.healthy = false }
            }
        }
        onExited: function(code, status) { if (code !== 0) root.healthy = false }
    }
    Process {
        id: titleReader
        command: ["/usr/bin/python3", root.helper, "titles"]
    }
    Process {
        id: dismissProcess
        onExited: function(code, status) {
            if (code !== 0) root.actionError = "Could not dismiss this job. It may have changed; refresh and try again."
            root.refresh()
        }
    }

    WidgetButton {
        id: button
        anchors.fill: parent
        bar: root.bar
        text: "◈ " + (!root.connected ? "?" : root.snapshot.active) + (root.snapshot.waiting > 0 ? " !" : root.snapshot.unknown > 0 ? " ?" : "")
        active: root.snapshot.waiting > 0
        tooltipText: "Codex · " + root.snapshot.active + " active chats" + (root.snapshot.unknown ? " · " + root.snapshot.unknown + " unknown" : "")
        onPressed: root.toggle()
        Rectangle {
            anchors.bottom: parent.bottom
            anchors.bottomMargin: Style.space(3)
            anchors.horizontalCenter: parent.horizontalCenter
            width: Style.space(22); height: Style.space(2)
            radius: height / 2
            color: root.accent
            visible: root.connected && root.snapshot.active > root.snapshot.waiting
            SequentialAnimation on opacity {
                running: root.connected && root.snapshot.active > root.snapshot.waiting
                loops: Animation.Infinite
                NumberAnimation { to: 0.25; duration: 700 }
                NumberAnimation { to: 1; duration: 700 }
            }
        }
    }

    KeyboardPanel {
        id: panel
        anchorItem: button
        owner: root
        bar: root.bar
        open: root.opened
        focusTarget: keys
        contentWidth: panel.fittedContentWidth(Style.space(460))
        contentHeight: panel.fittedContentHeight(column.implicitHeight, Style.space(620))
        Item {
            id: keys
            anchors.fill: parent
            focus: true
            Keys.onEscapePressed: root.close()
            Keys.onReturnPressed: root.refresh()
            Keys.onDownPressed: scroll.contentY = Math.max(0, Math.min(scroll.contentHeight - scroll.height, scroll.contentY + Style.space(88)))
            Keys.onUpPressed: scroll.contentY = Math.max(0, scroll.contentY - Style.space(88))
            Flickable {
                id: scroll
                anchors.fill: parent
                contentWidth: width
                contentHeight: column.implicitHeight
                clip: true
                boundsBehavior: Flickable.StopAtBounds
                ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }
                Column {
                    id: column
                    width: scroll.width
                    spacing: Style.space(12)
                    Text {
                        width: parent.width
                        text: "Codex"
                        textFormat: Text.PlainText
                        font.family: root.fontName
                        font.pixelSize: Style.font.display
                        color: root.fg
                    }
                    Row {
                        width: parent.width
                        spacing: Style.space(8)
                        Ui.Button {
                            id: currentButton
                            width: (parent.width - parent.spacing) / 2
                            text: "Current · " + root.currentRows.length
                            selected: !root.showHistory
                            focusable: true
                            foreground: root.fg
                            fontFamily: root.fontName
                            onClicked: root.selectHistory(false)
                        }
                        Ui.Button {
                            id: historyButton
                            width: (parent.width - parent.spacing) / 2
                            text: "History · " + root.historyRows.length
                            selected: root.showHistory
                            focusable: true
                            foreground: root.fg
                            fontFamily: root.fontName
                            onClicked: root.selectHistory(true)
                        }
                    }
                    Text {
                        width: parent.width
                        text: !root.connected ? "Connection unknown · local reader unavailable" : root.showHistory ? "Recent chats · past 7 days · 10 per page" : root.snapshot.active + " active  ·  " + root.snapshot.waiting + " awaiting approval"
                        textFormat: Text.PlainText
                        wrapMode: Text.WordWrap
                        font.family: root.fontName; font.pixelSize: Style.font.body
                        color: root.connected ? root.muted : root.warning
                    }
                    Text {
                        visible: root.rows.length === 0
                        width: parent.width
                        text: root.showHistory ? "No history yet. Finished responses and interrupted jobs will appear here." : "No current jobs. Finished responses and interrupted jobs move to History. New chats appear after their next hook event."
                        textFormat: Text.PlainText
                        wrapMode: Text.WordWrap
                        font.family: root.fontName; font.pixelSize: Style.font.body
                        color: root.muted
                    }
                    Text {
                        visible: root.actionError !== ""
                        width: parent.width
                        text: root.actionError
                        textFormat: Text.PlainText
                        wrapMode: Text.WordWrap
                        font.family: root.fontName; font.pixelSize: Style.font.body
                        color: root.warning
                    }
                    Repeater {
                        model: root.rows
                        delegate: Rectangle {
                            id: card
                            required property var modelData
                            readonly property string status: root.connected ? modelData.status : "connection_unknown"
                            width: column.width
                            height: body.implicitHeight + Style.space(24)
                            radius: Style.space(8)
                            color: Qt.rgba(root.fg.r, root.fg.g, root.fg.b, 0.045)
                            border.width: 1
                            border.color: Qt.rgba(root.fg.r, root.fg.g, root.fg.b, 0.13)
                            Column {
                                id: body
                                anchors { left: parent.left; right: parent.right; top: parent.top; margins: Style.space(12) }
                                spacing: Style.space(7)
                                Text {
                                    width: parent.width
                                    text: card.modelData.title
                                    textFormat: Text.PlainText
                                    maximumLineCount: 2; elide: Text.ElideRight; wrapMode: Text.Wrap
                                    color: root.fg
                                    font.family: root.fontName; font.pixelSize: Style.font.body; font.bold: true
                                }
                                Item {
                                    width: parent.width
                                    height: statusLabel.implicitHeight
                                    Text {
                                        id: statusLabel
                                        text: root.connected ? card.modelData.label : "Connection unknown"
                                        textFormat: Text.PlainText
                                        font.family: root.fontName; font.pixelSize: Style.font.body
                                        color: root.stateColor(card.status)
                                    }
                                    Text {
                                        anchors.right: parent.right
                                        text: (card.modelData.elapsedExact ? "" : "≥ ") + root.duration(card.modelData.elapsed)
                                        textFormat: Text.PlainText
                                        font.family: root.fontName; font.pixelSize: Style.font.body
                                        color: root.muted
                                    }
                                }
                                Text {
                                    width: parent.width
                                    text: card.modelData.activity
                                    textFormat: Text.PlainText
                                    maximumLineCount: 2; elide: Text.ElideRight; wrapMode: Text.Wrap
                                    font.family: root.fontName; font.pixelSize: Style.font.body
                                    color: root.muted
                                }
                                Rectangle {
                                    id: track
                                    visible: card.status === "working"
                                    width: parent.width; height: visible ? Style.space(3) : 0
                                    color: Qt.rgba(root.accent.r, root.accent.g, root.accent.b, 0.15)
                                    clip: true
                                    Rectangle {
                                        width: parent.width * 0.28; height: parent.height
                                        color: root.accent
                                        SequentialAnimation on x {
                                            running: root.opened && card.status === "working"
                                            loops: Animation.Infinite
                                            NumberAnimation { from: -track.width * 0.28; to: track.width; duration: 1600; easing.type: Easing.InOutSine }
                                        }
                                    }
                                }
                                Text {
                                    width: parent.width
                                    visible: !!card.modelData.milestone
                                    text: card.modelData.milestone ? card.modelData.milestone.done + "/" + card.modelData.milestone.total + " steps · agent-reported plan" : ""
                                    textFormat: Text.PlainText
                                    font.family: root.fontName; font.pixelSize: Style.font.body
                                    color: root.muted
                                }
                                Text {
                                    width: parent.width
                                    text: "Last event " + root.duration(card.modelData.age) + " ago" + (!card.modelData.titleKnown ? " · title pending" : "")
                                    textFormat: Text.PlainText
                                    font.family: root.fontName; font.pixelSize: Style.font.body
                                    color: root.muted
                                }
                                Ui.Button {
                                    visible: !root.showHistory && (card.status === "connection_unknown" || card.status === "idle")
                                    text: "Move to history"
                                    tooltipText: "Hide this observation until fresh activity arrives. This does not finish or stop the job."
                                    enabled: root.connected && !dismissProcess.running
                                    opacity: enabled ? 1 : 0.4
                                    focusable: true
                                    foreground: root.muted
                                    fontFamily: root.fontName
                                    onClicked: root.dismissJob(card.modelData)
                                }
                            }
                        }
                    }
                    Row {
                        visible: root.showHistory && root.historyRows.length > root.pageSize
                        width: parent.width
                        spacing: Style.space(8)
                        Ui.Button {
                            id: newerButton
                            width: (parent.width - parent.spacing) / 2
                            text: "← Newer"
                            enabled: root.historyPage > 0
                            opacity: enabled ? 1 : 0.4
                            focusable: true
                            foreground: root.fg
                            fontFamily: root.fontName
                            onClicked: { root.historyPage--; scroll.contentY = 0 }
                        }
                        Ui.Button {
                            id: olderButton
                            width: (parent.width - parent.spacing) / 2
                            text: "Older →"
                            enabled: (root.historyPage + 1) * root.pageSize < root.historyRows.length
                            opacity: enabled ? 1 : 0.4
                            focusable: true
                            foreground: root.fg
                            fontFamily: root.fontName
                            onClicked: { root.historyPage++; scroll.contentY = 0 }
                        }
                    }
                    Text {
                        width: parent.width
                        text: "Motion means activity; ≥ marks a partial time observation. A finished response does not mean the task is complete."
                        textFormat: Text.PlainText
                        wrapMode: Text.WordWrap
                        font.family: root.fontName; font.pixelSize: Style.font.body
                        color: root.muted
                    }
                }
            }
        }
    }
}
