"use client";

import { Compass, PlayCircle, RotateCw } from "lucide-react";
import Link from "next/link";
import { formatClock } from "@/lib/format";

/** The free-tier API sleeps; waking it is a state, not an error. Always offer the demo. */
export function WakingNotice({
  elapsedMs,
  onRetry,
  failed,
  message,
  compact,
}: {
  elapsedMs?: number;
  onRetry?: () => void;
  failed?: boolean;
  message?: string;
  compact?: boolean;
}) {
  const secs = Math.floor((elapsedMs ?? 0) / 1000);
  return (
    <div role="status" aria-live="polite" className={compact ? "rounded-2xl border border-line bg-surface-2 p-4" : "card mx-auto max-w-lg p-7 text-center"}>
      <div className={compact ? "flex items-start gap-3" : "flex flex-col items-center gap-3"}>
        <div className="relative flex h-12 w-12 shrink-0 items-center justify-center rounded-full bg-sun-soft">
          {!failed && <span className="pulse-ring absolute inset-0 rounded-full border-2 border-sun" aria-hidden />}
          <Compass className={`h-6 w-6 text-ink ${failed ? "" : "animate-[spin_6s_linear_infinite]"}`} aria-hidden />
        </div>
        <div className={compact ? "min-w-0 flex-1" : ""}>
          <p className="font-display text-lg font-semibold">{failed ? "The agents are still asleep" : "Waking the agents…"}</p>
          <p className="mt-1 text-sm text-ink-2">
            {message ??
              (failed
                ? "The free-tier server didn't answer in time. Try again in a minute, or explore the sample trip."
                : "Voyager's API runs on a free tier that naps when idle. A cold start takes about 30–60 seconds.")}
          </p>
          {!failed && elapsedMs !== undefined && (
            <p className="mt-2 font-mono text-xs text-ink-3 tabular">
              {formatClock(secs)} elapsed · checking every 3 s
            </p>
          )}
          <div className={`mt-4 flex flex-wrap gap-2 ${compact ? "" : "justify-center"}`}>
            {onRetry && (
              <button type="button" onClick={onRetry} className="btn btn-ghost !py-2 text-sm">
                <RotateCw className="h-4 w-4" aria-hidden /> Retry now
              </button>
            )}
            <Link href="/trip/demo" className="btn btn-primary !py-2 text-sm">
              <PlayCircle className="h-4 w-4" aria-hidden /> Watch the sample run
            </Link>
          </div>
        </div>
      </div>
    </div>
  );
}
