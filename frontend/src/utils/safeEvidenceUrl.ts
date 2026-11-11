export const safeEvidenceUrl = (value?: string) => {
  try { const url = new URL(value || ''); return ['http:', 'https:'].includes(url.protocol) ? url.href : undefined } catch { return undefined }
}
