import React from 'react'

/**
 * ProvenanceBadge displays the source_type and verification_state of a health
 * entity. These fields are server-owned and read-only — they are shown purely
 * for informational purposes and are never editable by the user.
 *
 * Design:
 * - source_type 'PATIENT_REPORTED' → neutral grey pill (default)
 * - source_type 'SOURCE_DOCUMENT'  → blue pill (linked to a document)
 * - verification_state badges use muted colours to distinguish state
 */

interface ProvenanceBadgeProps {
  /** The source_type returned by the API (e.g. 'PATIENT_REPORTED') */
  sourceType: string
  /** The verification_state returned by the API (e.g. 'PATIENT_REPORTED') */
  verificationState: string
  /** Optional CSS classes to apply to the wrapper. */
  className?: string
}

const SOURCE_TYPE_STYLES: Record<string, string> = {
  PATIENT_REPORTED: 'bg-gray-100 text-gray-600',
  SOURCE_DOCUMENT: 'bg-blue-100 text-blue-700',
  CLINICIAN_CONFIRMED: 'bg-green-100 text-green-700',
}

const VERIFICATION_STYLES: Record<string, string> = {
  PATIENT_REPORTED: 'bg-gray-100 text-gray-500',
  SOURCE_RECORDED: 'bg-blue-50 text-blue-600',
  CLINICIAN_CONFIRMED: 'bg-green-50 text-green-600',
  AI_DERIVED: 'bg-purple-50 text-purple-600',
  UNCERTAIN: 'bg-yellow-50 text-yellow-600',
}

/** Format a SCREAMING_SNAKE_CASE string to Title Case with spaces. */
function toLabel(value?: string): string {
  if (!value) return ''
  return value
    .toLowerCase()
    .split('_')
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(' ')
}

export const ProvenanceBadge: React.FC<ProvenanceBadgeProps> = ({
  sourceType,
  verificationState,
  className = '',
}) => {
  const stClass =
    SOURCE_TYPE_STYLES[sourceType] ?? 'bg-gray-100 text-gray-500'
  const vsClass =
    VERIFICATION_STYLES[verificationState] ?? 'bg-gray-100 text-gray-500'

  return (
    <span
      className={`inline-flex gap-1 items-center flex-wrap ${className}`}
      data-testid="provenance-badge"
    >
      <span
        className={`text-xs px-2 py-0.5 rounded-full font-medium ${stClass}`}
        data-testid="provenance-source-type"
        title={`Source: ${sourceType}`}
      >
        {toLabel(sourceType)}
      </span>
      <span
        className={`text-xs px-2 py-0.5 rounded-full ${vsClass}`}
        data-testid="provenance-verification-state"
        title={`Verification: ${verificationState}`}
      >
        {toLabel(verificationState)}
      </span>
    </span>
  )
}
