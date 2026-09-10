/**
 * Tests for frontend/src/lib/api.ts
 *
 * Required by SDD Mini-Feature 10:
 *   - Bearer header is attached on every request
 *   - Errors are propagated correctly (ApiError with status + message)
 *
 * We mock global.fetch to keep tests pure (no network).
 */

import { describe, it, expect, vi, beforeEach } from 'vitest'
import {
  ApiError,
  healthProfileApi,
  conditionsApi,
  symptomsApi,
  medicationsApi,
  allergiesApi,
  goalsApi,
} from './api'

const MOCK_TOKEN = 'test-bearer-token'

// ─── Helper to inspect what fetch was called with ────────────────────────────

function lastFetchArgs() {
  const mock = vi.mocked(global.fetch)
  expect(mock).toHaveBeenCalled()
  const [url, init] = mock.mock.calls[mock.mock.calls.length - 1]
  return { url: url as string, init: init as RequestInit }
}

function mockFetchOk(body: unknown, status = 200) {
  vi.mocked(global.fetch).mockResolvedValueOnce(
    new Response(JSON.stringify(body), {
      status,
      headers: { 'Content-Type': 'application/json' },
    }),
  )
}

function mockFetch204() {
  vi.mocked(global.fetch).mockResolvedValueOnce(new Response(null, { status: 204 }))
}

function mockFetchError(status: number, detail: string) {
  vi.mocked(global.fetch).mockResolvedValueOnce(
    new Response(JSON.stringify({ detail }), {
      status,
      headers: { 'Content-Type': 'application/json' },
    }),
  )
}

// ─── Setup ────────────────────────────────────────────────────────────────────

beforeEach(() => {
  vi.stubGlobal('fetch', vi.fn())
})

// ─── Bearer header ────────────────────────────────────────────────────────────

describe('Bearer header is attached on every request', () => {
  it('attaches Authorization: Bearer <token> on GET health-profile', async () => {
    mockFetchOk({ id: '1', patient_id: 'p1' })
    await healthProfileApi.get(MOCK_TOKEN)
    const { init } = lastFetchArgs()
    const headers = init.headers as Record<string, string>
    expect(headers['Authorization']).toBe(`Bearer ${MOCK_TOKEN}`)
  })

  it('attaches Bearer token on POST conditions', async () => {
    mockFetchOk({ id: '2', patient_id: 'p1', name: 'Asthma', status: 'active' }, 201)
    await conditionsApi.create(MOCK_TOKEN, { name: 'Asthma', status: 'active' })
    const { init } = lastFetchArgs()
    const headers = init.headers as Record<string, string>
    expect(headers['Authorization']).toBe(`Bearer ${MOCK_TOKEN}`)
  })

  it('attaches Bearer token on DELETE symptom', async () => {
    mockFetch204()
    await symptomsApi.delete(MOCK_TOKEN, 'sym-id-1')
    const { init } = lastFetchArgs()
    const headers = init.headers as Record<string, string>
    expect(headers['Authorization']).toBe(`Bearer ${MOCK_TOKEN}`)
  })

  it('attaches Bearer token on PATCH medication', async () => {
    mockFetchOk({ id: 'm1', status: 'stopped' })
    await medicationsApi.update(MOCK_TOKEN, 'm1', { status: 'stopped' })
    const { init } = lastFetchArgs()
    const headers = init.headers as Record<string, string>
    expect(headers['Authorization']).toBe(`Bearer ${MOCK_TOKEN}`)
  })

  it('attaches Bearer token on GET allergies list', async () => {
    mockFetchOk([])
    await allergiesApi.list(MOCK_TOKEN)
    const { init } = lastFetchArgs()
    const headers = init.headers as Record<string, string>
    expect(headers['Authorization']).toBe(`Bearer ${MOCK_TOKEN}`)
  })

  it('attaches Bearer token on POST goals', async () => {
    mockFetchOk({ id: 'g1', description: 'Run 5K', status: 'active' }, 201)
    await goalsApi.create(MOCK_TOKEN, { description: 'Run 5K', status: 'active' })
    const { init } = lastFetchArgs()
    const headers = init.headers as Record<string, string>
    expect(headers['Authorization']).toBe(`Bearer ${MOCK_TOKEN}`)
  })
})

