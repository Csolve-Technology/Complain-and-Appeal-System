# Dashboard SSO across dedicated app realms

Keycloak brokering is configured for all eight app realms, with the extra provider button hidden. The dashboard now enables SSO card routing by default. Deploy the app routing changes FIRST and the dashboard LAST. Application code changes remain local until you push/deploy them; use DASHBOARD_BROKER_ENABLED=false only for rollback or a staged rollout. The setup details below are retained for review and reinstallations.

The dashboard realm authenticates the person. Each target app realm issues its own token and enforces its own roles and permissions. Dashboard tokens are never sent to app APIs. Native app accounts and CAS/CLMS registration stay app-specific.

## 1. Grant central administrator access

In realm **dashboard**, create realm role **ALL_APPS_ADMIN**. Do not make it a default role. Assign BOTH this role and **dashboard-api → ADMIN** to the intended administrator. Keep the account enabled and its email verified.

The client role opens the dashboard. The new realm role authorizes the app-role mappings below. Other dashboard administrators need not receive all-app access.

## 2. Create eight confidential broker clients in dashboard

These clients are distinct from existing browser/API/provisioner clients.

| Target realm | Client in dashboard realm | Exact Valid redirect URI |
|---|---|---|
| hrms | broker-hrms | https://auth.chirocity.gov.et/realms/hrms/broker/dashboard-sso/endpoint |
| chrms | broker-chrms | https://auth.chirocity.gov.et/realms/chrms/broker/dashboard-sso/endpoint |
| lms | broker-lms | https://auth.chirocity.gov.et/realms/lms/broker/dashboard-sso/endpoint |
| clms | broker-clms | https://auth.chirocity.gov.et/realms/clms/broker/dashboard-sso/endpoint |
| cas | broker-cas | https://auth.chirocity.gov.et/realms/cas/broker/dashboard-sso/endpoint |
| dca | broker-dca | https://auth.chirocity.gov.et/realms/dca/broker/dashboard-sso/endpoint |
| ccrs | broker-ccrs | https://auth.chirocity.gov.et/realms/ccrs/broker/dashboard-sso/endpoint |
| cctbm | broker-cctbm | https://auth.chirocity.gov.et/realms/cctbm/broker/dashboard-sso/endpoint |

For each client:

1. OpenID Connect; **Client authentication ON**, **Standard Flow ON**. Direct Access Grants OFF, Service Accounts OFF, and Consent Required OFF.
2. Use its one exact redirect URI above; no wildcards. Web origins can stay empty because Keycloak performs the token exchange server-side.
3. Client scopes → dedicated scope → Add mapper → By configuration → **User Realm Role**:
   - Name: `central-admin-roles`
   - Token claim name: **chiro_dashboard_roles**
   - Claim JSON type: String; **Multivalued ON**
   - Add to ID token, access token, and UserInfo: **ON**
   - No realm-role prefix. This must map actual roles, not an editable user attribute.
4. If Full Scope Allowed is OFF, include ALL_APPS_ADMIN in this client's role scope mappings. Evaluate the central administrator's ID token: it must include `"chiro_dashboard_roles": ["ALL_APPS_ADMIN"]`. A user without this role must not have that value.
5. Copy its client secret only into the target realm's identity provider in section 3. Do not put broker secrets in Git or frontend environment files.
6. For independent logout domains: **Admin URL empty**, **Backchannel logout URL empty**, **Front channel logout OFF**. Do not configure dashboard-to-app logout callbacks for these broker clients.

## 3. Configure an identity provider in each app realm

Example: select **hrms** → Identity providers → Add provider → **OpenID Connect v1.0**.

| Setting | Value |
|---|---|
| Alias | **dashboard-sso**, exactly the same in every app realm |
| Display name | Chiro Dashboard |
| Enabled | ON |
| Account linking only | OFF |
| Hide on Login Page | **ON** (API property `hideOnLogin=true`; explicit broker hints still work) |
| Discovery endpoint | https://auth.chirocity.gov.et/realms/dashboard/.well-known/openid-configuration |
| Client ID | broker-hrms (use the matching client for each realm) |
| Client secret | Matching confidential broker client secret |
| Client authentication | Client secret sent as POST, or matching supported confidential method |
| Default scopes | openid profile email |
| Signature validation | ON; use discovery JWKS; preserve HTTPS verification |
| Sync Mode | **FORCE** |
| First Login Flow | Built-in **first broker login**, with secure existing-account verification |
| Prompt | **none** |
| Logout URL | **EMPTY after importing discovery** |
| Backchannel Logout support | OFF |

Enable Trust Email only because you control the dashboard realm and verify these administrator addresses; confirm their upstream email_verified claim is true.

Import discovery first, then clear Logout URL and save: discovery normally fills it. An empty provider Logout URL prevents an app-realm logout from logging out of the upstream dashboard realm.

The app requests `prompt=login` in its own realm for dashboard launches, so a different app-only account's existing cookie is not silently reused. The identity provider's **Prompt=none** overrides this upstream, allowing the existing dashboard session to authenticate without another password. If the dashboard session expired, return to the dashboard and sign in again.

