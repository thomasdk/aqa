import { updateGenerationSleepInhibition } from "./desktopBridge";

export type GenerationSleepInhibitionSnapshot = {
  enabled: boolean;
};

let snapshot: GenerationSleepInhibitionSnapshot = { enabled: true };
let nextOperationId = 0;
const activeOperations = new Set<string>();
const operationQueues = new Map<string, Promise<void>>();
const listeners = new Set<() => void>();

function applyNativeState(operationId: string, active: boolean): void {
  const previous = operationQueues.get(operationId) ?? Promise.resolve();
  const enabled = snapshot.enabled;
  const queued = previous
    .catch(() => undefined)
    .then(() =>
      updateGenerationSleepInhibition(operationId, active, enabled).catch((error) => {
        console.debug("[Power] Sleep inhibition is unavailable (non-fatal):", error);
      }),
    )
    .finally(() => {
      if (operationQueues.get(operationId) === queued) operationQueues.delete(operationId);
    });
  operationQueues.set(operationId, queued);
}

export function createGenerationOperationId(): string {
  nextOperationId += 1;
  return `discussion-${nextOperationId}`;
}

export function setGenerationOperationActive(operationId: string, active: boolean): void {
  const wasActive = activeOperations.has(operationId);
  if (active) activeOperations.add(operationId);
  else activeOperations.delete(operationId);
  if (!active && !wasActive) return;
  applyNativeState(operationId, active);
}

export function setPreventSleepWhileGenerating(enabled: boolean): void {
  if (snapshot.enabled === enabled) return;
  snapshot = { enabled };
  for (const listener of listeners) listener();
  for (const operationId of activeOperations) applyNativeState(operationId, true);
}

export function getGenerationSleepInhibitionSnapshot(): GenerationSleepInhibitionSnapshot {
  return snapshot;
}

export function subscribeGenerationSleepInhibition(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function resetGenerationSleepInhibitionForTests(): void {
  snapshot = { enabled: true };
  nextOperationId = 0;
  activeOperations.clear();
  operationQueues.clear();
  listeners.clear();
}