// ─── URL routing ──────────────────────────────────────────────────────────────

describe('request URLs are correctly formed', () => {
  it('calls /api/v1/health-profile for GET', async () => {
    mockFetchOk({})
    await healthProfileApi.get(MOCK_TOKEN)
    const { url } = lastFetchArgs()
    expect(url).toBe('http://localhost:8000/api/v1/health-profile')
  })

  it('calls /api/v1/conditions for list', async () => {
    mockFetchOk([])
    await conditionsApi.list(MOCK_TOKEN)
    const { url } = lastFetchArgs()
    expect(url).toBe('http://localhost:8000/api/v1/conditions')
  })

  it('calls /api/v1/conditions/<id> for get-by-id', async () => {
    mockFetchOk({ id: 'cond-123' })
    await conditionsApi.get(MOCK_TOKEN, 'cond-123')
    const { url } = lastFetchArgs()
    expect(url).toBe('http://localhost:8000/api/v1/conditions/cond-123')
  })

  it('calls /api/v1/symptoms/<id> for delete', async () => {
    mockFetch204()
    await symptomsApi.delete(MOCK_TOKEN, 'sym-456')
    const { url } = lastFetchArgs()
    expect(url).toBe('http://localhost:8000/api/v1/symptoms/sym-456')
  })

  it('calls /api/v1/medications/<id> for patch', async () => {
    mockFetchOk({})
    await medicationsApi.update(MOCK_TOKEN, 'med-789', { status: 'stopped' })
    const { url } = lastFetchArgs()
    expect(url).toBe('http://localhost:8000/api/v1/medications/med-789')
  })

  it('calls /api/v1/allergies for list', async () => {
    mockFetchOk([])
    await allergiesApi.list(MOCK_TOKEN)
    const { url } = lastFetchArgs()
    expect(url).toBe('http://localhost:8000/api/v1/allergies')
  })

  it('calls /api/v1/goals for list', async () => {
    mockFetchOk([])
    await goalsApi.list(MOCK_TOKEN)
    const { url } = lastFetchArgs()
    expect(url).toBe('http://localhost:8000/api/v1/goals')
  })
})

// ─── HTTP method routing ──────────────────────────────────────────────────────

describe('HTTP methods are correct', () => {
  it('uses GET for health-profile.get', async () => {
    mockFetchOk({})
    await healthProfileApi.get(MOCK_TOKEN)
    expect(lastFetchArgs().init.method).toBe('GET')
  })

  it('uses PUT for health-profile.update', async () => {
    mockFetchOk({})
    await healthProfileApi.update(MOCK_TOKEN, { blood_group: 'O+' })
    expect(lastFetchArgs().init.method).toBe('PUT')
  })

  it('uses POST for conditions.create', async () => {
    mockFetchOk({}, 201)
    await conditionsApi.create(MOCK_TOKEN, { name: 'Hypertension', status: 'active' })
    expect(lastFetchArgs().init.method).toBe('POST')
  })

  it('uses PATCH for conditions.update', async () => {
    mockFetchOk({})
    await conditionsApi.update(MOCK_TOKEN, 'c1', { status: 'resolved' })
    expect(lastFetchArgs().init.method).toBe('PATCH')
  })

  it('uses DELETE for conditions.delete', async () => {
    mockFetch204()
    await conditionsApi.delete(MOCK_TOKEN, 'c1')
    expect(lastFetchArgs().init.method).toBe('DELETE')
  })
})

// ─── Error propagation ────────────────────────────────────────────────────────

