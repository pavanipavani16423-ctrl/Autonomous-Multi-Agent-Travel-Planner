"use client";

import { ArrowUp, BookOpen, Check, ExternalLink, Loader2, RotateCcw, Sparkles, Square, Trash2, Wand2, X } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { usePathname, useRouter } from "next/navigation";
import { useCallback, useEffect, useId, useRef, useState } from "react";
import { useAssistantBinding, type AssistantTripBinding } from "@/lib/assistant-binding";
import { cn } from "@/lib/format";
import { requestPlan } from "@/lib/plan-handoff";
import type { Citation } from "@/lib/types";
import { useChat, type ChatMessage } from "@/lib/use-chat";
import { useMediaQuery } from "@/lib/use-reduced-motion";
import { MarkdownLite } from "./markdown-lite";

const TRIP_STARTERS = ["Why did you pick these hotels?", "Is day 2 too packed?", "What should I pack?", "How was the budget calculated?"];
const SITE_STARTERS = ["How does Voyager plan a trip?", "Plan 3 days in Goa under ₹30k", "What does the A2A budget analyst do?"];

const FOCUSABLE = 'a[href], button:not([disabled]), textarea:not([disabled]), input:not([disabled]), [tabindex]:not([tabindex="-1"])';

/**
 * The floating "Ask Voyager" assistant: a glowing launcher on every page and a chat panel that streams
 * grounded answers from POST /api/chat. Change requests surface an "Apply to my plan" button that runs the
 * trip's own refine flow; new-trip requests hand off to the landing page's parse → confirm flow.
 */
