# CAS centralized sign-in

Realm: `chirocity` at `https://auth.chirocity.gov.et`.

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

Applicant registration remains public at `/auth/sign-up`. This introduction page opens Keycloak registration with PKCE and the existing `/login` callback. Users can also use the Register link on the Keycloak login page when realm registration is enabled. No local password account or privileged role is created by the browser.

Enable **Realm settings > Login > User registration** in the `chirocity` realm. Configure SMTP and email verification for applicants. Each applicant must receive `cas-api > CITIZEN` for own-case access. Assign it manually after review, or map it to a `CAS Applicants` group and make that a default group if all new realm users should automatically receive applicant access. A default group applies to all newly created users in this shared realm; it is not restricted to the CAS registration link. Staff roles must remain explicitly assigned.

## Optional email confirmation

`CAS_REQUIRE_VERIFIED_EMAIL=true` is the default. Set it to `false` in the VPS `.env` and recreate only `cas-api` to allow CAS applicants to sign in without confirming their email. This does not mark the email verified in Keycloak, relax token issuer/signature/audience/client checks, allow unknown CAS roles, or automatically link existing email accounts. The signup instructions follow the runtime policy. Other applications retain their own verification requirements.

Keycloak can still require verification before issuing a token. To allow login without confirmation, its Verify email switch and any applicant Verify Email required action must also permit this. Realm-wide settings affect the shared realm; they do not change other applications' server-side requirements.

## Automatic login configuration

No Keycloak changes are required for automatic login. Keep `cas-web` public, Standard Flow enabled, PKCE S256, the existing production/local `/login` redirect and post logout URIs, and their web origins. Keep the `cas-api` audience mapper and role grants. The change uses the existing Authorization Code flow. Deploy the updated frontend through the normal CAS deployment workflow; no database migration or identity relinking is needed.

For local Django development, install `api/requirements.txt` and put `AUTH_MODE=keycloak` and the server-only provisioner settings in the ignored `api/.env`. Django loads this file without overriding environment variables already set by the terminal or Docker. Use `FRONTEND_BASE_URL=http://localhost:3000` locally. Restart Django after environment-file changes, then reload the frontend. `/api/auth/config/` must report `mode: keycloak`; `mode: local` intentionally retains the legacy login form. Production Docker continues to use the root `.env` through Compose.
