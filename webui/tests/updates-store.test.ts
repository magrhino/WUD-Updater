import { createPinia, setActivePinia } from "pinia";
import { flushPromises } from "@vue/test-utils";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { webApi } from "../src/api/client";
import { useAuthStore } from "../src/stores/auth";
import { useConnectionStore } from "../src/stores/connection";
import { useSettingsStore } from "../src/stores/settings";
import { useUpdatesStore, APPLY_JOB_RECOVERY_MESSAGE } from "../src/stores/updates";
import { useRunsStore } from "../src/stores/runs";
import {
  jsonRequestBody,
  jsonResponse,
  mockFetch,
} from "./helpers/storeActions";
import {
  applyJobLogResponse,
  applyJobResponse,
  pendingItem,
  pendingResponse,
  pendingRescanResponse,
  wudApiStatus,
  wudContainerMetadata,
  releaseNoteInfo,
  releaseNotesResponse,
  retagPlanResponse,
  retagPreviewJobResponse,
  retagTarget,
  retagTargetsResponse,
  planResponse,
  selfUpdateApplyResponse,
  selfUpdatePlanResponse,
  selfUpdatePrepareResponse,
  selfUpdateResponse,
  updateTargetsResponse,
} from "./helpers/fixtures";

const TEST_RELEASE_TAG = "v0.5.0";
const TEST_RELEASE_URL =
  "https://github.com/t-mart/mousehole/releases/tag/v0.5.0";
const TEST_CHANGELOG_URL =
  "https://raw.githubusercontent.com/t-mart/mousehole/master/CHANGELOG.md";
const TEST_CHANGELOG_LINK =
  "[changelog](https://github.com/t-mart/mousehole/blob/master/CHANGELOG.md)";

function githubReleaseNote() {
  return releaseNoteInfo({
    release_tag: TEST_RELEASE_TAG,
    links: [
      {
        label: "GitHub release",
        url: TEST_RELEASE_URL,
        kind: "github_release",
      },
    ],
  });
}

function releaseChangelogMarkdown(entry: string, includeOlder = false): string {
  const lines = [
    "# Changelog",
    "",
    `## [${TEST_RELEASE_TAG}](${TEST_RELEASE_URL}) - 2026-06-20`,
    "",
    entry,
  ];
  if (includeOlder) {
    lines.push(
      "",
      "## [v0.4.0](https://github.com/t-mart/mousehole/releases/tag/v0.4.0) - 2026-06-04",
      "",
      "- Older release",
    );
  }
  return lines.join("\n");
}

