"use client";

import { useRouter } from "next/navigation";
import { useCallback, useRef, useState } from "react";
import { ApiError, api, waitForApi } from "./api";
import { getClientId } from "./client-id";
import type { TripRequest } from "./types";

export type CreateState =
  | { status: "idle" }
  | { status: "submitting" }
  | { status: "waking"; elapsedMs: number }
  | { status: "error"; message: string; offline?: boolean };

/** POST /api/trips, riding out a free-tier cold start before giving up, then open the workspace. */
export function useCreateTrip() {
  const router = useRouter();
  const [state, setState] = useState<CreateState>({ status: "idle" });
  const abort = useRef<AbortController | null>(null);

  const submit = useCallback(
    async (req: TripRequest) => {
      abort.current?.abort();
      const ctrl = new AbortController();
      abort.current = ctrl;
      const body: TripRequest = { ...req, client_id: getClientId() || undefined };
      setState({ status: "submitting" });
      for (let attempt = 0; attempt < 2; attempt++) {
        try {
          const { trip_id } = await api.createTrip(body);
          router.push(`/trip/${encodeURIComponent(trip_id)}`);
          return;
        } catch (err) {
          if (ctrl.signal.aborted) return;
          if (err instanceof ApiError && err.isOffline && attempt === 0) {
            setState({ status: "waking", elapsedMs: 0 });
            const ok = await waitForApi({ signal: ctrl.signal, onTick: (ms) => setState({ status: "waking", elapsedMs: ms }) });
            if (ok) continue;
            setState({ status: "error", message: "The planner is still asleep. Try again in a minute — or watch the sample run.", offline: true });
            return;
          }
          const message =
            err instanceof ApiError
              ? err.kind === "rate_limited"
                ? `Too many trips at once — try again in ${err.retryAfter ?? 30} s.`
                : err.message
              : "Something went wrong starting the agents.";
          setState({ status: "error", message, offline: err instanceof ApiError && err.isOffline });
          return;
        }
      }
    },
    [router],
  );

  const cancel = useCallback(() => {
    abort.current?.abort();
    setState({ status: "idle" });
  }, []);

  return { state, submit, cancel };
}
