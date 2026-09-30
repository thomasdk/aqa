# AGENTS.md — AQA

Behavioral guidance for autonomous agents working in this repository. Keep this
file short, current, and project-specific. Architecture belongs in code and
tests; detailed process belongs in the relevant public documentation.

## Authority And Scope

- Code and tests are authoritative for implemented behavior. Verify relevant
  behavior in the implementation and tests before changing it.
- User and maintainer instructions are authoritative for intent, scope, and
  authorization.
- Keep affected contracts synchronized. When a schema, API, prompt asset,
  persisted key, or user-facing label changes, update related code, tests, and
  shipped assets in the same change. Search relevant areas for stale names or
  copy before handoff.

## Product And Repository

The shipped products are the **Tauri desktop apps**. Each contains one
target-specific embedded Python runtime, starts the FastAPI backend, and loads
the built React UI in its native window. The source FastAPI and React web app is
the primary automated-test and local-development path, but it is not shipped as
a separate portable folder.

`packaging/runtime/` fetches, prepares, and validates the six supported desktop
runtime targets. `packaging/desktop/build_target.sh <target>` packages one
matching runtime into one app; other cached targets are not required.

Before editing, read the relevant implementation and tests. Inspect
`data/prompts/` and related `*.poml` files when prompt behavior is involved.

## UI, Accessibility, And Design System

New or changed UI must preserve `docs/ACCESSIBILITY.md` and follow
`docs/DESIGN_SYSTEM.md`. Before changing UI, inspect the rendered gallery at
`/?gallery=components`, the relevant shared components, and representative
consumers. Reuse established components and semantic tokens rather than
recreating shared controls or visual states.

Every change to shipped frontend source or assets must run `npm run build` from
`frontend/`. Actual UI changes must also run `npm run lint`,
`npm run typecheck`, and `npm run test:accessibility`, receive regression
coverage appropriate to the changed behavior and risk, and be inspected in the
rendered product at affected desktop and narrow layouts. Check both locales and
relevant keyboard, focus, disabled, loading, validation, error, reflow, and
reduced-motion states when the change can affect them. Do not add artificial new
tests for copy- or spacing-only adjustments when existing checks and rendered
inspection cover the risk.

When changing a shared component, token, variant, or pattern, update affected
consumers, gallery examples, `docs/DESIGN_SYSTEM.md`, and relevant regression
coverage in the same change. Remove superseded markup and styles and document
any justified design-system exception in that guide.

## Code Comments And Documentation

Prefer clear names, types, small functions, and straightforward control flow.
Comments should capture rationale, invariants, lifecycle or concurrency
constraints, external contracts, deliberate workarounds, or non-obvious
security, compatibility, performance, and data-integrity requirements—not
restate the code. Document important observable contracts for non-obvious public
interfaces. Keep comments current; use `TODO` only for a concrete action and do
not invent issue references.

## Compatibility Before Public Distribution

Until AQA is first distributed publicly, prefer a clean current schema, API,
and UI behavior over migrations, legacy fallbacks, or compatibility shims.
Internal beta numbering alone does not create compatibility obligations. At the
first public distribution, reassess this policy before changing persisted
formats that public users may rely on. Do not add compatibility code earlier
unless a maintainer explicitly requests it.

## Working Mode

Handle small and local tasks directly. Use subagents for substantial independent
workstreams or useful independent reviews when delegation materially helps.
Keep overlapping edits serial, and personally verify and integrate delegated
work.

## Verification And Evidence

Choose verification proportionate to changed behavior, risk, and acceptance
criteria. Add or update focused tests when behavior changes; do not run unrelated
full suites, rebuild unaffected products, or restart services solely because a
file changed. Documentation and agent-instruction changes need a read-back and
diff inspection unless the task requires more.

Verify affected native behavior in a fresh packaged Tauri app. Browser/gallery,
automated, source, simulated-provider, live-provider, package inspection,
cross-build, packaged-native, and screen-reader results are distinct evidence
classes and must be reported as such. Only behavior observed live in the
relevant packaged Tauri app counts as native GUI evidence.

Do not make contributor-run macOS or Windows testing a routine prerequisite or
execution gate. Prefer deterministic verification, exercise packaged behavior
directly when the task and environment permit it, and state remaining
native-platform or screen-reader evidence gaps clearly.

## Secrets And Local State

Never read, print, log, commit, or bundle ordinary application data or secrets,
including `.env`, `data/settings.json`, `.aqa/`, legacy `.aqa_workbench/`,
credentials, or saved conversations in `conversations/`. If a task appears to
require access to real or default-profile data, stop and ask the user.

Authorized task-created synthetic profiles and fixtures may be inspected,
mutated, and removed within that task's scope. This permission does not extend
to ordinary profiles or unrelated data. For packaged desktop tests, use a unique
disposable `AQA_DESKTOP_DATA_DIR`; `AQA_USER_DATA_DIR` alone is not the desktop
override. Confirm the intended mounted app process, backend child, and
disposable log/profile paths before GUI attachment and again before
state-changing interaction. Stop if attachment selects an uncontrolled
instance, and do not terminate unrelated installed-app processes.

`.gitignore` is a guardrail, not complete protection and not authorization to
access ignored data. It must continue to ignore sensitive state and generated
outputs such as `.env`, `data/settings.json`, `.aqa/`, `.aqa_workbench/`,
`frontend/dist/`, `dist/`, `runtime/`, `developer/pyinstaller/`,
`.pyinstaller/`, `.venv/`, and `.venv-packaging/`. Keep `data/prompts/`
trackable; never add an overbroad `data/` rule that shadows shipped source
assets.

## Changelog And Commits

Add notable user-visible and release-relevant changes under `Unreleased` in
`CHANGELOG.md`, using the applicable Keep a Changelog category. Describe user
impact concisely. Make breaking changes, security changes, and required user
actions prominent. Do not add entries for documentation-only,
agent-instruction-only, build-artifact-only, routine maintenance, or purely
internal refactoring changes unless they have release-relevant consequences.
At release, move the accumulated entries into a section bearing the actual
Semantic Versioning version and `YYYY-MM-DD` release date, then add a new empty
`Unreleased` section above it. Do not invent repository or tag links.

After completed and verified implementation work, default to one focused Git
commit before handoff. Stage only task-owned files, inspect the staged diff, and
never include unrelated worktree changes. This focused-commit policy applies
whether or not the work warrants a changelog entry. Explicit no-commit
instructions, incomplete work, or changes that cannot be separated safely from
unrelated edits override the default. Documentation- or agent-instruction-only
work does not require a commit unless the task explicitly asks for one.
