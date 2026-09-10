/**
 * Typed API client for the Personal Healthcare backend.
 *
 * Design decisions:
 * - All requests attach the Supabase access_token as `Authorization: Bearer <token>`.
 * - Non-2xx responses throw an `ApiError` carrying the HTTP status and a message
 *   parsed from the response body (falls back to `response.statusText`).
 * - The base URL is configurable via `VITE_API_BASE_URL`; defaults to '' (relative)
 *   so the Vite dev proxy (`/api → :8000`) works without extra config.
 * - `token` is passed explicitly by callers (from the auth session) so the client
 *   stays free of global auth state and is trivially testable.
 */

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? ''
const API_V1 = `${API_BASE}/api/v1`

// ─── Error type ───────────────────────────────────────────────────────────────

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    message: string,
  ) {
    super(message)
    this.name = 'ApiError'
  }
}

// ─── Low-level fetch wrapper ──────────────────────────────────────────────────

async function request<T>(
  method: string,
  path: string,
  token: string,
  body?: unknown,
): Promise<T> {
  const headers: Record<string, string> = {
    Authorization: `Bearer ${token}`,
    'Content-Type': 'application/json',
  }

  const response = await fetch(`${API_V1}${path}`, {
    method,
    headers,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  })

  if (!response.ok) {
    let message = response.statusText
    try {
      const data = await response.json()
      message = data?.detail ?? data?.message ?? message
    } catch {
      // ignore JSON parse error; keep statusText
    }
    throw new ApiError(response.status, message)
  }

  // 204 No Content — return undefined cast as T (callers should type accordingly)
  if (response.status === 204) {
    return undefined as T
  }

  return response.json() as Promise<T>
}

// ─── Shared domain types ──────────────────────────────────────────────────────

export interface HealthProfile {
  id: string
  patient_id: string
  date_of_birth: string | null
  biological_sex: string | null
  height_cm: number | null
  blood_group: string | null
  notes: string | null
  created_at: string
  updated_at: string
}

export interface HealthProfileUpdate {
  date_of_birth?: string | null
  biological_sex?: string | null
  height_cm?: number | null
  blood_group?: string | null
  notes?: string | null
}

export interface Condition {
  id: string
  patient_id: string
  name: string
  status: 'active' | 'resolved'
  is_chronic: boolean
  started_at: string | null
  ended_at: string | null
  recorded_at: string
  notes: string | null
  source_type: string
  created_at: string
  updated_at: string
}

export interface ConditionCreate {
  name: string
  status: 'active' | 'resolved'
  is_chronic?: boolean
  started_at?: string | null
  ended_at?: string | null
  notes?: string | null
}

export interface ConditionUpdate {
  name?: string
  status?: 'active' | 'resolved'
  is_chronic?: boolean
  started_at?: string | null
  ended_at?: string | null
  notes?: string | null
}

export interface Symptom {
  id: string
  patient_id: string
  name: string
  severity: 'mild' | 'moderate' | 'severe' | null
  started_at: string | null
  ended_at: string | null
  recorded_at: string
  notes: string | null
  source_type: string
  created_at: string
  updated_at: string
}

export interface SymptomCreate {
  name: string
  severity?: 'mild' | 'moderate' | 'severe' | null
  started_at?: string | null
  ended_at?: string | null
  notes?: string | null
}

export interface SymptomUpdate {
  name?: string
  severity?: 'mild' | 'moderate' | 'severe' | null
  started_at?: string | null
  ended_at?: string | null
  notes?: string | null
}

export interface Medication {
  id: string
  patient_id: string
  name: string
  dosage: string | null
  frequency: string | null
  status: 'active' | 'stopped'
  as_needed: boolean
  started_at: string | null
  ended_at: string | null
  recorded_at: string
  notes: string | null
  source_type: string
  created_at: string
  updated_at: string
}

export interface MedicationCreate {
  name: string
  status: 'active' | 'stopped'
  dosage?: string | null
  frequency?: string | null
  as_needed?: boolean
  started_at?: string | null
  ended_at?: string | null
  notes?: string | null
}

export interface MedicationUpdate {
  name?: string
  status?: 'active' | 'stopped'
  dosage?: string | null
  frequency?: string | null
  as_needed?: boolean
  started_at?: string | null
  ended_at?: string | null
  notes?: string | null
}

export interface Allergy {
  id: string
  patient_id: string
  allergen: string
  reaction: string | null
  severity: 'mild' | 'moderate' | 'severe' | 'life_threatening' | null
  recorded_at: string
  notes: string | null
  source_type: string
  created_at: string
  updated_at: string
}

export interface AllergyCreate {
  allergen: string
  reaction?: string | null
  severity?: 'mild' | 'moderate' | 'severe' | 'life_threatening' | null
  notes?: string | null
}