export function Assistant() {
  const pathname = usePathname() ?? "/";
  const router = useRouter();
  const binding = useAssistantBinding();
  const match = /^\/trip\/([^/?#]+)/.exec(pathname);
  const tripId = match ? decodeURIComponent(match[1]) : undefined;
  const trip = binding && binding.tripId === tripId ? binding : null;
  const chat = useChat({ scope: tripId ?? "global", tripId });
  const isPhone = useMediaQuery("(max-width: 640px)");

  const [open, setOpen] = useState(false);
  const [unread, setUnread] = useState(false);
  const [prevBusy, setPrevBusy] = useState(chat.busy);
  if (prevBusy !== chat.busy) {
    setPrevBusy(chat.busy);
    if (!chat.busy && !open) setUnread(true); // a reply finished while the panel was closed
  }

  const launcherRef = useRef<HTMLButtonElement>(null);
  const close = useCallback(() => {
    setOpen(false);
    requestAnimationFrame(() => launcherRef.current?.focus());
  }, []);

  // Phones: the sheet is full height, so stop the page behind it from scrolling.
  useEffect(() => {
    if (!open || !isPhone) return;
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = prev;
    };
  }, [open, isPhone]);

  const onAction = async (msg: ChatMessage) => {
    const action = msg.action;
    if (!action || action.status === "working" || action.status === "done") return;
    if (action.type === "plan") {
      chat.setAction(msg.id, "done", "Opening the planner…");
      setOpen(false);
      if (!requestPlan(action.message)) router.push("/");
      return;
    }
    if (!trip?.canApply) return;
    chat.setAction(msg.id, "working");
    const err = await trip.apply(action.message);
    if (err) {
      chat.setAction(msg.id, "error", err);
      return;
    }
    chat.setAction(msg.id, "done", `Sent to the agents — revising to v${trip.revision + 1}.`);
    setTimeout(() => setOpen(false), 700); // let the Refine dock's live progress take over
  };

  return (
    <div className="assistant-anchor no-print" data-dock={trip?.dock ? "true" : "false"}>
      <AnimatePresence>
        {open && (
          <Panel
            key="panel"
            isPhone={isPhone}
            trip={trip}
            tripId={tripId}
            chat={chat}
            onClose={close}
            onAction={onAction}
          />
        )}
      </AnimatePresence>

      <motion.button
        ref={launcherRef}
        type="button"
        onClick={() => {
          setUnread(false);
          setOpen((o) => !o);
        }}
        aria-label={open ? "Close the Voyager assistant" : "Ask Voyager"}
        aria-expanded={open}
        aria-haspopup="dialog"
        initial={{ opacity: 0, scale: 0.6 }}
        animate={{ opacity: open && isPhone ? 0 : 1, scale: open && isPhone ? 0.6 : 1 }}
        transition={{ type: "spring", stiffness: 380, damping: 26, delay: 0.15 }}
        whileHover={{ scale: 1.06 }}
        whileTap={{ scale: 0.94 }}
        style={{ bottom: "max(var(--a-bottom), env(safe-area-inset-bottom))", right: "var(--a-right)" }}
        className={cn("assistant-launcher group fixed z-40 h-14 w-14 rounded-full", open && isPhone && "pointer-events-none")}
      >
        <span aria-hidden className="assistant-aura pointer-events-none absolute -inset-1.5 rounded-full" />
        {!open && <span aria-hidden className="assistant-pulse pointer-events-none absolute inset-0 rounded-full border-2 border-sun" />}
        <span className="assistant-core relative grid h-14 w-14 place-items-center rounded-full shadow-float ring-1 ring-white/25">
          <AnimatePresence mode="wait" initial={false}>
            <motion.span
              key={open ? "x" : "spark"}
              initial={{ rotate: -45, opacity: 0, scale: 0.6 }}
              animate={{ rotate: 0, opacity: 1, scale: 1 }}
              exit={{ rotate: 45, opacity: 0, scale: 0.6 }}
              transition={{ duration: 0.18 }}
              className="grid place-items-center"
            >
              {open ? <X className="h-6 w-6" aria-hidden /> : <Sparkles className="h-6 w-6" aria-hidden />}
            </motion.span>
          </AnimatePresence>
        </span>
        {unread && !open && <span aria-hidden className="absolute right-0.5 top-0.5 h-3 w-3 rounded-full border-2 border-bg bg-coral" />}
        {!open && (
          <span className="pointer-events-none absolute right-[calc(100%+0.75rem)] top-1/2 hidden -translate-y-1/2 whitespace-nowrap rounded-full bg-ink px-3 py-1.5 text-xs font-bold text-bg opacity-0 shadow-float transition-opacity group-hover:opacity-100 group-focus-visible:opacity-100 sm:block">
            Ask Voyager
          </span>
        )}
      </motion.button>
    </div>
  );
}

type Chat = ReturnType<typeof useChat>;

function Panel({
  isPhone,
  trip,
  tripId,
  chat,
  onClose,
  onAction,
}: {
  isPhone: boolean;
  trip: AssistantTripBinding | null;
  tripId?: string;
  chat: Chat;
  onClose: () => void;
  onAction: (m: ChatMessage) => void;
}) {
  const titleId = useId();
  const panelRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const listRef = useRef<HTMLDivElement>(null);
  const stick = useRef(true);
  const [text, setText] = useState("");
  const { messages, busy, send, stop, clear } = chat;
  const last = messages[messages.length - 1];
  const starters = tripId ? TRIP_STARTERS : SITE_STARTERS;

  useEffect(() => {
    if (isPhone) panelRef.current?.focus();
    else inputRef.current?.focus();
  }, [isPhone]);

  // Escape closes from anywhere while open (focus can fall to <body>, e.g. when Stop unmounts).
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && !e.defaultPrevented && !document.querySelector("dialog[open]")) onClose();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);

  // Follow the stream unless the reader scrolled up.
  useEffect(() => {
    const el = listRef.current;
    if (el && stick.current) el.scrollTop = el.scrollHeight;
  }, [messages]);

  const submit = (value: string) => {
    const v = value.trim();
    if (!v || busy) return;
    stick.current = true;
    void send(v);
    setText("");
    inputRef.current?.focus();
  };

  const onKeyDown = (e: React.KeyboardEvent) => {
    if (e.key !== "Tab" || !panelRef.current) return;
    const nodes = Array.from(panelRef.current.querySelectorAll<HTMLElement>(FOCUSABLE)).filter((n) => n.offsetParent !== null);
    if (!nodes.length) return;
    const first = nodes[0];
    const lastNode = nodes[nodes.length - 1];
    if (e.shiftKey && (document.activeElement === first || document.activeElement === panelRef.current)) {
      e.preventDefault();
      lastNode.focus();
    } else if (!e.shiftKey && document.activeElement === lastNode) {
      e.preventDefault();
      first.focus();
    }
  };

  const lastUser = [...messages].reverse().find((m) => m.role === "user");
  // screen readers get the finished reply once, as plain text (not every streamed token)
  const announce =
    last?.role === "assistant" && last.status === "done" ? last.content.replace(/\*\*|__|`|\[(\d{1,2}(?:\s*,\s*\d{1,2})*)\]/g, "") : "";

  return (
    <motion.div
      ref={panelRef}
      role="dialog"
      aria-modal="true"
      aria-labelledby={titleId}
      tabIndex={-1}
      onKeyDown={onKeyDown}
      initial={isPhone ? { y: "100%" } : { opacity: 0, scale: 0.92, y: 16 }}
      animate={isPhone ? { y: 0 } : { opacity: 1, scale: 1, y: 0 }}
      exit={isPhone ? { y: "100%" } : { opacity: 0, scale: 0.94, y: 12 }}
      transition={{ type: "spring", stiffness: 340, damping: 32 }}
      style={
        isPhone
          ? undefined
          : {
              right: "var(--a-right)",
              bottom: "calc(var(--a-bottom) + 4.5rem)",
              height: "min(40rem, calc(100dvh - var(--a-bottom) - 10rem))",
              transformOrigin: "bottom right",
            }
      }
      className={cn(
        "fixed z-50 flex flex-col overflow-hidden border border-line bg-bg shadow-float outline-none",
        isPhone ? "inset-x-0 bottom-0 h-[calc(100dvh-0.5rem)] rounded-t-[1.5rem]" : "w-[25rem] min-h-[22rem] rounded-[1.5rem]",
      )}
    >
      {/* header */}
      <div className="relative flex items-start gap-3 border-b border-line bg-surface/80 px-4 pb-3 pt-4 backdrop-blur">
        <span className="assistant-core mt-0.5 grid h-9 w-9 shrink-0 place-items-center rounded-full shadow-card" aria-hidden>
          <Sparkles className="h-4 w-4" />
        </span>
        <div className="min-w-0 flex-1">
          <h2 id={titleId} className="font-display text-lg font-semibold leading-tight">
            Voyager assistant
          </h2>
          <p className="mt-0.5 flex flex-wrap items-center gap-1.5 text-[11.5px] text-ink-3">
            <span className="inline-flex items-center gap-1">
              <BookOpen className="h-3 w-3 shrink-0" aria-hidden />
              grounded in {tripId ? "your plan & guidebook" : "the guidebook & how Voyager works"}
            </span>
            {trip?.destination && (
              <span className="rounded-full bg-[var(--p-guide-bg)] px-1.5 py-px font-mono text-[10px] font-medium text-[var(--p-guide)]">
                {trip.destination} · v{trip.revision}
              </span>
            )}
          </p>
        </div>
        <div className="flex shrink-0 items-center gap-0.5">
          {messages.length > 0 && (
            <button type="button" onClick={clear} className="rounded-full p-2 text-ink-3 transition hover:bg-bg-2 hover:text-ink" aria-label="Clear conversation" title="Clear conversation">
              <Trash2 className="h-4 w-4" aria-hidden />
            </button>
          )}
          <button type="button" onClick={onClose} className="rounded-full p-2 text-ink-2 transition hover:bg-bg-2 hover:text-ink" aria-label="Close assistant">
            <X className="h-5 w-5" aria-hidden />
          </button>
        </div>
      </div>

      {/* messages */}
      <div
        ref={listRef}
        onScroll={(e) => {
          const el = e.currentTarget;
          stick.current = el.scrollHeight - el.scrollTop - el.clientHeight < 48;
        }}
        className="flex-1 space-y-4 overflow-y-auto overscroll-contain px-4 py-4"
      >
        {messages.length === 0 ? (
          <Welcome starters={starters} onPick={submit} onTrip={!!tripId} />
        ) : (
          messages.map((m) =>
            m.role === "user" ? (
              <div key={m.id} className="flex justify-end">
                <p className="max-w-[85%] whitespace-pre-wrap break-words rounded-2xl rounded-br-md bg-primary px-3.5 py-2.5 text-[14px] leading-relaxed text-primary-ink">{m.content}</p>
              </div>
            ) : (
              <AssistantMessage
                key={m.id}
                msg={m}
                trip={trip}
                onTripPage={!!tripId}
                onAction={() => onAction(m)}
                onRetry={m === last && lastUser ? () => submit(lastUser.content) : undefined}
              />
            ),
          )
        )}
      </div>
      <p className="sr-only" aria-live="polite">
        {announce}
      </p>

      {/* composer */}
      <form
        onSubmit={(e) => {
          e.preventDefault();
          submit(text);
        }}
        className="border-t border-line bg-surface/80 p-3 pb-[max(0.75rem,env(safe-area-inset-bottom))] backdrop-blur"
      >
        <div className="flex items-end gap-2 rounded-[1.25rem] border border-line-strong bg-surface p-1.5 pl-3.5 transition focus-within:border-coral focus-within:shadow-[0_0_0_4px_var(--coral-soft)]">
          <label htmlFor="assistant-input" className="sr-only">
            Ask the Voyager assistant
          </label>
          <textarea
            id="assistant-input"
            ref={inputRef}
            rows={1}
            value={text}
            maxLength={1000}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
                e.preventDefault();
                submit(text);
              }
            }}
            placeholder={tripId ? "Ask about this trip, or ask for a change…" : "Ask about Voyager or a destination…"}
            className="max-h-32 min-h-[2.25rem] flex-1 resize-none bg-transparent py-2 text-[14px] leading-snug text-ink outline-none [field-sizing:content] placeholder:text-ink-3"
          />
          {busy ? (
            <button
              type="button"
              onClick={() => {
                stop();
                inputRef.current?.focus();
              }}
              className="grid h-9 w-9 shrink-0 place-items-center rounded-full bg-ink text-bg transition hover:opacity-85" aria-label="Stop generating">
              <Square className="h-3.5 w-3.5 fill-current" aria-hidden />
            </button>
          ) : (
            <button type="submit" disabled={!text.trim()} className="btn btn-primary h-9 w-9 shrink-0 !p-0" aria-label="Send message">
              <ArrowUp className="h-4 w-4" aria-hidden />
            </button>
          )}
        </div>
        <p className="mt-1.5 px-1 text-[10.5px] text-ink-3">Answers cite the Wikivoyage guidebook. Prices are estimates, never live quotes.</p>
      </form>
    </motion.div>
  );
}

function Welcome({ starters, onPick, onTrip }: { starters: string[]; onPick: (s: string) => void; onTrip: boolean }) {
  return (
    <div className="pt-2">
      <p className="font-display text-[1.35rem] font-semibold leading-snug">
        {onTrip ? "Questions about this trip?" : "Hi, I'm Voyager's assistant."}
      </p>
      <p className="mt-1.5 text-[13.5px] leading-relaxed text-ink-2">
        {onTrip
          ? "I read your plan and the guidebook passages behind it. Ask why something's there — or ask for a change and I'll hand it to the agents when you say so."
          : "Ask how the agents plan a trip, what's in the guidebook for a city, or describe a trip and I'll start the planner for you."}
      </p>
      <p className="eyebrow mt-5">Try asking</p>
      <ul className="mt-2 space-y-2">
        {starters.map((s, i) => (
          <motion.li key={s} initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.05 * i + 0.1 }}>
            <button
              type="button"
              onClick={() => onPick(s)}
              className="group flex w-full items-center justify-between gap-2 rounded-2xl border border-line bg-surface px-3.5 py-2.5 text-left text-[13.5px] font-semibold text-ink-2 shadow-card transition hover:border-ink-3 hover:text-ink"
            >
              {s}
              <ArrowUp className="h-3.5 w-3.5 shrink-0 rotate-45 text-ink-3 transition group-hover:text-coral" aria-hidden />
            </button>
          </motion.li>
        ))}
      </ul>
    </div>
  );
}

function AssistantMessage({
  msg,
  trip,
  onTripPage,
  onAction,
  onRetry,
}: {
  msg: ChatMessage;
  trip: AssistantTripBinding | null;
  onTripPage: boolean;
  onAction: () => void;
  onRetry?: () => void;
}) {
  const [openSrc, setOpenSrc] = useState<string | null>(null);
  const streaming = msg.status === "streaming";
  const byId = new Map((msg.citations ?? []).map((c) => [c.id, c]));
  const numberOf = new Map(Object.entries(msg.refs ?? {}).map(([n, id]) => [id, n]));

  const renderCite = (n: string, key: string) => {
    const id = msg.refs?.[n];
    if (!id) {
      // unverified marker: muted while streaming, dropped once the server's sources are in
      return streaming ? (
        <sup key={key} className="ml-0.5 font-mono text-[10px] text-ink-3">
          [{n}]
        </sup>
      ) : null;
    }
    return (
      <button
        key={key}
        type="button"
        onClick={() => setOpenSrc((o) => (o === id ? null : id))}
        aria-label={`Source ${n}: ${byId.get(id)?.title ?? id}`}
        aria-expanded={openSrc === id}
        className={cn(
          "mx-0.5 inline-grid h-[1.15rem] min-w-[1.15rem] -translate-y-px place-items-center rounded-full px-1 align-middle font-mono text-[10px] font-medium transition",
          openSrc === id ? "bg-ink text-bg" : "bg-[var(--p-guide-bg)] text-[var(--p-guide)] hover:bg-ink hover:text-bg",
        )}
      >
        {n}
      </button>
    );
  };

  return (
    <div className="flex gap-2.5">
      <span className="assistant-core mt-0.5 grid h-7 w-7 shrink-0 place-items-center rounded-full" aria-hidden>
        <Sparkles className="h-3.5 w-3.5" />
      </span>
      <div className="min-w-0 flex-1">
        {streaming && !msg.content ? (
          <div className="flex items-center gap-2 py-1.5 text-[13px] text-ink-3" role="status">
            <span className="flex gap-1" aria-hidden>
              <span className="typing-dot h-1.5 w-1.5 rounded-full bg-coral" />
              <span className="typing-dot h-1.5 w-1.5 rounded-full bg-coral" />
              <span className="typing-dot h-1.5 w-1.5 rounded-full bg-coral" />
            </span>
            {onTripPage ? "Reading your plan & the guidebook…" : "Searching the guidebook…"}
          </div>
        ) : (
          <MarkdownLite text={msg.content} renderCite={renderCite} className={cn("text-[14px] leading-relaxed text-ink-2", streaming && "streaming-md")} />
        )}

        {msg.citations && msg.citations.length > 0 && (
          <Sources citations={msg.citations} numberOf={numberOf} openId={openSrc} onToggle={(id) => setOpenSrc((o) => (o === id ? null : id))} />
        )}

        {msg.action && !streaming && <ActionCard msg={msg} trip={trip} onAction={onAction} />}

        {msg.status === "stopped" && <p className="mt-1.5 font-mono text-[10.5px] uppercase tracking-wider text-ink-3">Stopped</p>}
        {msg.status === "error" && (
          <div role="alert" className="mt-2 flex flex-wrap items-center gap-2 rounded-xl bg-[var(--p-na-bg)] px-3 py-2 text-[12.5px] font-semibold text-[var(--p-na)]">
            {msg.error ?? "Something went wrong."}
            {onRetry && (
              <button type="button" onClick={onRetry} className="inline-flex items-center gap-1 underline underline-offset-2">
                <RotateCcw className="h-3 w-3" aria-hidden /> Retry
              </button>
            )}
          </div>
        )}
        {msg.status === "done" && msg.meta && msg.meta.intent !== "refused" && (
          <p className="mt-1.5 font-mono text-[10px] text-ink-3">
            {msg.meta.model === "offline" || msg.meta.model === "rules" ? "deterministic reply (no model)" : msg.meta.model}
            {msg.citations?.length ? ` · ${msg.citations.length} source${msg.citations.length === 1 ? "" : "s"}` : ""}
          </p>
        )}
      </div>
    </div>
  );
}

function Sources({
  citations,
  numberOf,
  openId,
  onToggle,
}: {
  citations: Citation[];
  numberOf: Map<string, string>;
  openId: string | null;
  onToggle: (id: string) => void;
}) {
  return (
    <div className="mt-2.5">
      <div className="flex flex-wrap gap-1.5">
        {citations.map((c) => (
          <button
            key={c.id}
            type="button"
            onClick={() => onToggle(c.id)}
            aria-expanded={openId === c.id}
            className={cn(
              "inline-flex max-w-full items-center gap-1.5 rounded-full border px-2 py-1 text-[11px] font-semibold transition",
              openId === c.id ? "border-ink bg-ink text-bg" : "border-line bg-surface text-ink-2 hover:border-ink-3 hover:text-ink",
            )}
          >
            <span className={cn("grid h-4 min-w-4 place-items-center rounded-full px-1 font-mono text-[9.5px]", openId === c.id ? "bg-bg/20" : "bg-[var(--p-guide-bg)] text-[var(--p-guide)]")}>
              {numberOf.get(c.id) ?? "•"}
            </span>
            <BookOpen className="h-3 w-3 shrink-0" aria-hidden />
            <span className="truncate">{c.title.replace(/\s*\(Wikivoyage\)$/, "")}</span>
          </button>
        ))}
      </div>
      <AnimatePresence initial={false}>
        {citations
          .filter((c) => c.id === openId)
          .map((c) => (
            <motion.div
              key={c.id}
              initial={{ opacity: 0, height: 0 }}
              animate={{ opacity: 1, height: "auto" }}
              exit={{ opacity: 0, height: 0 }}
              className="overflow-hidden"
            >
              <div className="mt-2 rounded-2xl border border-line bg-surface p-3">
                <p className="flex items-center gap-1.5 text-[10.5px] font-semibold uppercase tracking-wide text-ink-3">
                  <BookOpen className="h-3 w-3" aria-hidden /> Wikivoyage guidebook · <span className="font-mono normal-case">{c.id}</span>
                </p>
                <p className="mt-1 text-[12.5px] leading-relaxed text-ink-2">“{c.snippet}”</p>
                <a href={c.url} target="_blank" rel="noreferrer" className="mt-2 inline-flex items-center gap-1 text-xs font-bold text-coral hover:underline">
                  Open source <ExternalLink className="h-3 w-3" aria-hidden />
                </a>
              </div>
            </motion.div>
          ))}
      </AnimatePresence>
    </div>
  );
}

function ActionCard({ msg, trip, onAction }: { msg: ChatMessage; trip: AssistantTripBinding | null; onAction: () => void }) {
  const a = msg.action!;
  const isRefine = a.type === "refine";
  const unavailable = isRefine && !trip?.canApply && a.status !== "done";
  const why = !isRefine ? null : !trip ? "Open the finished plan to apply changes." : trip.busy ? "The agents are already revising this plan…" : !trip.canApply ? "Available once the plan is ready." : null;
  return (
    <motion.div initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} className="mt-3 rounded-2xl border border-line-strong bg-surface p-3 shadow-card">
      <p className="eyebrow !text-[10px]">{isRefine ? "Suggested change" : "New trip"}</p>
      <p className="mt-1 text-[13px] font-semibold leading-snug text-ink">“{a.message}”</p>
      <div className="mt-2.5 flex flex-wrap items-center gap-2">
        <button type="button" onClick={onAction} disabled={unavailable || a.status === "working" || a.status === "done"} className="btn btn-primary !px-3.5 !py-2 text-[13px]">
          {a.status === "working" ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> : a.status === "done" ? <Check className="h-4 w-4" aria-hidden /> : isRefine ? <Wand2 className="h-4 w-4" aria-hidden /> : <Sparkles className="h-4 w-4" aria-hidden />}
          {a.status === "done" ? (isRefine ? "Applied" : "Opened") : isRefine ? "Apply to my plan" : "Start planning"}
        </button>
        <span className="text-[11.5px] leading-snug text-ink-3">
          {a.note ?? why ?? (isRefine ? "Re-runs itinerary → budget (A2A) → critic. Nothing changes until you press it." : "You'll check the details before any agent starts.")}
        </span>
      </div>
      {a.status === "error" && <p className="mt-2 text-[12px] font-semibold text-[var(--p-na)]">Couldn’t apply it — try again.</p>}
    </motion.div>
  );
}
