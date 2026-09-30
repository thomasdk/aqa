# AQA Design System

This is the usage contract for the AQA UI. It defines the shared aquatic light and dark appearances without changing component geometry or introducing a component framework. The implementation is incremental: shared components own recurring visual and interaction contracts; feature styles own placement and genuinely feature-specific structures.

## Source Of Truth

- Semantic tokens and scales: `frontend/src/styles/base.css`
- Shared component styles: `frontend/src/styles/design-system.css`
- Shared React exports: `frontend/src/components/design-system/index.ts`
- Existing specialized primitives: `IconButton.tsx`, `MaterialSymbol.tsx`, `Modal.tsx`, `NoticeBanner.tsx`, and `BlockedActionHint.tsx`
- Shared recurring patterns: `ChoiceIndicator`, `StepMarker`, and `FavoriteToggle` from `frontend/src/components/design-system/`
- Rendered gallery: start the frontend and open `/?gallery=components` or `/design-system`
- Accessibility contract: `docs/ACCESSIBILITY.md`

Raw aquatic palette values in `base.css` feed semantic tokens for surfaces, text, borders, actions, feedback, focus, size, spacing, typography, radii, motion, shadow, and modal layering. New shared components must use semantic tokens. Add a token only when its purpose is reusable and distinct; do not create aliases with the same meaning or move feature data such as agent colors into the generic system.

## Appearance Ownership And Persistence

The System page and component gallery share the localized `AppearanceSelect` control. Adaptive is the default; Light and Dark apply immediately without Save or restart. `frontend/src/appearance.ts` owns the preference and resolves it to `light` or `dark` on the root `data-theme` attribute and `color-scheme`. Components must not resolve their own themes.

The server-backed `appearance` application preference is authoritative across restarts and changing desktop loopback origins. The `aqa.appearance` local cache supplies the startup palette and remains the fallback when the server is unavailable; a successful server read replaces that cache. A newer user selection wins over an in-flight hydration read. Preference writes are serialized so rapid selections cannot finish out of order. Persistence failure leaves the current selection usable but does not guarantee restoration on another origin.

The root palette is applied before React renders. Adaptive subscribes to `prefers-color-scheme` changes; explicit choices remove that listener. Missing media-query support resolves Adaptive to Light. Desktop chrome receives the explicit preference through the scoped native appearance command; Adaptive clears the app override. Native calls are serialized, and system resolution is refreshed after clearing an override. Listener cleanup also invalidates pending native completion callbacks.

### Palette Rules

`base.css` owns all fixed CSS colors. Its default tokens preserve the dark palette; `:root[data-theme="light"]` overrides color tokens with pale water backgrounds, white raised surfaces, deep navy text, and darker teal actions. Typography, spacing, geometry, and variants remain shared. Use semantic surface, text, border, focus, action, and feedback tokens in every consuming stylesheet. In particular, use `--aqa-action-primary-ink` for text on filled actions; the canvas token is a background, not action text.

Markdown, synthesis gradients, material surfaces, badges, selection, scrollbars, and shadows use purpose-specific tokens. Data-driven author borders remain a deliberate exception: they carry identity accents beside explicit perspective numbers and names, while readable message text uses semantic text tokens. The inline brand uses the shared ink and aquatic tokens through `currentColor`; its decorative artwork has a separate accessible application name. Static app icons retain their identity artwork.

The gallery is organized as a catalog rather than a screen mock: Controls, Selection And Workflow, Status And Feedback, and Composition And Dialogs. Each family names the intent of its examples and exposes both appearances and locales. Its state specimens include primary, secondary, danger, active, disabled, loading, invalid, focusable, persistent, dismissible, and blocked-action examples. The dialog specimen uses the production `Modal` contract so focus entry, containment, dismissal, and return can be exercised rather than inferred from a static footer.

Contrast regression coverage resolves both palettes, including tinted surfaces, essential boundaries, and focus indicators. Browser reflow tests use 320 CSS pixels as a 400% reflow proxy; this is distinct from native zoom or screen-reader evidence. Consumer screens remain the integration reference for specialized compositions; the gallery does not redefine their feature layout.

## Components

### Button And IconButton

Use `Button` for recurring text actions. Choose by intent:

