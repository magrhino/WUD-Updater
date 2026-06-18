import { nextTick } from "vue";

import { prefersReducedMotion } from "../../responsive";

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
