"use client";

import Image from "next/image";
import { useState } from "react";
import { cn } from "@/lib/format";
import { isOptimizable, useWikiImage } from "@/lib/wiki";

const POSITIONED = /(^|\s)(absolute|fixed)(\s|$)/;

function hue(s: string) {
  let h = 0;
  for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) % 360;
  return h;
}

/** Photography-led surfaces: a Wikipedia photo with a warm gradient placeholder while it loads. */
export function Photo({
  title,
  src,
  alt,
  className,
  sizes = "(max-width: 768px) 100vw, 50vw",
  priority,
  width = 960,
}: {
  title?: string;
  src?: string;
  alt: string;
  className?: string;
  sizes?: string;
  priority?: boolean;
  width?: number;
}) {
  const url = useWikiImage(title, src, width);
  const [loaded, setLoaded] = useState<string | null>(null);
  const [failed, setFailed] = useState<string | null>(null);
  const h = hue(title ?? alt);
  const show = url && failed !== url;
  return (
    <div
      className={cn("overflow-hidden", !POSITIONED.test(className ?? "") && "relative", className)}
      style={{
        background: `radial-gradient(120% 90% at 20% 10%, hsl(${(h + 30) % 360} 55% 72% / .9), transparent 60%), linear-gradient(135deg, hsl(${h} 38% 42%), hsl(${(h + 50) % 360} 45% 24%))`,
      }}
    >
      {show && (
        <Image
          src={url}
          alt={alt}
          fill
          sizes={sizes}
          priority={priority}
          unoptimized={!isOptimizable(url)}
          onLoad={() => setLoaded(url)}
          onError={() => setFailed(url)}
          className={cn(
            "object-cover transition-[opacity,transform] duration-700 ease-out",
            loaded === url ? "scale-100 opacity-100" : "scale-[1.03] opacity-0",
          )}
        />
      )}
    </div>
  );
}