function mockReleaseChangelogFetch(entry: string, includeOlder = false) {
  const fetchMock = vi
    .fn()
    .mockResolvedValueOnce(jsonResponse({ body: TEST_CHANGELOG_LINK }))
    .mockResolvedValueOnce(
      new Response(releaseChangelogMarkdown(entry, includeOlder)),
    );
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

function expectReleaseChangelogFetches(fetchMock: ReturnType<typeof vi.fn>): void {
  expect(fetchMock.mock.calls).toHaveLength(2);
  expect(fetchMock.mock.calls[0][0]).toBe(
    "https://api.github.com/repos/t-mart/mousehole/releases/tags/v0.5.0",
  );
  expect(fetchMock.mock.calls[1][0]).toBe(TEST_CHANGELOG_URL);
}

describe("updates store", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
  });

  it("passes csrf from auth store to plan creation", async () => {
    const fetchMock = mockFetch(planResponse());
    const auth = useAuthStore();
    const ensureCsrf = vi.spyOn(auth, "ensureCsrf").mockResolvedValue("csrf-plan");
    useConnectionStore();
    useSettingsStore();
    const updates = useUpdatesStore();
    useRunsStore();

    await updates.createPlan([1], true, [{ line_no: 1, tag: "1.1" }]);

    expect(ensureCsrf).toHaveBeenCalledTimes(1);
    expect(updates.plan?.plan_id).toBe("plan-test");
    expect(
      ((fetchMock.mock.calls[0][1] as RequestInit).headers as Headers).get(
        "x-wud-csrf-token",
      ),
    ).toBe("csrf-plan");
  });

  it("passes csrf from auth store to pending cleanup", async () => {
    const fetchMock = mockFetch({
      status: "success",
      audit_run_id: 12,
      removed_count: 1,
      removed: [
        {
          line_no: 3,
          raw: "repo/old:latest",
          image: "repo/old:latest",
          reason: "unmatched",
        },
      ],
    });
    const auth = useAuthStore();
    const ensureCsrf = vi
      .spyOn(auth, "ensureCsrf")
      .mockResolvedValue("csrf-cleanup");
    useConnectionStore();
    useSettingsStore();
    const updates = useUpdatesStore();
    useRunsStore();

    await updates.cleanupPending("cleanup-test", [
      { line_no: 3, raw: "repo/old:latest" },
    ]);

    expect(ensureCsrf).toHaveBeenCalledTimes(1);
    expect(updates.pendingCleanup?.audit_run_id).toBe(12);
    expect(jsonRequestBody(fetchMock.mock.calls[0])).toEqual({
      cleanup_id: "cleanup-test",
      lines: [{ line_no: 3, raw: "repo/old:latest" }],
      confirmation: "remove_unmatched",
    });
    expect(
      ((fetchMock.mock.calls[0][1] as RequestInit).headers as Headers).get(
        "x-wud-csrf-token",
      ),
    ).toBe("csrf-cleanup");
  });

  it("preserves cleanup success while refreshing pending state when requested", async () => {
    mockFetch(pendingResponse());
    useConnectionStore();
    useSettingsStore();
    const updates = useUpdatesStore();
    useRunsStore();
    updates.pendingCleanup = {
      status: "success",
      audit_run_id: 12,
      removed_count: 1,
      removed: [
        {
          line_no: 3,
          raw: "repo/old:latest",
          image: "repo/old:latest",
          reason: "unmatched",
        },
      ],
    };

    await updates.loadPending({ preserveCleanup: true });

    expect(updates.pendingCleanup?.audit_run_id).toBe(12);

    await updates.loadPending();

    expect(updates.pendingCleanup).toBeNull();
  });

  it("rescans pending updates and refreshes dependent state", async () => {
    const fetchMock = vi.fn((input: RequestInfo | URL) => {
      const url = String(input);
      if (url === "/api/v1/pending/rescan") {
        return Promise.resolve(jsonResponse(pendingRescanResponse()));
      }
      if (url === "/api/v1/pending") {
        return Promise.resolve(jsonResponse(pendingResponse()));
      }
      if (
        url === "/api/v1/release-notes" ||
        url === "/api/v1/release-notes/refresh"
      ) {
        return Promise.resolve(jsonResponse(releaseNotesResponse()));
      }
      if (url === "/api/v1/runs") {
        return Promise.resolve(jsonResponse([]));
      }
      return Promise.resolve(jsonResponse({}));
    });
    vi.stubGlobal("fetch", fetchMock);
    const auth = useAuthStore();
    const ensureCsrf = vi
      .spyOn(auth, "ensureCsrf")
      .mockResolvedValue("csrf-rescan");
    useConnectionStore();
    useSettingsStore();
    const updates = useUpdatesStore();
    useRunsStore();
    updates.pending = pendingResponse([
      pendingItem({ wud_metadata: wudContainerMetadata() }),
    ]);

    const response = await updates.rescanPending("selected", [1]);

    expect(ensureCsrf).toHaveBeenCalledTimes(2);
    expect(response.audit_run_id).toBe(24);
    expect(updates.pendingRescan?.audit_run_id).toBe(24);
    expect(updates.pending?.count).toBe(1);
    const urls = fetchMock.mock.calls.map((call) => call[0]);
    expect(urls.slice(0, 3)).toEqual([
      "/api/v1/pending/rescan",
      "/api/v1/pending",
      "/api/v1/release-notes",
    ]);
    expect(new Set(urls.slice(3))).toEqual(
      new Set(["/api/v1/release-notes/refresh", "/api/v1/runs"]),
    );
    expect(jsonRequestBody(fetchMock.mock.calls[0])).toEqual({
      confirmation: "rescan_wud",
      scope: "selected",
      line_numbers: [1],
      lines: [
        {
          line_no: 1,
          raw: "repo/app:1.0 sha256=abc",
          source_id: "file:1",
          source_hash: "pending-source-hash",
          container_id: "docker.local.app",
        },
      ],
    });
    expect(
      ((fetchMock.mock.calls[0][1] as RequestInit).headers as Headers).get(
        "x-wud-csrf-token",
      ),
    ).toBe("csrf-rescan");
  });

  it("rescans all pending updates without selected lines", async () => {
    const fetchMock = vi.fn((input: RequestInfo | URL) => {
      const url = String(input);
      if (url === "/api/v1/pending/rescan") {
        return Promise.resolve(jsonResponse(pendingRescanResponse()));
      }
      if (url === "/api/v1/pending") {
        return Promise.resolve(jsonResponse(pendingResponse()));
      }
      if (
        url === "/api/v1/release-notes" ||
        url === "/api/v1/release-notes/refresh"
      ) {
        return Promise.resolve(jsonResponse(releaseNotesResponse()));
      }
      if (url === "/api/v1/runs") {
        return Promise.resolve(jsonResponse([]));
      }
      return Promise.resolve(jsonResponse({}));
    });
    vi.stubGlobal("fetch", fetchMock);
    const auth = useAuthStore();
    vi.spyOn(auth, "ensureCsrf").mockResolvedValue("csrf-rescan-all");
    useConnectionStore();
    useSettingsStore();
    const updates = useUpdatesStore();
    useRunsStore();
    updates.pending = pendingResponse([
      pendingItem({ wud_metadata: wudContainerMetadata() }),
    ]);

    const response = await updates.rescanPending("all");

    expect(response.scope).toBe("all");
    expect(updates.pendingRescan?.scope).toBe("all");
    expect(updates.pending?.count).toBe(1);
    expect(jsonRequestBody(fetchMock.mock.calls[0])).toEqual({
      confirmation: "rescan_wud",
      scope: "all",
      line_numbers: [],
      lines: [],
    });
    const urls = fetchMock.mock.calls.map((call) => call[0]);
    expect(urls.slice(0, 3)).toEqual([
      "/api/v1/pending/rescan",
      "/api/v1/pending",
      "/api/v1/release-notes",
    ]);
    expect(new Set(urls.slice(3))).toEqual(
      new Set(["/api/v1/release-notes/refresh", "/api/v1/runs"]),
    );
  });

  it("rejects selected pending rescans without selected lines before requesting csrf", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    const auth = useAuthStore();
    const ensureCsrf = vi.spyOn(auth, "ensureCsrf").mockResolvedValue("csrf");
    const updates = useUpdatesStore();

    await expect(updates.rescanPending("selected", [])).rejects.toThrow(
      "Select at least one pending update to rescan.",
    );

    expect(ensureCsrf).not.toHaveBeenCalled();
    expect(fetchMock).not.toHaveBeenCalled();
    expect(updates.pendingRescan).toBeNull();
    expect(updates.error).toBe("Select at least one pending update to rescan.");
  });

  it("stores blocked pending rescan responses and refreshes dependent state", async () => {
    const fetchMock = vi.fn((input: RequestInfo | URL) => {
      const url = String(input);
      if (url === "/api/v1/pending/rescan") {
        return Promise.resolve(
          jsonResponse(
            pendingRescanResponse({
              status: "blocked",
              scope: "selected",
              requested_count: 1,
              watched_count: 0,
              wud_api: wudApiStatus({
                state: "auth_required",
                metadata_available: false,
              }),
            }),
          ),
        );
      }
      if (url === "/api/v1/pending") {
        return Promise.resolve(jsonResponse(pendingResponse()));
      }
      if (
        url === "/api/v1/release-notes" ||
        url === "/api/v1/release-notes/refresh"
      ) {
        return Promise.resolve(jsonResponse(releaseNotesResponse()));
      }
      if (url === "/api/v1/runs") {
        return Promise.resolve(jsonResponse([]));
      }
      return Promise.resolve(jsonResponse({}));
    });
    vi.stubGlobal("fetch", fetchMock);
    const auth = useAuthStore();
    vi.spyOn(auth, "ensureCsrf").mockResolvedValue("csrf-rescan-blocked");
    useConnectionStore();
    useSettingsStore();
    const updates = useUpdatesStore();
    useRunsStore();
    updates.pending = pendingResponse([
      pendingItem({ wud_metadata: wudContainerMetadata() }),
    ]);

    const response = await updates.rescanPending("selected", [1]);

    expect(response.status).toBe("blocked");
    expect(updates.pendingRescan?.status).toBe("blocked");
    expect(updates.pending?.count).toBe(1);
    const urls = fetchMock.mock.calls.map((call) => call[0]);
    expect(urls.slice(0, 3)).toEqual([
      "/api/v1/pending/rescan",
      "/api/v1/pending",
      "/api/v1/release-notes",
    ]);
    expect(new Set(urls.slice(3))).toEqual(
      new Set(["/api/v1/release-notes/refresh", "/api/v1/runs"]),
    );
  });

  it("skips dependent refreshes when pending rescan fails", async () => {
    const fetchMock = vi.fn((input: RequestInfo | URL) => {
      const url = String(input);
      if (url === "/api/v1/pending/rescan") {
        return Promise.resolve(jsonResponse({ detail: "WUD rescan failed" }, 503));
      }
      return Promise.resolve(jsonResponse({}));
    });
    vi.stubGlobal("fetch", fetchMock);
    const auth = useAuthStore();
    vi.spyOn(auth, "ensureCsrf").mockResolvedValue("csrf-rescan-error");
    useConnectionStore();
    useSettingsStore();
    const updates = useUpdatesStore();
    useRunsStore();
    updates.pending = pendingResponse([
      pendingItem({ line_no: 9, source_id: "file:9" }),
    ]);

    await expect(updates.rescanPending("selected", [9])).rejects.toThrow(
      "WUD rescan failed",
    );

    expect(updates.pendingRescan).toBeNull();
    expect(updates.pending?.items[0]?.line_no).toBe(9);
    expect(updates.error).toBe("WUD rescan failed");
    expect(fetchMock.mock.calls.map((call) => call[0])).toEqual([
      "/api/v1/pending/rescan",
    ]);
  });

  it("loads update targets for management selectors", async () => {
    const fetchMock = mockFetch(updateTargetsResponse());
    const updates = useUpdatesStore();

    await updates.loadUpdateTargets();

    expect(updates.updateTargets?.items[0]?.service_key).toBe("media/app");
    expect(fetchMock.mock.calls[0][0]).toBe("/api/v1/update-targets");
  });

  it("loads retag targets for read-only review", async () => {
    const fetchMock = mockFetch(retagTargetsResponse());
    const updates = useUpdatesStore();

    await updates.loadRetagTargets();

    expect(updates.retagTargets?.items[0]?.service_key).toBe("media/app");
    expect(updates.retagTargetTags["media/app"]).toBe("1.1");
    expect(fetchMock.mock.calls[0][0]).toBe("/api/v1/retag-targets");
  });

  it("refreshes retag GitHub latest fallback candidates", async () => {
    const fetchMock = mockFetch(retagTargetsResponse([
      retagTarget({
        candidate_source: "github-latest",
        candidate_warning: "GitHub latest fallback will update latest tracking to v1.1.",
        candidate_link_label: "GitHub release",
        candidate_link_url: "https://github.com/acme/app/releases/tag/v1.1",
      }),
    ]));
    const auth = useAuthStore();
    vi.spyOn(auth, "ensureCsrf").mockResolvedValue("csrf-retag");
    const updates = useUpdatesStore();

    await updates.setRetagGithubLatestFallback(true);

    expect(updates.retagGithubLatestFallback).toBe(true);
    expect(updates.retagTargets?.items[0]?.candidate_source).toBe("github-latest");
    expect(fetchMock.mock.calls[0][0]).toBe(
      "/api/v1/retag-targets/github-latest/refresh",
    );
  });

  it("previews retag choices through the updates store", async () => {
    vi.useFakeTimers();
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(
        jsonResponse(
          retagPreviewJobResponse({
            status: "queued",
            plan: null,
            warnings: [],
            progress: [
              {
                job_id: "retag-preview-test",
                phase: "refresh",
                status: "running",
                message: "Refreshing retag candidates.",
                created_at: "2026-01-02T00:00:00Z",
                stack: "",
                services: [],
                line_numbers: [],
              },
            ],
          }),
        ),
      )
      .mockResolvedValueOnce(jsonResponse(retagPreviewJobResponse()));
    vi.stubGlobal("fetch", fetchMock);
    const auth = useAuthStore();
    const ensureCsrf = vi.spyOn(auth, "ensureCsrf").mockResolvedValue("csrf-retag");
    const updates = useUpdatesStore();
    updates.retagTargets = retagTargetsResponse([
      retagTarget(),
      retagTarget({ service_key: "media/radarr", service: "radarr" }),
    ]);
    updates.setRetagChoice("media/app", "switch-to-concrete");

    try {
      const planPromise = updates.createRetagPlan();
      await flushPromises();
      await vi.advanceTimersByTimeAsync(400);
      const plan = await planPromise;

      expect(ensureCsrf).toHaveBeenCalledTimes(1);
      expect(plan.plan_id).toBe("retag-plan-test");
      expect(updates.retagPlan?.selected_count).toBe(1);
      expect(updates.retagPreviewJob?.status).toBe("success");
      expect(fetchMock.mock.calls[0][0]).toBe("/api/v1/retag-plans/preview");
      expect(fetchMock.mock.calls[1][0]).toBe(
        "/api/v1/retag-plans/preview/retag-preview-test",
      );
      expect(jsonRequestBody(fetchMock.mock.calls[0])).toEqual({
        choices: [
          { service_key: "media/app", choice: "switch-to-concrete" },
          { service_key: "media/radarr", choice: "keep-current" },
        ],
        github_latest_fallback: false,
      });
    } finally {
      vi.useRealTimers();
    }
  });

  it("sends retag fallback state when previewing", async () => {
    const fetchMock = mockFetch(retagPreviewJobResponse());
    const auth = useAuthStore();
    vi.spyOn(auth, "ensureCsrf").mockResolvedValue("csrf-retag");
    const updates = useUpdatesStore();
    updates.retagGithubLatestFallback = true;
    updates.retagTargets = retagTargetsResponse();
    updates.setRetagChoice("media/app", "switch-to-concrete");

    await updates.createRetagPlan();

    expect(jsonRequestBody(fetchMock.mock.calls[0])).toEqual({
      choices: [{ service_key: "media/app", choice: "switch-to-concrete" }],
      github_latest_fallback: true,
    });
  });

  it("falls back to keep-current for stale ineligible retag choices", async () => {
    const fetchMock = mockFetch(retagPreviewJobResponse());
    const auth = useAuthStore();
    vi.spyOn(auth, "ensureCsrf").mockResolvedValue("csrf-retag");
    const updates = useUpdatesStore();
    updates.retagTargets = retagTargetsResponse([
      retagTarget({
        proposed_tag: "",
        retag_available: false,
        retag_reason: "missing-provenance",
        choices: ["keep-current"],
        digest_provenance: null,
      }),
    ]);

    updates.setRetagChoice("media/app", "switch-to-concrete");
    expect(updates.retagChoices["media/app"]).toBe("keep-current");

    updates.retagChoices = { "media/app": "switch-to-concrete" };
    await updates.createRetagPlan();

    expect(jsonRequestBody(fetchMock.mock.calls[0])).toEqual({
      choices: [{ service_key: "media/app", choice: "keep-current" }],
      github_latest_fallback: false,
    });
  });

  it("sends manual retag target tags for fallback rows", async () => {
    const fetchMock = mockFetch(retagPreviewJobResponse());
    const auth = useAuthStore();
    vi.spyOn(auth, "ensureCsrf").mockResolvedValue("csrf-retag");
    const updates = useUpdatesStore();
    updates.retagTargets = retagTargetsResponse([
      retagTarget({
        service_key: "media/radarr",
        service: "radarr",
        image: "repo/radarr:5.21.1",
        image_repo: "repo/radarr",
        current_tag: "5.21.1",
        tracking_tag: "5.21.1",
        tracking_tag_source: "image",
        proposed_tag: "",
        final_image: "",
        retag_available: false,
        retag_reason: "not-latest-tracking",
        choices: ["keep-current"],
        digest_provenance: null,
      }),
    ]);

    updates.setRetagTargetTag("media/radarr", "5.22.4");
    await updates.createRetagPlan();

    expect(jsonRequestBody(fetchMock.mock.calls[0])).toEqual({
      choices: [
        {
          service_key: "media/radarr",
          choice: "switch-to-concrete",
          target_tag: "5.22.4",
        },
      ],
      github_latest_fallback: false,
    });
  });

  it("uses edited automatch target tags as manual overrides", async () => {
    const fetchMock = mockFetch(retagPreviewJobResponse());
    const auth = useAuthStore();
    vi.spyOn(auth, "ensureCsrf").mockResolvedValue("csrf-retag");
    const updates = useUpdatesStore();
    updates.retagTargets = retagTargetsResponse();

    updates.setRetagTargetTag("media/app", "1.2");
    await updates.createRetagPlan();

    expect(jsonRequestBody(fetchMock.mock.calls[0])).toEqual({
      choices: [
        {
          service_key: "media/app",
          choice: "switch-to-concrete",
          target_tag: "1.2",
        },
      ],
      github_latest_fallback: false,
    });
  });

  it("clears blank automatch overrides back to the proposed tag", async () => {
    const fetchMock = mockFetch(retagPreviewJobResponse());
    const auth = useAuthStore();
    vi.spyOn(auth, "ensureCsrf").mockResolvedValue("csrf-retag");
    const updates = useUpdatesStore();
    updates.retagTargets = retagTargetsResponse();

    updates.setRetagChoice("media/app", "switch-to-concrete");
    updates.setRetagTargetTag("media/app", "1.2");
    updates.setRetagTargetTag("media/app", "   ");
    await updates.createRetagPlan();

    expect(jsonRequestBody(fetchMock.mock.calls[0])).toEqual({
      choices: [{ service_key: "media/app", choice: "switch-to-concrete" }],
      github_latest_fallback: false,
    });
  });

  it("applies a retag plan as a tracked apply job", async () => {
    const fetchMock = mockFetch(applyJobResponse({ job_id: "retag-job" }));
    const auth = useAuthStore();
    const ensureCsrf = vi.spyOn(auth, "ensureCsrf").mockResolvedValue("csrf-retag");
    const updates = useUpdatesStore();
    updates.retagTargets = retagTargetsResponse();
    updates.retagChoices = { "media/app": "switch-to-concrete" };
    updates.retagPlan = retagPlanResponse();

    const job = await updates.applyRetagPlan();

    expect(ensureCsrf).toHaveBeenCalledTimes(1);
    expect(job.job_id).toBe("retag-job");
    expect(updates.applyJob?.job_id).toBe("retag-job");
    expect(fetchMock.mock.calls[0][0]).toBe("/api/v1/retag-plans/apply");
    expect(jsonRequestBody(fetchMock.mock.calls[0])).toEqual({
      plan_id: "retag-plan-test",
      choices: [{ service_key: "media/app", choice: "switch-to-concrete" }],
      github_latest_fallback: false,
      confirmation: "apply-retags",
    });
  });

  it("surfaces retag target loading errors", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(jsonResponse({ detail: "retag targets unavailable" }, 503));
    vi.stubGlobal("fetch", fetchMock);
    const updates = useUpdatesStore();

    await expect(updates.loadRetagTargets()).rejects.toThrow(
      "retag targets unavailable",
    );

    expect(updates.error).toBe("retag targets unavailable");
  });

  it("passes csrf from auth store to release-note refresh", async () => {
    const fetchMock = mockFetch(releaseNotesResponse());
    const auth = useAuthStore();
    const ensureCsrf = vi.spyOn(auth, "ensureCsrf").mockResolvedValue("csrf-notes");
    useConnectionStore();
    useSettingsStore();
    const updates = useUpdatesStore();
    useRunsStore();

    await updates.refreshReleaseNotes();

    expect(ensureCsrf).toHaveBeenCalledTimes(1);
    expect(updates.releaseNotes?.items[0].release_tag).toBe("v2.0.0");
    expect(fetchMock.mock.calls[0][0]).toBe("/api/v1/release-notes/refresh");
    expect(
      ((fetchMock.mock.calls[0][1] as RequestInit).headers as Headers).get(
        "x-wud-csrf-token",
      ),
    ).toBe("csrf-notes");
  });

  it("loads self-update status for the shell banner", async () => {
    const fetchMock = mockFetch(selfUpdateResponse());
    useConnectionStore();
    useSettingsStore();
    const updates = useUpdatesStore();
    useRunsStore();

    await updates.loadSelfUpdate();

    expect(fetchMock.mock.calls[0][0]).toBe("/api/v1/self-update");
    expect(updates.selfUpdate?.latest_tag).toBe("v0.25.0");
  });

  it("loads self-update tag prepare plan", async () => {
    const fetchMock = mockFetch(selfUpdatePlanResponse());
    const auth = useAuthStore();
    const ensureCsrf = vi.spyOn(auth, "ensureCsrf").mockResolvedValue("csrf-plan");
    useConnectionStore();
    useSettingsStore();
    const updates = useUpdatesStore();
    useRunsStore();

    const response = await updates.planSelfUpdate();

    expect(ensureCsrf).toHaveBeenCalledTimes(1);
    expect(fetchMock.mock.calls[0][0]).toBe("/api/v1/self-update/plan");
    expect(updates.selfUpdatePlan?.plan.plan_id).toBe("self-update-plan-test");
    expect(response.external_recreate_required).toBe(true);
    expect(
      ((fetchMock.mock.calls[0][1] as RequestInit).headers as Headers).get(
        "x-wud-csrf-token",
      ),
    ).toBe("csrf-plan");
  });

  it("passes csrf from auth store to self-update apply", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse(selfUpdateApplyResponse()))
      .mockResolvedValueOnce(jsonResponse(selfUpdateResponse()));
    vi.stubGlobal("fetch", fetchMock);
    const auth = useAuthStore();
    const ensureCsrf = vi
      .spyOn(auth, "ensureCsrf")
      .mockResolvedValue("csrf-self-update");
    useConnectionStore();
    useSettingsStore();
    const updates = useUpdatesStore();
    useRunsStore();
    updates.selfUpdate = selfUpdateResponse();

    const response = await updates.applySelfUpdate();

    expect(ensureCsrf).toHaveBeenCalledTimes(1);
    expect(response.container).toBe("wudup");
    expect(updates.selfUpdateMessage).toBe(
      "Image pulled. Recreate the WUDup container to run the new version. Tagged deployments are recommended for predictable updates.",
    );
    expect(fetchMock.mock.calls[0][0]).toBe("/api/v1/self-update");
    expect(jsonRequestBody(fetchMock.mock.calls[0])).toEqual({
      confirmation: "pull_image",
      current_tag: "v0.24.2",
      latest_tag: "v0.25.0",
      target_image: "ghcr.io/magrhino/wudup:latest",
      restart_container: "wudup",
    });
    expect(
      ((fetchMock.mock.calls[0][1] as RequestInit).headers as Headers).get(
        "x-wud-csrf-token",
      ),
    ).toBe("csrf-self-update");
  });

  it("prepares pinned self-update tags from cached plan", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse(selfUpdatePrepareResponse()))
      .mockResolvedValueOnce(jsonResponse(selfUpdateResponse({ strategy: "prepare_tag_update" })));
    vi.stubGlobal("fetch", fetchMock);
    const auth = useAuthStore();
    const ensureCsrf = vi
      .spyOn(auth, "ensureCsrf")
      .mockResolvedValue("csrf-self-update");
    useConnectionStore();
    useSettingsStore();
    const updates = useUpdatesStore();
    useRunsStore();
    updates.selfUpdate = selfUpdateResponse({
      strategy: "prepare_tag_update",
      current_image: "ghcr.io/magrhino/wudup:v0.24.2",
      target_image: "ghcr.io/magrhino/wudup:v0.25.0",
      external_recreate_required: true,
    });
    updates.selfUpdatePlan = selfUpdatePlanResponse();

    const response = await updates.applySelfUpdate();

    expect(ensureCsrf).toHaveBeenCalledTimes(1);
    expect(response.status).toBe("tag_prepared");
    expect(updates.selfUpdateMessage).toBe(
      "Tag updated and image pulled. Recreate the WUDup container from outside the WebUI to run the new version. Tagged deployments are recommended for predictable updates.",
    );
    expect(fetchMock.mock.calls[0][0]).toBe("/api/v1/self-update/prepare");
    expect(jsonRequestBody(fetchMock.mock.calls[0])).toEqual({
      confirmation: "prepare_tag_update",
      plan_id: "self-update-plan-test",
      current_tag: "v0.24.2",
      latest_tag: "v0.25.0",
      target_image: "ghcr.io/magrhino/wudup:v0.25.0",
      restart_container: "wudup",
    });
  });

  it("requires a loaded self-update tag prepare plan before applying", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    const auth = useAuthStore();
    const ensureCsrf = vi
      .spyOn(auth, "ensureCsrf")
      .mockResolvedValue("csrf-self-update");
    useConnectionStore();
    useSettingsStore();
    const updates = useUpdatesStore();
    useRunsStore();
    updates.selfUpdate = selfUpdateResponse({
      strategy: "prepare_tag_update",
      current_image: "ghcr.io/magrhino/wudup:v0.24.2",
      target_image: "ghcr.io/magrhino/wudup:v0.25.0",
      external_recreate_required: true,
    });

    await expect(updates.applySelfUpdate()).rejects.toThrow(
      "Self-update tag update preview must be loaded before applying",
    );

    expect(ensureCsrf).not.toHaveBeenCalled();
    expect(fetchMock).not.toHaveBeenCalled();
    expect(updates.selfUpdateError).toBe(
      "Self-update tag update preview must be loaded before applying",
    );
  });

  it("remembers active apply jobs and clears terminal jobs", async () => {
    mockFetch(applyJobResponse({ job_id: "job-active", status: "running" }));
    const auth = useAuthStore();
    vi.spyOn(auth, "ensureCsrf").mockResolvedValue("csrf-job");
    useConnectionStore();
    useSettingsStore();
    const updates = useUpdatesStore();
    useRunsStore();

    await updates.createJob("plan-test", [1], false, []);

    expect(updates.rememberedApplyJobId).toBe("job-active");
    expect(globalThis.sessionStorage.getItem("applyJobId")).toBe("job-active");

    updates.setApplyJobLog(applyJobLogResponse({ job_id: "job-active" }));
    expect(updates.applyJobLog?.content).toContain("docker-update-from-wud-v2");

    updates.setApplyJob(applyJobResponse({ job_id: "job-active", status: "success" }));

    expect(updates.rememberedApplyJobId).toBe("");
    expect(globalThis.sessionStorage.getItem("applyJobId")).toBeNull();
  });

  it("applies plans through the plan apply endpoint", async () => {
    const auth = useAuthStore();
    vi.spyOn(auth, "ensureCsrf").mockResolvedValue("csrf-plan-apply");
    const applyPlan = vi
      .spyOn(webApi, "applyPlan")
      .mockResolvedValue(applyJobResponse({ job_id: "job-plan", status: "running" }));
    const createJob = vi
      .spyOn(webApi, "createJob")
      .mockRejectedValue(new Error("wrong endpoint"));
    const updates = useUpdatesStore();

    const job = await updates.applyPlan("plan-test", [1], false, [], []);

    expect(applyPlan).toHaveBeenCalledWith(
      "plan-test",
      [1],
      false,
      [],
      [],
      "csrf-plan-apply",
    );
    expect(createJob).not.toHaveBeenCalled();
    expect(job.job_id).toBe("job-plan");
    expect(updates.applyJob?.job_id).toBe("job-plan");
    expect(updates.rememberedApplyJobId).toBe("job-plan");
  });

  it("loads a terminal apply job log from the persisted run log", async () => {
    const fetchMock = mockFetch({
      run_id: 10,
      log_file: "/out/logs/run-10.log",
      exists: true,
      content: "fallback run log\n",
      truncated: false,
      max_bytes: 65_536,
    });
    useConnectionStore();
    useSettingsStore();
    const updates = useUpdatesStore();
    useRunsStore();

    const log = await updates.loadApplyJobLogFromRun(
      applyJobResponse({
        job_id: "job-terminal",
        run_id: 10,
        log_file: "/out/logs/job-terminal.log",
      }),
    );

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/v1/runs/10/log?tail_bytes=65536",
      expect.any(Object),
    );
    expect(log).toEqual({
      job_id: "job-terminal",
      log_file: "/out/logs/run-10.log",
      exists: true,
      content: "fallback run log\n",
      truncated: false,
      max_bytes: 65_536,
      error: "",
    });
    expect(updates.applyJobLog?.content).toBe("fallback run log\n");
  });

  it("marks recovery when a remembered apply job is missing", async () => {
    globalThis.sessionStorage.setItem("applyJobId", "job-lost");
    const fetchMock = vi
      .fn()
      .mockResolvedValue(jsonResponse({ detail: "apply job not found" }, 404));
    vi.stubGlobal("fetch", fetchMock);
    useConnectionStore();
    useSettingsStore();
    const updates = useUpdatesStore();
    const runs = useRunsStore();

    const job = await updates.loadApplyJob("job-lost", { recoverMissing: true });

    expect(job).toBeNull();
    expect(updates.applyJob).toBeNull();
    expect(updates.applyJobLog).toBeNull();
    expect(updates.applyJobRecovery).toBe(APPLY_JOB_RECOVERY_MESSAGE);
    expect(updates.rememberedApplyJobId).toBe("");
    expect(runs.error).toBe("");
    expect(globalThis.sessionStorage.getItem("applyJobId")).toBeNull();
  });
});

