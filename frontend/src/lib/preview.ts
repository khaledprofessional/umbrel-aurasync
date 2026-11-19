import type {Device, Group, Mapping, MappingParams, Settings, Telemetry, Zone} from '../types'
import {clamp, hexToRgb, rgbToHex, statusColour} from './util'

const TEMPERATURE_STOPS: Array<[number, [number, number, number]]> = [
	[0, [59, 130, 246]],
	[0.25, [34, 211, 238]],
	[0.5, [34, 197, 94]],
	[0.72, [245, 158, 11]],
	[1, [239, 68, 68]],
]

function mix(a: [number, number, number], b: [number, number, number], amount: number) {
	return [
		a[0] + (b[0] - a[0]) * amount,
		a[1] + (b[1] - a[1]) * amount,
		a[2] + (b[2] - a[2]) * amount,
	] as [number, number, number]
}

function scale(colour: [number, number, number], factor: number): string {
	return rgbToHex([
		colour[0] * clamp(factor, 0, 1),
		colour[1] * clamp(factor, 0, 1),
		colour[2] * clamp(factor, 0, 1),
	])
}

export function temperatureColour(temp: number, low: number, high: number): string {
	const normalised = clamp((temp - low) / Math.max(0.1, high - low), 0, 1)
	for (let index = 0; index < TEMPERATURE_STOPS.length - 1; index += 1) {
		const [lowRatio, lowColour] = TEMPERATURE_STOPS[index]
		const [highRatio, highColour] = TEMPERATURE_STOPS[index + 1]
		if (normalised >= lowRatio && normalised <= highRatio) {
			return rgbToHex(mix(lowColour, highColour, (normalised - lowRatio) / (highRatio - lowRatio)))
		}
	}
	return rgbToHex(TEMPERATURE_STOPS[TEMPERATURE_STOPS.length - 1][1])
}

export function fillPreview(
	count: number,
	fraction: number,
	colour: string,
	params: MappingParams,
	factor = 1,
): string[] {
	const rgb = hexToRgb(colour)
	const units = clamp(fraction, 0, 1) * count
	const full = Math.floor(units)
	const remainder = units - full
	const output: string[] = []
	for (let index = 0; index < count; index += 1) {
		if (index < full) output.push(scale(rgb, (params.brightness / 100) * factor))
		else if (index === full && remainder > 0.01) {
			output.push(scale(rgb, (params.brightness / 100) * factor * remainder))
		} else {
			output.push(params.show_unlit ? scale(rgb, 0.04) : '#050708')
		}
	}
	if (params.reverse) output.reverse()
	return output
}

export function previewZoneColors(
	mapping: Mapping,
	ledCount: number,
	telemetry: Telemetry | null,
	settings: Settings | null,
): string[] {
	if (ledCount <= 0) return []
	const params = mapping.params
	if (mapping.mode === 'off' || !mapping.enabled) return Array.from({length: ledCount}, () => '#050708')
	if (mapping.mode === 'static') return Array.from({length: ledCount}, () => params.color)
	if (mapping.mode === 'storage') {
		const path = params.path || settings?.storage_path || '/'
		const storage = telemetry?.storage?.[path] ?? Object.values(telemetry?.storage ?? {})[0]
		const used = storage?.used_percent ?? 0
		return fillPreview(ledCount, used / 100, statusColour(100 - used), params)
	}
	if (mapping.mode === 'temp_cpu' || mapping.mode === 'temp_gpu') {
		const temp =
			mapping.mode === 'temp_cpu' ? telemetry?.cpu.temp : telemetry?.gpu?.temp
		if (temp === null || temp === undefined) return Array.from({length: ledCount}, () => '#1e293b')
		const colour = temperatureColour(temp, params.low, params.high)
		const normalised = clamp((temp - params.low) / Math.max(0.1, params.high - params.low), 0, 1)
		if (params.visual === 'bar' || params.visual === 'fill') {
			return fillPreview(ledCount, normalised, colour, params)
		}
		return Array.from({length: ledCount}, () => colour)
	}
	const percent =
		mapping.mode === 'cpu_load' ? telemetry?.cpu.load ?? 0 : telemetry?.memory.percent ?? 0
	const visual = params.visual === 'auto' ? (ledCount >= 4 ? 'fill' : 'brightness') : params.visual
	if (visual === 'fill' || visual === 'bar') {
		return fillPreview(ledCount, percent / 100, params.color, params)
	}
	const factor = visual === 'breathe' ? 0.65 : 0.2 + 0.8 * (percent / 100)
	return Array.from({length: ledCount}, () => scale(hexToRgb(params.color), factor))
}

export function targetZones(
	mapping: Pick<Mapping, 'target_type' | 'target_id'>,
	devices: Device[],
	groups: Group[],
): Zone[] {
	if (mapping.target_type === 'zone') {
		return devices.flatMap((device) => device.zones.filter((zone) => zone.id === mapping.target_id))
	}
	if (mapping.target_type === 'device') {
		return devices.find((device) => device.key === mapping.target_id)?.zones ?? []
	}
	const group = groups.find((item) => item.id === mapping.target_id)
	if (!group) return []
	const allZones = devices.flatMap((device) => device.zones)
	return group.zones
		.map((zoneId) => allZones.find((zone) => zone.id === zoneId))
		.filter((zone): zone is Zone => Boolean(zone))
}

export function previewMappingColors(
	mapping: Mapping,
	devices: Device[],
	groups: Group[],
	telemetry: Telemetry | null,
	settings: Settings | null,
	maxLeds = 40,
): string[] {
	const zones = targetZones(mapping, devices, groups)
	if (!zones.length) {
		return previewZoneColors(mapping, Math.min(16, maxLeds), telemetry, settings)
	}
	const total = zones.reduce((sum, zone) => sum + zone.led_count, 0)
	if (mapping.params.layout === 'extend' && zones.length > 1) {
		const rendered = previewZoneColors(
			mapping,
			Math.min(total, maxLeds),
			telemetry,
			settings,
		)
		return rendered
	}
	const first = zones[0]
	return previewZoneColors(mapping, Math.min(first.led_count, maxLeds), telemetry, settings)
}

export function mappingLedCount(mapping: Mapping, devices: Device[], groups: Group[]): number {
	return targetZones(mapping, devices, groups).reduce((sum, zone) => sum + zone.led_count, 0)
}
