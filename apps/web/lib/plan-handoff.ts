"use client";

/**
 * The assistant's "Start planning" goes through the landing page's own parse → confirm flow. On the
 * landing page the hero composer listens for the event; anywhere else the request is parked in
 * sessionStorage and picked up when the composer mounts.
 */
const EVENT = "voyager:plan";
const KEY = "voyager.pendingPlan";

export interface PlanRequestDetail {
  text: string;
}

/** Returns true when a mounted composer took the request; false means "navigate to / to finish". */
export function requestPlan(text: string): boolean {
  const ev = new CustomEvent<PlanRequestDetail>(EVENT, { detail: { text }, cancelable: true });
  const unhandled = window.dispatchEvent(ev);
  if (!unhandled) return true;
  try {
    sessionStorage.setItem(KEY, text);
  } catch {
    /* storage blocked: the composer just won't prefill */
  }
  return false;
}

export function takePendingPlan(): string | null {
  try {
    const text = sessionStorage.getItem(KEY);
    if (text) sessionStorage.removeItem(KEY);
    return text;
  } catch {
    return null;
  }
}

export function onPlanRequest(handler: (text: string) => void) {
  const listener = (e: Event) => {
    const detail = (e as CustomEvent<PlanRequestDetail>).detail;
    if (!detail?.text) return;
    e.preventDefault();
    handler(detail.text);
  };
  window.addEventListener(EVENT, listener);
  return () => window.removeEventListener(EVENT, listener);
}
