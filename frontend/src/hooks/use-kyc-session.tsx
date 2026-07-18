/**
 * Back-compat hook entry point — the provider + context live in
 * src/contexts/kyc-session-context.tsx (Phase 9B architecture: contexts/
 * hold providers, hooks/ hold consumption entry points).
 */

export {
  useKycSession,
  KycSessionProvider,
  type KycSessionContextValue,
} from "@/contexts/kyc-session-context";
