# CAS centralized sign-in

Realm: set `KEYCLOAK_REALM=chiro-public` for the separate public CAS realm at `https://auth.chirocity.gov.et`. Older installations may still use `chirocity`; changing this setting requires explicit migration of existing account links.

## Moving an existing account to another realm

Recreate the CAS clients, audience mapper, roles, provisioner permissions, redirect URIs and web origins in the target realm. Set `KEYCLOAK_REALM` and the target realm provisioner secret in the ignored environment file (`api/.env` locally, root `.env` for Docker). Restart Django or recreate the API container so it reads these settings.

Verify the target user's ID, email, enabled status and CAS client roles before linking. The management command rejects replacement of an existing identity unless both its expected previous subject and issuer are supplied. For the approved CAS administrator migration, run after deploying the updated command:

```sh
export LINK_EMAIL=cas@chirocity.gov.et
export KEYCLOAK_SUB=fa442fe7-ffff-4d8f-833f-217c57ace706
CAS_DATA_DIR=/srv/cas docker compose --env-file .env -f docker-compose.yml -f docker-compose.domains.yml exec -T -e LINK_EMAIL -e KEYCLOAK_SUB cas-api python manage.py link_chiro_user --previous-subject aa66d67e-d962-4424-ba47-3b7061392e5c --previous-issuer https://auth.chirocity.gov.et/realms/chirocity
unset LINK_EMAIL KEYCLOAK_SUB
```

This preserves the local account ID and its case/history relationships. Other existing accounts need their own verified migration; they are never matched automatically by email. Sign out and sign in again after switching realms. Keep the old realm until the remaining accounts are migrated. Provisioner credentials belong only in server environment files.

- Public OIDC client: `cas-web`, client authentication OFF, standard flow ON, PKCE S256.
- Valid redirect and post logout redirect: `https://cas.chirocity.gov.et/login`.
- Web origin: `https://cas.chirocity.gov.et`.
- API audience/client: `cas-api`; include the API audience in access tokens.
- Attach the `roles` client scope to cas-web as Default and permit the required cas-api roles through its role scope mappings.
- Users require a verified email and CAS client roles under `resource_access["cas-api"].roles`.

| Client role | CAS group |
| --- | --- |
| ADMIN | Admin |
| MAYOR_OFFICE | Mayor Office |
| DIRECTOR | Director |
| FOCAL_PERSON | Focal Person |
| CITIZEN | Citizen |

Exact existing group names are also accepted as explicitly mapped client role aliases. Roles from other clients and realm roles grant no access. CAS has single-primary-role workflows: when several roles are assigned, the highest role in this table wins. Citizen case scoping and existing group permissions remain enforced.

Run the normal deployment workflow first, then **Configure CAS Chiro Auth** with the independently verified account email and Keycloak subject. Existing matching accounts are linked without changing their local ID, office assignment, cases or history. Ambiguous or conflicting identities are rejected. A new email is provisioned at the first authorized sign-in. Email alone never automatically links accounts.

The activation workflow validates the Keycloak redirect, backs up `.env`, retains the `/srv/cas` data directory and edge networks, enables AUTH_MODE=keycloak, and checks API health and rejection of local password login. On failure it restores the environment and API container. Local password, registration and Django admin login endpoints cannot bypass Chiro Auth. Profile/office data and local account disabling remain in CAS; credentials and grants are managed in Chiro Auth.

`0002_workflow_schema` replaces four omitted migrations whose applied names were verified on the VPS. It creates the missing workflow schema on fresh databases and retains existing production tables when all four historical migrations were applied. `0006_chiro_identity` adds only nullable identity fields. The deployment creates a SQLite backup before migration and does not run the demo seed. The regression script checks this historical upgrade path and preservation of the existing user ID.

Run **Verify live CAS browser login** after activation. It verifies rendering and the redirect to the Chiro Auth login form without signing in as a real user.

## Applicant self-registration

CAS opens Keycloak login automatically from `/`, `/login`, `/auth/sign-in` and protected pages when no session exists. Existing Chiro Auth sessions enter CAS without another password prompt. The app sign-in screen remains only for recovery after a sign-in or authorization error.

Applicant registration is public at `/auth/sign-up`. The app form calls `/api/auth/applicant-registration/`; the backend creates a verified Keycloak identity with only `cas-api/CITIZEN` and a linked CAS profile. It does not issue tokens or accept browser-supplied roles. After signup the user signs in through Keycloak. The shared theme routes the cas-web Register link directly to this form.

Keep realm registration enabled so the theme displays Register. Do not use realm-wide CAS or CLMS applicant default groups: those grant access across app registration paths. Each app assigns only its own client role. Existing users of the shared realm need explicit app access; email alone never links existing CAS accounts. Deploy the CAS backend/frontend before deploying the updated Keycloak theme.

## Optional email confirmation

`CAS_REQUIRE_VERIFIED_EMAIL=true` is the default. Set it to `false` in the VPS `.env` and recreate only `cas-api` to allow CAS applicants to sign in without confirming their email. This does not mark the email verified in Keycloak, relax token issuer/signature/audience/client checks, allow unknown CAS roles, or automatically link existing email accounts. The signup instructions follow the runtime policy. Other applications retain their own verification requirements.

Keycloak can still require verification before issuing a token. To allow login without confirmation, its Verify email switch and any applicant Verify Email required action must also permit this. Realm-wide settings affect the shared realm; they do not change other applications' server-side requirements.

## Automatic login configuration

No Keycloak changes are required for automatic login. Keep `cas-web` public, Standard Flow enabled, PKCE S256, the existing production/local `/login` redirect and post logout URIs, and their web origins. Keep the `cas-api` audience mapper and role grants. The change uses the existing Authorization Code flow. Deploy the updated frontend through the normal CAS deployment workflow; no database migration or identity relinking is needed.

For local Django development, install `api/requirements.txt` and put `AUTH_MODE=keycloak` and the server-only provisioner settings in the ignored `api/.env`. Django loads this file without overriding environment variables already set by the terminal or Docker. Use `FRONTEND_BASE_URL=http://localhost:3000` locally. Restart Django after environment-file changes, then reload the frontend. `/api/auth/config/` must report `mode: keycloak`; `mode: local` intentionally retains the legacy login form. Production Docker continues to use the root `.env` through Compose.
