/**
 * Health + form schema services.
 * Routes: GET /health · GET /schema
 */

import { api } from "@/services/api-client";
import type { FormSchemaResponse, HealthResponse } from "@/types/api";

export const healthService = {
  /** GET /health — liveness probe (dashboard "Backend online" pill). */
  check: (signal?: AbortSignal) =>
    api.get<HealthResponse>("/health", { signal }),
};

export const formsService = {
  /** GET /schema — the interview form definition (cached in context). */
  getSchema: () => api.get<FormSchemaResponse>("/schema"),
};
