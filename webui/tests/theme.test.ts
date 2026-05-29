import { describe, expect, it } from "vitest";

import { applyThemeCssVars, designTokens, themeOverrides } from "../src/theme";

describe("webui theme tokens", () => {
  it("maps design tokens to CSS variables and Naive UI overrides", () => {
    const root = document.createElement("div");

    applyThemeCssVars(root);

    expect(root.style.getPropertyValue("--color-operational-teal")).toBe(
      designTokens.color.operationalTeal,
    );
    expect(root.style.getPropertyValue("--color-table-head")).toBe(
      designTokens.color.tableHead,
    );
    expect(themeOverrides.common?.primaryColor).toBe(
      designTokens.color.operationalTeal,
    );
    expect(themeOverrides.common?.tableHeaderColor).toBe(
      designTokens.color.tableHead,
    );
  });
});
