"use client";

import { useEffect, useSyncExternalStore } from "react";

/**
 * What the open trip page lends the assistant: its refine flow (so "Apply to my plan" re-streams through
 * the very same hook as the Refine dock) and whether the dock is on screen (so the launcher sits above it).
 * A tiny external store rather than a context: the assistant lives in the root layout, the trip page deep
 * below it.
 */
export interface AssistantTripBinding {
  tripId: string;
  destination?: string;
  revision: number;
  /** A finished plan is open and no refinement is running. */
  canApply: boolean;
  /** A refinement is running right now. */
  busy: boolean;
  /** The bottom Refine dock (and the phone Map button) are showing. */
  dock: boolean;
  /** Runs the trip's refine flow; resolves to an error message, or null on success. */
  apply: (message: string) => Promise<string | null>;
}

let current: AssistantTripBinding | null = null;
const listeners = new Set<() => void>();

function set(binding: AssistantTripBinding | null) {
  current = binding;
  listeners.forEach((l) => l());
}

function subscribe(cb: () => void) {
  listeners.add(cb);
  return () => {
    listeners.delete(cb);
  };
}

export function useAssistantBinding() {
  return useSyncExternalStore(
    subscribe,
    () => current,
    () => null,
  );
}

/** Call from the trip page with a memoised binding (or null while it isn't ready). */
export function useRegisterAssistantTrip(binding: AssistantTripBinding | null) {
  useEffect(() => {
    set(binding);
    return () => set(null);
  }, [binding]);
}
