"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "./api";
import { applyDemoRefinement, buildDemoScript, buildRefineScript, type DemoStep } from "./demo/script";
import { applyEvent, beginRevision, initialStreamState, type StreamState } from "./stream-state";
import type { StreamEvent, StreamEventType, TripPlan } from "./types";

export type StreamPhase = "idle" | "connecting" | "streaming" | "reconnecting" | "done" | "failed";
export type RunKind = "initial" | "refine" | "replay";

const EVENT_TYPES: StreamEventType[] = ["agent", "tool", "retrieval", "a2a", "partial", "plan", "error", "done"];
const MAX_RETRIES = 6;

interface LiveConn {
  key: number;
  minRevision: number;
}
interface DemoRun {
  key: number;
  steps: DemoStep[];
}

/**
 * Drives a trip's event stream into one reducer — either the live SSE endpoint (with reconnection and
 * replay de-duplication) or the scripted offline demo. Both feed the exact same UI.
 */
export function useTripStream(opts: { id: string; mode: "live" | "demo"; demoPlan?: TripPlan }) {
  const { id, mode, demoPlan } = opts;
  const [state, setState] = useState<StreamState>(() => initialStreamState());
  const [phase, setPhase] = useState<StreamPhase>(mode === "demo" ? "connecting" : "idle");
  const [runKind, setRunKind] = useState<RunKind>("initial");
  const [startedAt, setStartedAt] = useState<number | null>(null);
  const [live, setLive] = useState<LiveConn | null>(null);
  const [demo, setDemo] = useState<DemoRun | null>(() =>
    mode === "demo" && demoPlan ? { key: 0, steps: buildDemoScript(demoPlan) } : null,
  );
  const [speed, setSpeed] = useState(1);
  const speedRef = useRef(1);
  const skipRef = useRef(false);
  const seqRef = useRef(0);
  const stateRef = useRef(state);
  useEffect(() => {
    stateRef.current = state;
    speedRef.current = speed;
  });

  const push = useCallback((ev: StreamEvent) => {
    setState((s) => applyEvent(s, ev, performance.now()));
  }, []);

  // ── live SSE ────────────────────────────────────────────────────────────────
  useEffect(() => {
    if (mode !== "live" || !live) return;
    let es: EventSource | null = null;
    let closed = false;
    let retries = 0;
    let timer: ReturnType<typeof setTimeout> | undefined;

    const finish = (revision: number) => {
      closed = true;
      es?.close();
      setPhase("done");
      // If the plan event was missed (e.g. connection dropped right before it), fetch the stored trip.
      setTimeout(() => {
        if ((stateRef.current.plan?.revision ?? -1) >= revision) return;
        api
          .getTrip(id)
          .then((trip) => {
            if (trip.plan) push({ type: "plan", data: trip.plan });
          })
          .catch(() => undefined);
      }, 0);
    };

    const open = () => {
      es = new EventSource(api.streamUrl(id));
      es.onopen = () => {
        retries = 0;
        setPhase("streaming");
      };
      for (const type of EVENT_TYPES) {
        es.addEventListener(type, (e) => {
          // The native connection "error" shares the name with the SPEC's `event: error` — only the
          // server-sent one carries data.
          if (!(e instanceof MessageEvent) || typeof e.data !== "string" || !e.data) return;
          let data: unknown;
          try {
            data = JSON.parse(e.data);
          } catch {
            return;
          }
          const ev = { type, data } as StreamEvent;
          push(ev);
          if (ev.type === "done" && ev.data.revision >= live.minRevision) finish(ev.data.revision);
        });
      }
      es.onerror = (e) => {
        if (closed || (e instanceof MessageEvent && e.data)) return;
        if (es?.readyState === EventSource.CLOSED) {
          es.close();
          retries += 1;
          if (retries > MAX_RETRIES) {
            setPhase("failed");
            return;
          }
          setPhase("reconnecting");
          timer = setTimeout(open, Math.min(1000 * 2 ** retries, 15_000));
        } else {
          setPhase("reconnecting"); // the browser is auto-reconnecting; replayed events are de-duplicated
        }
      };
    };
    open();
    return () => {
      closed = true;
      es?.close();
      clearTimeout(timer);
    };
  }, [mode, live, id, push]);

  // ── offline demo player (virtual clock so it can fast-forward or skip) ──────
  useEffect(() => {
    if (!demo) return;
    let i = 0;
    let virtual = 0;
    let last = performance.now();
    let first = true;
    const emit = (step: DemoStep) => {
      seqRef.current += 1;
      const ev = { type: step.event.type, data: { ...step.event.data, ts: new Date().toISOString(), seq: seqRef.current } } as StreamEvent;
      push(ev);
    };
    const tick = () => {
      const now = performance.now();
      if (first) {
        first = false;
        setStartedAt(now);
        setPhase("streaming");
      }
      virtual += (now - last) * speedRef.current;
      last = now;
      while (i < demo.steps.length && (skipRef.current || demo.steps[i].at <= virtual)) {
        emit(demo.steps[i]);
        i += 1;
      }
      if (i >= demo.steps.length) {
        skipRef.current = false;
        setPhase("done");
        return;
      }
      timer = setTimeout(tick, 60);
    };
    let timer = setTimeout(tick, 250);
    return () => clearTimeout(timer);
  }, [demo, push]);

  // ── controls ────────────────────────────────────────────────────────────────
  /** Start streaming a live trip (call from an event or async callback). */
  const connect = useCallback((plan?: TripPlan) => {
    setState(initialStreamState(plan));
    setRunKind(plan ? "replay" : "initial");
    setPhase("connecting");
    setStartedAt(performance.now());
    setLive((c) => ({ key: (c?.key ?? 0) + 1, minRevision: plan?.revision ?? 0 }));
  }, []);

  /** Show a finished plan without streaming (trip already done). */
  const hydrate = useCallback((plan: TripPlan) => {
    setState(initialStreamState(plan));
    setPhase("done");
  }, []);

  const refine = useCallback(
    async (message: string) => {
      const current = stateRef.current.plan;
      if (mode === "demo") {
        if (!current) return;
        const next = applyDemoRefinement(current, message);
        setState((s) => beginRevision(s, next.revision));
        setRunKind("refine");
        setPhase("connecting");
        setStartedAt(performance.now());
        setDemo((d) => ({ key: (d?.key ?? 0) + 1, steps: buildRefineScript(next, message) }));
        return;
      }
      const res = await api.refine(id, message); // throws ApiError — the caller shows it
      setState((s) => beginRevision(s, res.revision));
      setRunKind("refine");
      setPhase("connecting");
      setStartedAt(performance.now());
      setLive((c) => ({ key: (c?.key ?? 0) + 1, minRevision: res.revision }));
    },
    [id, mode],
  );

  /** Watch the run again: the server replays stored events; the demo restarts its script. */
  const replay = useCallback(() => {
    const plan = stateRef.current.plan;
    if (mode === "demo") {
      if (!demoPlan) return;
      skipRef.current = false;
      setState(initialStreamState());
      setRunKind("replay");
      setPhase("connecting");
      setStartedAt(null);
      setDemo((d) => ({ key: (d?.key ?? 0) + 1, steps: buildDemoScript(plan ?? demoPlan) }));
      return;
    }
    connect(plan);
  }, [mode, demoPlan, connect]);

  const skip = useCallback(() => {
    skipRef.current = true;
  }, []);

  return { state, phase, runKind, startedAt, speed, setSpeed, connect, hydrate, refine, replay, skip };
}
