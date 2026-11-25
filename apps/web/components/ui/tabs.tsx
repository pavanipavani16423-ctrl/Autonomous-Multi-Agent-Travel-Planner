"use client";

import { motion } from "motion/react";
import { useId, useRef } from "react";
import { cn } from "@/lib/format";

export interface TabDef<T extends string> {
  id: T;
  label: string;
  icon?: React.ReactNode;
  badge?: React.ReactNode;
}

/** WAI-ARIA tabs: roving tabindex, arrow/Home/End keys, animated indicator. */
export function Tabs<T extends string>({
  tabs,
  value,
  onChange,
  label,
  className,
  idPrefix,
}: {
  tabs: TabDef<T>[];
  value: T;
  onChange: (v: T) => void;
  label: string;
  className?: string;
  idPrefix?: string;
}) {
  const auto = useId();
  const prefix = idPrefix ?? auto;
  const listRef = useRef<HTMLDivElement>(null);
  const focusTab = (id: T) => requestAnimationFrame(() => document.getElementById(`${prefix}-tab-${id}`)?.focus());

  return (
    <div
      ref={listRef}
      role="tablist"
      aria-label={label}
      className={cn("scrollbar-none flex gap-1 overflow-x-auto", className)}
      onKeyDown={(e) => {
        const i = tabs.findIndex((t) => t.id === value);
        let next = -1;
        if (e.key === "ArrowRight") next = (i + 1) % tabs.length;
        else if (e.key === "ArrowLeft") next = (i - 1 + tabs.length) % tabs.length;
        else if (e.key === "Home") next = 0;
        else if (e.key === "End") next = tabs.length - 1;
        if (next < 0) return;
        e.preventDefault();
        onChange(tabs[next].id);
        focusTab(tabs[next].id);
      }}
    >
      {tabs.map((t) => {
        const on = t.id === value;
        return (
          <button
            key={t.id}
            id={`${prefix}-tab-${t.id}`}
            role="tab"
            type="button"
            aria-selected={on}
            aria-controls={`${prefix}-panel-${t.id}`}
            tabIndex={on ? 0 : -1}
            onClick={() => onChange(t.id)}
            className={cn(
              "relative inline-flex shrink-0 items-center gap-1.5 rounded-full px-3.5 py-2 text-sm font-semibold transition-colors",
              on ? "text-bg" : "text-ink-2 hover:text-ink",
            )}
          >
            {on && (
              <motion.span
                layoutId={`${prefix}-pill`}
                className="absolute inset-0 rounded-full bg-ink"
                transition={{ type: "spring", stiffness: 420, damping: 36 }}
                aria-hidden
              />
            )}
            <span className="relative inline-flex items-center gap-1.5">
              {t.icon}
              {t.label}
              {t.badge}
            </span>
          </button>
        );
      })}
    </div>
  );
}

export function TabPanel({ id, prefix, active, children, className }: { id: string; prefix: string; active: boolean; children: React.ReactNode; className?: string }) {
  if (!active) return null;
  return (
    <div role="tabpanel" id={`${prefix}-panel-${id}`} aria-labelledby={`${prefix}-tab-${id}`} tabIndex={0} className={cn("outline-none", className)}>
      {children}
    </div>
  );
}
