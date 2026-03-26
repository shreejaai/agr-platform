# AGR Dashboard — Developer Context

Angular 17 standalone app. Tailwind CSS, @clerk/clerk-js, OnPush, signals, inject().

---

## Critical Patterns

```typescript
// No NgModules — standalone components only
// inject() over constructor injection
// OnPush change detection everywhere

// API key interceptor SKIPS if Authorization already set
// (protects Clerk JWT when calling /v1/clerk/api-key)
```

## Auth Flow
1. `ClerkService.init()` → if signed in + no localStorage key → `fetchApiKey()`
2. `fetchApiKey()` → GET /v1/clerk/api-key with Clerk JWT (3 retries, 2s delay)
3. Key stored in localStorage → `apiKeyInterceptor` injects `Bearer <agr_sk_>` on all `/v1/` requests
4. `authGuard` → Clerk signed-in check
5. `apiKeyGuard` → `agr_sk_` key in localStorage

## Key Files
- `src/app/core/auth/clerk.service.ts` — Clerk wrapper, `fetchApiKey()`, `FetchKeyResult`
- `src/app/core/http/api-key.interceptor.ts` — injects Bearer header (skips if Authorization set)
- `src/app/app.routes.ts` — lazy routes with `authGuard + apiKeyGuard`
- `src/environments/environment.ts` — `clerkPublishableKey`, `apiBase: '/v1'`
- `proxy.conf.json` — dev: `/v1 → http://localhost:8000`

## Shared Components
- `badge/badge.component.ts` — 10 colour variants
- `stat-card/stat-card.component.ts`
- `pipes/relative-time.pipe.ts` — Intl.RelativeTimeFormat

## Commands
```bash
cd apps/agr-dashboard
npm install --legacy-peer-deps
npm start          # dev server on :4200, proxies /v1 to :8000
npm run build      # production build
npm run lint
npm test -- --watch=false --browsers=ChromeHeadlessNoSandbox
```

## Styles
`styles.css` — Tailwind + custom classes: `.btn-primary`, `.card`, `.input`, `.table-*`
Dark slate/indigo palette — see `tailwind.config.js`
