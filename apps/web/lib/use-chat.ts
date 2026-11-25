"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError } from "./api";
import { streamChat } from "./chat-stream";
import { getClientId } from "./client-id";
import type { ChatAction, ChatDone, ChatTurn, Citation } from "./types";

export type ActionStatus = "idle" | "working" | "done" | "error";

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  status?: "streaming" | "done" | "stopped" | "error";
  error?: string;
  citations?: Citation[];
  refs?: Record<string, string>;
  action?: ChatAction & { status: ActionStatus; note?: string };
  meta?: Pick<ChatDone, "intent" | "model" | "grounded">;
}

const MAX_STORED = 40;
const HISTORY_TURNS = 10;

const storageKey = (scope: string) => `voyager.chat.${scope}`;
const newId = () => `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;

function load(scope: string): ChatMessage[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = sessionStorage.getItem(storageKey(scope));
    const list = raw ? (JSON.parse(raw) as ChatMessage[]) : [];
    // a reply interrupted by a reload can't resume: keep what arrived and mark it stopped
    return list.map((m) => (m.status === "streaming" ? { ...m, status: "stopped" } : m));
  } catch {
    return [];
  }
}

function save(scope: string, messages: ChatMessage[]) {
  try {
    if (messages.length) sessionStorage.setItem(storageKey(scope), JSON.stringify(messages.slice(-MAX_STORED)));
    else sessionStorage.removeItem(storageKey(scope));
  } catch {
    /* storage full or blocked: the conversation just won't survive a reload */
  }
}

/**
 * One conversation per scope (a trip id, or "global" off-trip), kept in sessionStorage. Sends the last
 * ten finished turns as history and streams the reply token by token.
 */
export function useChat(opts: { scope: string; tripId?: string }) {
  const { scope, tripId } = opts;
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [loadedScope, setLoadedScope] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const abortRef = useRef<AbortController | null>(null);

  // Switch conversations when the page (scope) changes — derived during render, no effect round-trip.
  if (loadedScope !== scope) {
    setLoadedScope(scope);
    setMessages(load(scope));
    setBusy(false);
  }

  useEffect(() => {
    if (loadedScope === scope) save(scope, messages);
  }, [scope, loadedScope, messages]);

  // Leaving a scope (or unmounting) stops its in-flight reply.
  useEffect(() => () => abortRef.current?.abort(), [scope]);

  const patch = useCallback((id: string, fn: (m: ChatMessage) => ChatMessage) => {
    setMessages((list) => list.map((m) => (m.id === id ? fn(m) : m)));
  }, []);

  const send = useCallback(
    async (text: string) => {
      const message = text.trim();
      if (!message || busy) return;
      const history: ChatTurn[] = messages
        .filter((m) => m.content && (m.role === "user" || m.status === "done" || m.status === "stopped"))
        .slice(-HISTORY_TURNS)
        .map((m) => ({ role: m.role, content: m.content.slice(0, 4000) }));
      const user: ChatMessage = { id: newId(), role: "user", content: message, status: "done" };
      const reply: ChatMessage = { id: newId(), role: "assistant", content: "", status: "streaming" };
      setMessages((list) => [...list, user, reply]);
      setBusy(true);
      const ctrl = new AbortController();
      abortRef.current = ctrl;
      try {
        const body = { message, history, trip_id: tripId, client_id: getClientId() || undefined };
        for await (const ev of streamChat(body, ctrl.signal)) {
          if (ev.type === "token") patch(reply.id, (m) => ({ ...m, content: m.content + ev.data.text }));
          else if (ev.type === "sources") patch(reply.id, (m) => ({ ...m, citations: ev.data.citations, refs: ev.data.refs }));
          else if (ev.type === "action") patch(reply.id, (m) => ({ ...m, action: { ...ev.data, status: "idle" } }));
          else if (ev.type === "error") patch(reply.id, (m) => ({ ...m, status: "error", error: ev.data.message }));
          else if (ev.type === "done") {
            const { intent, model, grounded } = ev.data;
            patch(reply.id, (m) => ({ ...m, status: m.status === "error" ? "error" : "done", meta: { intent, model, grounded } }));
          }
        }
        patch(reply.id, (m) => (m.status === "streaming" ? { ...m, status: m.content ? "done" : "error", error: m.content ? undefined : "The reply was cut off. Try again." } : m));
      } catch (err) {
        if (ctrl.signal.aborted) {
          patch(reply.id, (m) => ({ ...m, status: "stopped" }));
        } else {
          const msg = err instanceof ApiError ? err.message : "Something went wrong talking to the assistant.";
          patch(reply.id, (m) => ({ ...m, status: "error", error: msg }));
        }
      } finally {
        if (abortRef.current === ctrl) abortRef.current = null;
        setBusy(false);
      }
    },
    [busy, messages, patch, tripId],
  );

  const stop = useCallback(() => abortRef.current?.abort(), []);

  const clear = useCallback(() => {
    abortRef.current?.abort();
    setMessages([]);
  }, []);

  const setAction = useCallback(
    (id: string, status: ActionStatus, note?: string) => {
      patch(id, (m) => (m.action ? { ...m, action: { ...m.action, status, note } } : m));
    },
    [patch],
  );

  return { messages, busy, send, stop, clear, setAction };
}
