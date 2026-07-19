"use client";

import * as React from "react";
import { AnimatePresence, motion } from "framer-motion";
import { PartyPopper, X } from "lucide-react";

/**
 * One-time celebration for a genuinely completed milestone.
 *
 * Two deliberate constraints:
 *
 *  - NO new dependency. A confetti library is ~15 KB for twelve lines of
 *    physics; particles are drawn straight onto a canvas that unmounts when the
 *    burst ends, so nothing keeps running afterwards.
 *
 *  - prefers-reduced-motion is honoured properly. Users who ask for reduced
 *    motion get the message with no canvas mounted at all — not a slower
 *    animation, none. The information is in the banner; the confetti is
 *    decoration.
 *
 * Deciding WHEN to celebrate is the caller's job — this component only knows
 * how to celebrate.
 */

const PARTICLE_COUNT = 90;
const DURATION_MS = 2600;
const COLORS = ["#6366f1", "#22d3ee", "#a855f7", "#34d399", "#fbbf24", "#f472b6"];

type Particle = {
  x: number;
  y: number;
  vx: number;
  vy: number;
  size: number;
  rotation: number;
  spin: number;
  color: string;
};

/** Launch from the two bottom corners, angled inward across the viewport. */
function seedParticles(width: number, height: number): Particle[] {
  const particles: Particle[] = [];
  for (let i = 0; i < PARTICLE_COUNT; i += 1) {
    const fromLeft = i % 2 === 0;
    // Spread each corner's burst over a ~50° arc aimed up and inward.
    const angle = (fromLeft ? -60 : -120) + (Math.random() - 0.5) * 50;
    const radians = (angle * Math.PI) / 180;
    const speed = 11 + Math.random() * 11;
    particles.push({
      x: fromLeft ? -10 : width + 10,
      y: height + 10,
      vx: Math.cos(radians) * speed * (fromLeft ? 1 : -1),
      vy: Math.sin(radians) * speed,
      size: 5 + Math.random() * 6,
      rotation: Math.random() * Math.PI,
      spin: (Math.random() - 0.5) * 0.3,
      color: COLORS[i % COLORS.length],
    });
  }
  return particles;
}

/**
 * Subscribe to the OS "reduce motion" setting.
 *
 * `useSyncExternalStore` is the right tool here rather than useEffect +
 * setState: a media query IS an external store, and this way React reads it
 * during render instead of triggering a second render pass after mount. The
 * server snapshot returns `true` (reduced) so a user who wants less motion
 * never gets a frame of confetti before hydration corrects it.
 */
function usePrefersReducedMotion(): boolean {
  return React.useSyncExternalStore(
    (onChange) => {
      const query = window.matchMedia("(prefers-reduced-motion: reduce)");
      query.addEventListener("change", onChange);
      return () => query.removeEventListener("change", onChange);
    },
    () => window.matchMedia("(prefers-reduced-motion: reduce)").matches,
    () => true,
  );
}

function ConfettiCanvas() {
  const canvasRef = React.useRef<HTMLCanvasElement>(null);

  React.useEffect(() => {
    const canvas = canvasRef.current;
    const context = canvas?.getContext("2d");
    if (!canvas || !context) return;

    const ratio = window.devicePixelRatio || 1;
    const width = window.innerWidth;
    const height = window.innerHeight;
    canvas.width = width * ratio;
    canvas.height = height * ratio;
    context.scale(ratio, ratio);

    const particles = seedParticles(width, height);
    const started = performance.now();
    let frame = 0;

    const draw = (now: number) => {
      const elapsed = now - started;
      if (elapsed >= DURATION_MS) {
        context.clearRect(0, 0, width, height);
        return;
      }
      // Fade the whole burst out over its final third.
      const fade = Math.max(0, 1 - Math.max(0, elapsed / DURATION_MS - 0.65) / 0.35);
      context.clearRect(0, 0, width, height);
      context.globalAlpha = fade;

      for (const p of particles) {
        p.x += p.vx;
        p.y += p.vy;
        p.vy += 0.32; // gravity
        p.vx *= 0.995; // air resistance
        p.rotation += p.spin;

        context.save();
        context.translate(p.x, p.y);
        context.rotate(p.rotation);
        context.fillStyle = p.color;
        context.fillRect(-p.size / 2, -p.size / 4, p.size, p.size / 2);
        context.restore();
      }
      context.globalAlpha = 1;
      frame = requestAnimationFrame(draw);
    };

    frame = requestAnimationFrame(draw);
    return () => cancelAnimationFrame(frame);
  }, []);

  return (
    <canvas
      ref={canvasRef}
      aria-hidden
      className="pointer-events-none fixed inset-0 z-50 h-dvh w-dvw"
    />
  );
}

/**
 * Celebration banner (+ optional confetti).
 *
 * `show` should be set only once per genuinely-new milestone — this component
 * does not deduplicate, because only the caller knows what "new" means.
 */
export function Celebration({
  show,
  message,
  onDismiss,
}: {
  show: boolean;
  message: string;
  onDismiss: () => void;
}) {
  const reducedMotion = usePrefersReducedMotion();

  // Auto-dismiss so a celebration never becomes a permanent banner.
  React.useEffect(() => {
    if (!show) return;
    const timer = setTimeout(onDismiss, 9000);
    return () => clearTimeout(timer);
  }, [show, onDismiss]);

  return (
    <>
      {show && !reducedMotion && <ConfettiCanvas />}
      <AnimatePresence>
        {show && (
          <motion.div
            initial={reducedMotion ? { opacity: 0 } : { opacity: 0, y: -12, scale: 0.97 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: -8 }}
            transition={{ duration: reducedMotion ? 0.15 : 0.4, ease: [0.22, 1, 0.36, 1] }}
            className="flex items-center gap-3 rounded-xl border border-success/40 bg-success/10 px-4 py-3"
            role="status"
            aria-live="polite"
          >
            <span className="grid size-9 shrink-0 place-items-center rounded-lg bg-success/20 text-success">
              <PartyPopper className="size-5" aria-hidden />
            </span>
            <p className="flex-1 text-sm font-medium">{message}</p>
            <button
              type="button"
              onClick={onDismiss}
              aria-label="Dismiss"
              className="rounded-md p-1 text-muted-foreground transition-colors hover:bg-success/10 hover:text-foreground"
            >
              <X className="size-4" aria-hidden />
            </button>
          </motion.div>
        )}
      </AnimatePresence>
    </>
  );
}
