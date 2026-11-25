"use client";

import { X } from "lucide-react";
import { motion } from "motion/react";
import { useEffect, useRef } from "react";

/**
 * Modal sheet on the native <dialog> (focus trap, Escape, inert background for free). Bottom sheet on
 * phones, centred panel on larger screens.
 */
export function Sheet({
  open,
  onClose,
  title,
  subtitle,
  children,
}: {
  open: boolean;
  onClose: () => void;
  title: string;
  subtitle?: React.ReactNode;
  children: React.ReactNode;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const d = ref.current;
    if (!d) return;
    if (open && !d.open) d.showModal();
    if (!open && d.open) d.close();
  }, [open]);

  return (
    <dialog
      ref={ref}
      onClose={onClose}
      onCancel={(e) => {
        e.preventDefault();
        onClose();
      }}
      onClick={(e) => {
        if (e.target === ref.current) onClose();
      }}
      aria-labelledby="sheet-title"
      className="m-0 mt-auto max-h-[92dvh] w-full max-w-none overflow-visible bg-transparent p-0 text-ink backdrop:bg-transparent sm:m-auto sm:max-w-2xl"
    >
      {open && (
        <motion.div
          initial={{ opacity: 0, y: 40 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ type: "spring", stiffness: 320, damping: 32 }}
          className="flex max-h-[92dvh] flex-col overflow-hidden rounded-t-[1.75rem] border border-line bg-bg shadow-float sm:rounded-[1.75rem]"
        >
          <div className="flex items-start justify-between gap-4 border-b border-line px-5 pb-4 pt-5 sm:px-7">
            <div>
              <h2 id="sheet-title" className="font-display text-2xl font-semibold">
                {title}
              </h2>
              {subtitle && <div className="mt-1 text-sm text-ink-2">{subtitle}</div>}
            </div>
            <button
              type="button"
              onClick={onClose}
              className="rounded-full p-2 text-ink-2 transition hover:bg-bg-2 hover:text-ink"
              aria-label="Close"
            >
              <X className="h-5 w-5" />
            </button>
          </div>
          <div className="overflow-y-auto px-5 py-6 sm:px-7">{children}</div>
        </motion.div>
      )}
    </dialog>
  );
}