- `primary`: the main positive action in a surface.
- `secondary`: ordinary actions, including Cancel and Save where they are not the surface's main action.
- `danger`: destructive actions before confirmation; outlined at rest.
- `dangerPrimary`: the destructive confirmation action only.
- `toolbar`: global or content-toolbar actions that need stable labels.
- `text`: low-emphasis actions on an existing surface.

Use `size="small"` only for a compact context that still satisfies target-size and spacing requirements. `loading` disables activation and exposes `aria-busy`; provide a localized `loadingLabel` when the visible name should change.

Use `IconButton` for icon-only actions. Its non-empty localized `label` is both the accessible name and tooltip text. Hover or keyboard focus exposes the tooltip; Escape dismisses it without moving focus or activating the button and consumes only that keypress so a surrounding modal or menu remains open. The tooltip stays suppressed for the current hover/focus interaction and can return after the pointer leaves and re-enters or focus leaves and returns. Moving the pointer onto the tooltip keeps it open. `secondary`, `danger`, and `ghost` variants describe intent. Preserve native `aria-pressed`, `aria-expanded`, event handlers, and other state attributes when applicable. Use `MaterialSymbol` inside it with `decorative` because the button supplies the name.

### Fields And Native Controls

Use `Field` with `Input`, `Select`, or `Textarea` for conventional labelled form rows. `Field` supplies or accepts the control ID and joins its description and error IDs into `aria-describedby`; it propagates required, invalid, and error state to shared controls. Pass an existing `aria-describedby` when a feature has additional help—the shared control preserves and joins it.

Use the wrappers directly when a visible label already exists or a low-chrome inline editor needs feature-specific layout. Feature classes may set width, grid placement, min/max dimensions, or surrounding spacing, but must not redefine the shared control's typography, padding, height, colors, border, focus, disabled, or invalid treatment.

Use `IntegerInput` for editable whole-token limits. It uses the shared `Input` appearance, groups valid values with the selected application locale while idle, and keeps the draft ungrouped or as typed while focused to protect cursor placement. Consumers own bounds, validation feedback, and save timing. Plain digits and complete locale-specific three-digit groups are accepted; decimal settings continue to use their existing controls. Arrow Up and Arrow Down change valid values by one within the supplied bounds.

Native checkbox, radio, range, file, progress, and label-backed selection-card controls remain native compound patterns. They share semantic tokens and the accessibility contract but are not forced through text-field wrappers.

### Selection, Favorite, And Workflow Patterns

Keep the native radio input as the semantic and keyboard-operable control. Pair visually hidden card radios with `ChoiceIndicator`; its selected state is an aqua filled circle with a checkmark. Unavailable choices stay visible with a disabled native input and an unselected indicator. The owning label supplies card or compact-row layout, focus treatment, and visible copy.

Use `FavoriteToggle` for the interactive two-state star. It owns `aria-pressed`, the active/inactive accessible labels, tooltip, shared icon metrics, and pressed styling. Use `FavoriteStar` directly only as a noninteractive status marker inside an already named control or status surface.

Use `StepMarker` for compact numbered or completed workflow steps. It owns the high-contrast circular border, recessed fill, and number weight so feature styling cannot silently weaken or remove a different screen's workflow markers. The surrounding feature owns the step heading and layout.

Use `StatusBadge` for short, noninteractive state labels. Choose `neutral` for states without a semantic emphasis, `info` for available factual states such as Downloaded, and `success` for positive live states such as Running. A badge supplements the surrounding control or surface; it does not replace native selected, disabled, busy, or pressed semantics.

### Feedback And Notices

Use `NoticeBanner` for persistent or dismissible page-level feedback. Tones provide a consistent leading icon, border, background, and announcement default: information uses the information-circle symbol, success uses a check, warning uses a warning triangle, and error uses the error symbol. Pass an explicit role only when the message's timing requires `alert` or passive `note` semantics. Omitting `onDismiss` creates a persistent notice such as the Prepare external-AI disclosure or unavailable-source warning.

