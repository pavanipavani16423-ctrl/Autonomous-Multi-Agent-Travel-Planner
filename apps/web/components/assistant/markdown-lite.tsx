import { Fragment, type ReactNode } from "react";

/**
 * Just enough markdown for chat replies — paragraphs, "- " / "1. " lists, **bold**, *italic*, `code`,
 * [links](https://…) and bare URLs — built as React elements (never innerHTML). `[n]` citation markers
 * are handed to `renderCite`, so only markers the server confirmed become source chips.
 */
type Cite = (n: string, key: string) => ReactNode;

const INLINE = /(\*\*[^*\n]+\*\*|__[^_\n]+__|`[^`\n]+`|\[[^\]\n]+\]\((https?:\/\/[^)\s]+)\)|\[\d{1,2}(?:\s*,\s*\d{1,2})*\]|https?:\/\/[^\s<>()]+[^\s<>().,;:!?'"]|(?<![\w*])\*[^*\n]+\*(?![\w*])|(?<![\w_])_[^_\n]+_(?![\w_]))/g;

function safeHref(url: string) {
  try {
    const u = new URL(url);
    return u.protocol === "https:" || u.protocol === "http:" ? u.toString() : null;
  } catch {
    return null;
  }
}

function inline(text: string, cite: Cite | undefined, keyBase: string): ReactNode[] {
  const out: ReactNode[] = [];
  let last = 0;
  let i = 0;
  for (const m of text.matchAll(INLINE)) {
    const tok = m[0];
    const at = m.index ?? 0;
    if (at > last) out.push(text.slice(last, at));
    const key = `${keyBase}-${i++}`;
    if (tok.startsWith("**") || tok.startsWith("__")) {
      out.push(
        <strong key={key} className="font-bold text-ink">
          {inline(tok.slice(2, -2), cite, key)}
        </strong>,
      );
    } else if (tok.startsWith("`")) {
      out.push(
        <code key={key} className="rounded bg-bg-2 px-1 py-0.5 font-mono text-[0.85em]">
          {tok.slice(1, -1)}
        </code>,
      );
    } else if (/^\[\d/.test(tok) && !tok.includes("](")) {
      const nums = tok.slice(1, -1).split(/\s*,\s*/);
      out.push(<Fragment key={key}>{nums.map((n, j) => (cite ? cite(n, `${key}-${j}`) : `[${n}]`))}</Fragment>);
    } else if (tok.startsWith("[")) {
      const label = tok.slice(1, tok.indexOf("]("));
      const href = safeHref(tok.slice(tok.indexOf("](") + 2, -1));
      out.push(
        href ? (
          <a key={key} href={href} target="_blank" rel="noreferrer" className="font-semibold text-coral underline decoration-coral/40 underline-offset-2 hover:decoration-coral">
            {label}
          </a>
        ) : (
          label
        ),
      );
    } else if (tok.startsWith("http")) {
      const href = safeHref(tok);
      out.push(
        href ? (
          <a key={key} href={href} target="_blank" rel="noreferrer" className="break-all font-semibold text-coral underline decoration-coral/40 underline-offset-2">
            {tok.replace(/^https?:\/\//, "")}
          </a>
        ) : (
          tok
        ),
      );
    } else {
      out.push(<em key={key}>{inline(tok.slice(1, -1), cite, key)}</em>);
    }
    last = at + tok.length;
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
}

type Block = { kind: "p"; lines: string[] } | { kind: "ul" | "ol"; items: string[] };

function blocks(src: string): Block[] {
  const out: Block[] = [];
  for (const raw of src.replace(/\r/g, "").split("\n")) {
    const line = raw.trimEnd();
    const bullet = /^\s*[-*•]\s+(.*)$/.exec(line);
    const numbered = /^\s*\d{1,2}[.)]\s+(.*)$/.exec(line);
    const prev = out[out.length - 1];
    if (bullet || numbered) {
      const kind = bullet ? "ul" : "ol";
      const item = (bullet ?? numbered)![1];
      if (prev && prev.kind === kind) prev.items.push(item);
      else out.push({ kind, items: [item] });
    } else if (!line.trim()) {
      out.push({ kind: "p", lines: [] });
    } else if (/^#{1,6}\s+/.test(line)) {
      out.push({ kind: "p", lines: [`**${line.replace(/^#{1,6}\s+/, "")}**`] }); // headings → a bold line
    } else if (prev && prev.kind === "p" && prev.lines.length) {
      prev.lines.push(line);
    } else if (prev && prev.kind !== "p" && /^\s{2,}\S/.test(raw)) {
      prev.items[prev.items.length - 1] += ` ${line.trim()}`; // wrapped list item
    } else {
      out.push({ kind: "p", lines: [line] });
    }
  }
  return out.filter((b) => (b.kind === "p" ? b.lines.length > 0 : b.items.length > 0));
}

export function MarkdownLite({ text, renderCite, className }: { text: string; renderCite?: Cite; className?: string }) {
  return (
    <div className={className}>
      {blocks(text).map((b, i) => {
        const key = `b${i}`;
        if (b.kind === "p") {
          return (
            <p key={key} className="[&:not(:first-child)]:mt-2.5">
              {b.lines.map((l, j) => (
                <Fragment key={j}>
                  {j > 0 && <br />}
                  {inline(l, renderCite, `${key}-${j}`)}
                </Fragment>
              ))}
            </p>
          );
        }
        const List = b.kind === "ul" ? "ul" : "ol";
        return (
          <List key={key} className={`space-y-1.5 pl-5 [&:not(:first-child)]:mt-2.5 ${b.kind === "ul" ? "list-disc marker:text-coral" : "list-decimal marker:font-mono marker:text-[0.8em] marker:text-ink-3"}`}>
            {b.items.map((it, j) => (
              <li key={j} className="pl-0.5">
                {inline(it, renderCite, `${key}-${j}`)}
              </li>
            ))}
          </List>
        );
      })}
    </div>
  );
}
