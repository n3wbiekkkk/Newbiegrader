# Preserve the admin route during session startup — 2026-10-20

## Confirmed cause

`static/app.js` initially sets `is_admin=false`, paints the current route, then
loads `/api/auth/me`. Both the router and `renderAdmin()` treated that initial
unknown state as a confirmed denial and changed `#/admin` to home. A second
redirect in `refreshMe()` also ran before remember-me restoration completed.

## Correction

- Track initial session readiness separately from the admin role. Resolve
  `/me`, optional `/auth/restore`, and the restored identity before deciding.
- Keep the requested admin hash while pending. A status region is visible;
  admin controls are hidden and no admin data loaders run before authorization.
- After a confirmed non-admin/anonymous result, hide controls and replace the
  protected history entry with home. No role is trusted from browser storage.
- An identity/restore error keeps the URL and shows a reload message, with
  controls hidden. An unrelated health-check failure cannot override this route.
- Completion re-renders the current route, so leaving admin during the request
  does not navigate the visitor back. Existing identity request sequence checks
  remain intact. Public routes still paint before identity resolves.
- App asset version: 57. Backend authorization and production services unchanged.

## Verification

`node --test tests/test_*.js`: **110 passed, 0 failed, 0 skipped**. The nine new
tests execute the actual initialization, identity restoration, router and admin
rendering functions with synthetic DOM/API responses. Cases include delayed
identity, remember-me, regular/anonymous denial, errors, leaving during a fetch,
health failure, revocation and immediate rendering of public routes.

Playwright with isolated browser contexts and a loopback static server checked
direct entry, actual reload, remember-me restoration and non-admin denial.
Delayed synthetic identity/restore responses preserved `#/admin`; controls and
admin reads stayed blocked until authorization. No page errors, real accounts
or production API requests were used. Private screenshots were visually checked.
JavaScript syntax, frontend ID references and style guards passed.

The full Python suite also passed **423 tests, 0 skips** in disposable Docker
Linux ARM64/root, Python 3.11, with no network or production credentials and all
89 protected problem packages available.

This verifies the frontend routing fix with controlled identities, not a fresh
production OAuth/OTP login. API access control is still enforced server-side.

## Rollback

Revert this frontend fix commit and let Pages publish its parent assets. The
previous admin-reload defect will return. No database, file catalog, worker,
backend service or credential changes require rollback.
