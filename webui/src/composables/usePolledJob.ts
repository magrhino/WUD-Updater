import { shallowRef, ref } from "vue";

export type PolledJobOptions = {
  intervalMs?: number;
};

export function usePolledJob<TJob>(
  start: () => Promise<TJob>,
  poll: (job: TJob) => Promise<TJob>,
  isTerminal: (job: TJob) => boolean,
  options: PolledJobOptions = {},
) {
  const job = shallowRef<TJob | null>(null);
  const polling = ref(false);
  const error = ref("");
  const intervalMs = options.intervalMs ?? 500;
  let runId = 0;

  async function run(): Promise<TJob> {
    const activeRunId = ++runId;
    polling.value = true;
    error.value = "";
    try {
      let current = await start();
      if (activeRunId === runId) {
        job.value = current;
      }
      while (!isTerminal(current)) {
        await delay(intervalMs);
        if (activeRunId !== runId) {
          break;
        }
        current = await poll(current);
        if (activeRunId === runId) {
          job.value = current;
        }
      }
      return current;
    } catch (caughtError) {
      error.value =
        caughtError instanceof Error ? caughtError.message : String(caughtError);
      throw caughtError;
    } finally {
      if (activeRunId === runId) {
        polling.value = false;
      }
    }
  }

  function reset(): void {
    runId += 1;
    polling.value = false;
    error.value = "";
    job.value = null;
  }

  return {
    job,
    polling,
    error,
    run,
    reset,
  };
}

function delay(ms: number): Promise<void> {
  if (ms <= 0) {
    return Promise.resolve();
  }
  return new Promise((resolve) => {
    window.setTimeout(resolve, ms);
  });
}
