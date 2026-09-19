import { clsx } from "clsx";
import { twMerge } from "tailwind-merge";

// The `cn` helper every shadcn-style source expects at @/lib/utils: merge
// conditional class lists and let later utilities override earlier ones.
export function cn(...inputs) {
  return twMerge(clsx(inputs));
}
