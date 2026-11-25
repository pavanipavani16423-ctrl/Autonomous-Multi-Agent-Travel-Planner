import type { Metadata } from "next";
import { PlanClient } from "./plan-client";

export const metadata: Metadata = { title: "Plan a trip" };

export default async function PlanPage({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  const sp = await searchParams;
  const destination = typeof sp.destination === "string" ? sp.destination.slice(0, 80) : "";
  return (
    <div className="relative overflow-hidden">
      <div className="pointer-events-none absolute inset-x-0 top-0 h-[420px]" aria-hidden>
        <div className="aurora-a absolute -left-20 -top-32 h-96 w-[40rem] rounded-full bg-[radial-gradient(closest-side,var(--sun-soft),transparent)] blur-2xl" />
        <div className="aurora-b absolute -right-20 -top-20 h-96 w-[36rem] rounded-full bg-[radial-gradient(closest-side,var(--lagoon-soft),transparent)] blur-2xl" />
      </div>
      <div className="relative mx-auto max-w-3xl px-4 pb-24 pt-12 sm:px-6 sm:pt-16">
        <p className="eyebrow">Structured planner</p>
        <h1 className="mt-3 font-display text-4xl font-semibold leading-tight sm:text-5xl">
          Where are we <span className="display-italic text-coral">going?</span>
        </h1>
        <p className="mt-3 max-w-xl text-ink-2">
          Give the agents the essentials. Guidebook cities start instantly; anywhere else gets researched live first.
        </p>
        <PlanClient destination={destination} />
      </div>
    </div>
  );
}
