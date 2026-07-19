"use client";

/**
 * Auth context (Phase 12) — the frontend's session backbone.
 *
 * Token model:
 *  - The ACCESS token lives in JS memory only (module-level holder inside
 *    api-client). It is never written to localStorage or a cookie.
 *  - The REFRESH token is an HttpOnly cookie the browser manages — this code
 *    never reads it; it just calls /auth/refresh with credentials included.
 *
 * Persistent login: on mount we attempt ONE silent refresh. If the cookie is
 * valid the user is signed in with zero interaction; if not, they're a
 * guest — and everything except saved history keeps working (guest mode).
 *
 * The access token expires in ~30 minutes, so a timer proactively refreshes
 * a few minutes early; every refresh also ROTATES the cookie server-side.
 *
 * Structure notes:
 *  - adoptSession schedules a future silent refresh, and a silent refresh
 *    adopts the session it receives — a natural cycle. It is broken with a
 *    ref (silentRefreshRef): the timer dereferences the ref only WHEN IT
 *    FIRES, so neither callback needs the other in scope at declaration.
 *  - No state is set synchronously inside any effect: the boot effect only
 *    kicks off an async flow, and every setState happens after an await
 *    (i.e. in a later microtask), which keeps the React Compiler's
 *    set-state-in-effect rule satisfied without suppressions.
 */

import * as React from "react";

import { setAccessToken, toApiError } from "@/services/api-client";
import { authService } from "@/services";
import type { UserProfile } from "@/types/api";

/** Refresh this many minutes before the access token would expire. */
const REFRESH_EARLY_MINUTES = 5;

/**
 * Ceiling for the two SILENT refreshes (boot restore + scheduled renewal).
 *
 * The API client's 20s default is tuned for calls a user is actively waiting
 * on. It is wrong here for one specific reason: a free-tier backend sleeps
 * when idle, and the first request after that wakes the container instead of
 * being refused — it is queued and answered a cold start later, well past 20s.
 *
 * At 20s the client gave up on a request the server still went on to process,
 * and a returning user with a perfectly valid cookie was silently demoted to
 * guest. The obvious repair — retry — is the one thing we must NOT do: the
 * backend rotates refresh tokens single-use and revokes ALL of a user's
 * sessions when it sees one replayed, so a retry after an ambiguous timeout
 * risks signing them out everywhere. Waiting longer on a single attempt is
 * both the safer and the more honest option.
 *
 * This costs nothing on a warm backend (a ceiling is not a delay) and nothing
 * for genuine guests (no cookie answers 401 immediately). Only a signed-in
 * user meeting a cold start waits — and now waits for the right answer.
 */
const BACKGROUND_REFRESH_TIMEOUT_MS = 75_000;

export type AuthContextValue = {
  /** null = guest (or still restoring). */
  user: UserProfile | null;
  /** True while the silent boot refresh is in flight. */
  restoring: boolean;
  /** Convenience flag: user !== null. */
  isAuthenticated: boolean;

  login: (email: string, password: string) => Promise<UserProfile>;
  register: (
    email: string,
    password: string,
    fullName: string,
  ) => Promise<UserProfile>;
  /** Sign out on this device (revokes + clears the refresh cookie). */
  logout: () => Promise<void>;
  /** Sign out on EVERY device (revokes all refresh tokens). */
  logoutAll: () => Promise<number>;
  updateProfile: (fullName: string) => Promise<UserProfile>;
  /** Begin Google sign-in (navigates the browser to Google). */
  loginWithGoogle: () => Promise<void>;
};