export interface AllergyUpdate {
  allergen?: string
  reaction?: string | null
  severity?: 'mild' | 'moderate' | 'severe' | 'life_threatening' | null
  notes?: string | null
}

export interface Goal {
  id: string
  patient_id: string
  description: string
  status: 'active' | 'achieved' | 'abandoned'
  target_date: string | null
  recorded_at: string
  notes: string | null
  created_at: string
  updated_at: string
}

export interface GoalCreate {
  description: string
  status: 'active' | 'achieved' | 'abandoned'
  target_date?: string | null
  notes?: string | null
}

export interface GoalUpdate {
  description?: string
  status?: 'active' | 'achieved' | 'abandoned'
  target_date?: string | null
  notes?: string | null
}

// ─── Health Profile ───────────────────────────────────────────────────────────

export const healthProfileApi = {
  get: (token: string): Promise<HealthProfile> =>
    request<HealthProfile>('GET', '/health-profile', token),

  update: (token: string, data: HealthProfileUpdate): Promise<HealthProfile> =>
    request<HealthProfile>('PUT', '/health-profile', token, data),
}

// ─── Conditions ───────────────────────────────────────────────────────────────

export const conditionsApi = {
  list: (token: string): Promise<Condition[]> =>
    request<Condition[]>('GET', '/conditions', token),

  get: (token: string, id: string): Promise<Condition> =>
    request<Condition>('GET', `/conditions/${id}`, token),

  create: (token: string, data: ConditionCreate): Promise<Condition> =>
    request<Condition>('POST', '/conditions', token, data),

  update: (token: string, id: string, data: ConditionUpdate): Promise<Condition> =>
    request<Condition>('PATCH', `/conditions/${id}`, token, data),

  delete: (token: string, id: string): Promise<void> =>
    request<void>('DELETE', `/conditions/${id}`, token),
}

// ─── Symptoms ─────────────────────────────────────────────────────────────────

export const symptomsApi = {
  list: (token: string): Promise<Symptom[]> =>
    request<Symptom[]>('GET', '/symptoms', token),

  get: (token: string, id: string): Promise<Symptom> =>
    request<Symptom>('GET', `/symptoms/${id}`, token),

  create: (token: string, data: SymptomCreate): Promise<Symptom> =>
    request<Symptom>('POST', '/symptoms', token, data),

  update: (token: string, id: string, data: SymptomUpdate): Promise<Symptom> =>
    request<Symptom>('PATCH', `/symptoms/${id}`, token, data),

  delete: (token: string, id: string): Promise<void> =>
    request<void>('DELETE', `/symptoms/${id}`, token),
}

// ─── Medications ──────────────────────────────────────────────────────────────

export const medicationsApi = {
  list: (token: string): Promise<Medication[]> =>
    request<Medication[]>('GET', '/medications', token),

  get: (token: string, id: string): Promise<Medication> =>
    request<Medication>('GET', `/medications/${id}`, token),

  create: (token: string, data: MedicationCreate): Promise<Medication> =>
    request<Medication>('POST', '/medications', token, data),

  update: (token: string, id: string, data: MedicationUpdate): Promise<Medication> =>
    request<Medication>('PATCH', `/medications/${id}`, token, data),

  delete: (token: string, id: string): Promise<void> =>
    request<void>('DELETE', `/medications/${id}`, token),
}

// ─── Allergies ────────────────────────────────────────────────────────────────

export const allergiesApi = {
  list: (token: string): Promise<Allergy[]> =>
    request<Allergy[]>('GET', '/allergies', token),

  get: (token: string, id: string): Promise<Allergy> =>
    request<Allergy>('GET', `/allergies/${id}`, token),

  create: (token: string, data: AllergyCreate): Promise<Allergy> =>
    request<Allergy>('POST', '/allergies', token, data),

  update: (token: string, id: string, data: AllergyUpdate): Promise<Allergy> =>
    request<Allergy>('PATCH', `/allergies/${id}`, token, data),

  delete: (token: string, id: string): Promise<void> =>
    request<void>('DELETE', `/allergies/${id}`, token),
}

// ─── Goals ────────────────────────────────────────────────────────────────────

export const goalsApi = {
  list: (token: string): Promise<Goal[]> =>
    request<Goal[]>('GET', '/goals', token),

  get: (token: string, id: string): Promise<Goal> =>
    request<Goal>('GET', `/goals/${id}`, token),

  create: (token: string, data: GoalCreate): Promise<Goal> =>
    request<Goal>('POST', '/goals', token, data),

  update: (token: string, id: string, data: GoalUpdate): Promise<Goal> =>
    request<Goal>('PATCH', `/goals/${id}`, token, data),

  delete: (token: string, id: string): Promise<void> =>
    request<void>('DELETE', `/goals/${id}`, token),
}
