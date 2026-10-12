# GeoPort 0.1.4 design QA

final result: passed

## Visual truth and evidence

- Approved source: `docs/design/reference.png` (second generated proposal, approved by the user).
- Light implementation: `docs/design/workbench-light.png`.
- Dark implementation: `docs/design/workbench-dark.png`.
- Narrow layout: `docs/design/mobile-dark.png`.
- Source: 1505 × 1045 image pixels. Desktop browser: 1440 × 1000 CSS px, deviceScaleFactor 1; full-page capture 1440 × 1060. Mobile: 390 × 844 CSS px, capture 390 × 1658.
- The source is a style/layout target, not a literal copy of sample device names or random coordinates. Comparisons normalize source width to desktop width; sample content and platform system-font rendering may differ.
- Source and browser capture were opened together for full-view comparison. Form, coordinate strip, tab focus and the narrow dark capture were separately inspected at readable scale.

## Comparison history

1. Initial browser capture had unnecessarily large desktop gutters, and a top-level success message pushed the workspace downward (P2). Expanded the desktop shell to match the approved margins, adjusted heading size, and placed operation feedback within its card. Recaptured desktop and mobile light/dark layouts.
2. A settings success message remained in the location card after changing tabs (P2). Scoped status feedback to its originating page and restored the current operation state on tab changes. Re-ran keyboard navigation and settings tests, recaptured all themes.
3. Final inspection found no actionable P0/P1/P2 issues. Core cards align; controls remain readable and operable; narrow screens stack without overflow. There is no tagline below GeoPort.

## Required surfaces

- Typography: system SF Pro/PingFang SC on macOS with platform fallbacks; 40px desktop heading, 19px card headings, 14px controls, 12–14px secondary copy, monospaced coordinates. No web-font downloads.
- Rhythm: 56px desktop gutters, 18px main grid gap, 23–24px card padding, small 6–9px corner radii. Device/base cards on the left and location/actions on the right. Narrow layout stacks the cards and coordinate fields.
- Tokens: warm neutral light palette, graphite dark palette, restrained green confirmation, semantic error text. Secondary text contrast checked >= 4.5:1 in both appearances. Keyboard focus is explicit; motion honors reduced-motion preferences.
- Assets: original Tabler outline icons with MIT attribution, not drawn placeholders. New light/dark app icons share the same location-pin/orbit silhouette. Local favicons follow system appearance; native icon masters are converted by Apple tools into icon families and an appearance catalog.
- Copy: all actions describe actual behavior. Saving does not apply a location, history selection does not silently save/apply, random offsets remain based on the saved centre. Busy/unconnected controls prevent invalid operations. No backend or build details in the main flow.

## Browser verification

`tests/browser_design.py`: desktop/narrow light and dark, keyboard ARIA tabs, preferences persistence, unsaved coordinate indicator, connected/simulating state, theme tokens, local-only resource loading, no page errors or overflow. `tests/browser_smoke.py`: explicit save, radius restore, repeated single offsets, shared session, baseline restore, stop, process restart and failure/exit flow.

Native iPhone behavior, Finder/Dock icon appearance on the user's macOS version, and Safari's system font metrics remain part of physical acceptance; browser and source tests cannot prove those behaviors.

## HIG references

- https://developer.apple.com/design/human-interface-guidelines/layout
- https://developer.apple.com/design/human-interface-guidelines/typography
- https://developer.apple.com/design/human-interface-guidelines/buttons
- https://developer.apple.com/design/human-interface-guidelines/accessibility
- https://developer.apple.com/design/human-interface-guidelines/app-icons

Official pages and their DocC content were read during implementation. Primary actions use consistent styles, controls have labels and focus states, status is expressed in text as well as color, and dense desktop/narrow layouts use the same hierarchy.

## Follow-up polish

Actual macOS SF Pro/PingFang rendering and native icon appearance should be checked on the user's Mac. Do not change system security settings or drop device libraries to reduce size.
