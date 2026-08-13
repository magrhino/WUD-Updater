import { nextTick, type Directive } from "vue";

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
  const focusTarget =
    target.querySelector<HTMLElement>("summary") ??
    target.querySelector<HTMLElement>("h2") ??
    target;
  if (focusTarget.tagName !== "SUMMARY") {
    focusTarget.tabIndex = -1;
  }
  focusTarget.focus({ preventScroll: true });
}

export function syncSettingsSelectLoadingState(element: HTMLElement): void {
  const loadingIndicator =
    element.querySelector<HTMLElement>(".n-base-loading[aria-label='loading']");
  if (!loadingIndicator) {
    return;
  }
  if (loadingIndicator.querySelector(".n-base-loading__placeholder")) {
    loadingIndicator.setAttribute("aria-hidden", "true");
  } else {
    loadingIndicator.removeAttribute("aria-hidden");
  }
}

export const vSettingsSelectLoadingState: Directive<HTMLElement> = {
  mounted: syncSettingsSelectLoadingState,
  updated: syncSettingsSelectLoadingState,
};

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
