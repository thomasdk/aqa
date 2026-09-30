import { useEffect, useMemo, useRef, useState } from "react";
import {
  estimateDiscussionContext,
  estimateMaterialTokens,
  getMaterialWithLineNumbers,
  type ContextEstimate,
} from "../../api";
import type { AgentConfig, SynthesisConfig } from "../types";

export type DiscussionContextEstimateDraft = {
  agents: AgentConfig[];
  synthesis: SynthesisConfig;
  sessionType: string;
  targetLanguage: string;
  sessionInputValues: Record<string, string>;
  sequentialMode: boolean;
};

export function discussionContextRequest(
  material: string,
  materialType: string,
  draft: DiscussionContextEstimateDraft,
): Parameters<typeof estimateDiscussionContext>[0] | null {
  if (!draft.targetLanguage.trim()) return null;
  return {
    material,
    agents: draft.agents.map((agent) => ({ ...agent, api_key: null })),
    material_context: {
      material_type: materialType,
      session_type: draft.sessionType,
      target_language: draft.targetLanguage,
      input_values: {
        research_material_context: draft.sessionInputValues.research_material_context ?? "",
        main_input: draft.sessionInputValues.main_input ?? "",
        additional_instructions: draft.sessionInputValues.additional_instructions ?? "",
      },
    },
    synthesis: draft.synthesis,
    sequential_mode: draft.sequentialMode,
  };
}

/**
 * Keeps rendered material metadata aligned with the current discussion.
 * Aborted or superseded requests never replace the newer material value.
 */
export function useDiscussionMaterialPresentation(
  material: string,
  materialType: string,
  hasDiscussion: boolean,
  draft?: DiscussionContextEstimateDraft,
  contextRevision = "",
) {
  const [materialTokenEstimate, setMaterialTokenEstimate] = useState<number | null>(null);
  const [materialWithLineNumbers, setMaterialWithLineNumbers] = useState("");
  const [contextEstimateState, setContextEstimateState] = useState<{
    fingerprint: string;
    result: ContextEstimate;
  } | null>(null);
  const estimateAbortRef = useRef<AbortController | null>(null);
  const contextEstimateAbortRef = useRef<AbortController | null>(null);
  const contextRequestFingerprint = JSON.stringify(
    draft ? discussionContextRequest(material, materialType, draft) : null,
  );
  const contextRequest = useMemo(
    () =>
      JSON.parse(contextRequestFingerprint) as
        Parameters<typeof estimateDiscussionContext>[0] | null,
    [contextRequestFingerprint],
  );
  const contextStateKey = `${contextRequestFingerprint}:${contextRevision}`;
  const contextEstimate =
    !hasDiscussion && contextEstimateState?.fingerprint === contextStateKey
      ? contextEstimateState.result
      : null;

  useEffect(() => {
    estimateAbortRef.current?.abort();
    if (!material) {
      setMaterialTokenEstimate(0);
      return;
    }
    const controller = new AbortController();
    estimateAbortRef.current = controller;
    const timer = window.setTimeout(() => {
      void estimateMaterialTokens(material, materialType, controller.signal)
        .then((result) => {
          if (!controller.signal.aborted) setMaterialTokenEstimate(result.approximate_tokens);
        })
        .catch(() => {
          if (!controller.signal.aborted) setMaterialTokenEstimate(null);
        });
    }, 250);
    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
  }, [material, materialType]);

  useEffect(() => {
    contextEstimateAbortRef.current?.abort();
    setContextEstimateState(null);
    if (hasDiscussion || contextRequest === null) return;

    const controller = new AbortController();
    contextEstimateAbortRef.current = controller;
    const timer = window.setTimeout(() => {
      void estimateDiscussionContext(contextRequest, controller.signal)
        .then((result) => {
          if (!controller.signal.aborted) {
            setContextEstimateState({ fingerprint: contextStateKey, result });
          }
        })
        .catch(() => {});
    }, 250);
    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
  }, [contextRequest, contextStateKey, hasDiscussion]);

  useEffect(() => {
    if (!material || !hasDiscussion) {
      setMaterialWithLineNumbers("");
      return;
    }
    let cancelled = false;
    void getMaterialWithLineNumbers(material)
      .then((result) => {
        if (!cancelled) setMaterialWithLineNumbers(result.material);
      })
      .catch((error: unknown) => {
        if (!cancelled) console.error("Failed to get line-numbered material:", error);
      });
    return () => {
      cancelled = true;
    };
  }, [hasDiscussion, material]);

  return {
    contextEstimate,
    materialTokenEstimate,
    materialWithLineNumbers,
  };
}
