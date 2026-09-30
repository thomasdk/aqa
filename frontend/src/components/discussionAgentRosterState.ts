import type { AgentConfig } from "./types";

function hasNonBlankPromptId(promptId: string | null | undefined): boolean {
  return typeof promptId === "string" && promptId.trim().length > 0;
}

/** Only enabled agents with a non-blank role participate in a round. */
export function isAgentActive(agent: AgentConfig): boolean {
  return Boolean(agent.enabled) && hasNonBlankPromptId(agent.prompt_id);
}

/**
 * Return the original array for invalid or boundary moves so no-ops remain
 * observable by identity.
 */
export function moveAgent<T extends AgentConfig>(
  agents: readonly T[],
  index: number,
  delta: number,
): readonly T[] {
  if (delta === 0) return agents;
  if (index < 0 || index >= agents.length) return agents;
  const target = index + delta;
  if (target < 0 || target >= agents.length) return agents;
  if (index === target) return agents;

  const next = agents.slice();
  const moved = agents[index];
  const swapped = agents[target];
  next[index] = swapped;
  next[target] = moved;
  return next;
}

/**
 * Preserve every other field; a missing id returns a new array with shared
 * element references so React still observes the requested transition.
 */
export function setAgentEnabled<T extends AgentConfig>(
  agents: readonly T[],
  clientId: string,
  enabled: boolean,
): readonly T[] {
  let idx = -1;
  for (let i = 0; i < agents.length; i++) {
    if (agents[i].client_id === clientId) {
      idx = i;
      break;
    }
  }
  if (idx === -1) {
    return agents.slice();
  }
  const current = agents[idx];
  const updated = { ...current, enabled } as T;
  const next = agents.slice();
  next[idx] = updated;
  return next;
}
