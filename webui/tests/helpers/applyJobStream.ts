import { vi } from "vitest";

import { webApi } from "../../src/api/client";
import { applyJobLogResponse, applyJobResponse } from "./fixtures";

export function mockApplyJobStream() {
  const close = vi.fn();
  let jobListener: ((event: MessageEvent<string>) => void) | null = null;
  let logListener: ((event: MessageEvent<string>) => void) | null = null;
  let progressListener: ((event: MessageEvent<string>) => void) | null = null;
  vi.spyOn(webApi, "openJobStream").mockReturnValue({
    addEventListener: vi.fn((type: string, listener: EventListener) => {
      if (type === "job") {
        jobListener = listener as (event: MessageEvent<string>) => void;
      }
      if (type === "log") {
        logListener = listener as (event: MessageEvent<string>) => void;
      }
      if (type === "progress") {
        progressListener = listener as (event: MessageEvent<string>) => void;
      }
    }),
    close,
    onerror: null,
    onmessage: null,
    onopen: null,
    readyState: 1,
    url: "",
    withCredentials: true,
    CONNECTING: 0,
    OPEN: 1,
    CLOSED: 2,
    dispatchEvent: vi.fn(),
    removeEventListener: vi.fn(),
  } as unknown as EventSource);

  function emitJobData(data: string): void {
    jobListener?.(new MessageEvent("job", { data }));
  }

  function emitLogData(data: string): void {
    logListener?.(new MessageEvent("log", { data }));
  }

  function emitProgressData(data: string): void {
    progressListener?.(new MessageEvent("progress", { data }));
  }

  return {
    close,
    emitJob(job: ReturnType<typeof applyJobResponse>): void {
      emitJobData(JSON.stringify(job));
    },
    emitJobData,
    emitLog(log: ReturnType<typeof applyJobLogResponse>): void {
      emitLogData(JSON.stringify(log));
    },
    emitLogData,
    emitProgress(
      progress: ReturnType<typeof applyJobResponse>["progress"][number],
    ): void {
      emitProgressData(JSON.stringify(progress));
    },
    emitProgressData,
    emitInvalidLog(): void {
      emitLogData("{");
    },
    get observed(): boolean {
      return (
        jobListener !== null &&
        logListener !== null &&
        progressListener !== null
      );
    },
  };
}
