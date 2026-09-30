import { afterEach, describe, expect, it, vi } from "vitest";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { renderToStaticMarkup } from "react-dom/server";
import DiscussionView, { type StreamingAgent } from "./DiscussionView";
import type { DiscussionMessage } from "./types";

const streamingAgent: StreamingAgent = {
  message_id: "streaming-1",
  agent_index: 0,
  agent_name: "Agent 1",
  client_id: "agent-1",
  perspective_number: 1,
  theory_label: "Präzise",
  color: "#00c0c0",
  text: "",
  is_complete: false,
  error: null,
};
const mountedRoots: Root[] = [];

function makeUserMessage(overrides: Partial<DiscussionMessage> = {}): DiscussionMessage {
  return {
    id: "u1",
    role: "user",
    content: "Meine Frage",
    round_number: 1,
    agent_name: null,
    theory_label: null,
    color: null,
    agent_index: null,
    note: "",
    include_in_agent_context: true,
    ...overrides,
  };
}

function makeAgentMessage(overrides: Partial<DiscussionMessage> = {}): DiscussionMessage {
  return {
    id: "a1",
    role: "agent",
    content: "Antwort",
    round_number: 1,
    agent_name: "Agent 1",
    theory_label: "Präzise",
    color: "#00c0c0",
    agent_index: 0,
    note: "",
    include_in_agent_context: true,
    ...overrides,
  };
}

function makeSynthesisMessage(overrides: Partial<DiscussionMessage> = {}): DiscussionMessage {
  return {
    id: "s1",
    role: "synthesis",
    content: "- **Shared finding:** A substantive conclusion.",
    round_number: 1,
    agent_name: null,
    theory_label: null,
    color: null,
    agent_index: null,
    note: "",
    include_in_agent_context: false,
    ...overrides,
  };
}

function mountIntoContainer(element: React.ReactElement): {
  container: HTMLDivElement;
  root: Root;
} {
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root = createRoot(container);
  act(() => root.render(element));
  mountedRoots.push(root);
  return { container, root };
}

afterEach(() => {
  act(() => mountedRoots.splice(0).forEach((root) => root.unmount()));
  document.body.innerHTML = "";
});

