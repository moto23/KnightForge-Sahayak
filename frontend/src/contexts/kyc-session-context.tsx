"use client";

/**
 * KYC session context (Phase 9B) — the shared state backbone of the app.
 *
 * Responsibilities:
 *  - create the interview session lazily (`ensureSession`) and PERSIST its id
 *    in localStorage so reloading the page RESUMES the same session
 *  - load the form schema once (field labels/sections for every page)
 *  - expose live session + progress state and a `refresh()` all pages share
 *  - track which fields were AI-prefilled AND from which document (client-side
 *    provenance — the backend stores answers uniformly), so deleting a source
 *    document can roll back exactly the answers it contributed
 *    (`rollbackPrefill`) and manual answers drop their prefill mark
 *    (`markUserAnswered`)
 *
 * Single source of truth: session answers live on the backend; progress and
 * the next question are always server-computed from them. This context only
 * caches the latest server snapshot — it never derives its own progress.
 *
 * Concurrency note: sessionId and the provenance map are mirrored into refs.
 * Handlers like `markPrefilled` run inside async flows that may have CREATED
 * the session moments earlier (ensureSession) — a state-closure would still
 * see the pre-creation `null` and silently drop provenance, which would make
 * document deletion unable to roll its prefills back. Refs always see the
 * current value, so these callbacks are also stable across renders.
 *
 * Future modules (auth, RAG, agents) can mount sibling providers here without
 * touching pages.
 */

import * as React from "react";

import { ApiError, toApiError } from "@/services/api-client";
import { formsService, sessionService } from "@/services";
import type {
  KYCField,
  KYCForm,
  ProgressResponse,
  SessionResponse,
} from "@/types/api";

const SESSION_KEY = "kf.session_id";
const PREFILL_KEY = "kf.prefilled_fields";

/** field_id -> document_id it was prefilled from (null = unknown source). */
type PrefillProvenance = Record<string, string | null>;

/* --- localStorage helpers (SSR-safe) --------------------------------- */

function readStoredSessionId(): string | null {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem(SESSION_KEY);
}

function readPrefillMap(sessionId: string | null): PrefillProvenance {
  if (typeof window === "undefined" || !sessionId) return {};
  try {
    const raw = window.localStorage.getItem(`${PREFILL_KEY}.${sessionId}`);
    if (!raw) return {};
    const parsed = JSON.parse(raw) as unknown;
    // Legacy 9B.1 format: a plain array of field ids without provenance.
    if (Array.isArray(parsed)) {
      return Object.fromEntries(parsed.map((id) => [String(id), null]));
    }
    if (parsed && typeof parsed === "object") {
      return parsed as PrefillProvenance;
    }
    return {};
  } catch {
    return {};
  }
}

function writePrefillMap(sessionId: string, map: PrefillProvenance): void {
  window.localStorage.setItem(
    `${PREFILL_KEY}.${sessionId}`,
    JSON.stringify(map),
  );
}

/* --- Context shape ---------------------------------------------------- */

export type KycSessionContextValue = {
  /** null until a session exists (user hasn't started yet). */
  sessionId: string | null;
  session: SessionResponse | null;
  progress: ProgressResponse | null;
  /** Form schema — loaded once, null while loading. */
  schema: KYCForm | null;
  /** Flat map field_id -> KYCField for labels/sections everywhere. */
  fieldMap: Map<string, KYCField>;
  /** Field ids written by OCR prefill (client-side provenance). */
  prefilledIds: ReadonlySet<string>;
  /** True while restoring a persisted session on first load. */
  restoring: boolean;
  /** Set when the backend is unreachable or the restore failed hard. */
  error: ApiError | null;

  /** Return the existing session id or create+persist a new session. */
  ensureSession: () => Promise<string>;
  /** Adopt a session created elsewhere (e.g. POST /conversation/start). */
  adoptSession: (sessionId: string) => Promise<void>;
  /** Re-fetch session + progress from the backend. */
  refresh: () => Promise<void>;
  /** Record fields written by prefill, with the source document. */
  markPrefilled: (fieldIds: string[], documentId?: string | null) => void;
  /** A user answered these fields herself — drop their prefill mark. */
  markUserAnswered: (fieldIds: string[]) => void;
  /**
   * A source document was deleted: clear session answers that were prefilled
   * ONLY from it, then refresh session + progress everywhere.
   *
   * `keepFieldIds` protects fields the intelligence pipeline still owns after
   * its own recompute (another document supports them, or the user answered
   * them). Returns how many answers were cleared.
   */
  rollbackPrefill: (
    documentId: string,
    keepFieldIds?: string[],
  ) => Promise<number>;
  /** Delete the backend session and clear local persistence. */
  resetSession: () => Promise<void>;
};

const KycSessionContext = React.createContext<KycSessionContextValue | null>(
  null,
);

