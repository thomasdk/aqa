# Accessibility Contract

AQA targets WCAG 2.2 Level AA and the applicable requirements in the
currently published EN 301 549. This document records the product behaviors
that future UI work must preserve. Passing automated checks supports this goal;
it does not by itself establish formal conformance.

## Required behavior

- Use native HTML semantics where possible. Every control and form field must
  expose an accurate name, role, value, and state. Visible labels must be
  programmatically associated with their controls, and icon-only actions must
  identify their target.
- Every action must work from the keyboard. Focus must remain visible, follow a
  logical order, stay contained inside an open modal, and return to a useful
  element after navigation, cancellation, saving, or removal.
- Validation errors must identify the affected field. Loading, saving,
  connection, generation, insertion, and removal results must use restrained
  status or alert announcements without repeating whole content blocks.
- Normal text must retain at least 4.5:1 contrast where WCAG requires it.
  Essential control boundaries and focus indicators must retain at least 3:1.
  Use the shared tokens in `frontend/src/styles/base.css` and extend
  `frontend/src/accessibilityStyles.test.ts` when adding a new surface or state.
- Compact controls must meet the WCAG 2.2 target-size requirement or a valid
  spacing/semantic exception. Content and actions must remain usable through
  400% zoom without page-level horizontal clipping.
- Hover or focus help must be dismissible with Escape without moving focus,
  remain hoverable and persistent for the triggering interaction, and reopen
  on a genuinely new interaction. Dismissal must consume only the Escape that
  hides the help so a surrounding modal or menu does not also close. Product
  animation must respect `prefers-reduced-motion: reduce`.
- Removing a focused notice must return focus to a consumer-supplied meaningful
  target or a nearby usable fallback without escaping an open modal. Automatic
  removal or removal while focus is elsewhere must not steal focus.
- English and German visible copy, accessible names, errors, and announcements
  must stay synchronized.

## Verification for UI changes

From `frontend/`, run:

```bash
npm run test:accessibility
npm run lint
npm run typecheck
npm run build
```

Add a regression test beside the changed component for its keyboard, focus,
name/state, error, or announcement behavior. Add new visual tokens and custom
interaction patterns to `accessibilityStyles.test.ts` so contrast, focus,
target-size, tooltip, and reduced-motion contracts cannot drift silently.

Inspect the actual rendered product at the affected desktop width and a narrow
layout, including 100% and 400% zoom when layout or control geometry changes.
Check focus and hover states rather than only the resting screen. For native
verification, use a fresh packaged Tauri app and a unique disposable
`AQA_DESKTOP_DATA_DIR`. Confirm the intended app, backend child, and disposable
profile paths before attaching or changing state; preserve unrelated instances
and ordinary profiles.

Use VoiceOver on macOS or NVDA on Windows when a change affects dialogs, focus
management, live announcements, navigation, form relationships, or a custom
interactive widget. Record the application artifact, platform, journey, what
the screen reader announced, and any remaining evidence limits.

## Evidence boundaries

Lint, component tests, browser checks, accessibility-tree inspection, and
native screen-reader use are different evidence types. Report each accurately.
A browser result does not prove packaged Tauri behavior, and one screen reader
or operating system does not prove another platform.
