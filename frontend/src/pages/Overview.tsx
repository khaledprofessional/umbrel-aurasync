import {useEffect, useMemo, useState, type ReactNode} from 'react'
import {
	AlertTriangle,
	ArrowUpRight,
	Check,
	ChevronRight,
	Cpu,
	HardDrive,
	MemoryStick,
	Moon,
	Radio,
	Thermometer,
	Zap,
} from 'lucide-react'
import type {Bootstrap, Device, Live, TargetType} from '../types'
import {Button, Card, EmptyState, Pill} from '../components/ui'
import {RingGauge, Sparkline} from '../components/Gauge'
import {LedStrip, SpectrumBar} from '../components/LedStrip'
import {DeviceGlyph, deviceTypeLabel} from '../components/DeviceGlyph'
import {
	formatBytes,
	formatNumber,
	formatUptime,
	statusColour,
	statusEmoji,
	statusName,
	timeAgo,
} from '../lib/util'

interface Props {
	bootstrap: Bootstrap
	live: Live | null
	onNavigate: (page: 'mappings' | 'settings') => void
	onCreateMapping: (type: TargetType, id: string) => void
}

export function Overview({bootstrap, live, onNavigate, onCreateMapping}: Props) {
	const [history, setHistory] = useState<{cpu: number[]; memory: number[]; temp: number[]; gpu: number[]}>({
		cpu: [],
		memory: [],
		temp: [],
		gpu: [],
	})

	useEffect(() => {
		if (!live) return
		setHistory((previous) => ({
			cpu: [...previous.cpu, live.telemetry.cpu.load].slice(-36),
			memory: [...previous.memory, live.telemetry.memory.percent].slice(-36),
			temp: [...previous.temp, live.telemetry.cpu.temp ?? 0].slice(-36),
			gpu: [...previous.gpu, live.telemetry.gpu?.temp ?? 0].slice(-36),
		}))
	}, [live?.now])

	const storage = live?.summary.storage ?? Object.values(live?.telemetry.storage ?? {})[0] ?? null
	const used = storage?.used_percent ?? 0
	const free = 100 - used
	const colour = statusColour(free)
	const mode = live?.summary.mode ?? bootstrap.summary.mode
	const diagnostics = live?.diagnostics ?? bootstrap.diagnostics
	const warnings = diagnostics.recommendations
	const smbusWarning =
		!diagnostics.i2c_dev_loaded || diagnostics.i2c_adapters.length === 0
	const devices = bootstrap.devices

	const primaryMapping = useMemo(() => {
		if (!live?.summary.mode_id) return null
		return bootstrap.mappings.find((mapping) => mapping.id === live.summary.mode_id) ?? null
	}, [bootstrap.mappings, live?.summary.mode_id])

	const gpuTemp = live?.telemetry.gpu?.temp ?? null
	const cpuTemp = live?.telemetry.cpu.temp
	const night = live?.night_active

	return (
		<div className="overview">
			{warnings.length > 0 && smbusWarning ? (
				<div className="notice notice--warning">
					<div className="notice__icon">
						<AlertTriangle size={18} />
					</div>
					<div className="notice__body">
						<strong>SMBus visibility needs attention</strong>
						<p>{warnings[0]}</p>
						<div className="notice__command">
							<code>sudo modprobe i2c-dev</code>
							<span>then restart the app if RAM sticks are still missing</span>
						</div>
					</div>
					<Button variant="quiet" size="sm" onClick={() => onNavigate('settings')} icon={<ArrowUpRight size={14} />}>
						Diagnostics
					</Button>
				</div>
			) : null}

			<div className="overview-grid">
				<div className="overview-main">
					<Card className="hero">
						<div className="hero__glow" style={{background: colour}} />
						<div className="hero__copy">
							<div className="eyebrow">
								<Radio size={12} /> Storage fill · live
							</div>
							<div className="hero__headline">
								<span className="hero__value">
									{formatNumber(used, 0)}%
								</span>
								<span className="hero__unit">used</span>
							</div>
							<div className="hero__path">
								<HardDrive size={14} />
								<code>{storage?.path ?? live?.settings.storage_path ?? '/'}</code>
								<span>
									{formatBytes(storage?.free)} free of {formatBytes(storage?.total)}
								</span>
							</div>
							<div className="hero__status">
								<span className="hero__status-dot" style={{background: colour, boxShadow: `0 0 16px ${colour}`}} />
								<span style={{color: colour}}>{statusName(free)}</span>
								<span className="hero__status-sep">·</span>
								<span>{statusEmoji(free)} free-space band</span>
								{free < 5 ? <Pill tone="red">critical pulse</Pill> : null}
							</div>
							<div className="hero__thresholds">
								<SpectrumBar />
								<div className="hero__threshold-labels">
									<span>5% free</span>
									<span>25%</span>
									<span>50%</span>
									<span>100%</span>
								</div>
							</div>
						</div>
						<div className="hero__gauge">
							<RingGauge value={used / 100} size={168} stroke={10} colour={colour} label={`${used.toFixed(0)} percent used`}>
								<span className="ring-gauge__big" style={{color: colour}}>
									{Math.round(free)}%
								</span>
								<span className="ring-gauge__small">free</span>
							</RingGauge>
							<div className="hero__gauge-caption">{storage?.total_human ?? '—'} capacity</div>
						</div>
					</Card>

					<div className="metric-grid">
						<MetricCard
							icon={<Cpu size={16} />}
							label="CPU load"
							value={`${formatNumber(live?.telemetry.cpu.load, 1)}%`}
							detail={`${live?.telemetry.cpu.cores || bootstrap.telemetry.cpu.cores || '—'} threads`}
							colour="#7cf7d4"
							values={history.cpu}
						>
							<div className="metric__bar">
								<span style={{width: `${Math.min(100, live?.telemetry.cpu.load ?? 0)}%`, background: '#7cf7d4'}} />
							</div>
						</MetricCard>
						<MetricCard
							icon={<MemoryStick size={16} />}
							label="Memory"
							value={`${formatNumber(live?.telemetry.memory.percent, 0)}%`}
							detail={`${formatBytes(live?.telemetry.memory.used)} / ${formatBytes(live?.telemetry.memory.total)}`}
							colour="#60a5fa"
							values={history.memory}
						>
							<div className="metric__bar">
								<span
									style={{
										width: `${Math.min(100, live?.telemetry.memory.percent ?? 0)}%`,
										background: '#60a5fa',
									}}
								/>
							</div>
						</MetricCard>
						<MetricCard
							icon={<Thermometer size={16} />}
							label="CPU temperature"
							value={cpuTemp === null || cpuTemp === undefined ? '—' : `${formatNumber(cpuTemp, 1)}°C`}
							detail={live?.telemetry.cpu.sensor_label ?? 'No sensor selected'}
							colour="#fbbf24"
							values={history.temp}
						>
							<div className="metric__bar">
								<span
									style={{
										width: `${Math.min(100, ((cpuTemp ?? 0) / 100) * 100)}%`,
										background: 'linear-gradient(90deg,#60a5fa,#fbbf24,#ef4444)',
									}}
								/>
							</div>
						</MetricCard>
						<MetricCard
							icon={<Zap size={16} />}
							label="GPU"
							value={gpuTemp === null || gpuTemp === undefined ? '—' : `${formatNumber(gpuTemp, 1)}°C`}
							detail={live?.telemetry.gpu?.name ?? 'No GPU sensor exposed'}
							colour="#a78bfa"
							values={history.gpu}
						>
							<div className="metric__bar">
								<span
									style={{
										width: `${Math.min(100, live?.telemetry.gpu?.util ?? 0)}%`,
										background: 'linear-gradient(90deg,#a78bfa,#22d3ee)',
									}}
								/>
							</div>
						</MetricCard>
					</div>

					<Card className="section-card">
						<div className="section-head">
							<div>
								<div className="eyebrow">OpenRGB fabric</div>
								<h2 className="section-title">Light field</h2>
							</div>
							<div className="section-head__actions">
								<Pill tone={devices.length ? 'mint' : 'neutral'} dot>
									{devices.length} devices
								</Pill>
								<Button variant="quiet" size="sm" onClick={() => onNavigate('mappings')} icon={<ChevronRight size={14} />}>
									All mappings
								</Button>
							</div>
						</div>
						{devices.length === 0 ? (
							<EmptyState
								icon={<Radio size={24} />}
								title={live?.hardware.connected ? 'No lighting hardware discovered' : 'OpenRGB is not connected'}
								description={
									live?.hardware.connected
										? 'The controller service is reachable, but no lighting hardware was discovered. Check the host SMBus and USB access, then rescan.'
										: live?.hardware.error
											? `The controller container has not answered yet: ${live.hardware.error}`
											: 'Waiting for the OpenRGB SDK server. Check the controller container and host module access.'
								}
								action={
									<Button variant="secondary" onClick={() => onNavigate('settings')}>
										Open diagnostics
									</Button>
								}
							/>
						) : (
							<div className="light-field">
								{devices.map((device) => (
									<DeviceLightRow
										key={device.key}
										device={device}
										live={live}
										onMap={(zoneId) => onCreateMapping('zone', zoneId)}
									/>
								))}
							</div>
						)}
					</Card>
				</div>

				<aside className="overview-side">
					<Card className="side-card active-map-card">
						<div className="eyebrow">Active map</div>
						<div className="active-map__title">{mode}</div>
						<p className="active-map__copy">
							{primaryMapping
								? `${primaryMapping.target_label} · ${bootstrap.devices.length} controller${bootstrap.devices.length === 1 ? '' : 's'} in the light field.`
								: 'No mapping is active. The renderer is idle and leaves unmanaged zones untouched.'}
						</p>
						<div className="active-map__meta">
							<span>
								<Check size={13} /> {live?.summary.zone_count ?? 0} zones
							</span>
							<span>
								<Zap size={13} /> {live?.summary.led_count ?? 0} LEDs
							</span>
							{night ? (
								<span>
									<Moon size={13} /> quiet hours
								</span>
							) : null}
						</div>
						<Button
							variant="secondary"
							size="sm"
							onClick={() => onNavigate('mappings')}
							icon={<ArrowUpRight size={14} />}
							className="active-map__button"
						>
							{primaryMapping ? 'Edit mapping' : 'Create mapping'}
						</Button>
					</Card>

					<Card className="side-card">
						<div className="section-head section-head--compact">
							<div>
								<div className="eyebrow">Temporary overrides</div>
								<h3 className="section-title section-title--sm">Signal</h3>
							</div>
							<Zap size={16} className="muted-icon" />
						</div>
						{live?.overlays.length ? (
							<div className="overlay-list">
								{live.overlays.map((overlay) => (
									<div className="overlay-row" key={overlay.id}>
										<span
											className="overlay-row__swatch"
											style={{background: overlay.color, boxShadow: `0 0 12px ${overlay.color}`}}
										/>
										<div>
											<strong>{overlay.event_name ?? overlay.kind.replace('-', ' ')}</strong>
											<span>
												{overlay.effect} · {Math.max(0, Math.ceil(overlay.remaining))}s left
											</span>
										</div>
									</div>
								))}
							</div>
						) : (
							<div className="empty-inline">
								<span className="empty-inline__dot" />
								<span>No active overrides. Telemetry owns the lights.</span>
							</div>
						)}
						<div className="last-event">
							<div className="eyebrow">Last webhook</div>
							{live?.last_webhook ?? bootstrap.summary.last_webhook ? (
								<div className="last-event__row">
									<code>{(live?.last_webhook ?? bootstrap.summary.last_webhook)?.event}</code>
									<span>{timeAgo((live?.last_webhook ?? bootstrap.summary.last_webhook)?.created_at)}</span>
								</div>
							) : (
								<span className="muted">Nothing triggered yet.</span>
							)}
						</div>
					</Card>

					<Card className="side-card">
						<div className="eyebrow">Hardware link</div>
						<div className="link-status">
							<span className={`link-status__dot ${live?.hardware.connected ? 'is-online' : ''}`} />
							<div>
								<strong>{live?.hardware.connected ? 'OpenRGB connected' : 'OpenRGB disconnected'}</strong>
								<span>
									{live?.hardware.connected
										? `SDK protocol ${live.hardware.server_protocol ?? '—'} · ${live.frame.fps} fps`
										: live?.hardware.error ?? 'Waiting for the controller service'}
								</span>
							</div>
						</div>
						<div className="stat-list">
							<div>
								<span>Last frame</span>
								<strong>{live?.frame.last_frame_at ? timeAgo(live.frame.last_frame_at) : '—'}</strong>
							</div>
							<div>
								<span>Host</span>
								<strong>{live?.telemetry.hostname || '—'}</strong>
							</div>
							<div>
								<span>Uptime</span>
								<strong>{formatUptime(live?.telemetry.uptime)}</strong>
							</div>
							<div>
								<span>OS</span>
								<strong title={live?.telemetry.os_name}>{live?.telemetry.os_name || '—'}</strong>
							</div>
						</div>
					</Card>

					<Card className="side-card side-card--quiet">
						<div className="host-module-row">
							<span className={`module-dot ${diagnostics.i2c_dev_loaded ? 'module-dot--on' : ''}`} />
							<div>
								<strong>i2c-dev</strong>
								<span>{diagnostics.i2c_dev_loaded ? 'loaded' : 'not loaded'}</span>
							</div>
							<span className="host-module-row__count">{diagnostics.i2c_adapters.length} buses</span>
						</div>
						<div className="host-module-row">
							<span className={`module-dot ${diagnostics.smbus_loaded ? 'module-dot--on' : ''}`} />
							<div>
								<strong>SMBus driver</strong>
								<span>{diagnostics.smbus_loaded ? 'loaded' : 'not detected'}</span>
							</div>
							<span className="host-module-row__count">{diagnostics.hidraw.length} hidraw</span>
						</div>
						<Button variant="quiet" size="sm" onClick={() => onNavigate('settings')} icon={<ChevronRight size={14} />}>
							Host setup notes
						</Button>
					</Card>
				</aside>
			</div>
		</div>
	)
}