const AuthContext = React.createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = React.useState<UserProfile | null>(null);
  const [restoring, setRestoring] = React.useState(true);

  const refreshTimer = React.useRef<ReturnType<typeof setTimeout> | null>(null);
  /** Latest silentRefresh — read by the timer at fire time (breaks the cycle). */
  const silentRefreshRef = React.useRef<() => Promise<boolean>>(() =>
    Promise.resolve(false),
  );
  /** Guards the boot refresh so it runs exactly once (Strict Mode safe). */
  const bootedRef = React.useRef(false);

  const clearRefreshTimer = React.useCallback(() => {
    if (refreshTimer.current) {
      clearTimeout(refreshTimer.current);
      refreshTimer.current = null;
    }
  }, []);

  /** Adopt a successful auth response: token to memory, schedule renewal. */
  const adoptSession = React.useCallback(
    (accessToken: string, profile: UserProfile, expiresInMinutes: number) => {
      setAccessToken(accessToken);
      setUser(profile);
      clearRefreshTimer();
      const delayMinutes = Math.max(
        1,
        expiresInMinutes - REFRESH_EARLY_MINUTES,
      );
      refreshTimer.current = setTimeout(() => {
        void silentRefreshRef.current();
      }, delayMinutes * 60_000);
    },
    [clearRefreshTimer],
  );

  const clearSession = React.useCallback(() => {
    setAccessToken(null);
    setUser(null);
    clearRefreshTimer();
  }, [clearRefreshTimer]);

  const silentRefresh = React.useCallback(async (): Promise<boolean> => {
    try {
      const session = await authService.refresh(BACKGROUND_REFRESH_TIMEOUT_MS);
      adoptSession(
        session.access_token,
        session.user,
        session.expires_in_minutes,
      );
      return true;
    } catch {
      clearSession(); // no valid cookie — a guest, not an error
      return false;
    }
  }, [adoptSession, clearSession]);

  /* Keep the ref pointing at the newest silentRefresh. */
  React.useEffect(() => {
    silentRefreshRef.current = silentRefresh;
  }, [silentRefresh]);

  /*
   * Persistent login: one silent refresh on first mount. The effect body
   * only starts an async flow — every setState inside it happens after an
   * await, never synchronously during the effect.
   */
  React.useEffect(() => {
    if (!bootedRef.current) {
      bootedRef.current = true;
      void (async () => {
        await silentRefreshRef.current();
        setRestoring(false);
      })();
    }
    return () => {
      clearRefreshTimer();
    };
  }, [clearRefreshTimer]);

  const login = React.useCallback(
    async (email: string, password: string) => {
      const session = await authService.login(email, password);
      adoptSession(
        session.access_token,
        session.user,
        session.expires_in_minutes,
      );
      return session.user;
    },
    [adoptSession],
  );

  const register = React.useCallback(
    async (email: string, password: string, fullName: string) => {
      const session = await authService.register(email, password, fullName);
      adoptSession(
        session.access_token,
        session.user,
        session.expires_in_minutes,
      );
      return session.user;
    },
    [adoptSession],
  );

  const logout = React.useCallback(async () => {
    try {
      await authService.logout();
    } catch {
      /* revoking a dead session is fine */
    }
    clearSession();
  }, [clearSession]);

  const logoutAll = React.useCallback(async () => {
    const result = await authService.logoutAll();
    clearSession();
    return result.sessions_revoked;
  }, [clearSession]);

  const updateProfile = React.useCallback(async (fullName: string) => {
    const profile = await authService.updateProfile(fullName);
    setUser(profile);
    return profile;
  }, []);

  const loginWithGoogle = React.useCallback(async () => {
    try {
      const { auth_url } = await authService.googleLogin();
      window.location.assign(auth_url);
    } catch (err) {
      throw toApiError(err);
    }
  }, []);

  const value = React.useMemo<AuthContextValue>(
    () => ({
      user,
      restoring,
      isAuthenticated: user !== null,
      login,
      register,
      logout,
      logoutAll,
      updateProfile,
      loginWithGoogle,
    }),
    [
      user,
      restoring,
      login,
      register,
      logout,
      logoutAll,
      updateProfile,
      loginWithGoogle,
    ],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const context = React.useContext(AuthContext);
  if (!context) {
    throw new Error("useAuth must be used inside <AuthProvider>");
  }
  return context;
}