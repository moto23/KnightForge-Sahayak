"use client";

import * as React from "react";
import Image from "next/image";
import { Check, ImageUp, PenLine, Trash2, Upload } from "lucide-react";
import { toast } from "sonner";

import { StatusBadge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { cn } from "@/lib/utils";
import { fetchBlobUrl, toApiError } from "@/services/api-client";
import { assetsService } from "@/services";
import type { AssetKind, AssetRequirement } from "@/types/api";
import { formatBytes } from "@/utils/format";

/**
 * Copy per asset kind. Kept here (not in the backend DTO) because it is pure
 * presentation — the backend supplies only the requirement and the caps.
 */
const COPY: Record<
  AssetKind,
  { title: string; hint: string; icon: typeof ImageUp; alt: string }
> = {
  photo: {
    title: "Passport-size photograph",
    hint: "A recent photo of you, JPG or PNG.",
    icon: ImageUp,
    alt: "Your uploaded passport-size photograph",
  },
  signature: {
    title: "Your signature",
    hint: "A photo or scan of your signature on plain paper, JPG or PNG.",
    icon: PenLine,
    alt: "Your uploaded signature",
  },
};

type Props = {
  sessionId: string;
  requirement: AssetRequirement;
  /** Called after a successful upload or delete so the caller can re-sync. */
  onChanged: () => void | Promise<void>;
  /**
   * Shown when this asset is the question being asked AND is already supplied.
   * Without it the conversation has no way forward: the field is answered, so
   * uploading again is pointless, but nothing advances to the next question.
   */
  onKeepAndContinue?: () => void | Promise<void>;
  className?: string;
};

/**
 * Upload / preview / remove ONE form asset.
 *
 * Renders nothing when the active form does not require this asset — the
 * component is safe to mount unconditionally, and a form with no photo box
 * simply never shows a photo control.
 *
 * Client-side size and type checks mirror the backend exactly so the common
 * mistakes are caught before a multi-megabyte upload starts; the backend still
 * re-validates everything (including whether the image actually decodes).
 */
export function AssetUploadCard({
  sessionId,
  requirement,
  onChanged,
  onKeepAndContinue,
  className,
}: Props) {
  const [busy, setBusy] = React.useState(false);
  const [percent, setPercent] = React.useState(0);
  const [error, setError] = React.useState<string | null>(null);
  // Bumped after each successful change so the <img> re-fetches rather than
  // showing the browser's cached copy of the previous image at the same URL.
  const [version, setVersion] = React.useState(0);
  const inputRef = React.useRef<HTMLInputElement>(null);
  const kind = requirement.kind;

  /* Fetched with the auth header rather than pointed at directly: the asset
     file endpoint is ownership-checked, and a browser cannot attach a bearer
     token to <img src>, so a raw URL 404s for any session with an owner.
     Declared before the early return below — hooks must run in the same order
     on every render. */
  const [previewUrl, setPreviewUrl] = React.useState<string | null>(null);
  const provided = requirement.provided;
  React.useEffect(() => {
    if (!provided) return;
    let objectUrl: string | null = null;
    const controller = new AbortController();
    void fetchBlobUrl(`/assets/${sessionId}/${kind}/file`, controller.signal)
      .then((url) => {
        objectUrl = url;
        setPreviewUrl(url);
      })
      .catch(() => undefined);
    return () => {
      controller.abort();
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [provided, sessionId, kind, version]);

  if (!requirement.required) return null;

  const { title, hint, icon: Icon, alt } = COPY[requirement.kind];
  const maxMb = requirement.max_bytes / (1024 * 1024);

  const pick = (file: File) => {
    setError(null);
    if (!requirement.accepted_types.includes(file.type)) {
      setError("Please choose a JPG or PNG image.");
      return;
    }
    if (file.size > requirement.max_bytes) {
      setError(
        `That file is ${formatBytes(file.size)} — the maximum is ${maxMb} MB.`,
      );
      return;
    }
    void send(file);
  };

  const send = async (file: File) => {
    setBusy(true);
    setPercent(0);
    try {
      await assetsService.upload(sessionId, requirement.kind, file, setPercent);
      setVersion((v) => v + 1);
      await onChanged();
      toast.success(`${title} saved`, {
        description: "It will be placed on your form when you generate the PDF.",
      });
    } catch (err) {
      const apiError = toApiError(err);
      setError(apiError.message);
      toast.error(`Couldn't save your ${requirement.kind}`, {
        description: apiError.message,
      });
    } finally {
      setBusy(false);
      if (inputRef.current) inputRef.current.value = "";
    }
  };

  const remove = async () => {
    setBusy(true);
    setError(null);
    try {
      await assetsService.remove(sessionId, requirement.kind);
      setVersion((v) => v + 1);
      await onChanged();
      toast(`${title} removed`, {
        description: "This field is pending again.",
      });
    } catch (err) {
      const apiError = toApiError(err);
      setError(apiError.message);
      toast.error("Couldn't remove it", { description: apiError.message });
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card className={cn("overflow-hidden", className)}>
      <CardContent className="space-y-3 p-4">
        <div className="flex items-start justify-between gap-3">
          <div className="flex min-w-0 items-start gap-3">
            <span className="grid size-9 shrink-0 place-items-center rounded-lg bg-primary/15 text-primary">
              <Icon className="size-4.5" aria-hidden />
            </span>
            <div className="min-w-0">
              <p className="text-sm font-medium">{title}</p>
              <p className="text-xs text-muted-foreground">
                {hint} Up to {maxMb} MB.
              </p>
            </div>
          </div>
          <StatusBadge status={requirement.provided ? "answered" : "pending"} />
        </div>

        {provided && previewUrl && (
          <div className="flex items-center gap-3 rounded-lg border border-border bg-muted/30 p-2.5">
            {/* Unoptimized: this is a same-session private upload served by the
                API, not a static asset Next.js can optimise at build time. */}
            <Image
              src={previewUrl}
              alt={alt}
              width={64}
              height={64}
              unoptimized
              className={cn(
                "shrink-0 rounded border border-border bg-background object-contain",
                requirement.kind === "photo" ? "size-16" : "h-10 w-24",
              )}
            />
            <div className="min-w-0 flex-1">
              <p className="truncate text-xs font-medium">
                {requirement.asset?.original_filename}
              </p>
              <p className="text-xs text-muted-foreground">
                {requirement.asset
                  ? `${requirement.asset.width}×${requirement.asset.height} · ${formatBytes(requirement.asset.file_size)}`
                  : ""}
              </p>
            </div>
            <Check className="size-4 shrink-0 text-success" aria-hidden />
          </div>
        )}

        {busy && percent > 0 && percent < 100 && (
          <p className="text-xs text-muted-foreground" role="status">
            Uploading… {percent}%
          </p>
        )}

        {error && (
          <p className="text-xs text-destructive" role="alert">
            {error}
          </p>
        )}

        <div className="flex flex-wrap gap-2">
          {/* Already supplied and being asked about: the primary action is to
              move on, not to upload again. */}
          {requirement.provided && onKeepAndContinue && (
            <Button
              type="button"
              size="sm"
              variant="gradient"
              loading={busy}
              onClick={() => {
                // Held busy for the whole round trip so an impatient second
                // click cannot fire a second continue — which is what turned
                // one action into several identical messages.
                if (busy) return;
                setBusy(true);
                void (async () => {
                  try {
                    await onKeepAndContinue();
                  } finally {
                    setBusy(false);
                  }
                })();
              }}
            >
              <Check aria-hidden /> Keep &amp; Continue
            </Button>
          )}
          <input
            ref={inputRef}
            type="file"
            accept="image/jpeg,image/png"
            className="sr-only"
            aria-label={`Upload your ${title.toLowerCase()}`}
            onChange={(e) => {
              const file = e.target.files?.[0];
              if (file) pick(file);
            }}
          />
          <Button
            type="button"
            size="sm"
            variant={requirement.provided ? "outline" : "gradient"}
            loading={busy}
            onClick={() => inputRef.current?.click()}
          >
            <Upload aria-hidden />
            {requirement.provided ? "Replace" : "Upload"}
          </Button>
          {requirement.provided && (
            <Button
              type="button"
              size="sm"
              variant="ghost"
              disabled={busy}
              onClick={() => void remove()}
            >
              <Trash2 aria-hidden /> Remove
            </Button>
          )}
        </div>
      </CardContent>
    </Card>
  );
}
