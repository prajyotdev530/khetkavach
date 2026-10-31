// Grey placeholder block shown while a section is still loading.
import { cn } from "@/lib/utils";

export function Skeleton({ className }: { className?: string }) {
  return <div className={cn("animate-pulse rounded bg-slate-200", className)} aria-hidden="true" />;
}