function MetricCard({
	icon,
	label,
	value,
	detail,
	colour,
	values,
	children,
}: {
	icon: ReactNode
	label: string
	value: string
	detail: string
	colour: string
	values: number[]
	children: ReactNode
}) {
	return (
		<Card className="metric-card" interactive>
			<div className="metric__top">
				<span className="metric__icon" style={{color: colour}}>
					{icon}
				</span>
				<span className="metric__label">{label}</span>
				<span className="metric__value">{value}</span>
			</div>
			<div className="metric__chart">
				<Sparkline values={values} colour={colour} width={180} height={36} />
			</div>
			{children}
			<div className="metric__detail">{detail}</div>
		</Card>
	)
}

function DeviceLightRow({
	device,
	live,
	onMap,
}: {
	device: Device
	live: Live | null
	onMap: (zoneId: string) => void
}) {
	const mappedZones = live?.zone_colors ?? {}
	return (
		<div className="device-light-row">
			<div className="device-light-row__identity">
				<span className="device-light-row__icon">
					<DeviceGlyph type={device.type} size={17} />
				</span>
				<div>
					<strong>{device.name}</strong>
					<span>
						{deviceTypeLabel(device.type)} · {device.led_count} LEDs
					</span>
				</div>
			</div>
			<div className="device-light-row__zones">
				{device.zones.map((zone) => (
					<div className="zone-light" key={zone.id}>
						<div className="zone-light__meta">
							<span>{zone.name}</span>
							<button type="button" className="zone-light__map" onClick={() => onMap(zone.id)}>
								map
							</button>
						</div>
						<LedStrip colors={mappedZones[zone.id]} count={zone.led_count} size="sm" />
					</div>
				))}
			</div>
		</div>
	)
}
