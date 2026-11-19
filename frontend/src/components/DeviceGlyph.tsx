import {
	Box,
	CircuitBoard,
	Cpu,
	Fan,
	HardDrive,
	Keyboard,
	Lightbulb,
	MemoryStick,
	Monitor,
} from 'lucide-react'

const ICONS: Record<string, typeof Cpu> = {
	motherboard: CircuitBoard,
	dram: MemoryStick,
	gpu: Monitor,
	cooler: Fan,
	'led-strip': Lightbulb,
	keyboard: Keyboard,
	mouse: Box,
	mousepad: Box,
	headset: Box,
	'headset-stand': Box,
	gamepad: Box,
	light: Lightbulb,
	speaker: Box,
	storage: HardDrive,
	case: Fan,
	microphone: Box,
	accessory: Box,
	keypad: Keyboard,
	unknown: Box,
	virtual: Box,
}

export function DeviceGlyph({type, size = 18}: {type: string; size?: number}) {
	const Icon = ICONS[type] ?? Box
	return <Icon size={size} strokeWidth={1.7} />
}

export function deviceTypeLabel(type: string): string {
	return type
		.split('-')
		.map((part) => part.charAt(0).toUpperCase() + part.slice(1))
		.join(' ')
}
