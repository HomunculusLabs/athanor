// Athanor greeter ({{ label }}). Staged by `athanor boot`, installed by
// `sudo athanor-system install` and run by greetd as: cage -s -- quickshell -p <dir>.
// It is laid out like hyprlock, so the login and the lock are the same room.
// If it ever fails to start, /usr/local/bin/athanor-greeter falls back to tuigreet.
import QtQuick
import Quickshell
import Quickshell.Services.Greetd

ShellRoot {
  id: shell

  readonly property string user: "{{ user }}"
  readonly property var command: ["uwsm", "start", "-e", "-D", "Hyprland", "hyprland.desktop"]

  readonly property color bg: "{{ bg }}"
  readonly property color fg: "{{ fg }}"
  readonly property color dim: "{{ dim }}"
  readonly property color active: "{{ active }}"
  readonly property color wrong: "{{ a1 }}"

  // The text column sits where hyprlock's does, right of the plate's engraving.
  readonly property int margin: {{ margin }}

  property bool busy: false
  property string failure: ""
  property string pending: ""

  function submit(password) {
    if (busy || password.length === 0) return
    pending = password
    busy = true
    failure = ""
    Greetd.createSession(user)
  }

  function ordinal(n) {
    if (n % 100 >= 10 && n % 100 <= 20) return "th"
    return ({ 1: "st", 2: "nd", 3: "rd" })[n % 10] || "th"
  }

  Connections {
    target: Greetd
    function onAuthMessage(message, error, responseRequired, echoResponse) {
      if (responseRequired) {
        Greetd.respond(shell.pending)
        shell.pending = ""
      } else if (error) {
        shell.failure = message
      }
    }
    function onAuthFailure(message) {
      shell.pending = ""
      shell.busy = false
      shell.failure = "The word is wrong."
    }
    function onReadyToLaunch() {
      Greetd.launch(shell.command)
    }
    function onError(error) {
      shell.pending = ""
      shell.busy = false
      shell.failure = error
    }
  }

  SystemClock {
    id: clock
    precision: SystemClock.Minutes
  }

  FloatingWindow {
    id: win
    visible: true
    color: shell.bg

    readonly property int colX: Math.round({{ lock_x }} * width / {{ screen_w }})

    Image {
      anchors.fill: parent
      source: "plate.png"
      fillMode: Image.Stretch
      smooth: false
    }

    Image {
      id: sigil
      x: win.colX
      y: shell.margin
      width: 88
      height: 88
      source: "sigil.png"
      smooth: false
    }

    Column {
      x: sigil.x + sigil.width + 16
      y: shell.margin + 12
      spacing: 8
      Text {
        text: "{{ host }}"
        color: shell.fg
        font.family: "Vellum"
        font.pixelSize: 24
        renderType: Text.NativeRendering
      }
      Text {
        text: "{{ fingerprint }}"
        color: shell.dim
        font.family: "Vellum"
        font.pixelSize: 24
        renderType: Text.NativeRendering
      }
    }

    // Ossuary Display is drawn for 32px; 192px lands every pixel of the textura.
    Text {
      id: clockText
      x: win.colX
      y: 210
      text: Qt.formatDateTime(clock.date, "HH:mm")
      color: shell.fg
      font.family: "Ossuary Display"
      font.pixelSize: 192
      renderType: Text.NativeRendering
    }

    Text {
      x: win.colX
      y: 456
      text: Qt.formatDateTime(clock.date, "dddd") + ", the " + clock.date.getDate()
            + shell.ordinal(clock.date.getDate()) + " of " + Qt.formatDateTime(clock.date, "MMMM")
      color: shell.fg
      font.family: "Vellum"
      font.pixelSize: 24
      renderType: Text.NativeRendering
    }

    Column {
      x: win.colX
      anchors.bottom: parent.bottom
      anchors.bottomMargin: 64
      spacing: 16

      Text {
        text: "@ {{ name }} {{ title }}, speak the word:"
        color: shell.fg
        font.family: "Vellum"
        font.pixelSize: 24
        renderType: Text.NativeRendering
      }

      Rectangle {
        id: field
        width: {{ text_w }}
        height: 44
        color: shell.bg
        border.width: 2
        border.color: shell.failure.length > 0 ? shell.wrong : shell.active
        clip: true

        TextInput {
          id: input
          anchors.fill: parent
          anchors.margins: 12
          focus: true
          enabled: !shell.busy
          echoMode: TextInput.Password
          passwordMaskDelay: 0
          color: "transparent"
          selectionColor: "transparent"
          selectedTextColor: "transparent"
          cursorDelegate: Item {}
          Component.onCompleted: forceActiveFocus()
          onTextChanged: if (text.length > 0) shell.failure = ""
          onAccepted: { var p = text; text = ""; shell.submit(p) }
          Keys.onEscapePressed: text = ""
        }

        Row {
          id: dots
          x: 16
          anchors.verticalCenter: parent.verticalCenter
          spacing: 6
          readonly property int most: Math.floor((field.width - 32) / 14)
          Repeater {
            model: Math.min(input.text.length, dots.most)
            Rectangle { width: 8; height: 8; color: shell.fg }
          }
        }
      }

      Text {
        text: shell.busy ? "The fire is lit…"
              : shell.failure.length > 0 ? shell.failure
              : "Ctrl+Alt+F3 for a plain login"
        color: shell.failure.length > 0 && !shell.busy ? shell.wrong : shell.dim
        font.family: "Vellum"
        font.pixelSize: 24
        renderType: Text.NativeRendering
      }
    }
  }
}