When dismissal unmounts a notice while focus is inside it, `dismissReturnFocusRef` identifies the consumer's meaningful next action. The target is resolved after the dismissal commit so a control enabled by that update is valid. If the explicit target is missing, disconnected, hidden, disabled, inert, or outside the notice's modal, focus moves to the nearest usable control after the notice and then before it; a modal itself is the final contained fallback. Automatic removal and dismissal while focus is elsewhere never move focus. Consumers should provide an explicit target when the user's next action is clear rather than relying on the generic nearby fallback.

Use `BlockedActionHint` beside a visible disabled control when missing information, an unmet prerequisite, or a limit prevents the action. Every blocked-action explanation uses the semantic danger color by default; the component has no neutral variant. Its question-mark symbol distinguishes the explanation from the banner taxonomy without adding an alert or status announcement. Put genuinely non-blocking guidance in ordinary help or description text, and keep progress in the established progress/status patterns. Field validation stays with `Field` error text and `aria-invalid` rather than becoming a banner.

### Layout Patterns

- `PageHeader`: one page `h1`, optional explanatory subtitle and actions.
- `SectionHeader`: reusable `h2` or `h3`, optional subtitle and actions. Activity's restrained panel label and banded content headings remain specialized.
- `Card`: raised or recessed bounded surface. Use only when the surface itself is meaningful; do not wrap every section.
- `ActionGroup`: wrapping start, end, or spread alignment for related actions.
- `DialogFooter`: the standard modal action row and narrow-layout stacking behavior.
- Editor dialogs use `Modal layout="editor"` with one direct `EditorDialogBody` or `EditorDialogForm`, followed by a direct `DialogFooter`. This shared shell owns the fixed, divider-separated action region and independently scrolling body; feature styles may set the dialog width but must not recreate its padding, divider, background, or overflow behavior. Use `EditorDialogError` for failed-save feedback between the title and body.

Management tables keep native table markup because column structures and responsive minimum widths differ. Their shared contract is local horizontal scrolling, tokenized header/row/border treatment, and an action group in the action cell. A scroll wrapper that can overflow must be keyboard focusable and named when keyboard users otherwise cannot reach its horizontal content.

## Intentional Specialized Patterns

The following are not generic Button, Field, or Card variants. Reuse their established component or feature pattern and document any new exception here:

- Primary navigation tabs and the Configure menu, including its menu keyboard model.
- Label-backed session-type, AI-source, answer-mode, and Integrated AI model choices use the shared `ChoiceIndicator` with their feature-specific layout.
- Checkboxes, range controls, file inputs, and feature-specific progress compositions. Favorite state uses `FavoriteToggle`.
- Discussion message authorship surfaces, Markdown output, quick-action chips, reference actions, inline title editors, and the material pane/rail/separator compound widget.
- The discussion material pane uses internal scrolling alongside the desktop workspace and intrinsic height with bounded content scrolling when stacked; its header and toggle stay in the visible pane.
- The Activity Stop action, which immediately cancels live work rather than deleting a resource.
- Integrated AI lifecycle, transfer, storage, hardware, and maintenance structures.
- Prompt Preview output cards, which are read-only technical content rather than textareas.
- Prompt-configuration provenance badges, which identify shipped, changed, and custom source state.
- Data-driven agent colors and progress percentages supplied through inline styles.

Specialized patterns still use approved tokens, visible focus, native semantics, responsive reflow, reduced motion, and localized names. A legitimate reusable need should extend a shared API with a clearly named variant before introducing a one-off visual override.

## Change Workflow

Before changing UI, inspect this guide, the rendered gallery, the relevant shared component, and representative consumers. When changing a shared token, component, variant, or pattern, update affected consumers, the gallery, this guide, focused behavior tests, and accessibility/visual regression coverage in the same change. Remove superseded markup and CSS rather than leaving competing implementations.

Verify the component in the gallery and in representative consuming screens, including desktop and narrow layouts, English and German, keyboard focus, and applicable disabled, loading, validation, and error states. Run from `frontend/`:

```bash
npm run test:accessibility
npm run lint
npm run typecheck
npm run build
```

Use `npm run test:responsive` and focused product tests for layout or cross-screen changes. Browser, automated, and source checks are corroborating evidence; only a fresh packaged Tauri run with disposable data is native GUI evidence. Record macOS, Windows, and Linux evidence separately.
