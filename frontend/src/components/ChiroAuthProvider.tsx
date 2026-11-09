"use client";
import { createContext, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import { usePathname, useRouter } from "next/navigation";
import { configureAuth, initializeSso, getCachedAccessToken, signIn, signUp, signOut, type AuthSettings } from "@/services/auth-session";
import { authFetch, installAxiosAuth } from "@/services/auth-http";
import { defaultRouteForRole } from "@/lib/role";

type Session = { permissions: string[]; can: (permission: string) => boolean; requireVerifiedEmail: boolean; mode: "local" | "keycloak"; error: string | null; signIn: () => Promise<void>; signUp: () => Promise<void>; signOut: () => Promise<void> };
const Context = createContext<Session>({ permissions: [], can: () => false, requireVerifiedEmail: true, mode: "keycloak", error: null, signIn, signUp, signOut });
export const useChiroAuth = () => useContext(Context);
let startup: Promise<AuthSettings> | undefined;
function start() {
  startup ??= (async () => {
    const response = await fetch(`${process.env.NEXT_PUBLIC_API_URL}/auth/config/`, { cache: "no-store" });
    if (!response.ok) throw new Error("Unable to load sign-in settings. Please reload the page.");
    const config: AuthSettings = await response.json();
    configureAuth(config); installAxiosAuth();
    if (config.mode === "keycloak") {
      // Registration remains public; every normal entry opens Chiro Auth directly.
      const registration = window.location.pathname === "/auth/sign-up";
      await initializeSso({ requireLogin: !registration, skipSessionCheck: registration });
    }
    return config;
  })();
  return startup;
}
export function ChiroAuthProvider({ children }: { children: ReactNode }) {
  const [permissions, setPermissions] = useState<string[]>([]);
  const [ready, setReady] = useState(false);
  const [mode, setMode] = useState<"local" | "keycloak">("keycloak");
  const [requireVerifiedEmail, setRequireVerifiedEmail] = useState(true);
  const [authorized, setAuthorized] = useState(false);
  const [role, setRole] = useState("");
  const [error, setError] = useState<string | null>(null);
  const loginRequested = useRef(false);
  const router = useRouter();
  const pathname = usePathname();
  const isPublicAuthRoute = pathname === "/login" || pathname === "/auth/sign-in" || pathname === "/auth/sign-up";
  const redirectingAuthenticatedUser = authorized && (pathname === "/" || pathname === "/login" || pathname?.startsWith("/auth"));
  const openingSso = ready && mode === "keycloak" && !authorized && !error && pathname !== "/auth/sign-up";
  useEffect(() => {
    let active = true;
    const hydrate = async () => {
      if (!getCachedAccessToken()) { if (active) setAuthorized(false); return; }
      const response = await authFetch(`${process.env.NEXT_PUBLIC_API_URL}/auth/me/`, { cache: "no-store" });
      const me = await response.json();
      if (!response.ok) throw new Error(me.detail || me.message || "Unable to sign in to CAS.");
      if (!active) return;
      setPermissions(Array.isArray(me.permissions) ? me.permissions : []);
      localStorage.setItem("user_permissions", JSON.stringify(me.permissions || []));
      localStorage.setItem("user_groups", JSON.stringify(me.user_groups || []));
      localStorage.setItem("user_id", String(me.id));
      localStorage.setItem("role", me.user_groups?.[0] || "");
      setRole(me.user_groups?.[0] || ""); setAuthorized(true); setError(null);
    };
    start().then(async config => { if (active) { setMode(config.mode); setRequireVerifiedEmail(config.requireVerifiedEmail !== false); } await hydrate(); })
      .catch(e => { if (active) { setError(e.message); setAuthorized(false); } })
      .finally(() => { if (active) setReady(true); });
    const ended = () => { if (active) { setAuthorized(false); setPermissions([]); setError("Your session ended. Please sign in again."); } };
    const refreshed = () => { void hydrate().catch(e => { if (active) { setAuthorized(false); setError(e.message); } }); };
    window.addEventListener("cas:session-ended", ended);
    window.addEventListener("cas:token-refreshed", refreshed);
    return () => { active = false; window.removeEventListener("cas:session-ended", ended); window.removeEventListener("cas:token-refreshed", refreshed); };
  }, []);
  useEffect(() => {
    if (!ready) return;
    if (openingSso) {
      if (!loginRequested.current) {
        loginRequested.current = true;
        void signIn().catch(e => { setError(e.message || "Unable to open Chiro Auth."); });
      }
      return;
    }
    if (mode === "keycloak" && !authorized && !isPublicAuthRoute) router.replace("/auth/sign-in");
    if (redirectingAuthenticatedUser) router.replace(defaultRouteForRole(role));
  }, [ready, mode, authorized, isPublicAuthRoute, redirectingAuthenticatedUser, role, router, openingSso]);
  // Keep children unmounted until navigation completes; an effect alone allows
  // the sign-in form to paint for one frame after a successful session check.
  if (!ready || openingSso || redirectingAuthenticatedUser || (mode === "keycloak" && !authorized && !isPublicAuthRoute)) {
    return <div role="status" aria-live="polite" className="flex min-h-screen items-center justify-center">{openingSso ? "Opening Chiro Auth..." : ready && redirectingAuthenticatedUser ? "Opening CAS..." : "Checking your session..."}</div>;
  }
  return <Context.Provider value={{ mode, requireVerifiedEmail, error, signIn, signUp, signOut, permissions, can: permission => permissions.includes(permission) }}>{children}</Context.Provider>;
}
