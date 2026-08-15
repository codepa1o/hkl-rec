# NewsIntentRec Authentication Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add secure, polished email/password registration and session authentication to the existing FastAPI + React application.

**Architecture:** A focused authentication repository and service sit beside the recommendation runtime repository. FastAPI routes issue a short-lived JWT in an HttpOnly cookie; React restores `/auth/me` through an `AuthProvider` and gates the existing product shell with React Router.

**Tech Stack:** FastAPI, Pydantic, PyMySQL, pwdlib/Argon2, PyJWT, React 18, React Router 6, Vitest, Testing Library, CSS variables.

---

## File map

- Create `backend/app/auth/security.py`: password hashing and JWT primitives.
- Create `backend/app/auth/repository.py`: auth repository protocol and MySQL implementation.
- Create `backend/app/auth/service.py`: registration, login and current-user orchestration.
- Create `backend/app/schemas/auth.py`: validated API contracts.
- Create `backend/app/routers/auth.py`: Cookie-based HTTP endpoints and current-user dependency.
- Modify `backend/app/config.py`, `backend/app/dependencies.py`, `backend/app/main.py`: auth configuration and wiring.
- Modify `sql/schema.sql`; create `sql/migrations/001_auth.sql`: account table and `app_user` ID allocation.
- Create `tests/test_auth_security.py`, `tests/test_auth_service.py`, `tests/test_auth_routes.py`: backend red/green coverage.
- Create `product-frontend/src/context/AuthContext.tsx`: session state.
- Create `product-frontend/src/components/ProtectedRoute.tsx`: route gate.
- Create `product-frontend/src/pages/AuthPage.tsx`: login/registration UI.
- Create `product-frontend/src/context/AuthContext.test.tsx`, `product-frontend/src/pages/AuthPage.test.tsx`: frontend behavior coverage.
- Modify `product-frontend/src/App.tsx`, `product-frontend/src/components/TopNav.tsx`, `product-frontend/src/api/client.ts`, `product-frontend/src/api/types.ts`, `product-frontend/src/styles/global.css`: integration and presentation.

### Task 1: Security and domain behavior

- [ ] Write failing tests proving passwords are Argon2 hashes and JWTs accept valid tokens but reject expired/tampered tokens.
- [ ] Run `python -m pytest tests/test_auth_security.py -q` and verify failure is caused by the missing auth module.
- [ ] Implement `hash_password`, `verify_password`, `create_access_token`, and `decode_access_token` in `backend/app/auth/security.py` using `pwdlib` and `PyJWT`.
- [ ] Re-run the security tests to green.
- [ ] Write service tests with a test repository for normalized registration, duplicate email, successful login, generic invalid-credential failure, and disabled users.
- [ ] Run `python -m pytest tests/test_auth_service.py -q` and verify expected missing-service failure.
- [ ] Implement `AuthService` and the repository protocol minimally to satisfy those tests.
- [ ] Re-run both test modules.

### Task 2: Persistence and API routes

- [ ] Write route tests for register Cookie attributes, `/auth/me`, login failure, missing session and logout.
- [ ] Run `python -m pytest tests/test_auth_routes.py -q` and verify routes are absent.
- [ ] Add validated auth schemas and the four `/auth` routes.
- [ ] Implement `MysqlAuthRepository` with transaction-safe creation of `app_user`, `user_account`, and `user_profile`.
- [ ] Add auth settings and dependencies; include the router and enable credentialed CORS.
- [ ] Update fresh-install and incremental MySQL schema files.
- [ ] Add `pwdlib[argon2]`, `PyJWT`, and `email-validator` to pinned backend dependencies.
- [ ] Run `python -m pytest tests/test_auth_security.py tests/test_auth_service.py tests/test_auth_routes.py -q` to green.

### Task 3: Frontend session state and route protection

- [ ] Write failing `AuthContext` tests for session restoration, login state, logout state and API error propagation.
- [ ] Run `npm test -- --run src/context/AuthContext.test.tsx` and verify the missing context failure.
- [ ] Extend API types/client with `register`, `login`, `getCurrentUser`, `logout`; make all requests send credentials and parse structured API errors.
- [ ] Implement `AuthProvider`, `useAuth`, and `ProtectedRoute`.
- [ ] Re-run the context tests to green.
- [ ] Restructure `App.tsx` so `/auth` is public and the existing product shell is protected.

### Task 4: Polished login/registration experience

- [ ] Write failing UI tests for visible Chinese login fields, register-mode validation, successful submission and server error feedback.
- [ ] Run `npm test -- --run src/pages/AuthPage.test.tsx` and verify failure because the page is missing.
- [ ] Implement the editorial two-column `AuthPage`, accessible labels, password visibility control, pending state and mode switching.
- [ ] Add responsive auth styles using existing theme variables; add current-account and logout controls to `TopNav`.
- [ ] Re-run the UI tests, then all frontend tests.

### Task 5: Simulation, debugging and completion verification

- [ ] Run backend auth tests and inspect every failure before changing code.
- [ ] Run `python -m pytest -q --ignore=tests/test_search_artifacts.py --ignore=tests/test_als_recall.py` for the non-FAISS regression suite.
- [ ] Run `npm test -- --run` and `npm run build` in `product-frontend`.
- [ ] Run a TestClient scenario: register → me → logout → rejected me → login → restored me.
- [ ] Scan the final diff for secrets, plaintext passwords, insecure Cookie settings, accidental unrelated edits and missing environment documentation.
- [ ] If any verification fails, reproduce it, identify the root cause, add or refine a failing regression test, apply the smallest fix, and repeat the complete relevant verification suite.
