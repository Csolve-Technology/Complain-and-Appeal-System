# CAS users, roles and permissions

## Identity and applicant registration

CAS uses the `chirocity` realm, public client `cas-web`, and audience `cas-api`.
CAS opens Keycloak login automatically. Applicants can use its Register link or open `/auth/sign-up`, whose button starts Keycloak registration; CAS does not collect a second password.
Enable realm registration and make `CAS Applicants` a default group with the `cas-api` client role `CITIZEN`. Set an explicit `cas-api` access-token audience mapper on `cas-web`. Existing realm users need membership assigned explicitly. Keep the built-in `roles`, `profile` and `email` scopes configured so client roles and email are present in the access token.

Production redirect/logout URI: `https://cas.chirocity.gov.et/login`; web origin: `https://cas.chirocity.gov.et`.
Local redirect/logout URI: `http://localhost:3000/login`; web origin: `http://localhost:3000`.
These must be separate saved entries on **cas-web**, preserving production entries.
`CAS_REQUIRE_VERIFIED_EMAIL=false` allows sign-in without email confirmation under the existing CAS policy. It does not mark self-registered emails as verified.

## Backend management credentials

Create the confidential `cas-provisioner` client, enable service accounts and configure its realm-management permissions for user management and CAS client-role management. Standard `manage-users`, `view-clients`, and `manage-clients` roles are broad; use Keycloak fine-grained administration to restrict the account to CAS where available. The code only writes `cas-api` role mappings; never expose this secret to the frontend.

Set backend environment variables (Compose loads the VPS root `.env`):

```env
AUTH_MODE=keycloak
KEYCLOAK_URL=https://auth.chirocity.gov.et
KEYCLOAK_REALM=cas
KEYCLOAK_CLIENT_ID=cas-web
KEYCLOAK_AUDIENCE=cas-api
KEYCLOAK_ADMIN_CLIENT_ID=cas-provisioner
KEYCLOAK_ADMIN_CLIENT_SECRET=<server-only secret>
```

For local PowerShell, set these as `$env:NAME="value"` in the same terminal that starts Django. Django does not automatically load an `api/.env` file. Stop and restart Django after setting credentials. Never commit the secret. Run `./start-dev.ps1` from `api` to apply migrations, create missing roles and start Django with local Chiro Auth defaults while preserving credentials already set in that terminal.

```powershell
python manage.py migrate
python manage.py bootstrap_admin
python manage.py runserver 8000
```

`bootstrap_admin` creates missing standard roles without demo data and preserves existing role permissions in centralized mode. Do not run the demo seed on production.

## Creating and managing users

Users with `cas_app.add_user` can create an identity through Users or the case form. Enter a unique email/username, an initial temporary password and a permitted role. The backend creates the identity disabled, assigns only CAS roles, saves the local profile with an unusable local password, then enables the identity. The administrator-created email is marked verified, and Keycloak requires a password change at first sign-in. No SMTP setup is needed for this temporary-password flow.

Duplicate identities are not automatically linked by email. For an existing Keycloak user, grant CAS roles in Keycloak, then sign in to provision a local profile. If a local CAS profile already exists, use the explicit `link_chiro_user` management command after verifying the subject and email. Credentials and email changes for linked accounts remain in Keycloak.

Users with `cas_app.change_user` can change a linked user's CAS role in the Users form. Choices contain only roles whose local permissions the acting user holds. Changes update Keycloak and local groups; old tokens are rejected so a removed role cannot reappear. The affected user must sign out and sign in again. On creation, default inherited `CITIZEN` membership is retained. On explicit role updates, clearing Citizen removes membership in the dedicated root `CAS Applicants` group after verifying it grants only non-composite CAS Citizen roles and no realm or other-client roles. Other inherited role removal must be done in Keycloak's groups. Local inactive/deleted status continues to block CAS, without disabling the shared identity in other apps.

## Dynamic authorization

Keycloak assigns client-role membership; CAS groups define the permissions of those roles. Built-in aliases map ADMIN?Admin, MAYOR_OFFICE?Mayor Office, DIRECTOR?Director, FOCAL_PERSON?Focal Person, CITIZEN?Citizen. Custom role names match exactly, including case. All assigned configured roles contribute permissions.

On Roles, **Load Chiro Auth roles** imports missing client roles with no permissions and preserves existing grants. Creating a role in CAS also creates its client role in Keycloak. Grant local permissions in Roles before assigning it to users. If `cas-web` has restricted role scopes, include the custom `cas-api` roles in the access-token scope mappings.

The API checks model permissions on every list/read/create/change/delete request, including case status, activity, role administration and reports. The UI consumes effective permissions from `/api/auth/me/`. Hiding a button is not the security boundary.

- `view_case` permits reading cases. Without `view_all_cases`, results are limited to the applicant's own cases, and applicant field/action restrictions apply.
- `view_all_cases` additionally permits access across applicants. Existing standard staff groups receive this explicit scope in the migration. Grant it deliberately to custom staff roles.
- `add_case`, `change_case`, `delete_case` control case actions. Applicants cannot change case ownership or resolve their own cases.
- `add_assignment` and `add_transfer` control activity creation. Existing office and transfer hierarchy constraints still apply. A custom role needing transfers must also have its workflow hierarchy configured.
- `view_user`, `add_user`, `change_user`, `delete_user` control the directory and user administration independently.
- `auth.view_group`, `auth.add_group`, `auth.change_group`, `auth.delete_group` control role management. Delegation cannot grant permissions beyond the acting user's own access. Centralized role deletion/renaming and bulk group membership changes are blocked to avoid divergent Keycloak assignments.
- Offices, announcements, feedback and role hierarchy use their corresponding model permissions. Notifications are restricted to the current user's inbox.

CAS role permissions apply only inside CAS. Granting a CAS role does not grant access to HRMS, LMS or other city applications.

## Verification

```powershell
# api
python manage.py test cas_app --noinput
# frontend
npm run test:auth
npx tsc --noEmit
$env:NODE_ENV="production"
npm run build
```

No provisioner secret is needed for the isolated automated tests; management calls are mocked. A live user-creation check still requires the configured backend credentials and service-account grants.