describe('ApiError is thrown for non-2xx responses', () => {
  it('throws ApiError with status 401 for unauthenticated request', async () => {
    // Only one mock response — capture the single rejection and assert on it.
    mockFetchError(401, 'Not authenticated')
    let caught: ApiError | null = null
    try {
      await conditionsApi.list(MOCK_TOKEN)
    } catch (err) {
      caught = err as ApiError
    }
    expect(caught).toBeInstanceOf(ApiError)
    expect(caught?.status).toBe(401)
    expect(caught?.message).toBe('Not authenticated')
  })

  it('throws ApiError with status 403 for forbidden resource', async () => {
    mockFetchError(403, 'Not authorized to access this resource')
    let caught: ApiError | null = null
    try {
      await conditionsApi.get(MOCK_TOKEN, 'other-user-cond')
    } catch (err) {
      caught = err as ApiError
    }
    expect(caught).toBeInstanceOf(ApiError)
    expect(caught?.status).toBe(403)
    expect(caught?.message).toBe('Not authorized to access this resource')
  })

  it('throws ApiError with status 404 for missing resource', async () => {
    mockFetchError(404, 'Not Found')
    let caught: ApiError | null = null
    try {
      await goalsApi.get(MOCK_TOKEN, 'nonexistent-id')
    } catch (err) {
      caught = err as ApiError
    }
    expect(caught).toBeInstanceOf(ApiError)
    expect(caught?.status).toBe(404)
  })

  it('throws ApiError with status 422 for validation failure', async () => {
    mockFetchError(422, 'Unprocessable Entity')
    let caught: ApiError | null = null
    try {
      // @ts-expect-error — intentionally bad payload
      await conditionsApi.create(MOCK_TOKEN, { status: 'invalid-status' })
    } catch (err) {
      caught = err as ApiError
    }
    expect(caught).toBeInstanceOf(ApiError)
    expect(caught?.status).toBe(422)
  })

  it('falls back to statusText when response body is not JSON', async () => {
    vi.mocked(global.fetch).mockResolvedValueOnce(
      new Response('Internal Server Error', {
        status: 500,
        statusText: 'Internal Server Error',
        headers: { 'Content-Type': 'text/plain' },
      }),
    )
    let caught: ApiError | null = null
    try {
      await symptomsApi.list(MOCK_TOKEN)
    } catch (err) {
      caught = err as ApiError
    }
    expect(caught).toBeInstanceOf(ApiError)
    expect(caught?.status).toBe(500)
  })
})

// ─── 204 No Content ──────────────────────────────────────────────────────────

describe('204 No Content responses return undefined without throwing', () => {
  it('delete resolves to undefined on 204', async () => {
    mockFetch204()
    const result = await allergiesApi.delete(MOCK_TOKEN, 'a1')
    expect(result).toBeUndefined()
  })

  it('delete resolves to undefined for goals on 204', async () => {
    mockFetch204()
    const result = await goalsApi.delete(MOCK_TOKEN, 'g1')
    expect(result).toBeUndefined()
  })
})

// ─── Request body serialization ───────────────────────────────────────────────

describe('request body is JSON-serialized correctly', () => {
  it('sends JSON body on POST', async () => {
    mockFetchOk({ id: 'g1', description: 'Lose weight', status: 'active' }, 201)
    const payload = { description: 'Lose weight', status: 'active' as const }
    await goalsApi.create(MOCK_TOKEN, payload)
    const { init } = lastFetchArgs()
    expect(init.body).toBe(JSON.stringify(payload))
  })

  it('sends JSON body on PUT health-profile', async () => {
    mockFetchOk({})
    const payload = { blood_group: 'AB+', height_cm: 175 }
    await healthProfileApi.update(MOCK_TOKEN, payload)
    const { init } = lastFetchArgs()
    expect(init.body).toBe(JSON.stringify(payload))
  })

  it('sends no body on GET', async () => {
    mockFetchOk([])
    await medicationsApi.list(MOCK_TOKEN)
    const { init } = lastFetchArgs()
    expect(init.body).toBeUndefined()
  })
})