export function KycSessionProvider({
  children,
}: {
  children: React.ReactNode;
}) {
  const [sessionId, setSessionIdState] = React.useState<string | null>(null);
  const [session, setSession] = React.useState<SessionResponse | null>(null);
  const [progress, setProgress] = React.useState<ProgressResponse | null>(null);
  const [schema, setSchema] = React.useState<KYCForm | null>(null);
  const [prefillMap, setPrefillMapState] = React.useState<PrefillProvenance>(
    {},
  );
  const [restoring, setRestoring] = React.useState(true);
  const [error, setError] = React.useState<ApiError | null>(null);

  // Refs mirror the two values async handlers must never read stale
  // (see the concurrency note in the file header).
  const sessionIdRef = React.useRef<string | null>(null);
  const prefillMapRef = React.useRef<PrefillProvenance>({});
  /** In-flight session creation, shared by concurrent ensureSession callers. */
  const creatingSessionRef = React.useRef<Promise<string> | null>(null);

  const storeSessionId = React.useCallback((id: string | null) => {
    sessionIdRef.current = id;
    setSessionIdState(id);
  }, []);

  const storePrefillMap = React.useCallback(
    (map: PrefillProvenance, persistFor?: string | null) => {
      prefillMapRef.current = map;
      setPrefillMapState(map);
      if (persistFor) writePrefillMap(persistFor, map);
    },
    [],
  );

  /** Load session + progress for a known id; clears storage on 404. */
  const loadSession = React.useCallback(async (id: string) => {
    const [sessionData, progressData] = await Promise.all([
      sessionService.get(id),
      sessionService.progress(id),
    ]);
    setSession(sessionData);
    setProgress(progressData);
  }, []);

  /* Restore persisted session + fetch schema on first mount. */
  React.useEffect(() => {
    let cancelled = false;

    (async () => {
      const storedId = readStoredSessionId();

      /*
       * The form schema and the stored session are INDEPENDENT reads, and
       * awaiting the schema first made every consumer of this context pay
       * both round trips end to end before anything rendered. Overlapping
       * them makes the restore cost max(schema, session) instead of the sum.
       *
       * allSettled rather than two bare promises: it attaches handlers to
       * both immediately, so a session that fails fast while the schema is
       * still in flight cannot surface as an unhandled rejection. Each
       * outcome is still handled exactly as it was before.
       */
      const [schemaResult, sessionResult] = await Promise.allSettled([
        formsService.getSchema(),
        storedId ? loadSession(storedId) : Promise.resolve(null),
      ]);

      if (schemaResult.status === "fulfilled") {
        if (!cancelled) setSchema(schemaResult.value.form);
      } else if (!cancelled) {
        setError(toApiError(schemaResult.reason));
      }

      if (storedId) {
        if (sessionResult.status === "fulfilled") {
          if (!cancelled) {
            storeSessionId(storedId);
            storePrefillMap(readPrefillMap(storedId));
          }
        } else {
          const apiError = toApiError(sessionResult.reason);
          if (apiError.status === 404) {
            // Backend restarted (in-memory store) — stale id, start fresh.
            window.localStorage.removeItem(SESSION_KEY);
          } else if (!cancelled) {
            setError(apiError);
          }
        }
      }
      if (!cancelled) setRestoring(false);
    })();

    return () => {
      cancelled = true;
    };
  }, [loadSession, storeSessionId, storePrefillMap]);

  const ensureSession = React.useCallback(async (): Promise<string> => {
    if (sessionIdRef.current) return sessionIdRef.current;
    // Uploading several documents at once fires ensureSession concurrently.
    // Without this in-flight guard every caller sees a null ref and creates
    // its OWN session, scattering the documents across sessions so the merged
    // profile only ever sees one of them. All callers share one creation.
    if (creatingSessionRef.current) return creatingSessionRef.current;
    creatingSessionRef.current = (async () => {
      const created = await sessionService.create();
      const id = created.session.session_id;
      window.localStorage.setItem(SESSION_KEY, id);
      storeSessionId(id);
      setSession(created.session);
      storePrefillMap({}); // brand-new session — no provenance carries over
      setError(null);
      // Fresh progress snapshot (create() doesn't include one).
      try {
        setProgress(await sessionService.progress(id));
      } catch {
        /* non-fatal — refresh() will retry */
      }
      return id;
    })();
    try {
      return await creatingSessionRef.current;
    } finally {
      creatingSessionRef.current = null;
    }
  }, [storeSessionId, storePrefillMap]);

  const adoptSession = React.useCallback(
    async (id: string) => {
      window.localStorage.setItem(SESSION_KEY, id);
      storeSessionId(id);
      storePrefillMap(readPrefillMap(id));
      try {
        await loadSession(id);
        setError(null);
      } catch (err) {
        setError(toApiError(err));
      }
    },
    [loadSession, storeSessionId, storePrefillMap],
  );

  const refresh = React.useCallback(async () => {
    const id = sessionIdRef.current;
    if (!id) return;
    try {
      await loadSession(id);
      setError(null);
    } catch (err) {
      const apiError = toApiError(err);
      if (apiError.status === 404) {
        window.localStorage.removeItem(SESSION_KEY);
        storeSessionId(null);
        setSession(null);
        setProgress(null);
        storePrefillMap({});
      } else {
        setError(apiError);
      }
    }
  }, [loadSession, storeSessionId, storePrefillMap]);

  const markPrefilled = React.useCallback(
    (fieldIds: string[], documentId: string | null = null) => {
      const id = sessionIdRef.current;
      if (!id || fieldIds.length === 0) return;
      const next = { ...prefillMapRef.current };
      for (const fieldId of fieldIds) next[fieldId] = documentId;
      storePrefillMap(next, id);
    },
    [storePrefillMap],
  );

  const markUserAnswered = React.useCallback(
    (fieldIds: string[]) => {
      const id = sessionIdRef.current;
      if (!id || fieldIds.length === 0) return;
      if (!fieldIds.some((fieldId) => fieldId in prefillMapRef.current)) return;
      const next = { ...prefillMapRef.current };
      for (const fieldId of fieldIds) delete next[fieldId];
      storePrefillMap(next, id);
    },
    [storePrefillMap],
  );

  const rollbackPrefill = React.useCallback(
    async (documentId: string, keepFieldIds: string[] = []): Promise<number> => {
      const id = sessionIdRef.current;
      if (!id) return 0;
      // `keepFieldIds` are the fields the intelligence pipeline still owns
      // AFTER its own authoritative recompute — either another document also
      // supports them, or the user has since answered them. Clearing those
      // here would be deleting by field name and losing good data, so this
      // legacy rollback only sweeps up values the pipeline does NOT own
      // (e.g. the manual "Prefill my form" path).
      const keep = new Set(keepFieldIds);
      const fieldIds = Object.entries(prefillMapRef.current)
        .filter(([fieldId, docId]) => docId === documentId && !keep.has(fieldId))
        .map(([fieldId]) => fieldId);
      if (fieldIds.length === 0) return 0;

      // Clear each answer on the backend; a partial failure only unmarks
      // the fields that were actually cleared.
      const results = await Promise.allSettled(
        fieldIds.map((fieldId) => sessionService.clearAnswer(id, fieldId)),
      );
      const cleared = fieldIds.filter(
        (_, i) => results[i].status === "fulfilled",
      );
      const failed = results.filter((r) => r.status === "rejected");
      if (failed.length > 0) {
        // Most likely an outdated backend missing DELETE /session/.../answer.
        console.warn(
          `rollbackPrefill: ${failed.length}/${fieldIds.length} clear calls failed`,
          (failed[0] as PromiseRejectedResult).reason,
        );
      }

      if (cleared.length > 0) {
        const next = { ...prefillMapRef.current };
        for (const fieldId of cleared) delete next[fieldId];
        storePrefillMap(next, id);
      }
      // Recompute progress / next question / status for every page.
      await refresh();
      return cleared.length;
    },
    [refresh, storePrefillMap],
  );

  const resetSession = React.useCallback(async () => {
    const id = sessionIdRef.current;
    if (id) {
      try {
        await sessionService.remove(id);
      } catch {
        /* already gone is fine */
      }
      window.localStorage.removeItem(SESSION_KEY);
      window.localStorage.removeItem(`${PREFILL_KEY}.${id}`);
    }
    storeSessionId(null);
    setSession(null);
    setProgress(null);
    storePrefillMap({});
  }, [storeSessionId, storePrefillMap]);

  const fieldMap = React.useMemo(() => {
    const map = new Map<string, KYCField>();
    for (const section of schema?.sections ?? []) {
      for (const field of section.fields) map.set(field.id, field);
    }
    return map;
  }, [schema]);

  const prefilledIds = React.useMemo(
    () => new Set(Object.keys(prefillMap)),
    [prefillMap],
  );

  const value = React.useMemo<KycSessionContextValue>(
    () => ({
      sessionId,
      session,
      progress,
      schema,
      fieldMap,
      prefilledIds,
      restoring,
      error,
      ensureSession,
      adoptSession,
      refresh,
      markPrefilled,
      markUserAnswered,
      rollbackPrefill,
      resetSession,
    }),
    [
      sessionId,
      session,
      progress,
      schema,
      fieldMap,
      prefilledIds,
      restoring,
      error,
      ensureSession,
      adoptSession,
      refresh,
      markPrefilled,
      markUserAnswered,
      rollbackPrefill,
      resetSession,
    ],
  );

  return (
    <KycSessionContext.Provider value={value}>
      {children}
    </KycSessionContext.Provider>
  );
}

export function useKycSession(): KycSessionContextValue {
  const context = React.useContext(KycSessionContext);
  if (!context) {
    throw new Error("useKycSession must be used inside <KycSessionProvider>");
  }
  return context;
}
