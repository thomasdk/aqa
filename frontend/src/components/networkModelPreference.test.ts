import { describe, expect, it } from "vitest";
import {
  setPreferredModel,
  reconcileEditModelRow,
  reconcileRemoveModelRow,
  type PreferenceState,
} from "./networkModelPreference";

const state = (model: string, models: string[]): PreferenceState => ({
  model,
  models,
});

describe("networkModelPreference transitions", () => {
  describe("setPreferredModel", () => {
    it("sets model exactly to the chosen row value", () => {
      const result = setPreferredModel(state("alpha", ["alpha", "beta", "gamma"]), "beta");
      expect(result.model).toBe("beta");
    });

    it("never duplicates models", () => {
      const result = setPreferredModel(state("alpha", ["alpha", "beta", "gamma"]), "beta");
      expect(result.models).toEqual(["alpha", "beta", "gamma"]);
    });
  });

  describe("reconcileEditModelRow", () => {
    it("editing the preferred row keeps the new value preferred", () => {
      const result = reconcileEditModelRow(state("alpha", ["alpha", "beta"]), 0, "alpha-v2");
      expect(result.model).toBe("alpha-v2");
      expect(result.models).toEqual(["alpha-v2", "beta"]);
    });

    it("editing a non-preferred row leaves the preferred model unchanged", () => {
      const result = reconcileEditModelRow(state("alpha", ["alpha", "beta"]), 1, "beta-v2");
      expect(result.model).toBe("alpha");
      expect(result.models).toEqual(["alpha", "beta-v2"]);
    });

    it("editing a row that equals the preferred value keeps the new value preferred without duplicating models", () => {
      const result = reconcileEditModelRow(state("alpha", ["alpha", "beta"]), 0, "alpha-v2");
      expect(result.model).toBe("alpha-v2");
      expect(result.models).toEqual(["alpha-v2", "beta"]);
    });
  });

  describe("reconcileRemoveModelRow", () => {
    it("removing the preferred row falls back to the first normalized remaining model", () => {
      const result = reconcileRemoveModelRow(state("alpha", ["alpha", "beta", "gamma"]), 0);
      expect(result.model).toBe("beta");
      expect(result.models).toEqual(["beta", "gamma"]);
    });

    it("removing the preferred row and leaving only blank whitespace falls back to empty", () => {
      const result = reconcileRemoveModelRow(state("alpha", ["alpha", "   "]), 0);
      expect(result.model).toBe("");
      expect(result.models).toEqual(["   "]);
    });

    it("removing a non-preferred row leaves the preferred model unchanged", () => {
      const result = reconcileRemoveModelRow(state("alpha", ["alpha", "beta", "gamma"]), 1);
      expect(result.model).toBe("alpha");
      expect(result.models).toEqual(["alpha", "gamma"]);
    });

    it("removing the last row leaves the preferred model empty", () => {
      const result = reconcileRemoveModelRow(state("alpha", ["alpha"]), 0);
      expect(result.model).toBe("");
      expect(result.models).toEqual([]);
    });
  });
});
