$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot

# Preserve terminal settings, including the private provisioner secret.
$casDefaults = @{
    AUTH_MODE = "keycloak"
    KEYCLOAK_URL = "https://auth.chirocity.gov.et"
    KEYCLOAK_REALM = "chirocity"
    KEYCLOAK_CLIENT_ID = "cas-web"
    KEYCLOAK_AUDIENCE = "cas-api"
    KEYCLOAK_ADMIN_CLIENT_ID = "cas-provisioner"
    CAS_REQUIRE_VERIFIED_EMAIL = "false"
    FRONTEND_BASE_URL = "http://localhost:3000"
}
foreach ($casSetting in $casDefaults.GetEnumerator()) {
    if (-not [Environment]::GetEnvironmentVariable($casSetting.Key, "Process")) {
        [Environment]::SetEnvironmentVariable($casSetting.Key, $casSetting.Value, "Process")
    }
}
python manage.py migrate --noinput
if ($LASTEXITCODE -ne 0) { throw "CAS migrations failed." }
if ($env:AUTH_MODE -eq "keycloak") {
    python manage.py bootstrap_admin
    if ($LASTEXITCODE -ne 0) { throw "CAS role setup failed." }
}
python manage.py runserver 8000
