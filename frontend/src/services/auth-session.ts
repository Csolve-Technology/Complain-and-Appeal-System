import Keycloak from "keycloak-js";

export type AuthSettings = {
  mode: "local" | "keycloak";
  requireVerifiedEmail?: boolean;
  url: string;
  realm: string;
  clientId: string;
};
let settings: AuthSettings | undefined;
let keycloak: Keycloak | undefined;
let initialization: Promise<boolean> | undefined;

export function configureAuth(value: AuthSettings) {
  settings = value;
  if (value.mode === "keycloak") {
    localStorage.removeItem("token");
    localStorage.removeItem("user_groups");
    localStorage.removeItem("role");
    localStorage.removeItem("user_id");
    document.cookie = "token=; Max-Age=0; path=/; SameSite=Lax";
    keycloak ??= new Keycloak({
      url: value.url,
      realm: value.realm,
      clientId: value.clientId,
    });
    configureDashboardBroker(keycloak);
  }
}

export function endSession() {
  localStorage.removeItem("token");
  localStorage.removeItem("user_groups");
  keycloak?.clearToken();
  window.dispatchEvent(new Event("cas:session-ended"));
  window.dispatchEvent(new Event("localStorageChange"));
}

export async function accessToken() {
  if (settings?.mode !== "keycloak")
    return localStorage.getItem("token");
  if (!keycloak?.authenticated) return undefined;
  try {
    await keycloak.updateToken(30);
    return keycloak.token;
  } catch (error) {
    endSession();
    throw error;
  }
}

export function initializeSso(options: { requireLogin?: boolean; skipSessionCheck?: boolean } = {}) {
  if (!keycloak) throw new Error("Chiro Auth is not configured.");
  keycloak.onAuthLogout = () =>
    window.dispatchEvent(new Event("cas:session-ended"));
  window.dispatchEvent(new Event("localStorageChange"));
  keycloak.onAuthRefreshSuccess = () =>
    window.dispatchEvent(new Event("cas:token-refreshed"));
  keycloak.onTokenExpired = () => {
    void accessToken().catch(() => undefined);
  };
  initialization ??= keycloak.init({
    onLoad: options.skipSessionCheck ? undefined : options.requireLogin ? "login-required" : "check-sso",
    pkceMethod: "S256",
    flow: "standard",
    checkLoginIframe: false,
    scope: "openid profile email",
    redirectUri: `${window.location.origin}/login`,
  });
  return initialization;
}

export async function signIn(options: { loginHint?: string; prompt?: 'login' } = {}) {
  if (!keycloak) throw new Error("Chiro Auth is not configured.");
  await keycloak.login({ redirectUri: `${window.location.origin}/login`, ...options });
}

export async function signUp() {
  if (!keycloak) throw new Error("Chiro Auth is not configured.");
  await keycloak.register({ redirectUri: `${window.location.origin}/login` });
}

export async function signOut() {
  localStorage.removeItem("token");
  localStorage.removeItem("user_groups");
  if (keycloak?.authenticated) {
    await keycloak.logout({ redirectUri: `${window.location.origin}/login` });
  } else {
    endSession();
  }
}

// Synchronous reads support existing client components; actual requests always refresh below.
export function getCachedAccessToken(): string | null {
  if (typeof window === "undefined") return null;
  return settings?.mode === "keycloak" ? keycloak?.token || null : localStorage.getItem("token");
}
export function isCentralAuth() { return settings?.mode === "keycloak"; }


// The dashboard may select this fixed provider. This is routing only: the
// target realm still verifies the identity and grants its own client roles.
function configureDashboardBroker(client: Keycloak) {
  const search = typeof window === 'undefined' ? '' : window.location.search;
  if (!search || new URLSearchParams(search).get('chiro_idp') !== 'dashboard-sso') return;
  const login = client.login.bind(client);
  client.login = (options = {}) => login({ ...options, idpHint: 'dashboard-sso', prompt: 'login' });
}
