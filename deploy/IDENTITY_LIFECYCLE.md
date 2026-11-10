# Keycloak account lifecycle: CAS

## Behavior

Every protected API request checks the linked subject in this app's `cas` realm after verifying its JWT. A deleted central account receives 401; a disabled account receives 403, even if its JWT has not expired. There is no positive account-status cache. Account checks fail closed with 503 on a Keycloak outage or invalid provisioner credentials; an outage must never be interpreted as deletion.

User directories fetch the current central user IDs in pages of 100 and filter local linked profiles BEFORE pagination/counting. Deleted subjects and old-realm links are hidden; unlinked legacy profiles remain available for explicit migration. An open browser table refreshes on its next fetch, not by a pushed event. No webhook, Event Listener SPI, public callback endpoint, or database migration is required.

In apps with user management, disabling an account updates Keycloak and revokes its realm sessions before saving the local inactive state. Delete removes the linked Keycloak account and retains an inactive local profile so cases, records, employees, approvals and audit references survive. Deletion of an already-missing central subject is safe to retry. A remote failure returns an error rather than success; if disabling succeeded but deletion failed, the local profile can remain inactive until retry. Changes target the stored subject ID and require its stored issuer to match the configured realm. Email is never used as an automatic deletion/linking key.

DCA and the dashboard currently have no app user-management Delete action; their change is live account validation. Their roles/features are unchanged.

## Keycloak setup (do this before deploying)

1. Select realm **cas**. Use its existing `cas-provisioner` client, or create one if absent.
2. Set **Client authentication ON** and **Service accounts roles ON**. A provisioner is a confidential server-only client, not the browser client. Do not enable password grants for it.
3. Under **Service account roles ? Assign role ? Filter by clients ? realm-management**, grant **view-users** and **query-users** for live checks/directory reads. Apps that create, disable, or delete users also need **manage-users**. These standard roles provide realm-wide user access; use equivalent fine-grained permissions if your deployment requires narrower access. Preserve existing client/role-management grants used by role synchronization. No new `manage-realm` grant is needed for this feature.
4. Copy its client secret into a private backend environment. Never commit it or put it in a frontend/VITE_/NEXT_PUBLIC_ variable.

```dotenv
AUTH_MODE=keycloak
KEYCLOAK_URL=https://auth.chirocity.gov.et
KEYCLOAK_REALM=cas
KEYCLOAK_CLIENT_ID=cas-web
KEYCLOAK_AUDIENCE=cas-api
KEYCLOAK_ADMIN_CLIENT_ID=cas-provisioner
KEYCLOAK_ADMIN_CLIENT_SECRET=REPLACE_PRIVATELY
```

Local development: save in `api/.env` and restart the backend. On the VPS, save in the repository root `.env`; Docker does not automatically read the local backend file.

## Deploy and verify

Commit/push this repository using your normal workflow after setting the secret. This work was made locally only; no VPS, live realm, or user records were modified. Deploy each app separately. If manually recreating containers, use that app's existing complete Compose command (including its domains override where applicable), then test/reload the shared Nginx proxy. Do not delete Docker data volumes.

Use a disposable NON-administrator account for verification:

1. Create it in the app, assign a permitted role, and sign in.
2. Disable it in Keycloak while keeping the browser session open: its next protected API request must be denied.
3. Re-enable it in Keycloak: if the app also disabled its local profile, an app administrator must reactivate that profile too.
4. Delete it directly in Keycloak: its next protected API request must return 401 and it must disappear from the next user-directory response.
5. Create another disposable user in the app and delete it through the app's Delete action: confirm the subject is absent in Keycloak and historical records are retained.
6. Stop/block a test Keycloak connection: protected APIs must return 503; no local users should be deleted or treated as missing.

Self-deletion and removal of the last active administrator are blocked in management routes. Retain a separate Keycloak recovery administrator. Disabling/deleting the sole application administrator directly in Keycloak can still lock you out; the app cannot prevent an external administrator doing that.

Reference: [Keycloak Admin REST API](https://www.keycloak.org/docs-api/latest/rest-api/index.html) (`GET /users`, `GET/PUT/DELETE /users/{user-id}`, `POST /users/{user-id}/logout`).
