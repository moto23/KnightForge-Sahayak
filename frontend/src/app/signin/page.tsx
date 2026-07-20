"use client";

import * as React from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { zodResolver } from "@hookform/resolvers/zod";
import { motion } from "framer-motion";
import { ArrowLeft, LogIn, UserPlus } from "lucide-react";
import { useForm } from "react-hook-form";
import { toast } from "sonner";
import { z } from "zod";

import { Logo } from "@/components/shared/logo";
import { ThemeToggle } from "@/components/shared/theme-toggle";
import { Button } from "@/components/ui/button";
import { GlassCard } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useAuth } from "@/contexts/auth-context";
import { useBackendStatus } from "@/hooks/use-backend-status";
import { toApiError } from "@/services/api-client";
import { authService } from "@/services";

/**
 * Email shape. Deliberately stricter than "contains an @": a local part, a
 * domain with at least one dot, and a 2+ character TLD. "a@b" and "me@gmail"
 * are the two that slip through a naive check and then fail server-side.
 */
const EMAIL_PATTERN = /^[^\s@]+@[^\s@.]+(\.[^\s@.]+)+$/;

/**
 * Password policy — mirrors backend/app/schemas/auth.py verbatim.
 * If one side changes, change BOTH: a password this form accepts but the API
 * rejects surfaces to the user as an unexplained "could not create account".
 */
const PASSWORD_MIN_LENGTH = 6;

const passwordField = z
  .string()
  .min(PASSWORD_MIN_LENGTH, `At least ${PASSWORD_MIN_LENGTH} characters`)
  .regex(/[a-z]/, "Add a lowercase letter")
  .regex(/[A-Z]/, "Add an uppercase letter")
  .regex(/[0-9]/, "Add a number")
  .regex(/[^A-Za-z0-9]/, "Add a special character (e.g. ! ? @ #)");

/**
 * Sign-in and registration have genuinely different rules, so they are two
 * schemas rather than one with optional fields:
 *  - signing IN must NOT apply the policy (existing accounts predate it, and
 *    enforcing it here would also hint at what a valid password looks like);
 *  - registering requires a real name and a policy-compliant password.
 */
const signInSchema = z.object({
  email: z.string().regex(EMAIL_PATTERN, "Enter a valid email address"),
  password: z.string().min(1, "Enter your password"),
  fullName: z.string().optional(),
});

const registerSchema = z.object({
  email: z.string().regex(EMAIL_PATTERN, "Enter a valid email address"),
  password: passwordField,
  fullName: z
    .string()
    .trim()
    .min(1, "Enter your name"),
});

type SignInValues = z.infer<typeof signInSchema>;

const OAUTH_ERRORS: Record<string, string> = {
  google_cancelled: "Google sign-in was cancelled.",
  oauth_state_mismatch: "Google sign-in expired — please try again.",
  google_failed: "Google sign-in failed — please try again.",
};

/** Google "G" mark (lucide has no brand icons). */
function GoogleIcon(props: React.SVGProps<SVGSVGElement>) {
  return (
    <svg viewBox="0 0 24 24" aria-hidden fill="currentColor" {...props}>
      <path d="M21.35 11.1H12v2.9h5.35c-.5 2.5-2.6 4.3-5.35 4.3a5.8 5.8 0 1 1 0-11.6c1.5 0 2.85.55 3.9 1.45l2.15-2.15A8.86 8.86 0 0 0 12 3.5a8.5 8.5 0 1 0 0 17c4.9 0 8.6-3.45 8.6-8.3 0-.37-.1-.73-.25-1.1Z" />
    </svg>
  );
}

/**
 * Sign In / Create account (Phase 12 — real authentication).
 *
 * One screen, two modes. Email+password (Argon2id server-side) or Google
 * OAuth when the backend has credentials configured. Signing in is OPTIONAL:
 * the whole workspace works as a guest — an account only adds saved
 * conversations, history, and cross-device sync.
 */
function SignInContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { login, register: registerAccount, loginWithGoogle, isAuthenticated } = useAuth();
  const [mode, setMode] = React.useState<"signin" | "register">("signin");
  /*
   * Three states, because two produced a lie. `null` = the server has not
   * answered yet (still checking, or the free-tier backend is waking) and
   * says NOTHING about configuration; only a successful {"google": false}
   * may claim "Not configured". Collapsing the unknown state into `false` —
   * and starting there — meant every visitor saw "NOT CONFIGURED" for at
   * least one round trip, and a cold start pinned it there permanently.
   */
  const [googleAvailable, setGoogleAvailable] = React.useState<boolean | null>(
    null,
  );
  const [googleBusy, setGoogleBusy] = React.useState(false);
  const backend = useBackendStatus();

  const {
    register,
    handleSubmit,
    reset,
    formState: { errors, isSubmitting },
  } = useForm<SignInValues>({
    // Validate from the first keystroke and on every one after, so an error
    // appears as soon as the input is wrong and disappears the instant it is
    // corrected — rather than waiting for a blur or a rejected submit.
    mode: "onChange",
    reValidateMode: "onChange",
    resolver: zodResolver(mode === "register" ? registerSchema : signInSchema),
  });

  /** Switching mode changes the rules, so stale errors must not carry over. */
  const switchMode = (next: "signin" | "register") => {
    setMode(next);
    reset({ email: "", password: "", fullName: "" });
  };

  /* Surface OAuth callback errors (?error=...) once. */
  React.useEffect(() => {
    const error = searchParams.get("error");
    if (error) {
      toast.error(OAUTH_ERRORS[error] ?? "Sign-in failed — please try again.");
    }
  }, [searchParams]);

  /*
   * Ask the backend whether Google OAuth is configured. A transport failure
   * (timeout, network, 502/503 from a waking container) leaves the state at
   * `null` — we could not ask, so we assert nothing. Keyed on the shared
   * probe's status so the question is re-asked when the backend turns warm:
   * a visitor who arrived mid-cold-start gets the real answer seconds later
   * without refreshing.
   */
  React.useEffect(() => {
    if (backend.status !== "warm" && backend.status !== "checking") return;
    const controller = new AbortController();
    authService
      .providers(controller.signal)
      .then((p) => setGoogleAvailable(p.google))
      .catch(() => {
        /* unanswered — stays/returns to null, never a false "not configured" */
        setGoogleAvailable(null);
      });
    return () => controller.abort();
  }, [backend.status]);

  /* Already signed in? Straight to the workspace. */
  React.useEffect(() => {
    if (isAuthenticated) router.replace("/dashboard");
  }, [isAuthenticated, router]);

  const onSubmit = async (values: SignInValues) => {
    try {
      const profile =
        mode === "signin"
          ? await login(values.email, values.password)
          // Name is a validated, required field when registering, so it is
          // sent as typed — no silent fallback to the email's local part.
          : await registerAccount(
              values.email,
              values.password,
              (values.fullName ?? "").trim(),
            );
      toast.success(mode === "signin" ? "Welcome back!" : "Account created", {
        description: `Signed in as ${profile.email}.`,
      });
      router.replace("/dashboard");
    } catch (err) {
      const apiError = toApiError(err);
      toast.error(
        mode === "signin" ? "Could not sign in" : "Could not create the account",
        { description: apiError.message },
      );
    }
  };

  const onGoogle = async () => {
    setGoogleBusy(true);
    try {
      await loginWithGoogle(); // navigates away on success
    } catch (err) {
      setGoogleBusy(false);
      toast.error("Google sign-in unavailable", {
        description: toApiError(err).message,
      });
    }
  };

  return (
    <div className="bg-grid relative flex min-h-dvh flex-col items-center justify-center overflow-hidden px-4 py-10">
      <div
        aria-hidden
        className="pointer-events-none absolute left-1/2 top-[-10%] h-96 w-[40rem] -translate-x-1/2 rounded-full bg-primary/20 blur-[120px]"
      />

      <div className="absolute left-4 top-4 sm:left-6 sm:top-6">
        <Button variant="ghost" size="sm" asChild>
          <Link href="/">
            <ArrowLeft aria-hidden /> Back
          </Link>
        </Button>
      </div>
      <div className="absolute right-4 top-4 sm:right-6 sm:top-6">
        <ThemeToggle />
      </div>

      <motion.div
        initial={{ opacity: 0, y: 18 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.5, ease: [0.22, 1, 0.36, 1] }}
        className="w-full max-w-md"
      >
        <div className="mb-8 flex justify-center">
          <Logo />
        </div>

        <GlassCard glow className="p-6 sm:p-8">
          <h1 className="text-xl font-bold tracking-tight">
            {mode === "signin" ? "Welcome back" : "Create your account"}
          </h1>
          <p className="mt-1 text-sm text-muted-foreground">
            {mode === "signin"
              ? "Sign in to continue your KYC journey."
              : "Save conversations and pick up where you left off, on any device."}
          </p>

          {googleAvailable === true ? (
            <Button
              variant="outline"
              className="mt-6 w-full"
              onClick={onGoogle}
              loading={googleBusy}
            >
              <GoogleIcon /> Continue with Google
            </Button>
          ) : googleAvailable === null ? (
            /* Unknown ≠ unconfigured: the server hasn't answered (yet). */
            <Button variant="outline" className="mt-6 w-full" disabled>
              <GoogleIcon /> Continue with Google
              <span className="ml-1 rounded-full bg-muted px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
                {backend.isWaking ? "Waking up…" : "Checking…"}
              </span>
            </Button>
          ) : (
            /* The server itself said google:false — the only honest case. */
            <Button variant="outline" className="mt-6 w-full" disabled>
              <GoogleIcon /> Continue with Google
              <span className="ml-1 rounded-full bg-muted px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
                Not configured
              </span>
            </Button>
          )}

          <div className="my-6 flex items-center gap-3" role="separator" aria-label="or">
            <span className="h-px flex-1 bg-border" />
            <span className="text-xs uppercase tracking-widest text-muted-foreground">or</span>
            <span className="h-px flex-1 bg-border" />
          </div>

          <form onSubmit={handleSubmit(onSubmit)} className="space-y-4" noValidate>
            {mode === "register" && (
              <div className="space-y-1.5">
                <Label htmlFor="fullName">Name</Label>
                <Input
                  id="fullName"
                  type="text"
                  placeholder="Your name"
                  autoComplete="name"
                  aria-invalid={!!errors.fullName}
                  {...register("fullName")}
                />
                {errors.fullName && (
                  <p className="text-xs text-destructive" role="alert">
                    {errors.fullName.message}
                  </p>
                )}
              </div>
            )}

            <div className="space-y-1.5">
              <Label htmlFor="email">Email</Label>
              <Input
                id="email"
                type="email"
                placeholder="you@example.com"
                autoComplete="email"
                aria-invalid={!!errors.email}
                {...register("email")}
              />
              {errors.email && (
                <p className="text-xs text-destructive" role="alert">
                  {errors.email.message}
                </p>
              )}
            </div>

            <div className="space-y-1.5">
              <Label htmlFor="password">Password</Label>
              <Input
                id="password"
                type="password"
                placeholder="••••••••"
                autoComplete={mode === "signin" ? "current-password" : "new-password"}
                aria-invalid={!!errors.password}
                {...register("password")}
              />
              {errors.password ? (
                <p className="text-xs text-destructive" role="alert">
                  {errors.password.message}
                </p>
              ) : (
                mode === "register" && (
                  // Stated up front rather than only on failure — the rules
                  // are the same ones the backend enforces.
                  <p className="text-xs text-muted-foreground">
                    At least {PASSWORD_MIN_LENGTH} characters, with an uppercase
                    and a lowercase letter, a number and a special character.
                  </p>
                )
              )}
            </div>

            <Button
              type="submit"
              variant="gradient"
              className="w-full"
              loading={isSubmitting}
            >
              {mode === "signin" ? (
                <>
                  <LogIn aria-hidden /> Sign in
                </>
              ) : (
                <>
                  <UserPlus aria-hidden /> Create account
                </>
              )}
            </Button>
          </form>

          <p className="mt-4 text-center text-xs text-muted-foreground">
            {mode === "signin" ? (
              <>
                New here?{" "}
                <button
                  type="button"
                  className="text-primary hover:underline"
                  onClick={() => switchMode("register")}
                >
                  Create an account
                </button>
              </>
            ) : (
              <>
                Already have an account?{" "}
                <button
                  type="button"
                  className="text-primary hover:underline"
                  onClick={() => switchMode("signin")}
                >
                  Sign in
                </button>
              </>
            )}
          </p>

          <p className="mt-4 text-center text-xs text-muted-foreground">
            Just exploring?{" "}
            <Link href="/dashboard" className="text-primary hover:underline">
              Open the workspace without an account
            </Link>
          </p>
        </GlassCard>
      </motion.div>
    </div>
  );
}

/** useSearchParams requires a Suspense boundary during static prerender. */
export default function SignInPage() {
  return (
    <React.Suspense fallback={null}>
      <SignInContent />
    </React.Suspense>
  );
}
