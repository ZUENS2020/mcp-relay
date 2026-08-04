/**
 * CodeMirror 6 JSON editor for the mcp.json panel.
 * Vendored: /static/vendor/cm-json.js (codemirror + @codemirror/lang-json)
 */
import {
  EditorView,
  EditorState,
  Compartment,
  basicSetup,
  json,
  jsonParseLinter,
  linter,
  lintGutter,
  keymap,
  indentWithTab,
  indentUnit,
} from "./vendor/cm-json.js";

const editableComp = new Compartment();
const themeComp = new Compartment();

function themeExt(night) {
  const bg = night ? "#0b1220" : "#0a1a14";
  const fg = night ? "#e8edf5" : "#7bfeb8";
  const gut = night ? "#121a2a" : "#07140f";
  const line = night ? "#1e2a3d" : "#143328";
  const sel = night ? "#243552" : "#1a4a38";
  const caret = night ? "#9ec5fe" : "#7bfeb8";
  return EditorView.theme(
    {
      "&": {
        height: "100%",
        fontSize: "12px",
        backgroundColor: bg,
        color: fg,
      },
      ".cm-scroller": {
        fontFamily: "ui-monospace, SFMono-Regular, Menlo, Consolas, monospace",
        lineHeight: "1.55",
      },
      ".cm-content": { caretColor: caret },
      "&.cm-focused .cm-cursor": { borderLeftColor: caret },
      "&.cm-focused .cm-selectionBackground, .cm-selectionBackground, .cm-content ::selection": {
        backgroundColor: sel,
      },
      ".cm-gutters": {
        backgroundColor: gut,
        color: night ? "#8b9bb4" : "#5a9a7a",
        border: "none",
        borderRight: `1px solid ${line}`,
      },
      ".cm-activeLineGutter": { backgroundColor: sel },
      ".cm-activeLine": { backgroundColor: night ? "#151f30" : "#0e241c" },
      ".cm-matchingBracket": {
        outline: `1px solid ${caret}`,
        backgroundColor: "transparent",
      },
      ".cm-lintRange-error": { backgroundImage: "none", borderBottom: "2px wavy #ff6b6b" },
      ".cm-tooltip": { backgroundColor: gut, border: `1px solid ${line}`, color: fg },
    },
    { dark: true }
  );
}

function editableExt(readOnly) {
  return [EditorView.editable.of(!readOnly), EditorState.readOnly.of(readOnly)];
}

function formatJsonDoc(view) {
  const raw = view.state.doc.toString();
  try {
    const pretty = JSON.stringify(JSON.parse(raw), null, 2);
    if (pretty === raw) return true;
    view.dispatch({
      changes: { from: 0, to: view.state.doc.length, insert: pretty },
    });
    return true;
  } catch {
    return false;
  }
}

let view = null;

export const McpJsonEditor = {
  mount(el) {
    if (view) {
      view.destroy();
      view = null;
    }
    el.replaceChildren();
    const night = document.body.dataset.theme === "night";
    view = new EditorView({
      parent: el,
      state: EditorState.create({
        doc: "",
        extensions: [
          basicSetup,
          json(),
          linter(jsonParseLinter()),
          lintGutter(),
          indentUnit.of("  "),
          keymap.of([
            indentWithTab,
            {
              key: "Mod-Shift-f",
              run: (v) => {
                formatJsonDoc(v);
                return true;
              },
            },
          ]),
          themeComp.of(themeExt(night)),
          editableComp.of(editableExt(true)),
          EditorView.lineWrapping,
        ],
      }),
    });
  },
  getValue() {
    return view ? view.state.doc.toString() : "";
  },
  setValue(text) {
    if (!view) return;
    const next = text ?? "";
    if (view.state.doc.toString() === next) return;
    view.dispatch({
      changes: { from: 0, to: view.state.doc.length, insert: next },
    });
  },
  setReadOnly(ro) {
    if (!view) return;
    view.dispatch({ effects: editableComp.reconfigure(editableExt(!!ro)) });
  },
  setNight(night) {
    if (!view) return;
    view.dispatch({ effects: themeComp.reconfigure(themeExt(!!night)) });
  },
  format() {
    if (!view) return false;
    return formatJsonDoc(view);
  },
  focus() {
    view?.focus();
  },
};

window.McpJsonEditor = McpJsonEditor;
