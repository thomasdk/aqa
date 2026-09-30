---
key: critique
label: Critique
description: Critically examine an interpretation.
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
    label: Interpretation
    hint: Enter the interpretation you want to examine critically.
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

- Critically examine the interpretation provided as USER INPUT.
- Formulate counterarguments and plausible alternative readings.
- Identify blind spots, prior assumptions, and counter-evidence in the material.