describe("connection store focused coverage", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
  });

  it("loads release notes with independent loading state", async () => {
    const fetchMock = mockFetch(releaseNotesResponse());
    const updates = useUpdatesStore();

    await updates.loadReleaseNotes();

    expect(fetchMock.mock.calls[0][0]).toBe("/api/v1/release-notes");
    expect(updates.releaseNotes?.items[0]?.release_tag).toBe("v2.0.0");
    expect(updates.releaseNotesLoading).toBe(false);
    expect(updates.releaseNotesError).toBe("");
    expect(updates.loading).toBe(false);
  });

  it("surfaces release note errors without changing main loading state", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(jsonResponse({ detail: "notes unavailable" }, 503)),
    );
    const updates = useUpdatesStore();

    await expect(updates.loadReleaseNotes()).rejects.toMatchObject({
      message: "notes unavailable",
    });

    expect(updates.releaseNotesError).toBe("notes unavailable");
    expect(updates.releaseNotesLoading).toBe(false);
    expect(updates.loading).toBe(false);
  });

  it("loads release changelogs on demand", async () => {
    const fetchMock = mockReleaseChangelogFetch(
      "- **Breaking**: Live updates use Server-Sent Events instead of WebSockets.",
      true,
    );
    const updates = useUpdatesStore();
    const note = githubReleaseNote();

    await updates.loadReleaseChangelog(note);

    const changelog = updates.releaseChangelogStateFor(note);
    expectReleaseChangelogFetches(fetchMock);
    expect(changelog.status).toBe("ready");
    expect(changelog.body).toContain("Server-Sent Events");
    expect(changelog.body).not.toContain("Older release");
  });

  it("deduplicates concurrent release changelog loads", async () => {
    const fetchMock = mockReleaseChangelogFetch("- Concurrent entry");
    const updates = useUpdatesStore();
    const note = githubReleaseNote();

    await Promise.all([
      updates.loadReleaseChangelog(note),
      updates.loadReleaseChangelog(note),
    ]);

    expect(fetchMock).toHaveBeenCalledTimes(2);
    expectReleaseChangelogFetches(fetchMock);
    expect(updates.releaseChangelogStateFor(note)).toMatchObject({
      status: "ready",
      body: expect.stringContaining("Concurrent entry"),
    });
  });

  it("short-circuits release changelog loads when ready", async () => {
    const fetchMock = mockReleaseChangelogFetch("- Cached entry");
    const updates = useUpdatesStore();
    const note = githubReleaseNote();

    await updates.loadReleaseChangelog(note);
    expect(updates.releaseChangelogStateFor(note)).toMatchObject({
      status: "ready",
      body: expect.stringContaining("Cached entry"),
    });

    await updates.loadReleaseChangelog(note);

    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("keeps changelog failures scoped to the release row", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockRejectedValueOnce(new Error("network failed")),
    );
    const updates = useUpdatesStore();
    const note = githubReleaseNote();

    await updates.loadReleaseChangelog(note);

    expect(updates.releaseChangelogStateFor(note)).toMatchObject({
      status: "error",
      error: "network failed",
    });
    expect(updates.releaseNotesError).toBe("");
  });

  it("sets stream errors through the updates store action", () => {
    const updates = useUpdatesStore();

    updates.setError("Job status stream returned invalid data.");

    expect(updates.error).toBe("Job status stream returned invalid data.");
  });
});