describe("DiscussionView answer-mode notice", () => {
  it("keeps the Independent Answers explanation visible while streaming and after completion", () => {
    const props = {
      messages: [] as DiscussionMessage[],
      currentAgents: [],
      independentAnswers: true,
      onContinue: () => undefined,
      onSetNote: () => undefined,
      onSetContextInclusion: () => undefined,
    };
    const { container, root } = mountIntoContainer(
      <DiscussionView {...props} streamingAgents={[streamingAgent]} isStreaming />,
    );
    const notice = container.querySelector<HTMLElement>('.discussion-mode-notice[role="note"]');
    expect(notice).not.toBeNull();
    expect(notice?.querySelector(".material-symbol")?.textContent).toBe("help");
    expect(notice?.getAttribute("aria-labelledby")).toBe("discussion-independent-answers-title");
    expect(
      notice!.compareDocumentPosition(container.querySelector(".discussion-messages")!) &
        Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBe(Node.DOCUMENT_POSITION_FOLLOWING);

    act(() =>
      root.render(
        <DiscussionView
          {...props}
          messages={[makeAgentMessage()]}
          streamingAgents={[]}
          isStreaming={false}
        />,
      ),
    );
    expect(container.querySelector('.discussion-mode-notice[role="note"]')).not.toBeNull();

    act(() =>
      root.render(
        <DiscussionView
          {...props}
          independentAnswers={false}
          messages={[makeAgentMessage()]}
          streamingAgents={[]}
          isStreaming={false}
        />,
      ),
    );
    expect(container.querySelector(".discussion-mode-notice")).toBeNull();
  });
});

describe("DiscussionView streaming message state", () => {
  it("announces lifecycle transitions without making streamed tokens live", () => {
    const baseProps = {
      messages: [] as DiscussionMessage[],
      currentAgents: [],
      onContinue: () => undefined,
      onSetNote: () => undefined,
      onSetContextInclusion: () => undefined,
    };
    const { container, root } = mountIntoContainer(
      <DiscussionView {...baseProps} streamingAgents={[]} isStreaming={false} />,
    );

    act(() =>
      root.render(<DiscussionView {...baseProps} streamingAgents={[streamingAgent]} isStreaming />),
    );
    const status = container.querySelector('.visually-hidden[role="status"]')!;
    expect(status.textContent).toBe("Die Diskussionsrunde wurde gestartet.");
    const announcementNode = status.firstElementChild;

    act(() =>
      root.render(
        <DiscussionView
          {...baseProps}
          streamingAgents={[{ ...streamingAgent, text: "Ein neues Token" }]}
          isStreaming
        />,
      ),
    );
    expect(status.textContent).toBe("Die Diskussionsrunde wurde gestartet.");
    expect(status.firstElementChild).toBe(announcementNode);

    act(() =>
      root.render(
        <DiscussionView
          {...baseProps}
          streamingAgents={[{ ...streamingAgent, text: "Fertig", is_complete: true }]}
          isStreaming
        />,
      ),
    );
    expect(status.textContent).toContain("Perspektive 1, Präzise, ist abgeschlossen.");

    act(() =>
      root.render(
        <DiscussionView
          {...baseProps}
          messages={[makeAgentMessage({ status: "completed" })]}
          streamingAgents={[]}
          isStreaming={false}
        />,
      ),
    );
    expect(status.textContent).toBe("Die Diskussionsrunde ist abgeschlossen.");
  });

  it("announces a new streaming failure but does not replay persisted historical errors", () => {
    const props = {
      messages: [] as DiscussionMessage[],
      currentAgents: [],
      onContinue: () => undefined,
      onSetNote: () => undefined,
      onSetContextInclusion: () => undefined,
    };
    const { container, root } = mountIntoContainer(
      <DiscussionView {...props} streamingAgents={[streamingAgent]} isStreaming />,
    );
    act(() =>
      root.render(
        <DiscussionView
          {...props}
          streamingAgents={[{ ...streamingAgent, error: "connection failed" }]}
          isStreaming
        />,
      ),
    );
    expect(container.querySelector('.visually-hidden[role="alert"]')?.textContent).toContain(
      "Perspektive 1, Präzise, ist fehlgeschlagen.",
    );

    act(() =>
      root.render(
        <DiscussionView
          {...props}
          messages={[makeAgentMessage({ error: "old failure", status: "failed" })]}
          streamingAgents={[]}
          isStreaming={false}
        />,
      ),
    );
    expect(container.querySelector(".message-error")?.getAttribute("role")).toBeNull();
  });

  it("does not present an intentional interruption as an Integrated AI failure", () => {
    const { container } = mountIntoContainer(
      <DiscussionView
        messages={[
          makeAgentMessage({ status: "completed" }),
          makeAgentMessage({
            id: "a2",
            agent_index: 1,
            status: "interrupted",
            error: "Discussion generation was interrupted.",
            error_code: "discussion_generation_interrupted",
          }),
        ]}
        streamingAgents={[]}
        isStreaming={false}
        usesIntegratedAI
        currentAgents={[]}
        onContinue={() => undefined}
        onSetNote={() => undefined}
        onSetContextInclusion={() => undefined}
      />,
    );

    expect(container.textContent).toContain("Runde unterbrochen — Teilantwort erhalten");
    expect(container.textContent).not.toContain("Die letzte Runde ist fehlgeschlagen");
    expect(container.textContent).not.toContain("Dienst unter „Integrierte KI“ starten");
    expect(container.textContent).not.toContain("„Integrierte KI“ öffnen");
  });

  it("retains Integrated AI repair guidance for genuine failed responses", () => {
    const { container } = mountIntoContainer(
      <DiscussionView
        messages={[
          makeAgentMessage({
            status: "failed",
            error: "connection failed",
            error_code: "local_ai_not_running",
          }),
        ]}
        streamingAgents={[]}
        isStreaming={false}
        usesIntegratedAI
        currentAgents={[]}
        onContinue={() => undefined}
        onSetNote={() => undefined}
        onSetContextInclusion={() => undefined}
      />,
    );

    expect(container.textContent).toContain("Die letzte Runde ist fehlgeschlagen");
    expect(container.textContent).toContain("„Integrierte KI“ öffnen");
  });

  it("uses only the inline streaming caret, without a redundant header spinner", () => {
    const html = renderToStaticMarkup(
      <DiscussionView
        messages={[]}
        streamingAgents={[streamingAgent]}
        isStreaming
        currentAgents={[]}
        onContinue={() => undefined}
        onSetNote={() => undefined}
        onSetContextInclusion={() => undefined}
      />,
    );

    expect(html).toContain('class="streaming-caret"');
    expect(html).not.toContain("message-stream-spinner");
    expect(html).not.toContain("⠋");
    expect(html).not.toContain("Perspektiven antworten");
  });

  it("renders bare material line references and ranges as inline code", () => {
    const html = renderToStaticMarkup(
      <DiscussionView
        messages={[
          makeAgentMessage({
            content: "Evidence at Z0024 and Z0004-Z0009; already formatted as `Z0067`.",
          }),
        ]}
        streamingAgents={[]}
        isStreaming={false}
        currentAgents={[]}
        onContinue={() => undefined}
        onSetNote={() => undefined}
        onSetContextInclusion={() => undefined}
      />,
    );

    expect(html.match(/<code>Z0024<\/code>/g)).toHaveLength(1);
    expect(html.match(/<code>Z0004-Z0009<\/code>/g)).toHaveLength(1);
    expect(html.match(/<code>Z0067<\/code>/g)).toHaveLength(1);
  });

  it("routes Integrated AI failures to Integrated AI recovery copy", () => {
    const html = renderToStaticMarkup(
      <DiscussionView
        messages={[
          makeAgentMessage({
            content: "",
            error: "raw connection detail",
            error_code: "agent_generation_failed",
          }),
        ]}
        streamingAgents={[]}
        isStreaming={false}
        currentAgents={[]}
        usesIntegratedAI
        onContinue={() => undefined}
        onSetNote={() => undefined}
        onSetContextInclusion={() => undefined}
      />,
    );

    expect(html).toContain("„Integrierte KI“ öffnen");
    expect(html).not.toContain("unter „Externe KI“ prüfen");
    expect(html).toContain("raw connection detail");
    expect(html).not.toContain("Leere Antwort");
  });

  it("explains context overflow without suggesting Integrated AI repair", () => {
    const html = renderToStaticMarkup(
      <DiscussionView
        messages={[
          makeAgentMessage({
            content: "",
            error: "context_limit_exceeded",
            error_code: "context_limit_exceeded",
            error_params: {
              input_tokens: 43_166,
              available_input_tokens: 28_672,
              context_tokens: 32_768,
              reserved_output_tokens: 4_096,
            },
          }),
        ]}
        streamingAgents={[]}
        isStreaming={false}
        currentAgents={[]}
        usesIntegratedAI
        onContinue={() => undefined}
        onSetNote={() => undefined}
        onSetContextInclusion={() => undefined}
      />,
    );

    expect(html).toContain("43.166 Eingabe-Tokens");
    expect(html).toContain("frühere Diskussionsantworten aus dem Kontext aus");
    expect(html).not.toContain("Dienst starten oder reparieren");
    expect(html).not.toContain("„Integrierte KI“ öffnen");
  });

  it("normalizes bare line-range dashes and perspective references as inline code", () => {
    const html = renderToStaticMarkup(
      <DiscussionView
        messages={[
          makeAgentMessage({
            content:
              "See Z0054‐Z0056, Z0100‑Z0102, Z0200–Z0202 and Z0300—Z0302; reply to Perspective 1. Existing `Perspective 2` and `Z0400‑Z0402` stay unchanged.",
          }),
        ]}
        streamingAgents={[]}
        isStreaming={false}
        currentAgents={[]}
        onContinue={() => undefined}
        onSetNote={() => undefined}
        onSetContextInclusion={() => undefined}
      />,
    );

    expect(html).toContain("<code>Z0054-Z0056</code>");
    expect(html).toContain("<code>Z0100-Z0102</code>");
    expect(html).toContain("<code>Z0200-Z0202</code>");
    expect(html).toContain("<code>Z0300-Z0302</code>");
    expect(html.match(/<code>Perspective 1<\/code>/g)).toHaveLength(1);
    expect(html.match(/<code>Perspective 2<\/code>/g)).toHaveLength(1);
    expect(html).toContain("<code>Z0400‑Z0402</code>");
  });
});

describe("DiscussionView synthesis cards", () => {
  it("uses the dedicated synthesis card without context or follow-up controls", () => {
    const { container } = mountIntoContainer(
      <DiscussionView
        messages={[makeSynthesisMessage()]}
        streamingAgents={[]}
        isStreaming={false}
        currentAgents={[]}
        onContinue={() => undefined}
        onSetNote={() => undefined}
        onSetContextInclusion={() => undefined}
      />,
    );

    const card = container.querySelector(".message-synthesis");
    expect(card).not.toBeNull();
    expect(card?.textContent).toContain("Synthese · Runde 1");
    expect(card?.querySelector(".material-symbol")).not.toBeNull();
    expect(card?.querySelector('input[type="checkbox"]')).toBeNull();
    expect(card?.querySelector(".message-bezugspunkt-btn")).toBeNull();
  });

  it("renders Markdown list markers in synthesis content", () => {
    const html = renderToStaticMarkup(
      <DiscussionView
        messages={[
          makeSynthesisMessage({ content: "- First finding\n- Second finding\n\n1. First step" }),
        ]}
        streamingAgents={[]}
        isStreaming={false}
        currentAgents={[]}
        onContinue={() => undefined}
        onSetNote={() => undefined}
        onSetContextInclusion={() => undefined}
      />,
    );

    expect(html).toContain("<ul>");
    expect(html).toContain("<ol>");
    expect(html).toContain("<li>First finding</li>");
  });

  it("formats bare material line references in synthesis content", () => {
    const html = renderToStaticMarkup(
      <DiscussionView
        messages={[makeSynthesisMessage({ content: "- Befund aus Z0035-Z0037." })]}
        streamingAgents={[]}
        isStreaming={false}
        currentAgents={[]}
        onContinue={() => undefined}
        onSetNote={() => undefined}
        onSetContextInclusion={() => undefined}
      />,
    );

    expect(html).toContain("<code>Z0035-Z0037</code>");
  });

  it("renders an all-failed synthesis as one canonical failed card", () => {
    const { container } = mountIntoContainer(
      <DiscussionView
        messages={[
          makeSynthesisMessage({
            content: "",
            status: "failed",
            error_code: "synthesis_no_usable_contributions",
          }),
        ]}
        streamingAgents={[]}
        isStreaming={false}
        currentAgents={[]}
        onContinue={() => undefined}
        onSetNote={() => undefined}
        onSetContextInclusion={() => undefined}
      />,
    );

    const card = container.querySelector(".message-synthesis");
    expect(card?.textContent).toContain("Synthese wurde nicht gestartet");
    expect(card?.textContent).toContain("Runde fehlgeschlagen");
    expect(card?.querySelectorAll(".message-error")).toHaveLength(1);
    expect(card?.textContent).not.toContain("Leere Antwort");
  });

  it("keeps synthesis cards out of the user-excluded context styling", () => {
    const { container } = mountIntoContainer(
      <DiscussionView
        messages={[makeSynthesisMessage({ include_in_agent_context: false })]}
        streamingAgents={[]}
        isStreaming={false}
        currentAgents={[]}
        onContinue={() => undefined}
        onSetNote={() => undefined}
        onSetContextInclusion={() => undefined}
      />,
    );

    expect(container.querySelector(".message-synthesis.is-excluded-from-context")).toBeNull();
  });

  it("uses synthesis-specific error copy", () => {
    const { container } = mountIntoContainer(
      <DiscussionView
        messages={[
          makeSynthesisMessage({ content: "", error_code: "synthesis_generation_failed" }),
        ]}
        streamingAgents={[]}
        isStreaming={false}
        currentAgents={[]}
        onContinue={() => undefined}
        onSetNote={() => undefined}
        onSetContextInclusion={() => undefined}
      />,
    );

    expect(container.textContent).toContain("Synthesefehler:");
    expect(container.textContent).toContain("Die Synthese konnte nicht erzeugt werden.");
    expect(container.textContent).not.toContain("Perspektivenfehler:");
  });
});

describe("DiscussionView follow-up controls", () => {
  it("shows and locks the Integrated AI preflight state", () => {
    const { container } = mountIntoContainer(
      <DiscussionView
        messages={[makeUserMessage()]}
        streamingAgents={[]}
        isStreaming={false}
        isContinuePending
        followUpDraft="Continue after startup"
        onContinue={() => undefined}
        onSetNote={() => undefined}
        onSetContextInclusion={() => undefined}
      />,
    );

    const followup = container.querySelector(".followup-area textarea") as HTMLTextAreaElement;
    const button = container.querySelector(
      ".followup-area .ds-button--primary",
    ) as HTMLButtonElement;
    expect(followup.disabled).toBe(true);
    expect(button.disabled).toBe(true);
    expect(button.textContent).toContain("Die integrierte KI wird gestartet");
  });

  it("retains a follow-up when preflight blocks continuation", async () => {
    const onContinue = vi.fn().mockResolvedValue(false);
    const { container } = mountIntoContainer(
      <DiscussionView
        messages={[makeUserMessage()]}
        streamingAgents={[]}
        isStreaming={false}
        onContinue={onContinue}
        onSetNote={() => undefined}
        onSetContextInclusion={() => undefined}
      />,
    );
    const followup = container.querySelector(".followup-area textarea") as HTMLTextAreaElement;
    const setter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value")?.set;
    setter?.call(followup, "Retry this safely");
    act(() => followup.dispatchEvent(new Event("input", { bubbles: true })));

    await act(async () => {
      (container.querySelector(".followup-area .ds-button--primary") as HTMLButtonElement).click();
      await Promise.resolve();
    });

    expect(onContinue).toHaveBeenCalledWith("Retry this safely", null, null);
    expect(followup.value).toBe("Retry this safely");
  });

  it("uses a contained text selection as the reference and omits assessment boilerplate", () => {
    const { container } = mountIntoContainer(
      <DiscussionView
        messages={[makeAgentMessage({ content: "First sentence. Selected sentence." })]}
        streamingAgents={[]}
        isStreaming={false}
        currentAgents={[]}
        onContinue={() => undefined}
        onSetNote={() => undefined}
        onSetContextInclusion={() => undefined}
      />,
    );

    const content = container.querySelector(".message-content") as HTMLElement;
    const textNode = content.querySelector("p")?.firstChild as Text;
    const selection = window.getSelection();
    const range = document.createRange();
    range.setStart(textNode, 16);
    range.setEnd(textNode, textNode.textContent?.length ?? 0);
    selection?.removeAllRanges();
    selection?.addRange(range);

    act(() => (container.querySelector(".message-bezugspunkt-btn") as HTMLButtonElement).click());

    const followup = container.querySelector(".followup-area textarea") as HTMLTextAreaElement;
    expect(followup.value).toContain("`Perspective ?`");
    expect(followup.value).toContain("> Selected sentence.");
    expect(followup.value).not.toContain("Präzise");
    expect(followup.value).not.toContain("Assess whether");
    expect(container.querySelector(".message-bezugspunkt-icon")?.textContent).toBe("south_east");
    expect(container.querySelector(".message-note-area")).not.toBeNull();
  });

  it("appends a generated reference after existing follow-up text", () => {
    const { container } = mountIntoContainer(
      <DiscussionView
        messages={[makeAgentMessage({ content: "First sentence. Selected sentence." })]}
        streamingAgents={[]}
        isStreaming={false}
        currentAgents={[]}
        onContinue={() => undefined}
        onSetNote={() => undefined}
        onSetContextInclusion={() => undefined}
      />,
    );

    const followup = container.querySelector(".followup-area textarea") as HTMLTextAreaElement;
    const setter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value")?.set;
    setter?.call(followup, "Keep this instruction");
    act(() => followup.dispatchEvent(new Event("input", { bubbles: true })));

    act(() => (container.querySelector(".message-bezugspunkt-btn") as HTMLButtonElement).click());

    expect(followup.value).toBe(
      "Keep this instruction\n\nIn der nächsten Runde bitte diesem Punkt aus der Diskussion besondere Aufmerksamkeit widmen:\n\n`Perspective ?`\n\n> First sentence. Selected sentence.",
    );
  });

  it("keeps multiline and truncated references inside a blockquote", () => {
    const { container } = mountIntoContainer(
      <DiscussionView
        messages={[
          makeAgentMessage({
            content: `First line.\nSecond line.\n\n${"x".repeat(1600)}`,
            perspective_number: 3,
            theory_label: "Skepticism",
          }),
        ]}
        streamingAgents={[]}
        isStreaming={false}
        currentAgents={[]}
        onContinue={() => undefined}
        onSetNote={() => undefined}
        onSetContextInclusion={() => undefined}
      />,
    );

    act(() => (container.querySelector(".message-bezugspunkt-btn") as HTMLButtonElement).click());

    const followup = container.querySelector(".followup-area textarea") as HTMLTextAreaElement;
    expect(followup.value).toContain("`Perspective 3`");
    expect(followup.value).not.toContain("Skepticism");
    expect(followup.value).toContain("> First line.\n> Second line.\n> \n>");
    expect(followup.value).toContain("> [... truncated ...]");
  });

  it("renders Moderator messages as Markdown paragraphs and blockquotes", () => {
    const html = renderToStaticMarkup(
      <DiscussionView
        messages={[
          makeUserMessage({
            content: "First paragraph with `Perspective 1`.\n\n> Referenced response.",
          }),
        ]}
        streamingAgents={[]}
        isStreaming={false}
        currentAgents={[]}
        onContinue={() => undefined}
        onSetNote={() => undefined}
        onSetContextInclusion={() => undefined}
      />,
    );

    expect(html).toContain("<p>First paragraph with <code>Perspective 1</code>.</p>");
    expect(html).toContain("<blockquote>\n<p>Referenced response.</p>\n</blockquote>");
  });

  it("shows the human-reflection disclaimer only after a discussion round has finished", () => {
    const props = {
      messages: [makeUserMessage()],
      streamingAgents: [],
      onContinue: () => undefined,
      onSetNote: () => undefined,
      onSetContextInclusion: () => undefined,
    };
    const streamingHtml = renderToStaticMarkup(<DiscussionView {...props} isStreaming />);
    const completedHtml = renderToStaticMarkup(<DiscussionView {...props} isStreaming={false} />);

    expect(streamingHtml).not.toContain("Wahrscheinlichkeit ersetzt keine menschliche Reflexion.");
    expect(completedHtml).toContain("Wahrscheinlichkeit ersetzt keine menschliche Reflexion.");
    expect(completedHtml).toContain("keine Evidenz oder Schlussfolgerungen.");
  });

  it("uses the concise next-round direction placeholder", () => {
    const html = renderToStaticMarkup(
      <DiscussionView
        messages={[makeUserMessage()]}
        streamingAgents={[]}
        isStreaming={false}
        onContinue={() => undefined}
        onSetNote={() => undefined}
        onSetContextInclusion={() => undefined}
      />,
    );

    expect(html).toContain('placeholder="Anweisungen für die nächste Diskussionsrunde geben …"');
  });

  it("renders configured text-only quick actions and inserts their verbatim prompt", () => {
    const { container } = mountIntoContainer(
      <DiscussionView
        messages={[makeUserMessage()]}
        streamingAgents={[]}
        isStreaming={false}
        quickActions={[{ id: "inspect", label: "Inspect", prompt: "Inspect the evidence." }]}
        onContinue={() => undefined}
        onSetNote={() => undefined}
        onSetContextInclusion={() => undefined}
      />,
    );

    const action = container.querySelector(".quick-prompt-chip") as HTMLButtonElement;
    expect(action.textContent).toBe("Inspect");
    expect(action.querySelector(".material-symbol")).toBeNull();
    act(() => action.click());
    expect((container.querySelector(".followup-area textarea") as HTMLTextAreaElement).value).toBe(
      "Inspect the evidence.",
    );
  });

  it("localizes unchanged shipped labels while keeping their prompts in English", () => {
    const { container } = mountIntoContainer(
      <DiscussionView
        messages={[makeUserMessage()]}
        streamingAgents={[]}
        isStreaming={false}
        quickActions={[
          {
            id: "debate",
            label: "Debate",
            prompt: "Continue the discussion.",
            origin: "shipped_default",
          },
        ]}
        onContinue={() => undefined}
        onSetNote={() => undefined}
        onSetContextInclusion={() => undefined}
      />,
    );

    const action = container.querySelector(".quick-prompt-chip") as HTMLButtonElement;
    expect(action.textContent).toBe("Diskutieren");
    act(() => action.click());
    expect((container.querySelector(".followup-area textarea") as HTMLTextAreaElement).value).toBe(
      "Continue the discussion.",
    );
  });

  it("does not submit a follow-up with Ctrl/Cmd+Enter", () => {
    const onContinue = vi.fn();
    const { container } = mountIntoContainer(
      <DiscussionView
        messages={[makeUserMessage()]}
        streamingAgents={[]}
        isStreaming={false}
        onContinue={onContinue}
        onSetNote={() => undefined}
        onSetContextInclusion={() => undefined}
      />,
    );

    const textarea = container.querySelector(".followup-area textarea") as HTMLTextAreaElement;
    act(() =>
      textarea.dispatchEvent(
        new KeyboardEvent("keydown", { key: "Enter", ctrlKey: true, bubbles: true }),
      ),
    );
    expect(onContinue).not.toHaveBeenCalled();
  });
});

describe("DiscussionView note context controls", () => {
  it("labels note and follow-up textareas and restores focus after saving a note", () => {
    const onSetNote = vi.fn();
    const { container } = mountIntoContainer(
      <DiscussionView
        messages={[makeAgentMessage()]}
        streamingAgents={[]}
        isStreaming={false}
        currentAgents={[]}
        onContinue={() => undefined}
        onSetNote={onSetNote}
        onSetContextInclusion={() => undefined}
      />,
    );
    expect(container.querySelector('label[for="discussion-follow-up"]')?.textContent).toContain(
      "Anweisungen für die nächste Runde",
    );
    const addNote = container.querySelector(".note-add-btn") as HTMLButtonElement;
    act(() => addNote.click());
    expect(container.querySelector('label[for="discussion-note-a1"]')?.textContent).toBe(
      "Notiz bearbeiten",
    );
    const editor = container.querySelector(".note-editor textarea") as HTMLTextAreaElement;
    const setter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value")!.set!;
    setter.call(editor, "Human note");
    act(() => editor.dispatchEvent(new Event("input", { bubbles: true })));
    act(() =>
      Array.from(container.querySelectorAll<HTMLButtonElement>(".note-editor button"))
        .find((button) => button.textContent === "Speichern")!
        .click(),
    );
    expect(onSetNote).toHaveBeenCalledWith("a1", "Human note", false);
    expect(document.activeElement).toBe(container.querySelector(".note-add-btn"));
  });

  it("renders note context as an explicit status on the saved note", () => {
    const { container } = mountIntoContainer(
      <DiscussionView
        messages={[
          makeAgentMessage({
            note: "Human qualification",
            include_note_in_agent_context: true,
          }),
        ]}
        streamingAgents={[]}
        isStreaming={false}
        currentAgents={[]}
        onContinue={() => undefined}
        onSetNote={() => undefined}
        onSetContextInclusion={() => undefined}
      />,
    );

    const status = container.querySelector(".message-note-context-state");
    expect(status?.className).toContain("is-included");
    expect(status?.getAttribute("data-context-state")).toBe("included");
    expect(status?.textContent).toBe("Im Diskussionskontext");
    expect(container.textContent).not.toContain("Agentenkontext");
  });

  it("does not add a context notice to a note that is not included", () => {
    const { container } = mountIntoContainer(
      <DiscussionView
        messages={[makeAgentMessage({ note: "Private qualification" })]}
        streamingAgents={[]}
        isStreaming={false}
        currentAgents={[]}
        onContinue={() => undefined}
        onSetNote={() => undefined}
        onSetContextInclusion={() => undefined}
      />,
    );

    expect(container.querySelector(".message-note-context-state")).toBeNull();
    expect(container.querySelector(".message-note")?.getAttribute("aria-label")).toBe(
      "Private qualification",
    );
    expect(container.querySelector(".message-note")?.textContent).not.toContain(
      "Diskussionskontext",
    );
  });

  it("orders note, reference, and message context consistently", () => {
    const { container } = mountIntoContainer(
      <DiscussionView
        messages={[makeAgentMessage()]}
        streamingAgents={[]}
        isStreaming={false}
        currentAgents={[]}
        onContinue={() => undefined}
        onSetNote={() => undefined}
        onSetContextInclusion={() => undefined}
      />,
    );

    const footer = container.querySelector(".message-footer");
    expect(footer).not.toBeNull();
    expect(Array.from(footer?.children ?? []).map((child) => child.className)).toEqual([
      "message-note-area message-footer-item",
      "message-bezugspunkt-btn message-footer-item",
      "message-context-row message-footer-item",
    ]);
    expect(container.querySelector(".message-context-badge--included")).not.toBeNull();
  });

  it("does not opt a new note into discussion context by default", () => {
    const onSetNote = vi.fn();
    const { container } = mountIntoContainer(
      <DiscussionView
        messages={[makeAgentMessage()]}
        streamingAgents={[]}
        isStreaming={false}
        currentAgents={[]}
        onContinue={() => undefined}
        onSetNote={onSetNote}
        onSetContextInclusion={() => undefined}
      />,
    );

    act(() => (container.querySelector(".note-add-btn") as HTMLButtonElement).click());
    const checkbox = container.querySelector(".note-context-checkbox input") as HTMLInputElement;
    expect(checkbox.checked).toBe(false);

    const editor = container.querySelector(".note-editor textarea") as HTMLTextAreaElement;
    const setter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value")?.set;
    setter?.call(editor, "Default note");
    act(() => editor.dispatchEvent(new Event("input", { bubbles: true })));
    act(() =>
      (container.querySelector(".note-editor .ds-button--secondary") as HTMLButtonElement).click(),
    );

    expect(onSetNote).toHaveBeenCalledWith("a1", "Default note", false);
  });

  it("uses the shared secondary button treatment and edit icon for a new note", () => {
    const { container } = mountIntoContainer(
      <DiscussionView
        messages={[makeAgentMessage()]}
        streamingAgents={[]}
        isStreaming={false}
        currentAgents={[]}
        onContinue={() => undefined}
        onSetNote={() => undefined}
        onSetContextInclusion={() => undefined}
      />,
    );

    const button = container.querySelector(".note-add-btn");
    expect(button?.classList.contains("ds-button--secondary")).toBe(true);
    expect(button?.querySelector(".material-symbol")?.textContent).toBe("edit");
    expect(button?.textContent).toContain("Notiz hinzufügen");
    expect(button?.textContent).not.toContain("+");
  });

  it("clears note context inclusion when a saved note is deleted", () => {
    const onSetNote = vi.fn();
    const { container } = mountIntoContainer(
      <DiscussionView
        messages={[
          makeAgentMessage({
            note: "Human qualification",
            include_note_in_agent_context: true,
          }),
        ]}
        streamingAgents={[]}
        isStreaming={false}
        currentAgents={[]}
        onContinue={() => undefined}
        onSetNote={onSetNote}
        onSetContextInclusion={() => undefined}
      />,
    );

    act(() => (container.querySelector(".message-note") as HTMLElement).click());
    const editor = container.querySelector(".note-editor textarea") as HTMLTextAreaElement;
    const setter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value")?.set;
    setter?.call(editor, "");
    act(() => editor.dispatchEvent(new Event("input", { bubbles: true })));
    act(() =>
      (container.querySelector(".note-editor .ds-button--secondary") as HTMLButtonElement).click(),
    );

    expect(onSetNote).toHaveBeenCalledWith("a1", "", false);
  });
});

describe("DiscussionView perspective labels", () => {
  it("uses a colon between the stable slot and perspective name", () => {
    const html = renderToStaticMarkup(
      <DiscussionView
        messages={[
          makeAgentMessage({
            perspective_number: 1,
            agent_name: "Unused Label",
            theory_label: "Conceptualization",
          }),
        ]}
        streamingAgents={[{ ...streamingAgent, perspective_number: 1 }]}
        isStreaming
        currentAgents={[]}
        onContinue={() => undefined}
        onSetNote={() => undefined}
        onSetContextInclusion={() => undefined}
      />,
    );

    expect(html).toContain("Perspektive 1: Conceptualization");
    expect(html).not.toContain("Perspektive 1 — Conceptualization");
  });

  it("renders canonical theory labels without agent-name fallbacks", () => {
    const duplicateStreamingAgent = {
      ...streamingAgent,
      agent_name: "Skepticism",
      theory_label: "Skepticism",
    };
    const html = renderToStaticMarkup(
      <DiscussionView
        messages={[
          makeAgentMessage({
            agent_name: "Skepticism",
            perspective_number: 1,
            theory_label: "Skepticism",
          }),
        ]}
        streamingAgents={[duplicateStreamingAgent]}
        isStreaming
        currentAgents={[]}
        onContinue={() => undefined}
        onSetNote={() => undefined}
        onSetContextInclusion={() => undefined}
      />,
    );

    expect(html.match(/message-theory/g)).toBeNull();
    expect(html.match(/Skepticism/g)).toHaveLength(2);
  });
});

describe("DiscussionView context-inclusion controls", () => {
  it("renders a native checkbox on the latest round's included user message with the dynamic included label", () => {
    const { container } = mountIntoContainer(
      <DiscussionView
        messages={[
          makeUserMessage({ id: "u1", round_number: 1, include_in_agent_context: true }),
          makeUserMessage({ id: "u2", round_number: 2, include_in_agent_context: true }),
        ]}
        streamingAgents={[]}
        isStreaming={false}
        currentAgents={[]}
        onContinue={() => undefined}
        onSetNote={() => undefined}
        onSetContextInclusion={() => undefined}
      />,
    );

    const inputs = container.querySelectorAll('input[type="checkbox"]');
    expect(inputs).toHaveLength(1);
    const checkbox = inputs[0] as HTMLInputElement;
    expect(checkbox.checked).toBe(true);
    expect(container.textContent).toContain("Im Diskussionskontext");
    expect(container.textContent).not.toContain("Nicht im Diskussionskontext");
  });

  it("renders an unchecked checkbox with the excluded label for an excluded latest-round message", () => {
    const { container } = mountIntoContainer(
      <DiscussionView
        messages={[
          makeUserMessage({ id: "u1", round_number: 1, include_in_agent_context: true }),
          makeUserMessage({ id: "u2", round_number: 2, include_in_agent_context: true }),
          makeUserMessage({
            id: "u3",
            round_number: 3,
            include_in_agent_context: false,
          }),
        ]}
        streamingAgents={[]}
        isStreaming={false}
        currentAgents={[]}
        onContinue={() => undefined}
        onSetNote={() => undefined}
        onSetContextInclusion={() => undefined}
      />,
    );

    expect(container.querySelector(".is-excluded-from-context")).not.toBeNull();
    expect(container.textContent).toContain("Nicht im Diskussionskontext");
    const inputs = Array.from(
      container.querySelectorAll('input[type="checkbox"]'),
    ) as HTMLInputElement[];
    const unchecked = inputs.filter((cb) => !cb.checked);
    expect(unchecked).toHaveLength(1);
  });

  it("invokes onSetContextInclusion with the new boolean when the checkbox toggles", () => {
    const spy = vi.fn();
    const { container } = mountIntoContainer(
      <DiscussionView
        messages={[
          makeUserMessage({ id: "u1", round_number: 1, include_in_agent_context: true }),
          makeUserMessage({ id: "u2", round_number: 2, include_in_agent_context: true }),
        ]}
        streamingAgents={[]}
        isStreaming={false}
        currentAgents={[]}
        onContinue={() => undefined}
        onSetNote={() => undefined}
        onSetContextInclusion={spy}
      />,
    );

    const input = container.querySelector('input[type="checkbox"]') as HTMLInputElement;
    expect(input.checked).toBe(true);
    act(() => input.click());
    expect(spy).toHaveBeenCalledWith("u2", false);
  });

  it("shows the static final-state label for older-round messages without checkbox, lock phrase, or lock glyph", () => {
    const { container } = mountIntoContainer(
      <DiscussionView
        messages={[
          makeUserMessage({ id: "u1", round_number: 1, include_in_agent_context: false }),
          makeAgentMessage({
            id: "a1",
            round_number: 1,
            include_in_agent_context: false,
          }),
          makeUserMessage({ id: "u2", round_number: 2, include_in_agent_context: true }),
        ]}
        streamingAgents={[]}
        isStreaming={false}
        currentAgents={[]}
        onContinue={() => undefined}
        onSetNote={() => undefined}
        onSetContextInclusion={() => undefined}
      />,
    );

    expect(container.textContent).toContain("Nicht im Diskussionskontext");
    expect(container.textContent).not.toContain("für Folgerunde festgelegt");
    expect(container.textContent).not.toContain("🔒");
    const checkboxes = container.querySelectorAll('input[type="checkbox"]');
    expect(checkboxes).toHaveLength(1);
  });

  it("exposes no context control for a streaming partial message", () => {
    const { container } = mountIntoContainer(
      <DiscussionView
        messages={[]}
        streamingAgents={[streamingAgent]}
        isStreaming={true}
        currentAgents={[]}
        onContinue={() => undefined}
        onSetNote={() => undefined}
        onSetContextInclusion={() => undefined}
      />,
    );

    expect(container.querySelector('input[type="checkbox"]')).toBeNull();
  });

  it("renders the is-excluded-from-context class on the message div whenever the message has include_in_agent_context=false", () => {
    const { container } = mountIntoContainer(
      <DiscussionView
        messages={[
          makeUserMessage({ id: "u1", round_number: 1, include_in_agent_context: false }),
          makeAgentMessage({ id: "a1", round_number: 1, include_in_agent_context: false }),
          makeUserMessage({ id: "u2", round_number: 2, include_in_agent_context: true }),
        ]}
        streamingAgents={[]}
        isStreaming={false}
        currentAgents={[]}
        onContinue={() => undefined}
        onSetNote={() => undefined}
        onSetContextInclusion={() => undefined}
      />,
    );

    const matches = container.querySelectorAll(".is-excluded-from-context");
    expect(matches.length).toBeGreaterThanOrEqual(2);
  });
});
