import Link from "next/link";
import { Github } from "@/components/ui/icons";
import { Logo } from "./logo";
import { ThemeToggle } from "./theme-toggle";

export const GITHUB_URL = "https://github.com/pavanipavani16423-ctrl/Autonomous-Multi-Agent-Travel-Planner";

export function SiteNav() {
  return (
    <header className="no-print sticky top-0 z-40 border-b border-line bg-bg/75 backdrop-blur-xl supports-[backdrop-filter]:bg-bg/60">
      <nav className="mx-auto flex h-16 max-w-7xl items-center gap-3 px-4 sm:px-6" aria-label="Main">
        <Logo />
        <div className="ml-6 hidden items-center gap-1 text-sm font-semibold text-ink-2 md:flex">
          <Link href="/#agents" className="rounded-full px-3 py-2 transition hover:bg-ocean-soft hover:text-ink">
            How it works
          </Link>
          <Link href="/trip/demo" className="rounded-full px-3 py-2 transition hover:bg-ocean-soft hover:text-ink">
            Live demo
          </Link>
          <Link href="/trips" className="rounded-full px-3 py-2 transition hover:bg-ocean-soft hover:text-ink">
            My trips
          </Link>
        </div>
        <div className="ml-auto flex items-center gap-2">
          <a
            href={GITHUB_URL}
            target="_blank"
            rel="noreferrer"
            className="hidden h-9 w-9 items-center justify-center rounded-full border border-line-strong text-ink-2 transition hover:text-ink sm:inline-flex"
            aria-label="Source on GitHub"
          >
            <Github className="h-4 w-4" />
          </a>
          <ThemeToggle />
          <Link href="/plan" className="btn btn-primary !px-4 !py-2.5 text-sm">
            Plan a trip
          </Link>
        </div>
      </nav>
    </header>
  );
}
