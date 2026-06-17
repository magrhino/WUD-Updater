export function runInBackground(promise: Promise<unknown>): void {
  promise.catch(() => undefined);
}
