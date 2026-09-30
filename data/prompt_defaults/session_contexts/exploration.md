---
key: exploration
label: Exploration
description: Explore the material, focusing on patterns and possible interpretations.
include_unchanged_research_material_context_in_prompt: false
session_inputs:
  - key: research_material_context
    label: Research Material Context
    hint: Optional context about the material and how it was collected.
    default_text: |-
      **Research Topic and Question**

      …

      **Information on the Case / Material, Speaker Assignment, etc.**

      …

      **Important Terms and Background Knowledge**

      …
    prompt_heading: RESEARCH MATERIAL CONTEXT
    required: false
  - key: main_input
    label: Exploration Task
    hint: An exploration task to begin the open analysis.
    default_text: Explore the material, developing hypotheses while staying grounded in the actual text. Draw out recurring patterns, breaks, tensions, and plausible alternative interpretations.
    prompt_heading: USER INPUT
    required: true
  - key: additional_instructions
    label: Additional Instructions
    hint: Optional guidance for the analysis.
    prompt_heading: ADDITIONAL USER INSTRUCTIONS
    required: false
default_agent_prompt_ids:
  - conceptualization
  - precision
  - skepticism
---

- Use USER INPUT as your starting point.
- Do not assume the user has already settled on an interpretation.
