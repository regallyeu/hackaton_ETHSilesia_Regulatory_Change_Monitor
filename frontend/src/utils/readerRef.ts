const LS_KEY = 'rcm-compliance-reader-ref'

/**
 * Stable pseudonymous id for audit trails (read receipts). Not authentication.
 */
export function getComplianceReaderRef(): string {
  try {
    let v = localStorage.getItem(LS_KEY)
    if (!v) {
      v = typeof crypto !== 'undefined' && crypto.randomUUID ? crypto.randomUUID() : `anon-${Date.now()}`
      localStorage.setItem(LS_KEY, v)
    }
    return v
  } catch {
    return 'anonymous'
  }
}
