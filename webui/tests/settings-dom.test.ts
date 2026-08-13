import { afterEach, describe, expect, it, vi } from "vitest";

import {
  scrollToElementId,
  syncSettingsSelectLoadingState,
} from "../src/views/settings/settingsDom";

describe("settings DOM helpers", () => {
  afterEach(() => {
    document.body.replaceChildren();
  });

  it("moves focus to the destination heading after scrolling", () => {
    const target = document.createElement("section");
    target.id = "settings-preferences";
    target.innerHTML = "<h2>Preferences</h2>";
    target.scrollIntoView = vi.fn();
    document.body.append(target);

    scrollToElementId(target.id);

    const heading = target.querySelector("h2")!;
    expect(target.scrollIntoView).toHaveBeenCalledWith({
      behavior: "smooth",
      block: "start",
    });
    expect(heading.tabIndex).toBe(-1);
    expect(document.activeElement).toBe(heading);
  });

  it("hides idle select loading labels without hiding active loading state", () => {
    const select = document.createElement("div");
    select.innerHTML = `
      <div class="n-base-loading" role="img" aria-label="loading">
        <div class="n-base-loading__placeholder"></div>
      </div>
    `;
    const loadingIndicator = select.querySelector<HTMLElement>(".n-base-loading")!;

    syncSettingsSelectLoadingState(select);
    expect(loadingIndicator.hasAttribute("aria-hidden")).toBe(true);

    loadingIndicator.innerHTML = '<div class="n-base-loading__transition-wrapper"></div>';
    syncSettingsSelectLoadingState(select);
    expect(loadingIndicator.hasAttribute("aria-hidden")).toBe(false);
  });
});
