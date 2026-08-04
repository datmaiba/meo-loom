### Frontend (React + TypeScript, standalone SPA — no in-repo backend)

- Flow (MUST): component → hook → api. No fetch/axios calls in components. React Query owns ALL server state; Zustand (or equivalent) holds UI-only state — never store server data in it.
- Page/module structure (MUST): each feature module owns its own `api/`, `hooks/`, `stores/`, `components/`, `types.ts`. No cross-module imports except through `shared/`.
- Component folder standard (MUST): PascalCase folder matching the exported component name; `ComponentName.tsx` + `ComponentName.module.scss` + `index.ts` barrel; named exports only; extract to sub-components/hooks past ~200 lines.
- Reuse before building (MUST): grep `shared/components/` (and the module's own `common/`) for an existing badge/icon/button/modal/popover/form-control before writing a new one — duplicating a shared component is a defect, not a style nit.
- No raw markup for solved problems (MUST NOT): no bare `<table>/<tr>/<td>` — use the project's table abstraction (e.g. `DataTable`/`ListingTable`); no raw `btn`-styled `<button>`/href-less `<a>` — use the shared `<Button>`. If the project has (or should have) an ESLint rule enforcing either, wire it — these are cheap to lint and expensive to review by eye.
- Styling: design tokens only (`var(--…)`), never raw hex/px/rem for colour, spacing, radius, or shadow; BEM kebab-case class names (`.driver-form__field--error`, not `.driverForm__field--error`), bracket access from CSS Modules (`styles['driver-form__field--error']`).
- Two-tier tokens (Tailwind v4 projects): a hand-rolled `--color-*`/`--spacing-*`/`--font-size-*` CSS-variable layer AND a Tailwind `@theme { … }` block that re-exposes the same names as utility classes are two separate files that must be kept in sync — a token added to only one is invisible from the other surface. Confirm both when adding/renaming a token.
- Permission-gated UI: reference permissions via typed constants (`Permission.xxx.read`/`.write`), never raw strings.
- i18n (if the project is multilingual): all UI strings through the i18n helper; hardcoded UI strings are blocking defects.
