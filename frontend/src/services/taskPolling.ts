/** Sequential, cancellable polling. A failed status request is not a failed task. */
export const isTaskTerminal = (status: string) => ['completed', 'failed', 'cancelled', 'interrupted'].includes(status)

export function pollTask<T extends { status: string }>({ query, onUpdate, onRetry, intervalMs = 1500 }: {
  query: () => Promise<T>
  onUpdate: (value: T) => void
  onRetry?: (error: unknown, failures: number) => void
  intervalMs?: number
}): () => void {
  let stopped = false
  let timer: ReturnType<typeof setTimeout> | undefined
  let failures = 0
  const tick = async () => {
    let delay = intervalMs
    try {
      const value = await query()
      if (stopped) return
      failures = 0
      onUpdate(value)
      if (isTaskTerminal(value.status)) return
    } catch (error) {
      if (stopped) return
      failures += 1
      onRetry?.(error, failures)
      delay = Math.min(intervalMs * 2 ** Math.min(failures, 4), 15000)
    }
    if (!stopped) timer = setTimeout(tick, delay)
  }
  void tick()
  return () => { stopped = true; clearTimeout(timer) }
}
