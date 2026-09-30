import { de } from "./locales";

export type TranslationContext = {
  location: string;
  function: string;
  tone: "action" | "status" | "instruction" | "technical" | "accessibility";
  length: "short" | "medium" | "long";
  notes: string;
};

/**
 * Translator context inherited by every leaf key in a namespace.
 * Interpolation variables remain part of the catalogue value and are checked
 * separately, so a translator has both the functional context and wire shape.
 */
export const TRANSLATION_CONTEXT: Record<keyof typeof de, TranslationContext> = {
  app: {
    location: "Document and global shell",
    function: "Application identity and language selection",
    tone: "accessibility",
    length: "short",
    notes: "Keep the product name unchanged.",
  },
  nav: {
    location: "Primary navigation",
    function: "Name a destination",
    tone: "action",
    length: "short",
    notes: "Use concise destination nouns.",
  },
  common: {
    location: "Shared controls",
    function: "Describe reusable actions and states",
    tone: "action",
    length: "short",
    notes: "Prefer verbs for buttons and nouns for states.",
  },
  about: {
    location: "About dialog",
    function: "Label project identity, credits, affiliation, and links",
    tone: "instruction",
    length: "medium",
    notes:
      "Keep the official German project title unchanged; translate institutional names only for the English locale.",
  },
  release: {
    location: "About dialog and System tab",
    function: "Describe shared release metadata and project links",
    tone: "status",
    length: "short",
    notes: "Version, date, status, and link destinations are data and remain untranslated.",
  },
  designSystem: {
    location: "Developer component gallery",
    function: "Document shared component variants and states",
    tone: "technical",
    length: "medium",
    notes: "Use the same control terminology as consuming screens.",
  },
  setup: {
    location: "Setup tab",
    function: "Label research inputs and perspective options",
    tone: "instruction",
    length: "medium",
    notes: "Do not translate user-entered material or prompt content.",
  },
  discussion: {
    location: "Discussion tab",
    function: "Explain discussion actions and message state",
    tone: "action",
    length: "medium",
    notes: "Quick-action labels are UI; their submitted prompt text is separate domain content.",
  },
  activity: {
    location: "Perspective activity panel",
    function: "Report live generation state",
    tone: "status",
    length: "short",
    notes: "Keep status language neutral and screen-reader friendly.",
  },
  sessions: {
    location: "Sessions tab",
    function: "Manage saved discussions",
    tone: "action",
    length: "medium",
    notes: "Destructive text must name the affected session and consequence.",
  },
  network: {
    location: "Network configuration",
    function: "Configure model hosts",
    tone: "technical",
    length: "medium",
    notes: "Never translate host labels, URLs, model names, or API-key data.",
  },
  localAi: {
    location: "Local AI tab",
    function: "Manage local runtime and models",
    tone: "technical",
    length: "medium",
    notes: "Keep model, profile, path, and hardware values as data.",
  },
  prompts: {
    location: "Role, system, and prompt-preview views",
    function: "Manage prompt metadata and configuration",
    tone: "technical",
    length: "medium",
    notes: "Translate the editor shell and shipped display metadata, never prompt bodies.",
  },
  system: {
    location: "System landing view",
    function: "Summarise configuration tools",
    tone: "instruction",
    length: "medium",
    notes: "Use the shared session-type terminology.",
  },
  errors: {
    location: "Client-side error surfaces",
    function: "Explain a failed action",
    tone: "status",
    length: "medium",
    notes: "State the problem and safe next step without exposing raw backend details.",
  },
  apiErrors: {
    location: "API and stream error surfaces",
    function: "Translate stable backend error codes",
    tone: "status",
    length: "medium",
    notes: "Keys are public machine codes and must not be renamed with display copy.",
  },
  toolbar: {
    location: "Global toolbar",
    function: "Control discussion and application lifecycle",
    tone: "action",
    length: "short",
    notes: "Confirmation text must state any loss of in-progress work.",
  },
  activityLog: {
    location: "Activity log",
    function: "Label local diagnostic events",
    tone: "technical",
    length: "short",
    notes: "Technical event payloads themselves remain untranslated.",
  },
};

export function translationContextFor(key: string): TranslationContext | null {
  const namespace = key.split(".", 1)[0] as keyof typeof de;
  return TRANSLATION_CONTEXT[namespace] ?? null;
}
