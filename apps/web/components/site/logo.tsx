import Link from "next/link";

/** Wordmark: a compass-rose star over a horizon line. */
export function Logo({ className = "" }: { className?: string }) {
  return (
    <Link href="/" className={`group inline-flex items-center gap-2 ${className}`} aria-label="Voyager home">
      <svg viewBox="0 0 32 32" className="h-7 w-7" aria-hidden>
        <circle cx="16" cy="16" r="15" fill="var(--primary)" />
        <path d="M16 5.5 18.4 13.6 26.5 16 18.4 18.4 16 26.5 13.6 18.4 5.5 16 13.6 13.6Z" fill="var(--primary-ink)" />
        <path d="M16 5.5 18.4 13.6 16 16Z M26.5 16 18.4 18.4 16 16Z M16 26.5 13.6 18.4 16 16Z M5.5 16 13.6 13.6 16 16Z" fill="var(--coral)" opacity="0.9" />
        <circle cx="16" cy="16" r="1.6" fill="var(--primary)" />
      </svg>
      <span className="font-display text-[1.35rem] font-semibold leading-none tracking-tight">Voyager</span>
    </Link>
  );
}