Do NOT configure a realm-wide default Identity Provider Redirector. The app code selects this provider only for dashboard-launched URLs. Native login and applicant registration remain available, without an extra Chiro Dashboard button. If you require PKCE on the broker hop, enable S256 on BOTH the provider and its upstream confidential client.

## 4. Map the central grant to each app's role

In every target realm → Identity providers → dashboard-sso → Mappers → Add mapper:

| Setting | Value |
|---|---|
| Name | dashboard-all-apps-admin |
| Mapper type | **Claim to Role** |
| Sync Mode Override | **FORCE** |
| Claim | **chiro_dashboard_roles** |
| Claim Value | **ALL_APPS_ADMIN** |
| Role | The target API client's **ADMIN** role, e.g. **hrms-api → ADMIN** |

Use the role picker. For other realms select chrms-api, lms-api, clms-api, cas-api, dca-api, ccrs-api, or cctbm-api → ADMIN respectively. Keep existing app role-to-permission settings.

Do not map realm-management administrator roles. Do not use a Hardcoded Role mapper or a default group granting all broker users ADMIN.

FORCE refreshes mapped roles at the next broker login. Revocation is not retroactive to existing app sessions/tokens. For immediate offboarding, disable/delete the linked account and terminate sessions in each app realm.

## 5. Securely link existing accounts once

For a new email, the first broker login creates a linked user in the app realm, and an authorized app login provisions its local profile. No separate app password is needed.

For an existing email, the built-in broker flow may require a one-time confirmation/authentication to link the existing realm account. Keep that verification. A Keycloak administrator can alternatively establish the verified federated identity link through the Admin API. Never automatically link accounts solely because emails match.

The app stores the **target realm's user ID**, not the dashboard user ID. If an existing local profile points to another identity, use that app's guarded identity-link migration with the verified old/new IDs and issuer. Preserve audit and business records. Do not delete existing accounts as a shortcut.

## 6. Roll out

1. Commit/push and deploy the local routing changes in all eight app frontends FIRST. Deploy the dashboard LAST. If staging the dashboard earlier, explicitly set DASHBOARD_BROKER_ENABLED=false until all apps are ready.
2. Complete the Keycloak settings above. Keep a native app recovery administrator.
3. Routing is enabled by default in the dashboard code and Compose file. If the VPS already has the rollback flag set to false, change it to true in the dashboard root `.env`:

```dotenv
DASHBOARD_BROKER_ENABLED=true
```

4. Commit/push and deploy the dashboard code; recreate its container with the updated environment. For local development, set this variable in the terminal running `npm run dev`.
5. Cards now point to e.g. `https://hrms.chirocity.gov.et/login?chiro_idp=dashboard-sso`. The adapter sends the actual Keycloak parameter `kc_idp_hint=dashboard-sso`. The URL selects a fixed provider; it never grants roles or carries passwords/tokens.

## 7. Acceptance checks

- Sign into the dashboard, launch HRMS then CHRMS. After initial secure linking, both should open as the central administrator with brief redirects and no extra password prompt.
- Start with a different native HRMS account signed in. Launch from the dashboard and confirm the account changes to the central administrator. Confirm target prompt=login and upstream prompt=none.
- Inspect only decoded metadata: app issuer is its dedicated realm, azp is app-web, audience includes app-api, and app-api has ADMIN. Never share encoded tokens.
- A dashboard user without ALL_APPS_ADMIN must not acquire app administrator access.
- Direct app entry without the query parameter still offers native login. CAS/CLMS registration stays app-specific.
- Sign out of HRMS: CHRMS and the dashboard remain signed in. Launching HRMS from the dashboard intentionally signs it in again.
- Sign out of the dashboard: existing app sessions remain independent with the logout callback settings above. A full security logout requires terminating app-realm sessions too.
- Remove ALL_APPS_ADMIN and launch again: the mapped role must be removed. Revoke existing app sessions separately for immediate effect.
- Repeat for all eight realms before general rollout.

Disabling/deleting a dashboard user alone does not disable its existing app-realm mirrors. Independent sessions require explicit app-realm lifecycle actions for immediate offboarding; brokering is not a real-time cross-realm deletion synchronizer.

## Rollback

Set DASHBOARD_BROKER_ENABLED=false and recreate the dashboard container. Cards return to native app links. Turning off routing does not revoke roles already granted; review/remove broker grants and links separately if needed.

## Official references

- [Keycloak server administration and identity brokering](https://www.keycloak.org/docs/latest/server_admin/)
- [JavaScript adapter idpHint](https://www.keycloak.org/securing-apps/javascript-adapter)
- [Claim to Role array matching](https://github.com/keycloak/keycloak/blob/main/services/src/main/java/org/keycloak/broker/oidc/mappers/ClaimToRoleMapper.java)
- [Upstream prompt override](https://github.com/keycloak/keycloak/blob/main/services/src/main/java/org/keycloak/broker/oidc/AbstractOAuth2IdentityProvider.java)
- [Empty provider Logout URL behavior](https://github.com/keycloak/keycloak/blob/main/services/src/main/java/org/keycloak/broker/oidc/OIDCIdentityProvider.java)

UI labels vary by Keycloak version. Verify this configuration and the acceptance checks on the installed version before enabling production routing. Local tests cannot establish that live realms are correctly configured.
