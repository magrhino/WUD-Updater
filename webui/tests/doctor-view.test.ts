import { createPinia, setActivePinia } from "pinia";
import { flushPromises } from "@vue/test-utils";
import { beforeEach, describe, expect, it, vi } from "vitest";

import DoctorView from "../src/views/DoctorView.vue";
import { doctorResponse } from "./helpers/fixtures";
import { mountWithApp } from "./helpers/mount";
import { setupStores } from "./helpers/viewSecurity";

describe("doctor view", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
  });

  it("renders doctor results with redacted details and copyable suggestions", async () => {
    const { pinia, connection } = setupStores(false);
    connection.doctor = doctorResponse({
      checks: [
        {
          status: "FAIL",
          code: "docker-daemon-info",
          category: "docker",
          name: "Docker daemon info",
          detail: "exit 17: info failed: <redacted>",
          target: "",
          suggestions: [
            {
              label: "Wire Docker access",
              description: "Mount the Docker socket or configure DOCKER_HOST.",
              snippet: "DOCKER_HOST=unix:///var/run/docker.sock",
            },
          ],
        },
      ],
    });
    vi.spyOn(connection, "loadDoctor").mockResolvedValue();

    const wrapper = mountWithApp(DoctorView, { pinia });
    await flushPromises();
    const text = wrapper.text();

    expect(text).toContain("Doctor results");
    expect(text).toContain("Docker daemon info");
    expect(text).toContain("exit 17: info failed: <redacted>");
    expect(text).toContain("Wire Docker access");
    expect(text).toContain("Copy");
    expect(text).not.toContain("github-token-secret");
  });
});
