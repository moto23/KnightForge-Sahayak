/**
 * Health + form schema services.
 * Routes: GET /health · GET /schema
 */

import { api } from "@/services/api-client";
import type { FormSchemaResponse, HealthResponse } from "@/types/api";

export const healthService = {
  /**
   * GET /health — liveness probe (dashboard pill, cold-start detection).
   *
   * `timeoutMs` lets the cold-start probe wait out a container that is still
   * booting; the endpoint is dependency-free and idempotent, so waiting on it
   * (or retrying it) is always safe.
   */
  check: (signal?: AbortSignal, timeoutMs?: number) =>
    api.get<HealthResponse>("/health", {
      signal,
      ...(timeoutMs === undefined ? {} : { timeoutMs }),
    }),
};

export const formsService = {
  /** GET /schema — the interview form definition (cached in context). */
  getSchema: () => api.get<FormSchemaResponse>("/schema"),
};
