import { nextTick } from "vue";

function prefersReducedMotion(): boolean {
  return (
    typeof globalThis.window !== "undefined" &&
    typeof globalThis.window.matchMedia === "function" &&
    globalThis.window.matchMedia("(prefers-reduced-motion: reduce)").matches
  );
}

export function scrollToElementId(id: string): void {
  if (typeof document === "undefined") {
    return;
  }
  const target = document.getElementById(id);
  if (!target) {
    return;
  }
  target.scrollIntoView({
    behavior: prefersReducedMotion() ? "auto" : "smooth",
    block: "start",
  });
}

export async function focusOnboardingChecklist(): Promise<void> {
  if (typeof document === "undefined") {
    return;
  }
  await nextTick();
  const target = document.getElementById("onboarding-checklist");
  if (!target) {
    return;
  }
  target.scrollIntoView({
    behavior: prefersReducedMotion() ? "auto" : "smooth",
    block: "start",
  });
  target.focus({ preventScroll: true });
}
