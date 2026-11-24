import Editor from "@monaco-editor/react";

export interface YamlCodeEditorProps {
  readonly value: string;
  readonly onChange: (nextValue: string) => void;
  readonly readOnly?: boolean;
  readonly testMode?: boolean;
}

/**
 * Monaco YAML editor wrapper with deterministic textarea fallback for jsdom tests.
 */
export function YamlCodeEditor({
  value,
  onChange,
  readOnly = false,
  testMode = false,
}: YamlCodeEditorProps) {
  const isJsdom =
    testMode || (typeof navigator !== "undefined" && navigator.userAgent.includes("jsdom"));

  if (isJsdom) {
    return (
      <textarea
        aria-label="robot.yaml editor"
        className="h-full w-full resize-none bg-slate-950 p-3 font-mono text-xs text-slate-100 focus:outline-none"
        readOnly={readOnly}
        spellCheck={false}
        value={value}
        onChange={(event) => onChange(event.target.value)}
      />
    );
  }

  return (
    <Editor
      height="100%"
      defaultLanguage="yaml"
      theme="vs-dark"
      value={value}
      onChange={(next) => {
        if (next !== undefined) onChange(next);
      }}
      options={{
        fontSize: 13,
        minimap: { enabled: false },
        readOnly,
        scrollBeyondLastLine: false,
        tabSize: 2,
        wordWrap: "on",
      }}
    />
  );
}
