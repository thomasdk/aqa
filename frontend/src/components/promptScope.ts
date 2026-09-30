type Translate = (key: string) => string;

/** Formats persisted prompt-scope values for display without leaking identifiers. */
export function formatPromptScope(scope: string | null, t: Translate): string {
  if (scope === null) return t("prompts.alwaysActive");
  if (scope === "multi_agent") return t("prompts.multiAgentLabel");
  if (scope === "synthesis") return t("prompts.synthesisLabel");
  return scope.replace(/_/g, "-");
}
