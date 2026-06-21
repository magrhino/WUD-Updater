import { describe, expect, it, vi } from "vitest";

import { fetchReleaseChangelog } from "../src/utils/releaseChangelog";

function textResponse(body: string, init: ResponseInit = {}): Response {
  return new Response(body, init);
}

function streamlessTextResponse(body: string, init: ResponseInit = {}): Response {
  const status = init.status ?? 200;
  return {
    ok: status >= 200 && status < 300,
    status,
    headers: new Headers(init.headers),
    body: null,
    text: vi.fn().mockResolvedValue(body),
  } as unknown as Response;
}

describe("release changelog fetching", () => {
  it("returns unavailable when the release body has no changelog link", async () => {
    const fetchMock = vi.fn().mockResolvedValueOnce(
      textResponse(JSON.stringify({ body: "No changelog here." })),
    );

    await expect(
      fetchReleaseChangelog(
        "https://github.com/t-mart/mousehole/releases/tag/v0.5.0",
        "v0.5.0",
        { fetch: fetchMock },
      ),
    ).resolves.toMatchObject({
      status: "unavailable",
      error: "No changelog link found in the GitHub release body.",
    });
  });

  it("returns unavailable when the changelog has no matching tag section", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(
        textResponse(
          JSON.stringify({
            body: "[changelog](https://github.com/t-mart/mousehole/blob/master/CHANGELOG.md)",
          }),
        ),
      )
      .mockResolvedValueOnce(textResponse("# Changelog\n\n## [v0.4.0]\n\n- Old"));

    await expect(
      fetchReleaseChangelog(
        "https://github.com/t-mart/mousehole/releases/tag/v0.5.0",
        "v0.5.0",
        { fetch: fetchMock },
      ),
    ).resolves.toMatchObject({
      status: "unavailable",
      error: "No changelog section found for v0.5.0.",
    });
  });

  it("falls back to text responses when streams are unavailable", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(
        streamlessTextResponse(
          JSON.stringify({
            body: "[changelog](https://github.com/t-mart/mousehole/blob/master/CHANGELOG.md)",
          }),
        ),
      )
      .mockResolvedValueOnce(
        streamlessTextResponse(
          [
            "# Changelog",
            "",
            "## [v0.5.0](https://github.com/t-mart/mousehole/releases/tag/v0.5.0)",
            "",
            "- Streamless response body",
            "",
            "## [v0.4.0]",
            "",
            "- Older release",
          ].join("\n"),
        ),
      );

    await expect(
      fetchReleaseChangelog(
        "https://github.com/t-mart/mousehole/releases/tag/v0.5.0",
        "v0.5.0",
        { fetch: fetchMock },
      ),
    ).resolves.toMatchObject({
      status: "ready",
      body: expect.stringContaining("Streamless response body"),
    });
  });

  it("rejects oversized and failed fetches", async () => {
    const oversizedFetch = vi.fn().mockResolvedValueOnce(
      textResponse("{}", { headers: { "content-length": "20" } }),
    );
    await expect(
      fetchReleaseChangelog(
        "https://github.com/t-mart/mousehole/releases/tag/v0.5.0",
        "v0.5.0",
        { fetch: oversizedFetch, maxBytes: 10 },
      ),
    ).rejects.toThrow("GitHub release response is too large.");

    const oversizedBodyFetch = vi.fn().mockResolvedValueOnce(textResponse("{}"));
    await expect(
      fetchReleaseChangelog(
        "https://github.com/t-mart/mousehole/releases/tag/v0.5.0",
        "v0.5.0",
        { fetch: oversizedBodyFetch, maxBytes: 1 },
      ),
    ).rejects.toThrow("GitHub release response is too large.");

    const oversizedStreamlessFetch = vi
      .fn()
      .mockResolvedValueOnce(streamlessTextResponse("{}"));
    await expect(
      fetchReleaseChangelog(
        "https://github.com/t-mart/mousehole/releases/tag/v0.5.0",
        "v0.5.0",
        { fetch: oversizedStreamlessFetch, maxBytes: 1 },
      ),
    ).rejects.toThrow("GitHub release response is too large.");

    const failedStatusFetch = vi
      .fn()
      .mockResolvedValueOnce(textResponse("Not found", { status: 404 }));
    await expect(
      fetchReleaseChangelog(
        "https://github.com/t-mart/mousehole/releases/tag/v0.5.0",
        "v0.5.0",
        { fetch: failedStatusFetch },
      ),
    ).rejects.toThrow("Could not fetch GitHub release (404).");

    const failedFetch = vi.fn().mockRejectedValueOnce(new Error("network failed"));
    await expect(
      fetchReleaseChangelog(
        "https://github.com/t-mart/mousehole/releases/tag/v0.5.0",
        "v0.5.0",
        { fetch: failedFetch },
      ),
    ).rejects.toThrow("network failed");
  });

  it("aborts streamed fetches when the cumulative body limit is exceeded", async () => {
    let signal: AbortSignal | undefined;
    const fetchMock = vi.fn(async (_input: string, init?: RequestInit) => {
      signal = init?.signal ?? undefined;
      const chunks = [Uint8Array.of(123), Uint8Array.of(125)];
      return new Response(
        new ReadableStream<Uint8Array>({
          pull(controller) {
            const chunk = chunks.shift();
            if (chunk) {
              controller.enqueue(chunk);
              return;
            }
            controller.close();
          },
        }),
      );
    });

    await expect(
      fetchReleaseChangelog(
        "https://github.com/t-mart/mousehole/releases/tag/v0.5.0",
        "v0.5.0",
        { fetch: fetchMock, maxBytes: 1 },
      ),
    ).rejects.toThrow("GitHub release response is too large.");

    expect(signal?.aborted).toBe(true);
  });
});
