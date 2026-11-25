"use client";

import { CheckCircle2, Network, PiggyBank, TriangleAlert, Users } from "lucide-react";
import { motion } from "motion/react";
import { Cell, Pie, PieChart, ResponsiveContainer, Tooltip } from "recharts";
import { Counter } from "@/components/ui/counter";
import { ProvenancePill } from "@/components/ui/pills";
import { BUDGET_CATEGORY } from "@/lib/categories";
import { cn, formatMoney } from "@/lib/format";
import type { Budget } from "@/lib/types";

export function BudgetPanel({ budget, travellers }: { budget: Budget; travellers: number }) {
  const viaA2A = /a2a/i.test(budget.analyst);
  const data = budget.lines
    .filter((l) => l.amount.amount > 0)
    .map((l) => ({ name: BUDGET_CATEGORY[l.category]?.label ?? l.category, value: l.amount.amount, color: BUDGET_CATEGORY[l.category]?.color ?? "#999", line: l }));
  const util = Math.max(0, budget.utilisation);
  const fmt = (n: number) => formatMoney({ amount: n, currency: budget.total.currency });

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <span
          className={cn(
            "inline-flex items-center gap-1.5 rounded-full px-3 py-1.5 text-xs font-bold",
            viaA2A ? "bg-coral-soft text-coral" : "bg-bg-2 text-ink-2",
          )}
        >
          <Network className="h-3.5 w-3.5" aria-hidden />
          {viaA2A ? "Costed by Budget Analyst via A2A" : `Costed by ${budget.analyst}`}
        </span>
        <ProvenancePill value="estimate" />
        <span className="text-xs text-ink-3">Totals are estimates for planning, not quotes.</span>
      </div>

      <div className="grid gap-4 lg:grid-cols-[1.1fr_1fr]">
        <div className="card p-5 sm:p-6">
          <div className="grid items-center gap-6 sm:grid-cols-[13rem_1fr]">
            <div className="relative mx-auto h-52 w-52">
              <ResponsiveContainer width="100%" height="100%">
                <PieChart>
                  <Pie data={data} dataKey="value" nameKey="name" innerRadius="68%" outerRadius="100%" paddingAngle={2} stroke="none" isAnimationActive animationDuration={900}>
                    {data.map((d) => (
                      <Cell key={d.name} fill={d.color} />
                    ))}
                  </Pie>
                  <Tooltip
                    formatter={(v) => fmt(Number(v))}
                    contentStyle={{ background: "var(--surface)", border: "1px solid var(--line)", borderRadius: 12, color: "var(--ink)", fontSize: 12 }}
                    itemStyle={{ color: "var(--ink)" }}
                  />
                </PieChart>
              </ResponsiveContainer>
              <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center text-center">
                <span className="text-[11px] font-semibold uppercase tracking-wider text-ink-3">Total</span>
                <Counter value={budget.total.amount} format={fmt} className="tabular font-display text-2xl font-semibold" />
              </div>
            </div>
            <ul className="space-y-2.5">
              {data.map((d) => (
                <li key={d.name} className="flex items-start gap-3">
                  <span className="mt-1.5 h-2.5 w-2.5 shrink-0 rounded-full" style={{ background: d.color }} aria-hidden />
                  <div className="min-w-0 flex-1">
                    <div className="flex items-baseline justify-between gap-2">
                      <span className="text-sm font-bold">{d.name}</span>
                      <span className="tabular text-sm font-semibold">{fmt(d.value)}</span>
                    </div>
                    <p className="text-xs leading-snug text-ink-3">{d.line.note}</p>
                  </div>
                </li>
              ))}
            </ul>
          </div>
        </div>

        <div className="space-y-4">
          <div className="card p-5 sm:p-6">
            <div className="flex items-start justify-between gap-3">
              <div>
                <p className="eyebrow">Budget used</p>
                <p className="mt-1 font-display text-4xl font-semibold tabular">
                  <Counter value={util * 100} format={(n) => `${Math.round(n)}%`} />
                </p>
              </div>
              <span
                className={cn(
                  "inline-flex items-center gap-1.5 rounded-full px-3 py-1.5 text-xs font-bold",
                  budget.within_budget ? "bg-[var(--p-live-bg)] text-[var(--p-live)]" : "bg-[var(--p-na-bg)] text-[var(--p-na)]",
                )}
              >
                {budget.within_budget ? <CheckCircle2 className="h-3.5 w-3.5" aria-hidden /> : <TriangleAlert className="h-3.5 w-3.5" aria-hidden />}
                {budget.within_budget ? "Within budget" : "Over budget"}
              </span>
            </div>
            <div
              className="relative mt-5 h-3 rounded-full bg-bg-2"
              role="meter"
              aria-valuemin={0}
              aria-valuemax={100}
              aria-valuenow={Math.round(util * 100)}
              aria-label="Share of the budget used"
            >
              <motion.div
                className={cn("h-full rounded-full", budget.within_budget ? "bg-gradient-to-r from-lagoon to-[var(--p-live)]" : "bg-gradient-to-r from-sun to-coral")}
                initial={{ width: 0 }}
                animate={{ width: `${Math.min(util, 1.2) * (100 / 1.2)}%` }}
                transition={{ duration: 1.1, ease: [0.16, 1, 0.3, 1] }}
              />
              <span className="absolute -top-1 bottom-[-4px] w-0.5 rounded bg-ink" style={{ left: `${100 / 1.2}%` }} aria-hidden />
            </div>
            <div className="mt-2 flex justify-between text-xs text-ink-3">
              <span>{fmt(budget.total.amount)} planned</span>
              <span>limit {fmt(budget.limit.amount)}</span>
            </div>
            <div className="mt-5 grid grid-cols-2 gap-3 border-t border-line pt-4">
              <div>
                <p className="flex items-center gap-1 text-xs font-semibold text-ink-3">
                  <Users className="h-3.5 w-3.5" aria-hidden /> Per person
                </p>
                <p className="tabular font-display text-xl font-semibold">{formatMoney(budget.per_person)}</p>
                <p className="text-[11px] text-ink-3">{travellers} travellers</p>
              </div>
              <div>
                <p className="text-xs font-semibold text-ink-3">{budget.within_budget ? "Headroom" : "Over by"}</p>
                <p className={cn("tabular font-display text-xl font-semibold", budget.within_budget ? "text-lagoon" : "text-coral")}>
                  {fmt(Math.abs(budget.limit.amount - budget.total.amount))}
                </p>
              </div>
            </div>
          </div>

          {budget.savings_tips.length > 0 && (
            <div className="card p-5 sm:p-6">
              <p className="flex items-center gap-2 text-sm font-bold">
                <PiggyBank className="h-4 w-4 text-coral" aria-hidden /> Savings tips from the analyst
              </p>
              <ul className="mt-3 space-y-2.5">
                {budget.savings_tips.map((t, i) => (
                  <motion.li key={t} initial={{ opacity: 0, x: -8 }} animate={{ opacity: 1, x: 0 }} transition={{ delay: 0.2 + i * 0.08 }} className="flex gap-3 text-sm leading-relaxed text-ink-2">
                    <span className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-sun-soft font-mono text-[11px] font-bold text-ink">{i + 1}</span>
                    {t}
                  </motion.li>
                ))}
              </ul>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
