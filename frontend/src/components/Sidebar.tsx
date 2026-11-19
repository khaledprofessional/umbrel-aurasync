import {
	Activity,
	Gauge,
	Layers3,
	Settings2,
	Webhook,
	Wifi,
	WifiOff,
} from 'lucide-react'
import type {Live} from '../types'
import type {Page} from '../navigation'
import {StatusDot} from './ui'

const NAV: Array<{page: Page; label: string; icon: typeof Activity}> = [
	{page: 'overview', label: 'Overview', icon: Gauge},
	{page: 'devices', label: 'Devices', icon: Layers3},
	{page: 'mappings', label: 'Mappings', icon: Activity},
	{page: 'webhooks', label: 'Webhooks', icon: Webhook},
	{page: 'settings', label: 'Settings', icon: Settings2},
]

export function Sidebar({
	page,
	onNavigate,
	live,
	version,
}: {
	page: Page
	onNavigate: (page: Page) => void
	live: Live | null
	version: string
}) {
	const connected = Boolean(live?.hardware.connected)
	return (
		<aside className="sidebar">
			<div className="brand">
				<img src="/aura.svg" className="brand__mark" alt="" width={38} height={38} />
				<div>
					<div className="brand__name">AuraSync</div>
					<div className="brand__sub">umbrelOS light engine</div>
				</div>
			</div>

			<nav className="nav" aria-label="Primary">
				<div className="nav__label">Workspace</div>
				{NAV.map((item) => {
					const Icon = item.icon
					return (
						<button
							key={item.page}
							type="button"
							className={`nav__item ${page === item.page ? 'nav__item--active' : ''}`}
							onClick={() => onNavigate(item.page)}
							aria-label={item.label}
							aria-current={page === item.page ? 'page' : undefined}
						>
							<Icon size={17} strokeWidth={1.8} />
							<span>{item.label}</span>
							{page === item.page ? <span className="nav__active-mark" /> : null}
						</button>
					)
				})}
			</nav>

			<div className="sidebar__spacer" />

			<div className={`hardware-chip ${connected ? 'hardware-chip--online' : ''}`}>
				<div className="hardware-chip__head">
					{connected ? <Wifi size={15} /> : <WifiOff size={15} />}
					<span>OpenRGB</span>
					<StatusDot online={connected} />
				</div>
				<div className="hardware-chip__meta">
					{connected
						? `${live?.hardware.device_count ?? 0} devices · protocol ${live?.hardware.server_protocol ?? '—'}`
						: 'Controller unreachable'}
				</div>
				{connected ? (
					<div className="hardware-chip__frame">
						<span>{live?.frame.fps ?? 0} fps</span>
						<span>{live?.summary.led_count ?? 0} LEDs</span>
					</div>
				) : (
					<button type="button" className="text-link" onClick={() => onNavigate('settings')}>
						Review host setup →
					</button>
				)}
			</div>

			<div className="sidebar__footer">
				<span>AuraSync {version}</span>
				<span className="sidebar__dot" />
				<span>self-hosted</span>
			</div>
		</aside>
	)
}
