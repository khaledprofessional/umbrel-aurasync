export type Mode =
	| 'storage'
	| 'temp_cpu'
	| 'temp_gpu'
	| 'cpu_load'
	| 'ram_load'
	| 'static'
	| 'off'

export type Effect = 'solid' | 'flash' | 'pulse' | 'breathe' | 'rainbow'
export type TargetType = 'zone' | 'device' | 'group'
export type Visual = 'auto' | 'solid' | 'bar' | 'fill' | 'brightness' | 'breathe'

export interface Zone {
	id: string
	index: number
	name: string
	type: string
	led_count: number
	start_idx: number
	matrix: {height: number; width: number; leds: number[]} | null
	segments: Array<{index: number; name: string; type: string; start_idx: number; led_count: number}>
	led_names: string[]
}

export interface Device {
	key: string
	index: number
	name: string
	type: string
	vendor: string
	description: string
	version: string
	serial: string
	location: string
	active_mode: number
	modes: string[]
	led_count: number
	zones: Zone[]
}

export interface Group {
	id: string
	name: string
	zones: string[]
	created_at?: string
	zone_count: number
	device_names: string[]
	missing_zones: string[]
}

export interface MappingParams {
	color: string
	brightness: number
	layout: 'mirror' | 'extend'
	reverse: boolean
	path: string | null
	show_unlit: boolean
	low: number
	high: number
	visual: Visual
	speed: number
	critical_pulse: boolean
}

export interface Mapping {
	id: string
	target_type: TargetType
	target_id: string
	mode: Mode
	params: MappingParams
	enabled: boolean
	target_exists: boolean
	target_label: string
}

export interface NightSchedule {
	enabled: boolean
	start: string
	end: string
	behaviour: 'dim' | 'off'
	brightness: number
	color: string
}

export interface Settings {
	brightness: number
	fps: number
	smoothing: boolean
	storage_path: string
	cpu_sensor: string
	gpu_sensor: string
	timezone: string
	night: NightSchedule
}

export interface Sensor {
	id: string
	chip: string
	label: string
	temp: number
	kind: 'cpu' | 'gpu' | 'other'
}

export interface StorageInfo {
	path: string
	total: number
	used: number
	free: number
	usable: number
	used_percent: number
	free_percent: number
	total_human: string
	free_human: string
}

export interface Telemetry {
	timestamp: number
	cpu: {
		load: number
		temp: number | null
		sensor_id: string | null
		sensor_label: string | null
		model: string
		cores: number
	}
	memory: {total: number; used: number; percent: number}
	gpu: {
		index: number
		name: string
		temp: number | null
		util: number | null
		memory_used: number | null
		memory_total: number | null
		vendor: string
		sensor_id: string | null
		sensor_label: string | null
	} | null
	storage: Record<string, StorageInfo>
	sensors: Sensor[]
	uptime: number
	loadavg: number[]
	hostname: string
	os_name: string
	errors: string[]
}

export interface HardwareStatus {
	connected: boolean
	error: string | null
	server_protocol: number | null
	device_count: number
	last_discovery: number | null
	last_write: number | null
	last_write_error: string | null
}

export interface DiagnosticModule {
	name: string
	loaded: boolean
}

export interface Diagnostics {
	modules: DiagnosticModule[]
	i2c_dev_loaded: boolean
	smbus_loaded: boolean
	i2c_adapters: string[]
	hidraw: string[]
	usb_device_count: number
	recommendations: string[]
	host: {
		uptime: number
		loadavg: number[]
		hostname: string
		os_name: string
		cpu_model: string
		cpu_cores: number
	}
	os_release: string
}

export interface Mount {
	path: string
	total: number
	free: number
	label: string
}

export interface WebhookLog {
	id: number
	event: string
	outcome: string
	source_ip: string
	detail: {
		color?: string
		effect?: string
		duration?: number
		priority?: number
		message?: string
	}
	created_at: string
}

export interface Preset {
	event: string
	color: string
	effect: Effect
	duration: number
	brightness: number
}

export interface Overlay {
	id: string
	kind: string
	effect: Effect
	color: string
	brightness: number
	priority: number
	event_name: string | null
	message: string | null
	target_scope: 'managed' | 'all'
	mapping_id: string | null
	created_at: number
	expires_at: number
	remaining: number
}

export interface Bootstrap {
	server: {name: string; version: string; started_at: number; timezone: string}
	settings: Settings
	devices: Device[]
	groups: Group[]
	mappings: Mapping[]
	telemetry: Telemetry
	sensors: Sensor[]
	mounts: Mount[]
	diagnostics: Diagnostics
	presets: Preset[]
	logs: WebhookLog[]
	webhook: {token: string; endpoint: string; auth: string}
	summary: {
		mode: string
		storage: StorageInfo | null
		last_webhook: WebhookLog | null
		device_count: number
	}
	widgets: {status: string; storage: string}
}

export interface Live {
	now: number
	hardware: HardwareStatus
	telemetry: Telemetry
	settings: Settings
	night_active: boolean
	overlays: Overlay[]
	zone_colors: Record<string, string[]>
	frame: {last_frame_at: number | null; fps: number}
	last_webhook: WebhookLog | null
	summary: {
		mode: string
		mode_id: string | null
		storage: StorageInfo | null
		device_count: number
		zone_count: number
		led_count: number
	}
	diagnostics: Diagnostics
}

export interface MappingInput {
	target_type: TargetType
	target_id: string
	mode: Mode
	params: MappingParams
	enabled: boolean
}

export interface GroupInput {
	name: string
	zones: string[]
}
