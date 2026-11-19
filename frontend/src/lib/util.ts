import type {Mode, MappingParams, TargetType} from '../types'

const STORAGE_STOPS: Array<[number, [number, number, number]]> = [
	[100, [34, 211, 238]],
	[50, [52, 211, 153]],
	[25, [251, 191, 36]],
	[15, [249, 115, 22]],
	[5, [239, 68, 68]],
	[0, [220, 38, 38]],
]

export function clamp(value: number, low: number, high: number): number {
	return Math.max(low, Math.min(high, value))
}

export function hexToRgb(value: string): [number, number, number] {
	const match = /^#?([0-9a-f]{6})$/i.exec(value.trim())
	if (!match) return [34, 211, 238]
	const raw = match[1]
	return [parseInt(raw.slice(0, 2), 16), parseInt(raw.slice(2, 4), 16), parseInt(raw.slice(4, 6), 16)]
}

export function rgbToHex(rgb: [number, number, number]): string {
	return `#${rgb.map((value) => Math.round(clamp(value, 0, 255)).toString(16).padStart(2, '0')).join('')}`
}

function mix(a: [number, number, number], b: [number, number, number], amount: number): [number, number, number] {
	return [
		a[0] + (b[0] - a[0]) * amount,
		a[1] + (b[1] - a[1]) * amount,
		a[2] + (b[2] - a[2]) * amount,
	]
}

export function statusColour(freePercent: number): string {
	const value = clamp(freePercent, 0, 100)
	for (let index = 0; index < STORAGE_STOPS.length - 1; index += 1) {
		const [highValue, highColour] = STORAGE_STOPS[index]
		const [lowValue, lowColour] = STORAGE_STOPS[index + 1]
		if (value <= highValue && value >= lowValue) {
			const span = highValue - lowValue
			return rgbToHex(mix(lowColour, highColour, span ? (value - lowValue) / span : 0))
		}
	}
	return rgbToHex(STORAGE_STOPS[STORAGE_STOPS.length - 1][1])
}

export function statusName(freePercent: number): string {
	if (freePercent > 75) return 'Cyan'
	if (freePercent > 50) return 'Green'
	if (freePercent > 25) return 'Amber'
	if (freePercent > 15) return 'Orange'
	if (freePercent > 5) return 'Red'
	return 'Critical red'
}

export function statusEmoji(freePercent: number): string {
	if (freePercent > 75) return '🟦'
	if (freePercent > 50) return '🟩'
	if (freePercent > 25) return '🟨'
	if (freePercent > 15) return '🟧'
	if (freePercent > 5) return '🟥'
	return '🔴'
}

export function formatBytes(value: number | null | undefined, digits = 1): string {
	if (value === null || value === undefined || !Number.isFinite(value)) return '—'
	const units = ['B', 'KB', 'MB', 'GB', 'TB', 'PB']
	let number = Math.max(0, value)
	let unit = 0
	while (number >= 1024 && unit < units.length - 1) {
		number /= 1024
		unit += 1
	}
	return `${number.toFixed(unit === 0 ? 0 : digits)} ${units[unit]}`
}

export function formatNumber(value: number | null | undefined, digits = 1): string {
	if (value === null || value === undefined || !Number.isFinite(value)) return '—'
	return value.toFixed(digits)
}

export function formatUptime(seconds: number | null | undefined): string {
	if (!seconds || !Number.isFinite(seconds)) return '—'
	const days = Math.floor(seconds / 86400)
	const hours = Math.floor((seconds % 86400) / 3600)
	const minutes = Math.floor((seconds % 3600) / 60)
	if (days > 0) return `${days}d ${hours}h`
	if (hours > 0) return `${hours}h ${minutes}m`
	return `${minutes}m`
}

export function timeAgo(timestamp: string | number | null | undefined): string {
	if (timestamp === null || timestamp === undefined) return 'never'
	const millis = typeof timestamp === 'number' ? (timestamp > 10_000_000_000 ? timestamp : timestamp * 1000) : Date.parse(timestamp)
	if (!Number.isFinite(millis)) return 'unknown'
	const delta = Math.max(0, Math.round((Date.now() - millis) / 1000))
	if (delta < 10) return 'just now'
	if (delta < 60) return `${delta}s ago`
	if (delta < 3600) return `${Math.floor(delta / 60)}m ago`
	if (delta < 86400) return `${Math.floor(delta / 3600)}h ago`
	return `${Math.floor(delta / 86400)}d ago`
}

export function modeLabel(mode: Mode): string {
	return {
		storage: 'Storage gauge',
		temp_cpu: 'CPU temperature',
		temp_gpu: 'GPU temperature',
		cpu_load: 'CPU load',
		ram_load: 'RAM load',
		static: 'Static colour',
		off: 'Off',
	}[mode]
}

export function modeDescription(mode: Mode): string {
	return {
		storage: 'A physical fill bar for disk usage and free-space colour alerts.',
		temp_cpu: 'Cool blue through amber to hot red, driven by the CPU package sensor.',
		temp_gpu: 'A thermal gradient for the GPU edge or package sensor.',
		cpu_load: 'Turn processor load into a fill bar, brightness, or breathing rate.',
		ram_load: 'Visualise memory pressure across a zone or a grouped array.',
		static: 'A solid colour at a fixed brightness.',
		off: 'Keep the zone dark without removing its mapping.',
	}[mode]
}

export function targetTypeLabel(type: TargetType): string {
	return {zone: 'LED zone', device: 'Device', group: 'Group'}[type]
}

export function effectLabel(effect: string): string {
	return {
		solid: 'Solid',
		flash: 'Flash',
		pulse: 'Pulse',
		breathe: 'Breathe',
		rainbow: 'Rainbow',
	}[effect] ?? effect
}

export function defaultParams(): MappingParams {
	return {
		color: '#22d3ee',
		brightness: 100,
		layout: 'mirror',
		reverse: false,
		path: null,
		show_unlit: false,
		low: 30,
		high: 90,
		visual: 'auto',
		speed: 1,
		critical_pulse: true,
	}
}

export function parseHexInput(value: string): string {
	const trimmed = value.trim()
	if (/^#[0-9a-f]{6}$/i.test(trimmed)) return trimmed.toLowerCase()
	if (/^[0-9a-f]{6}$/i.test(trimmed)) return `#${trimmed.toLowerCase()}`
	return trimmed
}

export function safePercent(value: number | null | undefined): number {
	if (value === null || value === undefined || !Number.isFinite(value)) return 0
	return clamp(value, 0, 100)
}
