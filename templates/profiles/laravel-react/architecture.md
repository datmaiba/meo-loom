### Backend (PHP / Laravel)

- Layers, one-way (MUST): `Controllers → Services → Repositories → Models`. One API per controller, single `__invoke`.
- CQRS-lite (MUST): Command services (one write op, `execute()`) vs Query services (read-only).
- Repositories return plain DTOs — no Eloquent leakage above the repository (MUST).
- Routes: one file per entity under `routes/api/`; permission checks via constants; raw permission strings FORBIDDEN.
- Multilingual content (if the project is bilingual): all translated fields live in `*_translations` tables — MUST NOT add per-locale columns (`title_en`, `title_vi`, …).

### Frontend (React + TypeScript)

- Flow (MUST): component → hook → api. No fetch/axios in components. React Query for ALL server data; UI state only in local state/store.
- Component folder standard (MUST): PascalCase folder, `ComponentName.tsx` + `.module.scss` + `index.ts`; named exports only; <200 lines per file.
- Styling: design tokens only (`var(--…)`) defined in the project's tokens file; no raw hex/px; BEM kebab-case class names, bracket access from modules.
- i18n (MUST, if bilingual): all UI strings through the i18n helper (`t('key')`); hardcoded UI strings are blocking defects.
