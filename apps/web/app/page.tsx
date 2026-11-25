import { ArrowDown } from "lucide-react";
import Link from "next/link";
import { Bento } from "@/components/landing/bento";
import { Gallery } from "@/components/landing/gallery";
import { HeroComposer } from "@/components/landing/hero-composer";
import { HeroScene } from "@/components/landing/hero-scene";
import { PipelineShowcase } from "@/components/landing/pipeline-showcase";
import { SiteFooter } from "@/components/site/footer";

const STACK = ["LangGraph", "MCP", "A2A", "Qdrant", "Langfuse", "Ragas", "Groq", "OpenStreetMap", "Open-Meteo", "Wikivoyage"];

export default function Home() {
  return (
    <>
      <section className="grain relative overflow-hidden">
        <div className="pointer-events-none absolute inset-0" aria-hidden>
          <div className="aurora-a absolute -left-[10%] -top-[20%] h-[70%] w-[60%] rounded-full bg-[radial-gradient(closest-side,var(--sun-soft),transparent)] blur-2xl" />
          <div className="aurora-b absolute -right-[10%] top-[10%] h-[80%] w-[55%] rounded-full bg-[radial-gradient(closest-side,var(--lagoon-soft),transparent)] blur-2xl" />
          <div className="aurora-a absolute bottom-[-30%] left-[30%] h-[60%] w-[50%] rounded-full bg-[radial-gradient(closest-side,var(--coral-soft),transparent)] blur-3xl" />
        </div>
        <div className="relative mx-auto grid max-w-7xl items-center gap-10 px-4 pb-16 pt-10 sm:px-6 sm:pt-16 lg:min-h-[calc(100dvh-4rem)] lg:grid-cols-[1.05fr_1fr] lg:gap-6 lg:pb-20">
          <div className="max-w-2xl">
            <p className="inline-flex items-center gap-2 rounded-full border border-line-strong bg-surface/70 px-3 py-1.5 text-xs font-semibold text-ink-2 backdrop-blur">
              <span className="live-dot h-1.5 w-1.5 rounded-full bg-coral" aria-hidden />
              Voyager v2 · 11 agents · live data · cited
            </p>
            <h1 className="mt-6 font-display text-[clamp(2.75rem,7vw,5.5rem)] font-semibold leading-[0.95]">
              Plan the trip,
              <br />
              <span className="display-italic text-coral">not the tabs.</span>
            </h1>
            <p className="mt-6 max-w-xl text-lg leading-relaxed text-ink-2">
              Describe it in a sentence. Specialist agents research weather, stays, food and costs in parallel — with live data, guidebook
              citations and a budget analyst that checks the maths.
            </p>
            <div className="mt-8">
              <HeroComposer />
            </div>
          </div>
          <HeroScene />
        </div>
        <div className="relative border-y border-line bg-surface/50 backdrop-blur">
          <div className="scrollbar-none mx-auto flex max-w-7xl items-center gap-6 overflow-x-auto px-4 py-4 sm:px-6">
            <span className="eyebrow shrink-0">Built on</span>
            {STACK.map((s) => (
              <span key={s} className="shrink-0 font-mono text-sm font-medium text-ink-2">
                {s}
              </span>
            ))}
            <a href="#agents" className="ml-auto hidden shrink-0 items-center gap-1 text-sm font-semibold text-ink-2 hover:text-ink lg:inline-flex">
              See the pipeline <ArrowDown className="h-4 w-4" aria-hidden />
            </a>
          </div>
        </div>
      </section>
      <PipelineShowcase />
      <Bento />
      <Gallery />
      <section className="px-4 pb-24 sm:px-6">
        <div className="grain relative mx-auto max-w-7xl overflow-hidden rounded-[2rem] bg-[#0e3a48] px-6 py-16 text-center text-[#f6efe2] sm:px-12">
          <div
            className="aurora-b pointer-events-none absolute -right-20 -top-20 h-80 w-80 rounded-full bg-[radial-gradient(closest-side,rgba(242,179,61,.35),transparent)]"
            aria-hidden
          />
          <h2 className="relative font-display text-4xl font-semibold sm:text-5xl">
            Where to <span className="display-italic text-[#f2b33d]">next?</span>
          </h2>
          <p className="relative mx-auto mt-4 max-w-xl text-[#f6efe2]/80">
            One sentence in, a cited, costed, weather-aware plan out — usually in under a minute.
          </p>
          <div className="relative mt-8 flex flex-wrap justify-center gap-3">
            <Link href="/plan" className="btn bg-[#f2b33d] text-[#0f2430] hover:bg-[#f7c868]">
              Plan a trip
            </Link>
            <Link href="/trip/demo" className="btn border border-white/30 text-white hover:bg-white/10">
              Watch the sample run
            </Link>
          </div>
        </div>
      </section>
      <SiteFooter />
    </>
  );
}
