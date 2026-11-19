export class ApiError extends Error {
	status: number
	detail: string

	constructor(status: number, detail: string) {
		super(detail)
		this.name = 'ApiError'
		this.status = status
		this.detail = detail
	}
}

async function parseError(response: Response): Promise<string> {
	const text = await response.text()
	if (!text) return `${response.status} ${response.statusText}`
	try {
		const parsed = JSON.parse(text) as {detail?: unknown}
		if (typeof parsed.detail === 'string') return parsed.detail
		if (Array.isArray(parsed.detail)) {
			return parsed.detail
				.map((item) => {
					if (item && typeof item === 'object' && 'msg' in item) {
						const record = item as {msg?: string; loc?: unknown[]}
						const location = Array.isArray(record.loc) ? record.loc.slice(1).join('.') : ''
						return location ? `${location}: ${record.msg}` : String(record.msg)
					}
					return String(item)
				})
				.join('; ')
		}
		if (parsed.detail) return JSON.stringify(parsed.detail)
	} catch {
		// Fall through to the raw response text.
	}
	return text.length > 500 ? `${text.slice(0, 500)}…` : text
}

export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
	const headers = new Headers(init.headers)
	if (init.body && !headers.has('Content-Type')) {
		headers.set('Content-Type', 'application/json')
	}
	headers.set('Accept', 'application/json')
	const response = await fetch(path, {
		...init,
		headers,
		credentials: 'same-origin',
	})
	if (!response.ok) {
		throw new ApiError(response.status, await parseError(response))
	}
	if (response.status === 204) return undefined as T
	const text = await response.text()
	return (text ? JSON.parse(text) : undefined) as T
}

export function post<T>(path: string, body?: unknown): Promise<T> {
	return api<T>(path, {
		method: 'POST',
		body: body === undefined ? undefined : JSON.stringify(body),
	})
}

export function put<T>(path: string, body: unknown): Promise<T> {
	return api<T>(path, {method: 'PUT', body: JSON.stringify(body)})
}

export function del<T>(path: string): Promise<T> {
	return api<T>(path, {method: 'DELETE'})
}
