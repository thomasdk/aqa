import { normalizeModelNames } from "./hostModelSelection";

export type PreferenceState = {
  model: string;
  models: string[];
};

/**
 * Mark a specific model row value as the preferred model.
 * Models are kept in their existing order; only `model` changes.
 */
export function setPreferredModel<T extends PreferenceState>(state: T, value: string): T {
  return {
    ...state,
    model: value,
  };
}

/**
 * Edit a model row, keeping the preferred value in sync when the row
 * being edited currently equals the preferred model.
 */
export function reconcileEditModelRow<T extends PreferenceState>(
  state: T,
  index: number,
  value: string,
): T {
  const models = state.models.map((item, idx) => (idx === index ? value : item));
  const editedRowWasPreferred = state.models[index] === state.model;
  const normalized = normalizeModelNames(editedRowWasPreferred ? value : state.model, models);
  return {
    ...state,
    models,
    // Clearing or invalidating the preferred row must not leave an otherwise
    // valid model list without a preference. The first valid row is the
    // deterministic fallback used by both the editor and saved host payload.
    model: editedRowWasPreferred ? (normalized[0] ?? "") : state.model || normalized[0] || "",
  };
}

/**
 * Remove a model row, falling back to the first remaining normalized model
 * if the removed row held the preferred value. Returns an empty preferred
 * model when no valid rows remain.
 */
export function reconcileRemoveModelRow<T extends PreferenceState>(state: T, index: number): T {
  const removed = state.models[index];
  const models = state.models.filter((_, idx) => idx !== index);
  let model = state.model;
  if (removed === state.model) {
    const remaining = normalizeModelNames(undefined, models);
    model = remaining[0] ?? "";
  }
  return { ...state, models, model } as T;
}
