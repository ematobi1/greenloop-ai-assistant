# Authentication and token storage

## The token

`scripts\setup.ps1` generates a random 256-bit token, prints it once, and stores only its SHA-256 hash in `.env` (`GREENLOOP_API_TOKEN_HASH`). Every endpoint except `GET /v1/health` requires `Authorization: Bearer <token>`. `scripts\new-token.ps1` replaces it.

## How the dashboard holds the token (current behavior)

The dashboard keeps the token in browser **`sessionStorage`** under the key `greenloop.apiToken` (`services/frontend/src/auth/tokenStorage.ts`).

| Property | Behavior |
|---|---|
| Lifetime | Until the tab or window is closed. Survives a page reload. |
| Scope | One tab. A new tab, or a copy opened from a link, starts locked. |
| `localStorage`, cookies, IndexedDB | Not used. Nothing persists after the tab closes. |
| Sent to | The same-origin `/v1` API only, as a Bearer header. It is never sent to a model provider. |
| Cleared by | The **Lock** button, any 401 response, or closing the tab |
| Storage blocked | Reads and writes are wrapped in `try/catch`. If the browser refuses, the token lives in memory for the page and the user re-enters it after a reload. |

### Risk

Any script running in the dashboard's origin can read `sessionStorage`. React escapes rendered text, the app uses no `dangerouslySetInnerHTML`, and it loads no third-party scripts, so today there is no known path for injected script. If that ever changes (for example rendering model output as HTML or Markdown), a cross-site scripting bug would expose the token to the page. The token can then be replayed against the API from this machine only, because the API rejects any `Host` other than `127.0.0.1` and `localhost` and binds to loopback.

### Option: memory-only storage

To keep the token out of browser storage entirely:

1. Replace `tokenStorage.ts` with a module-level variable (`let token: string | null`). `readStoredToken`, `storeToken`, and `clearStoredToken` keep their signatures, so `Dashboard.tsx` does not change.
2. The trade-off: a page reload locks the dashboard and the user pastes the token again. There is no way to keep the token across reloads without persisting it somewhere.
3. Tests to change: the two `sessionStorage` assertions in `Dashboard.test.tsx`.

A step beyond that is an `HttpOnly`, `SameSite=Strict` cookie set by the backend after an unlock request. That hides the token from page scripts but adds cookie handling and CSRF protection, so it is worth doing only when the API is exposed beyond a single local user.

**Decision status:** `sessionStorage` is kept for now. Switching to memory-only is a small change and can be requested at any time.
