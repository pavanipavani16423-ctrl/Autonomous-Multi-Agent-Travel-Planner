"use client";

import { AlertTriangle, Compass, PlayCircle } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { WakingNotice } from "@/components/ui/waking";
import { ApiError, api, waitForApi } from "@/lib/api";
import { useRegisterAssistantTrip } from "@/lib/assistant-binding";
import { DEMO_ID, DEMO_PLAN } from "@/lib/demo";
import type { TripRequest } from "@/lib/types";
import { useTripStream } from "@/lib/use-trip-stream";
import { MissionControl } from "./mission-control";
import { Workspace } from "./workspace";

type Load =
  | { status: "loading" }
  | { status: "waking"; elapsedMs: number; failed?: boolean }
  | { status: "notfound" }
  | { status: "error"; message: string }
  | { status: "ready" };

/**
 * /trip/[id]: load the trip, then either stream it live into mission control or open the finished
 * workspace. `demo` replays a scripted run with no backend at all.
 */
export function TripClient({ id }: { id: string }) {
  const isDemo = id === DEMO_ID;
  const stream = useTripStream({ id, mode: isDemo ? "demo" : "live", demoPlan: isDemo ? DEMO_PLAN : undefined });
  const { state, phase, startedAt, runKind, connect, hydrate, refine } = stream;
  const [load, setLoad] = useState<Load>(isDemo ? { status: "ready" } : { status: "loading" });
  const [request, setRequest] = useState<TripRequest | undefined>(isDemo ? DEMO_PLAN.request : undefined);
  const [attempt, setAttempt] = useState(0);
  const [opened, setOpened] = useState(false);
  const [refineError, setRefineError] = useState<string | null>(null);
  const ctrlRef = useRef<AbortController | null>(null);

  useEffect(() => {
    if (isDemo) return;
    const ctrl = new AbortController();
    ctrlRef.current = ctrl;
    const run = async () => {
      for (let pass = 0; pass < 2; pass++) {
        try {
          const trip = await api.getTrip(id, ctrl.signal);
          if (ctrl.signal.aborted) return;
          setRequest(trip.request);
          if (trip.status === "error" && !trip.plan) {
            setLoad({ status: "error", message: trip.error ?? "The agents couldn't finish this trip." });
            return;
          }
          if (trip.status === "done" && trip.plan) hydrate(trip.plan);
          else connect();
          setLoad({ status: "ready" });
          return;
        } catch (err) {
          if (ctrl.signal.aborted) return;
          if (err instanceof ApiError && err.kind === "not_found") {
            setLoad({ status: "notfound" });
            return;
          }
          if (err instanceof ApiError && err.isOffline && pass === 0) {
            setLoad({ status: "waking", elapsedMs: 0 });
            const ok = await waitForApi({ signal: ctrl.signal, onTick: (ms) => setLoad({ status: "waking", elapsedMs: ms }) });
            if (ctrl.signal.aborted) return;
            if (ok) continue;
            setLoad({ status: "waking", elapsedMs: 0, failed: true });
            return;
          }
          setLoad(err instanceof ApiError && err.isOffline ? { status: "waking", elapsedMs: 0, failed: true } : { status: "error", message: err instanceof Error ? err.message : "Unknown error" });
          return;
        }
      }
    };
    void run();
    return () => ctrl.abort();
  }, [id, isDemo, attempt, connect, hydrate]);

  const onOpen = useCallback(() => setOpened(true), []);

  /** The one refine flow — used by the Refine dock and by the assistant's "Apply to my plan". */
  const applyRefine = useCallback(
    async (message: string): Promise<string | null> => {
      setRefineError(null);
      try {
        await refine(message);
        return null;
      } catch (err) {
        const msg = err instanceof ApiError ? (err.isOffline ? "The planner is asleep — try again in a moment." : err.message) : "Couldn't send that refinement.";
        setRefineError(msg);
        return msg;
      }
    },
    [refine],
  );
  const onRefine = (message: string) => {
    void applyRefine(message);
  };

  const plan = state.plan;
  const refining = runKind === "refine" && phase !== "done" && phase !== "failed";
  // Finished trips open straight away; a run we watched live hands over after the "plan ready" beat.
  const showWorkspace = !!plan && (runKind === "refine" || startedAt === null || opened);
  const ready = load.status === "ready";
  const binding = useMemo(
    () =>
      ready
        ? {
            tripId: id,
            destination: plan?.destination.name ?? request?.destination,
            revision: plan?.revision ?? 0,
            canApply: !!plan && showWorkspace && !refining,
            busy: refining,
            dock: !!plan && showWorkspace,
            apply: applyRefine,
          }
        : null,
    [ready, id, plan, request?.destination, showWorkspace, refining, applyRefine],
  );
  useRegisterAssistantTrip(binding);

  const onReplay = () => {
    setOpened(false);
    stream.replay();
    window.scrollTo({ top: 0 });
  };

  // ── non-ready states ──
  if (load.status === "loading") {
    return (
      <div className="mx-auto flex min-h-[60vh] max-w-md flex-col items-center justify-center gap-3 px-4 text-center" role="status">
        <Compass className="h-8 w-8 animate-[spin_4s_linear_infinite] text-coral" aria-hidden />
        <p className="text-sm text-ink-2">Opening your trip…</p>
      </div>
    );
  }
  if (load.status === "waking") {
    return (
      <div className="px-4 py-16">
        <WakingNotice elapsedMs={load.elapsedMs} failed={load.failed} onRetry={() => setAttempt((n) => n + 1)} />
      </div>
    );
  }
  if (load.status === "notfound" || load.status === "error") {
    return (
      <div className="px-4 py-16">
        <div className="card mx-auto max-w-lg p-8 text-center">
          <AlertTriangle className="mx-auto h-8 w-8 text-coral" aria-hidden />
          <h1 className="mt-3 font-display text-2xl font-semibold">{load.status === "notfound" ? "We couldn't find that trip" : "This trip didn't finish"}</h1>
          <p className="mt-2 text-sm text-ink-2">
            {load.status === "notfound" ? "Trips live on the server that planned them — the link may be from another deployment, or the trip expired." : load.message}
          </p>
          <div className="mt-5 flex flex-wrap justify-center gap-2">
            <Link href="/plan" className="btn btn-primary !py-2 text-sm">
              Plan a new trip
            </Link>
            <Link href="/trip/demo" className="btn btn-ghost !py-2 text-sm">
              <PlayCircle className="h-4 w-4" aria-hidden /> See the sample
            </Link>
          </div>
        </div>
      </div>
    );
  }
  if (phase === "failed" && !state.plan) {
    return (
      <div className="px-4 py-16">
        <WakingNotice failed message="We lost the live connection to the agents. Your trip keeps planning on the server — reconnect to pick it up." onRetry={() => connect()} />
      </div>
    );
  }

  if (plan && showWorkspace) {
    return (
      <Workspace plan={plan} stream={state} refining={refining} refineError={refineError} demo={isDemo} onRefine={onRefine} onReplay={onReplay} />
    );
  }

  const req = request ?? plan?.request;
  const name = state.partials.destination?.name ?? req?.destination;
  return (
    <MissionControl
      state={state}
      phase={phase}
      startedAt={startedAt}
      request={req}
      title={name ? `Planning ${name}` : "Planning your trip"}
      demo={isDemo}
      onSkip={stream.skip}
      speed={stream.speed}
      onSpeed={stream.setSpeed}
      onOpen={onOpen}
    />
  );
}
