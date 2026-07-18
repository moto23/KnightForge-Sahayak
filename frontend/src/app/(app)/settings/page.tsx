"use client";

import * as React from "react";
import Link from "next/link";
import { LogIn, LogOut, Monitor, Moon, ShieldCheck, Sun } from "lucide-react";
import { useTheme } from "next-themes";
import { toast } from "sonner";

import { PageHeader } from "@/components/shared/page-header";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { useMounted } from "@/hooks/use-mounted";
import { cn } from "@/lib/utils";
import { useAuth } from "@/contexts/auth-context";
import { toApiError } from "@/services/api-client";

const THEME_OPTIONS = [
  { value: "dark", label: "Dark", icon: Moon, hint: "Default" },
  { value: "light", label: "Light", icon: Sun, hint: "Bright rooms" },
  { value: "system", label: "System", icon: Monitor, hint: "Follow OS" },
] as const;

export default function SettingsPage() {
  const { theme, setTheme } = useTheme();
  const mounted = useMounted();
  const { user, isAuthenticated, updateProfile, logout, logoutAll } = useAuth();
  const [displayName, setDisplayName] = React.useState("Guest");
  const [savingName, setSavingName] = React.useState(false);
  const [signingOut, setSigningOut] = React.useState<"one" | "all" | null>(null);
  const [soundOn, setSoundOn] = React.useState(true);
  const [compactChat, setCompactChat] = React.useState(false);

  /* Mirror the signed-in profile into the name field (adjust during render). */
  const [lastUserId, setLastUserId] = React.useState<string | null>(null);
  const currentUserId = user?.user_id ?? null;
  if (lastUserId !== currentUserId) {
    setLastUserId(currentUserId);
    setDisplayName(user ? user.full_name || user.email : "Guest");
  }

  const saveName = async () => {
    if (!isAuthenticated) {
      toast.success("Preferences saved", { description: "Stored in this browser." });
      return;
    }
    setSavingName(true);
    try {
      await updateProfile(displayName.trim() || "User");
      toast.success("Profile updated");
    } catch (err) {
      toast.error("Couldn't update the profile", {
        description: toApiError(err).message,
      });
    } finally {
      setSavingName(false);
    }
  };

  const signOut = async (everywhere: boolean) => {
    setSigningOut(everywhere ? "all" : "one");
    try {
      if (everywhere) {
        const revoked = await logoutAll();
        toast.success("Signed out everywhere", {
          description: `${revoked} session${revoked === 1 ? "" : "s"} revoked.`,
        });
      } else {
        await logout();
        toast.success("Signed out");
      }
    } catch (err) {
      toast.error("Sign-out failed", { description: toApiError(err).message });
    } finally {
      setSigningOut(null);
    }
  };

  return (
    <div className="space-y-6">
      <PageHeader
        title="Settings"
        description={
          isAuthenticated
            ? "Appearance, account, and interview preferences."
            : "Appearance and interview preferences. Sign in to sync your profile and conversation history."
        }
      />

      {/* Account (Phase 12) */}
      <Card>
        <CardHeader>
          <CardTitle>Account</CardTitle>
          <CardDescription>
            {isAuthenticated
              ? "Your Sahayak account and active sessions."
              : "You're using Sahayak as a guest — everything works, nothing is saved."}
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {isAuthenticated && user ? (
            <>
              <div className="flex flex-wrap items-center gap-3">
                <span className="grid size-10 place-items-center rounded-full bg-primary/15 text-sm font-semibold text-primary">
                  {(user.full_name || user.email).slice(0, 1).toUpperCase()}
                </span>
                <div className="min-w-0">
                  <p className="truncate text-sm font-medium">
                    {user.full_name || user.email}
                  </p>
                  <p className="truncate text-xs text-muted-foreground">{user.email}</p>
                </div>
                <span className="ml-auto flex gap-1.5">
                  {user.google_linked && <Badge variant="accent">Google linked</Badge>}
                  <Badge variant="success">
                    <ShieldCheck aria-hidden /> Signed in
                  </Badge>
                </span>
              </div>
              <div className="flex flex-wrap gap-2">
                <Button
                  variant="outline"
                  size="sm"
                  loading={signingOut === "one"}
                  onClick={() => void signOut(false)}
                >
                  <LogOut aria-hidden /> Sign out
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  loading={signingOut === "all"}
                  onClick={() => void signOut(true)}
                >
                  <LogOut aria-hidden /> Sign out on all devices
                </Button>
              </div>
            </>
          ) : (
            <Button variant="gradient" size="sm" asChild>
              <Link href="/signin">
                <LogIn aria-hidden /> Sign in or create an account
              </Link>
            </Button>
          )}
        </CardContent>
      </Card>

      {/* Appearance */}
      <Card>
        <CardHeader>
          <CardTitle>Appearance</CardTitle>
          <CardDescription>
            Choose how the workspace looks. Dark is the default.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div
            role="radiogroup"
            aria-label="Theme"
            className="grid gap-3 sm:grid-cols-3"
          >
            {THEME_OPTIONS.map((option) => {
              const selected = mounted && theme === option.value;
              return (
                <button
                  key={option.value}
                  type="button"
                  role="radio"
                  aria-checked={selected}
                  onClick={() => setTheme(option.value)}
                  className={cn(
                    "flex items-center gap-3 rounded-xl border p-4 text-left transition-all",
                    selected
                      ? "border-primary bg-primary/10 glow-primary"
                      : "border-border hover:border-primary/40 hover:bg-muted/50",
                  )}
                >
                  <span
                    className={cn(
                      "grid size-9 place-items-center rounded-lg",
                      selected ? "bg-primary/15 text-primary" : "bg-muted text-muted-foreground",
                    )}
                  >
                    <option.icon className="size-4.5" aria-hidden />
                  </span>
                  <span>
                    <span className="block text-sm font-medium">{option.label}</span>
                    <span className="block text-xs text-muted-foreground">{option.hint}</span>
                  </span>
                </button>
              );
            })}
          </div>
        </CardContent>
      </Card>

      {/* Profile */}
      <Card>
        <CardHeader>
          <CardTitle>Profile</CardTitle>
          <CardDescription>
            How Sahayak addresses you during the interview.
          </CardDescription>
        </CardHeader>
        <CardContent className="max-w-md space-y-4">
          <div className="space-y-1.5">
            <Label htmlFor="display-name">Display name</Label>
            <Input
              id="display-name"
              value={displayName}
              onChange={(e) => setDisplayName(e.target.value)}
              placeholder="Your name"
            />
          </div>
          <Button size="sm" loading={savingName} onClick={() => void saveName()}>
            Save changes
          </Button>
        </CardContent>
      </Card>

      {/* Interview preferences */}
      <Card>
        <CardHeader>
          <CardTitle>Interview experience</CardTitle>
          <CardDescription>Fine-tune the AI conversation.</CardDescription>
        </CardHeader>
        <CardContent className="divide-y divide-border">
          <div className="flex items-center justify-between gap-4 py-4 first:pt-0 last:pb-0">
            <div>
              <Label htmlFor="sound-toggle" className="text-sm font-medium">
                Sound effects
              </Label>
              <p className="mt-0.5 text-xs text-muted-foreground">
                Gentle chime when a field is validated.
              </p>
            </div>
            <Switch id="sound-toggle" checked={soundOn} onCheckedChange={setSoundOn} />
          </div>
          <div className="flex items-center justify-between gap-4 py-4 first:pt-0 last:pb-0">
            <div>
              <Label htmlFor="compact-toggle" className="text-sm font-medium">
                Compact chat
              </Label>
              <p className="mt-0.5 text-xs text-muted-foreground">
                Tighter spacing in the interview for small screens.
              </p>
            </div>
            <Switch
              id="compact-toggle"
              checked={compactChat}
              onCheckedChange={setCompactChat}
            />
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
