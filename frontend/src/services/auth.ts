/**
 * Authentication service — 1:1 with the backend /auth routes (Phase 12).
 *
 * The refresh token is an HttpOnly cookie the browser manages by itself —
 * this module never sees it; it only asks the endpoints that use it to run
 * with `credentials: "include"`. The access token comes back in the body
 * and is handed to the auth context (memory only).
 */

import { api } from "@/services/api-client";
import type {
  AuthResponse,
  GoogleLoginResponse,
  LogoutResponse,
  ProvidersResponse,
  UserProfile,
} from "@/types/api";

const withCookies = { credentials: "include" as RequestCredentials };

export const authService = {
  register: (email: string, password: string, fullName: string) =>
    api.post<AuthResponse>(
      "/auth/register",
      { email, password, full_name: fullName },
      withCookies,
    ),
  login: (email: string, password: string) =>
    api.post<AuthResponse>("/auth/login", { email, password }, withCookies),
  /** Silent persistent login — succeeds only if the refresh cookie is valid. */
  refresh: () => api.post<AuthResponse>("/auth/refresh", undefined, withCookies),
  logout: () => api.post<LogoutResponse>("/auth/logout", undefined, withCookies),
  logoutAll: () =>
    api.post<LogoutResponse>("/auth/logout-all", undefined, withCookies),
  me: (signal?: AbortSignal) => api.get<UserProfile>("/auth/me", { signal }),
  updateProfile: (fullName: string) =>
    api.patch<UserProfile>("/auth/me", { full_name: fullName }),
  providers: (signal?: AbortSignal) =>
    api.get<ProvidersResponse>("/auth/providers", { signal }),
  /** Returns the Google consent URL; the caller navigates the browser to it. */
  googleLogin: () =>
    api.get<GoogleLoginResponse>("/auth/google/login", withCookies),
};
