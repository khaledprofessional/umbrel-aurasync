export type Page = 'overview' | 'devices' | 'mappings' | 'webhooks' | 'settings'

export const PAGE_META: Record<Page, {eyebrow: string; title: string; subtitle: string}> = {
	overview: {
		eyebrow: 'Live hardware',
		title: 'Overview',
		subtitle: 'A real-time view of the machine and the light it casts.',
	},
	devices: {
		eyebrow: 'Discovery',
		title: 'Devices & zones',
		subtitle: 'Every OpenRGB controller, zone, and individual LED index.',
	},
	mappings: {
		eyebrow: 'Rendering',
		title: 'Light mappings',
		subtitle: 'Bind telemetry, static colour, or sleep to any target.',
	},
	webhooks: {
		eyebrow: 'Integrations',
		title: 'Webhooks',
		subtitle: 'Temporary light overrides from anything that can send HTTP.',
	},
	settings: {
		eyebrow: 'Configuration',
		title: 'Settings',
		subtitle: 'Rendering cadence, sensors, quiet hours, and host access.',
	},
}
