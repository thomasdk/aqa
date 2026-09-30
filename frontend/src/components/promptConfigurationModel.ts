import type { SessionTypeUpdatePayload } from "../api";
import type {
  GlobalBlock,
  PromptConfigOrigin,
  SessionInputDefinition,
  SessionTypeDetail,
} from "./types";

export type SessionTypeFormState = {
  key: string;
  label: string;
  description: string;
  body: string;
  selectedRoleIds: string[];
  includeUnchangedResearchMaterialContextInPrompt: boolean;
  inputs: SessionInputDefinition[];
};

export type GlobalFormState = {
  label: string;
  content: string;
};

export type RestoreTarget =
  | { resource: "session"; id: string; label: string }
  | { resource: "global"; id: string; label: string };

export const PROVENANCE_LABEL_KEYS: Record<PromptConfigOrigin, string> = {
  shipped_default: "common.default",
  shipped_modified: "prompts.changed",
  custom: "prompts.customConfigOrigin",
};

export const PROVENANCE_CLASS: Record<PromptConfigOrigin, string> = {
  shipped_default: "pcm-badge pcm-badge--shipped-default",
  shipped_modified: "pcm-badge pcm-badge--shipped-modified",
  custom: "pcm-badge pcm-badge--custom",
};

export function provenanceTitleKey(origin: PromptConfigOrigin): string {
  switch (origin) {
    case "shipped_default":
      return "prompts.shippedConfigDefault";
    case "shipped_modified":
      return "prompts.shippedConfigModified";
    case "custom":
      return "prompts.customConfigOrigin";
  }
}

export const EMPTY_SESSION_FORM: SessionTypeFormState = {
  key: "",
  label: "",
  description: "",
  body: "",
  selectedRoleIds: [],
  includeUnchangedResearchMaterialContextInPrompt: false,
  inputs: fixedSessionInputs(),
};

export const EMPTY_GLOBAL_FORM: GlobalFormState = {
  label: "",
  content: "",
};

/**
 * The three setup values are a shared orchestration contract.  Session types
 * can customise their presentation, but cannot add, remove, rename or
 * reorder the semantic inputs.
 */
export function fixedSessionInputs(): SessionInputDefinition[] {
  return [
    {
      key: "research_material_context",
      label: "Research Material Context",
      hint: "Optional context about the material and how it was collected.",
      default_text: "",
      prompt_heading: "RESEARCH MATERIAL CONTEXT",
      required: false,
    },
    {
      key: "main_input",
      label: "Main input",
      hint: "The central question, interpretation, or task for this session.",
      default_text: "",
      prompt_heading: "USER INPUT",
      required: true,
    },
    {
      key: "additional_instructions",
      label: "Additional instructions",
      hint: "Optional guidance for the approach.",
      default_text: "",
      prompt_heading: "ADDITIONAL USER INSTRUCTIONS",
      required: false,
    },
  ];
}

export function sessionFormFromDetail(detail: SessionTypeDetail): SessionTypeFormState {
  return {
    key: detail.key,
    label: detail.label,
    description: detail.description,
    body: detail.body,
    selectedRoleIds: [...detail.default_agent_prompt_ids],
    includeUnchangedResearchMaterialContextInPrompt:
      detail.include_unchanged_research_material_context_in_prompt,
    inputs: detail.inputs ?? [],
  };
}

export function globalFormFromBlock(block: GlobalBlock): GlobalFormState {
  return { label: block.label, content: block.content };
}

export function uniqueOrdered(values: string[]): string[] {
  const seen = new Set<string>();
  return values.filter((value) => {
    if (!value || seen.has(value)) return false;
    seen.add(value);
    return true;
  });
}

export function sessionTypePayloadDiff(
  original: SessionTypeDetail,
  form: SessionTypeFormState,
): SessionTypeUpdatePayload | null {
  const diff: SessionTypeUpdatePayload = {};
  if (form.label !== original.label) diff.label = form.label;
  if (form.description !== original.description) {
    diff.description = form.description;
  }
  if (form.body !== original.body) diff.body = form.body;
  if (
    form.includeUnchangedResearchMaterialContextInPrompt !==
    original.include_unchanged_research_material_context_in_prompt
  ) {
    diff.include_unchanged_research_material_context_in_prompt =
      form.includeUnchangedResearchMaterialContextInPrompt;
  }

  // Definitions are fully ordered data. Sending the complete array makes
  // reordering and localized subfields unambiguous.
  const originalInputs = original.inputs ?? [];
  if (JSON.stringify(form.inputs) !== JSON.stringify(originalInputs)) {
    diff.inputs = form.inputs;
  }

  const originalIds = uniqueOrdered(original.default_agent_prompt_ids);
  const formIds = uniqueOrdered(form.selectedRoleIds);
  if (
    originalIds.length !== formIds.length ||
    originalIds.some((id, index) => id !== formIds[index])
  ) {
    diff.default_agent_prompt_ids = formIds;
  }
  return Object.keys(diff).length > 0 ? diff : null;
}
