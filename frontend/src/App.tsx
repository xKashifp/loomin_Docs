import React, { useEffect, useMemo, useRef, useState } from "react";
import "./styles.css";
import { EditorContent, useEditor } from "@tiptap/react";
import StarterKit from "@tiptap/starter-kit";
import { Markdown } from "@tiptap/markdown";

type ModelProfile = {
  id: string;
  displayName: string;
  chatModel: string;
  embedModel: string;
  maxContextTokens: number;
};

type Citation = {
  id: string;
  fileName: string;
  snippet: string;
  pageNumber?: number | null;
};

type ChatResponse = {
  request_id: string;
  retrieval_time_ms: number;
  token_generation_speed_tokens_per_second: number;
  answer: string;
  citations: Citation[];
  context_usage_pct?: number;
};

export default function App() {
  const editorDomRef = useRef<HTMLDivElement | null>(null);

  const backendBaseUrl = useMemo(() => {
    const host = window.location.hostname;
    // The backend is exposed on port 8000 in the docker-compose stack.
    return `${window.location.protocol}//${host}:8000`;
  }, []);

  const [models, setModels] = useState<ModelProfile[]>([]);
  const [activeModelId, setActiveModelId] = useState<string>("");
  const activeModel = useMemo(
    () => models.find((m) => m.id === activeModelId) ?? null,
    [models, activeModelId],
  );

  const [docId, setDocId] = useState<string>("doc-1");
  const [initialMarkdown] = useState<string>(
    "# Loomin-Docs\n\nOpen two tabs to see collaboration.\n\nSelect text and click Summarize / Improve.",
  );

  const editor = useEditor({
    extensions: [
      StarterKit,
      Markdown.configure({
        markedOptions: { gfm: true, breaks: false },
      }),
    ],
    content: initialMarkdown,
    contentType: "markdown",
    onUpdate: ({ editor }) => {
      const md = (editor.storage as any)?.markdown?.getMarkdown?.();
      if (typeof md === "string") {
        setEditorMarkdown(md);
      }
    },
  });

  const [editorMarkdown, setEditorMarkdown] = useState<string>(initialMarkdown);
  const [loadedMarkdown, setLoadedMarkdown] = useState<string | null>(null);
  const didApplyLoadedMarkdownRef = useRef<string | null>(null);

  const [sidebarTab, setSidebarTab] = useState<"chat" | "files">("chat");
  const [files, setFiles] = useState<
    { id: string; fileName: string; mimeType: string; uploadedAt: number }[]
  >([]);

  // AI sidebar state
  const [chatInput, setChatInput] = useState<string>("");
  const [chatMessages, setChatMessages] = useState<
    { role: "user" | "assistant"; content: string }[]
  >([{ role: "assistant", content: "Ready." }]);

  const [latestCitations, setLatestCitations] = useState<Citation[]>([]);
  const [tokenPct, setTokenPct] = useState<number>(0);
  const [tokenPctFromBackend, setTokenPctFromBackend] = useState<boolean>(false);
  const [isLoading, setIsLoading] = useState<boolean>(false);

  function getCurrentMarkdown(): string {
    const md = (editor as any)?.storage?.markdown?.getMarkdown?.();
    if (typeof md === "string" && md.trim().length >= 0) return md;
    return editorMarkdown;
  }

  useEffect(() => {
    // Load last persisted markdown from SQLite for the active docId.
    fetch(`${backendBaseUrl}/api/docs/${docId}`)
      .then((r) => r.json())
      .then((data) => {
        if (typeof data?.markdown === "string" && data.markdown.trim().length > 0) {
          setEditorMarkdown(data.markdown);
          setLoadedMarkdown(data.markdown);
        }
      })
      .catch(() => {
        // Ignore; local dev might not have an initialized SQLite doc.
      });
  }, [backendBaseUrl, docId]);

  useEffect(() => {
    if (!editor || loadedMarkdown == null) return;
    if (didApplyLoadedMarkdownRef.current === loadedMarkdown) return;
    didApplyLoadedMarkdownRef.current = loadedMarkdown;
    editor.commands.setContent(loadedMarkdown, false);
  }, [editor, loadedMarkdown]);

  useEffect(() => {
    fetch(`${backendBaseUrl}/api/models`)
      .then((r) => r.json())
      .then((data: ModelProfile[]) => {
        setModels(data);
        if (data[0]?.id) setActiveModelId(data[0].id);
      })
      .catch(() => {
        // Ignore; local dev might require setting different base URL.
      });
  }, []);

  useEffect(() => {
    if (sidebarTab !== "files") return;
    fetch(`${backendBaseUrl}/api/files`)
      .then((r) => r.json())
      .then((data) => setFiles(data))
      .catch(() => {
        // ignore
      });
  }, [sidebarTab]);

  useEffect(() => {
    if (tokenPctFromBackend) return;
    // Token usage placeholder: real implementation will request estimates from backend.
    const max = activeModel?.maxContextTokens ?? 4096;
    const approxTokens = Math.ceil(editorMarkdown.length / 4);
    setTokenPct(Math.min(100, Math.round((approxTokens / max) * 100)));
  }, [editorMarkdown, activeModel]);

  async function summarizeOrImprove(kind: "summarize" | "improve") {
    if (!editor) return;
    const { from, to } = editor.state.selection;
    const selection = editor.state.doc.textBetween(from, to, "\n").trim();
    if (!selection) {
      alert("Select some text in the editor first.");
      return;
    }

    setIsLoading(true);
    try {
      const resp = await fetch(
        `${backendBaseUrl}/api/assistant/${kind}`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            docId,
            modelId: activeModelId,
            selection,
            documentMarkdown: getCurrentMarkdown(),
          }),
        },
      );
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const data = await resp.json();
      setLatestCitations(data.citations ?? []);
      if (typeof data.context_usage_pct === "number") {
        setTokenPct(data.context_usage_pct);
        setTokenPctFromBackend(true);
      }
      if (typeof data.replacementMarkdown === "string") {
        // Replace selection with returned Markdown text (inserted as text for now).
        editor
          .chain()
          .focus()
          .insertContentAt(
            { from, to },
            data.replacementMarkdown,
            { contentType: "markdown" },
          )
          .run();
      }
    } catch {
      alert("AI action failed (backend not ready).");
    } finally {
      setIsLoading(false);
    }
  }

  async function onSendChat() {
    const text = chatInput.trim();
    if (!text) return;
    setChatInput("");

    const userMsg = { role: "user" as const, content: text };
    const nextMessages = [...chatMessages, userMsg];
    setChatMessages(nextMessages);
    setLatestCitations([]);

    setIsLoading(true);
    try {
      const resp = await fetch(`${backendBaseUrl}/api/assistant/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          docId,
          modelId: activeModelId,
          messages: nextMessages,
          documentMarkdown: getCurrentMarkdown(),
        }),
      });
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const data = (await resp.json()) as ChatResponse;
      setChatMessages((prev) => [
        ...prev,
        { role: "assistant", content: data.answer },
      ]);
      if (typeof data.context_usage_pct === "number") {
        setTokenPct(data.context_usage_pct);
        setTokenPctFromBackend(true);
      }
      setLatestCitations(data.citations ?? []);
    } catch {
      setChatMessages((prev) => [
        ...prev,
        { role: "assistant", content: "Chat failed (backend not ready)." },
      ]);
      setLatestCitations([]);
    } finally {
      setIsLoading(false);
    }
  }

  async function onUploadFile(file: File) {
    const fd = new FormData();
    fd.append("file", file);
    setIsLoading(true);
    try {
      const resp = await fetch(`${backendBaseUrl}/api/files/upload`, {
        method: "POST",
        body: fd,
      });
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      await resp.json();
      const refresh = await fetch(`${backendBaseUrl}/api/files`);
      const data = await refresh.json();
      setFiles(data);
    } catch {
      alert("File upload failed (backend not ready).");
    } finally {
      setIsLoading(false);
    }
  }

  async function onDeleteFile(fileId: string) {
    setIsLoading(true);
    try {
      const resp = await fetch(`${backendBaseUrl}/api/files/${fileId}`, {
        method: "DELETE",
      });
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const refresh = await fetch(`${backendBaseUrl}/api/files`);
      const data = await refresh.json();
      setFiles(data);
    } catch {
      alert("Delete failed (backend not ready).");
    } finally {
      setIsLoading(false);
    }
  }

  function onCitationClick(c: Citation) {
    // Best-effort: focus editor (rich text doesn't map to plain index reliably).
    editor?.commands.focus();
    // Also make citations "clickable" by copying snippet (best-effort).
    navigator.clipboard?.writeText?.(c.snippet).catch(() => {
      /* ignore */
    });
  }

  return (
    <div className="appRoot">
      <header className="topBar">
        <div className="brand">Loomin-Docs</div>
        <div className="modelSelect">
          <select
            value={activeModelId}
            onChange={(e) => setActiveModelId(e.target.value)}
          >
            {models.map((m) => (
              <option key={m.id} value={m.id}>
                {m.displayName}
              </option>
            ))}
          </select>
        </div>
        <div className="tokenViz">
          Context: <strong>{tokenPct}%</strong>
        </div>
      </header>

      <main className="mainGrid">
        <section className="editorPane">
          <div
            className="tiptapWrap"
            ref={editorDomRef}
            onKeyDown={() => setTokenPctFromBackend(false)}
          >
            <EditorContent editor={editor} />
          </div>
          <div className="editorActions">
            <button type="button" disabled={isLoading} onClick={() => summarizeOrImprove("summarize")}>
              Summarize
            </button>
            <button type="button" disabled={isLoading} onClick={() => summarizeOrImprove("improve")}>
              Improve
            </button>
          </div>
        </section>

        <aside className="sidebar">
          <div className="sidebarHeader">AI Assistant</div>
          <div className="sidebarTabs">
            <button
              type="button"
              className={sidebarTab === "chat" ? "tabActive" : "tab"}
              onClick={() => setSidebarTab("chat")}
            >
              Chat
            </button>
            <button
              type="button"
              className={sidebarTab === "files" ? "tabActive" : "tab"}
              onClick={() => setSidebarTab("files")}
            >
              Files
            </button>
          </div>

          <div className="selectionActions">
            <div className="selectionActionsTitle">Selection Actions</div>
            <div className="selectionActionsRow">
              <button
                type="button"
                disabled={isLoading}
                onClick={() => summarizeOrImprove("summarize")}
              >
                Summarize
              </button>
              <button
                type="button"
                disabled={isLoading}
                onClick={() => summarizeOrImprove("improve")}
              >
                Improve
              </button>
            </div>
          </div>

          {sidebarTab === "chat" ? (
            <>
              <div className="chatList">
                {chatMessages.map((m, idx) => (
                  <div
                    key={`${m.role}-${idx}`}
                    className={m.role === "user" ? "chatUser" : "chatAsst"}
                  >
                    <div className="chatRole">{m.role}</div>
                    <div className="chatContent">{m.content}</div>
                  </div>
                ))}
              </div>

              <div className="chatComposer">
                <input
                  className="chatInput"
                  value={chatInput}
                  placeholder="Ask about the active document..."
                  onChange={(e) => setChatInput(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") onSendChat();
                  }}
                />
                <button
                  type="button"
                  className="sendBtn"
                  disabled={isLoading}
                  onClick={onSendChat}
                >
                  Send
                </button>
              </div>

              <div className="citationsBlock">
                <div className="citationsTitle">Citations</div>
                {latestCitations.length === 0 ? (
                  <div className="citationsEmpty">No citations yet.</div>
                ) : (
                  <div className="citationsList">
                    {latestCitations.map((c) => (
                      <div key={c.id} className="citationCard">
                        <button
                          type="button"
                          className="citationBtn"
                          onClick={() => onCitationClick(c)}
                        >
                          {c.id} · {c.fileName}
                          {typeof c.pageNumber === "number" ? ` · p.${c.pageNumber}` : ""}
                        </button>
                        <div className="citationSnippet">{c.snippet}</div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </>
          ) : (
            <div className="filesPane">
              <div className="filesHeader">RAG Files</div>
              <div className="filesList">
                {files.map((f) => (
                  <div key={f.id} className="fileRow">
                    <div className="fileName">{f.fileName}</div>
                    <div className="fileMeta">{f.mimeType}</div>
                    <div style={{ marginTop: 8 }}>
                      <button
                        type="button"
                        className="deleteBtn"
                        disabled={isLoading}
                        onClick={() => onDeleteFile(f.id)}
                      >
                        Delete
                      </button>
                    </div>
                  </div>
                ))}
              </div>
              <div className="uploadBox">
                <input
                  type="file"
                  accept=".pdf,.md,.txt"
                  onChange={(e) => {
                    const file = e.target.files?.[0];
                    if (file) onUploadFile(file);
                    e.currentTarget.value = "";
                  }}
                  disabled={isLoading}
                />
              </div>
            </div>
          )}
        </aside>
      </main>
    </div>
  );
}

