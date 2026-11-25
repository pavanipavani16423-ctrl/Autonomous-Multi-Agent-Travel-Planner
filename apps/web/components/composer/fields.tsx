"use client";

import { Minus, Plus } from "lucide-react";
import { useId } from "react";
import { cn } from "@/lib/format";

export function FieldError({ id, message }: { id?: string; message?: string }) {
  if (!message) return null;
  return (
    <p id={id} role="alert" className="mt-1.5 text-xs font-semibold text-coral">
      {message}
    </p>
  );
}

export function Stepper({
  label,
  value,
  min,
  max,
  onChange,
  hint,
}: {
  label: string;
  value: number;
  min: number;
  max: number;
  onChange: (n: number) => void;
  hint?: string;
}) {
  const id = useId();
  return (
    <div>
      <span className="label" id={id}>
        {label}
      </span>
      <div
        role="group"
        aria-labelledby={id}
        className="flex items-center justify-between rounded-[0.875rem] border border-line-strong bg-surface p-1"
      >
        <button
          type="button"
          onClick={() => onChange(Math.max(min, value - 1))}
          disabled={value <= min}
          className="inline-flex h-9 w-9 items-center justify-center rounded-[0.65rem] text-ink-2 transition hover:bg-bg-2 hover:text-ink disabled:opacity-35"
          aria-label={`Fewer ${label.toLowerCase()}`}
        >
          <Minus className="h-4 w-4" />
        </button>
        <output className="tabular min-w-8 text-center text-base font-bold" aria-live="polite">
          {value}
        </output>
        <button
          type="button"
          onClick={() => onChange(Math.min(max, value + 1))}
          disabled={value >= max}
          className="inline-flex h-9 w-9 items-center justify-center rounded-[0.65rem] text-ink-2 transition hover:bg-bg-2 hover:text-ink disabled:opacity-35"
          aria-label={`More ${label.toLowerCase()}`}
        >
          <Plus className="h-4 w-4" />
        </button>
      </div>
      {hint && <p className="mt-1 text-xs text-ink-3">{hint}</p>}
    </div>
  );
}

export function ChipGroup({
  label,
  options,
  value,
  onChange,
}: {
  label: string;
  options: { value: string; label: string; icon?: React.ReactNode }[];
  value: string[];
  onChange: (v: string[]) => void;
}) {
  const id = useId();
  return (
    <div>
      <span className="label" id={id}>
        {label}
      </span>
      <div role="group" aria-labelledby={id} className="flex flex-wrap gap-2">
        {options.map((o) => {
          const on = value.includes(o.value);
          return (
            <button
              key={o.value}
              type="button"
              className="chip"
              aria-pressed={on}
              onClick={() => onChange(on ? value.filter((v) => v !== o.value) : [...value, o.value])}
            >
              {o.icon}
              {o.label}
            </button>
          );
        })}
      </div>
    </div>
  );
}

/** Single-choice control rendered as an accessible radiogroup with arrow-key support. */
export function Segmented<T extends string>({
  label,
  options,
  value,
  onChange,
  className,
}: {
  label: string;
  options: { value: T; label: string; hint?: string; icon?: React.ReactNode }[];
  value: T;
  onChange: (v: T) => void;
  className?: string;
}) {
  const id = useId();
  const move = (dir: 1 | -1) => {
    const i = options.findIndex((o) => o.value === value);
    const next = options[(i + dir + options.length) % options.length];
    onChange(next.value);
    requestAnimationFrame(() => document.getElementById(`${id}-${next.value}`)?.focus());
  };
  return (
    <div className={className}>
      <span className="label" id={id}>
        {label}
      </span>
      <div
        role="radiogroup"
        aria-labelledby={id}
        className="grid gap-1 rounded-[0.95rem] border border-line-strong bg-surface p-1"
        style={{ gridTemplateColumns: `repeat(${options.length}, minmax(0, 1fr))` }}
        onKeyDown={(e) => {
          if (e.key === "ArrowRight" || e.key === "ArrowDown") {
            e.preventDefault();
            move(1);
          } else if (e.key === "ArrowLeft" || e.key === "ArrowUp") {
            e.preventDefault();
            move(-1);
          }
        }}
      >
        {options.map((o) => {
          const on = o.value === value;
          return (
            <button
              key={o.value}
              id={`${id}-${o.value}`}
              type="button"
              role="radio"
              aria-checked={on}
              tabIndex={on ? 0 : -1}
              onClick={() => onChange(o.value)}
              className={cn(
                "flex min-h-10 flex-col items-center justify-center gap-0.5 rounded-[0.7rem] px-2 py-1.5 text-sm font-semibold transition",
                on ? "bg-ink text-bg shadow-sm" : "text-ink-2 hover:bg-bg-2 hover:text-ink",
              )}
            >
              <span className="inline-flex items-center gap-1.5">
                {o.icon}
                {o.label}
              </span>
              {o.hint && <span className={cn("text-[11px] font-medium", on ? "text-bg/70" : "text-ink-3")}>{o.hint}</span>}
            </button>
          );
        })}
      </div>
    </div>
  );
}
