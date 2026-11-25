import Link from "next/link";
import { Github } from "@/components/ui/icons";
import { Logo } from "./logo";
import { GITHUB_URL } from "./nav";

export function SiteFooter() {
  return (
    <footer className="no-print border-t border-line bg-bg-2/50">
      <div className="mx-auto grid max-w-7xl gap-8 px-4 py-12 sm:px-6 md:grid-cols-[1.4fr_1fr_1fr]">
        <div>
          <Logo />
          <p className="mt-3 max-w-sm text-sm text-ink-2">
            A multi-agent trip planner: LangGraph, MCP tool servers, an A2A budget agent, hybrid RAG over Wikivoyage, and Langfuse + Ragas
            scoring on every run.
          </p>
          <p className="mt-5 text-sm font-semibold">
            Built by Pavani B<span className="text-coral">.</span>
          </p>
        </div>
        <div className="text-sm">
          <p className="eyebrow mb-3">Product</p>
          <ul className="space-y-2 text-ink-2">
            <li>
              <Link className="hover:text-ink" href="/plan">Plan a trip</Link>
            </li>
            <li>
              <Link className="hover:text-ink" href="/trip/demo">Live demo</Link>
            </li>
            <li>
              <Link className="hover:text-ink" href="/trips">My trips</Link>
            </li>
            <li>
              <Link className="hover:text-ink" href="/#agents">How it works</Link>
            </li>
          </ul>
        </div>
        <div className="text-sm">
          <p className="eyebrow mb-3">Data &amp; source</p>
          <ul className="space-y-2 text-ink-2">
            <li>
              <a className="inline-flex items-center gap-1.5 hover:text-ink" href={GITHUB_URL} target="_blank" rel="noreferrer">
                <Github className="h-3.5 w-3.5" /> GitHub repository
              </a>
            </li>
            <li>Guidebook: Wikivoyage (CC BY-SA)</li>
            <li>Maps: OpenStreetMap · OpenFreeMap</li>
            <li>Weather: Open-Meteo · FX: Frankfurter</li>
          </ul>
        </div>
      </div>
    </footer>
  );
}
