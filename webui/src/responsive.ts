import { useBreakpoints, useMediaQuery } from "@vueuse/core";

export const responsiveBreakpoints = {
  compact: 560,
  narrowActions: 760,
  dataCards: 768,
  appShell: 920,
  managementCards: 1120,
  policyManagementCards: 1200,
} as const;

export const responsiveCustomMedia = {
  compact: "--wud-compact",
  narrowActions: "--wud-narrow-actions",
  dataCards: "--wud-data-cards",
  appShell: "--wud-app-shell",
  managementCards: "--wud-management-cards",
  policyManagementCards: "--wud-policy-management-cards",
  reducedMotion: "--wud-reduced-motion",
} as const;

export const responsiveMediaQueries = {
  compact: `(max-width: ${responsiveBreakpoints.compact}px)`,
  narrowActions: `(max-width: ${responsiveBreakpoints.narrowActions}px)`,
  dataCards: `(max-width: ${responsiveBreakpoints.dataCards}px)`,
  appShell: `(max-width: ${responsiveBreakpoints.appShell}px)`,
  managementCards: `(max-width: ${responsiveBreakpoints.managementCards}px)`,
  policyManagementCards: `(max-width: ${responsiveBreakpoints.policyManagementCards}px)`,
  reducedMotion: "(prefers-reduced-motion: reduce)",
} as const;

export function useCompactBreakpoint() {
  return useMediaQuery(responsiveMediaQueries.compact);
}

export function useDataCardsBreakpoint() {
  return useBreakpoints(responsiveBreakpoints).smallerOrEqual("dataCards");
}

export function useManagementCardsBreakpoint() {
  return useBreakpoints(responsiveBreakpoints).smallerOrEqual("managementCards");
}

export function usePolicyManagementCardsBreakpoint() {
  return useBreakpoints(responsiveBreakpoints).smallerOrEqual("policyManagementCards");
}

export function prefersReducedMotion(): boolean {
  return (
    typeof window !== "undefined" &&
    typeof window.matchMedia === "function" &&
    window.matchMedia(responsiveMediaQueries.reducedMotion).matches
  );
}
