import {useEffect, useMemo, useState} from 'react'
import {
	AlertTriangle,
	Check,
	Clock3,
	Cpu,
	HardDrive,
	Info,
	Moon,
	RefreshCw,
	Save,
	Shield,
	Sun,
	Terminal,
	Thermometer,
	Trash2,
	Zap,
} from 'lucide-react'
import type {Bootstrap, Live, Settings as SettingsType} from '../types'
import {Button, Card, Field, KeyValue, Pill, RangeField, Select, Toggle} from '../components/ui'
import {del, post, put} from '../lib/api'
import {formatBytes, formatUptime} from '../lib/util'

interface Props {
	bootstrap: Bootstrap
	live: Live | null
	onChanged: () => void
	notify: (message: string, tone?: 'success' | 'error' | 'info') => void
}

export function Settings({bootstrap, live, onChanged, notify}: Props) {
	const [draft, setDraft] = useState<SettingsType>(bootstrap.settings)
	const [saving, setSaving] = useState(false)
	const [rescanning, setRescanning] = useState(false)
	const [clearing, setClearing] = useState(false)
	const settingsKey = JSON.stringify(bootstrap.settings)

	useEffect(() => {
		setDraft(bootstrap.settings)
	}, [settingsKey])

	const patch = (value: Partial<SettingsType>) => setDraft((current) => ({...current, ...value}))
	const patchNight = (value: Partial<SettingsType['night']>) =>
		setDraft((current) => ({...current, night: {...current.night, ...value}}))

	const sensors = bootstrap.sensors
	const cpuSensors = sensors.filter((sensor) => sensor.kind === 'cpu' || sensor.kind === 'other')
	const gpuSensors = sensors.filter((sensor) => sensor.kind === 'gpu')

	const diagnostics = live?.diagnostics ?? bootstrap.diagnostics
	const save = async () => {
		setSaving(true)
		try {
			await put('/api/settings', draft)
			notify('Settings saved. The renderer picked up the change.', 'success')
			onChanged()
		} catch (error) {
			notify(error instanceof Error ? error.message : 'Could not save settings', 'error')
		} finally {
			setSaving(false)
		}
	}

	const rescan = async () => {
		setRescanning(true)
		try {
			await post('/api/devices/rescan')
			notify('OpenRGB rescan requested', 'info')
			window.setTimeout(onChanged, 2200)
		} catch (error) {
			notify(error instanceof Error ? error.message : 'Could not request rescan', 'error')
		} finally {
			setRescanning(false)
		}
	}

	const clearOverlays = async () => {
		setClearing(true)
		try {
			const result = await del<{cleared: number}>('/api/overlays')
			notify(`${result.cleared} temporary override${result.cleared === 1 ? '' : 's'} cleared`, 'success')
			onChanged()
		} catch (error) {
			notify(error instanceof Error ? error.message : 'Could not clear overrides', 'error')
		} finally {
			setClearing(false)
		}
	}

	const currentStorage = useMemo(
		() =>
			bootstrap.mounts.find((mount) => mount.path === draft.storage_path) ??
			Object.values(bootstrap.telemetry.storage ?? {}).find((entry) => entry.path === draft.storage_path),
		[bootstrap.mounts, bootstrap.telemetry.storage, draft.storage_path],
	)

	return (
		<div className="settings-page">
			<div className="settings-topline">
				<div className="settings-topline__state">
					<Pill tone={live?.hardware.connected ? 'mint' : 'red'} dot>
						{live?.hardware.connected ? 'Controller online' : 'Controller offline'}
					</Pill>
					{live?.night_active ? (
						<Pill tone="blue" dot>
							Quiet hours active
						</Pill>
					) : null}
					{live?.overlays.length ? <Pill tone="amber">{live.overlays.length} override(s)</Pill> : null}
				</div>
				<Button variant="primary" onClick={save} disabled={saving} icon={<Save size={14} />}>
					{saving ? 'Saving…' : 'Save settings'}
				</Button>
			</div>

			<div className="settings-grid">
				<div className="settings-column">
					<Card className="settings-card">
						<div className="section-head">
							<div>
								<div className="eyebrow">Render engine</div>
								<h2 className="section-title">Light output</h2>
							</div>
							<Sun size={18} className="muted-icon" />
						</div>
						<RangeField
							label="Master brightness"
							value={draft.brightness}
							min={0}
							max={100}
							suffix="%"
							onChange={(value) => patch({brightness: value})}
							hint="Scales every mapping, night mode, and temporary override."
						/>
						<RangeField
							label="Render rate"
							value={draft.fps}
							min={1}
							max={20}
							suffix=" fps"
							onChange={(value) => patch({fps: value})}
							hint="Six frames per second is smooth and light on CPU. Increase for faster animations."
						/>
						<div className="inline-toggle inline-toggle--row">
							<Toggle checked={draft.smoothing} onChange={(value) => patch({smoothing: value})} label="Smooth telemetry" />
							<div>
								<strong>Telemetry smoothing</strong>
								<span>Ease temperature and load changes instead of jumping between frames.</span>
							</div>
						</div>
					</Card>

					<Card className="settings-card">
						<div className="section-head">
							<div>
								<div className="eyebrow">Storage source</div>
								<h2 className="section-title">Fill gauge path</h2>
							</div>
							<HardDrive size={18} className="muted-icon" />
						</div>
						<Field
							label="Default mount point"
							hint="Memory mappings can override this path. The backend reads the host file system read-only."
						>
							<input
								className="input"
								list="settings-mounts"
								value={draft.storage_path}
								onChange={(event) => patch({storage_path: event.target.value})}
								placeholder="/"
							/>
							<datalist id="settings-mounts">
								{bootstrap.mounts.map((mount) => (
									<option key={mount.path} value={mount.path}>
										{mount.path}
									</option>
								))}
							</datalist>
						</Field>
						{currentStorage ? (
							<div className="storage-preview">
								<div>
									<span>{currentStorage.path}</span>
									<strong>{formatBytes('free' in currentStorage ? currentStorage.free : 0)} free</strong>
								</div>
								<div>
									<span>Capacity</span>
									<strong>{formatBytes(currentStorage.total)}</strong>
								</div>
							</div>
						) : null}
						<div className="mount-list">
							{bootstrap.mounts.slice(0, 6).map((mount) => (
								<button
									key={mount.path}
									type="button"
									className={`mount-chip ${draft.storage_path === mount.path ? 'mount-chip--active' : ''}`}
									onClick={() => patch({storage_path: mount.path})}
								>
									<span>{mount.path}</span>
									<small>{formatBytes(mount.free)} free</small>
								</button>
							))}
						</div>
					</Card>

					<Card className="settings-card">
						<div className="section-head">
							<div>
								<div className="eyebrow">Sensors</div>
								<h2 className="section-title">Thermal inputs</h2>
							</div>
							<Thermometer size={18} className="muted-icon" />
						</div>
						<Field label="CPU temperature sensor" hint="Auto prefers Package id 0 or Tctl/Tdie, then the hottest CPU sensor.">
							<Select value={draft.cpu_sensor} onChange={(value) => patch({cpu_sensor: value})}>
								<option value="auto">Auto-detect</option>
								{cpuSensors.map((sensor) => (
									<option key={sensor.id} value={sensor.id}>
										{sensor.label} · {sensor.temp.toFixed(1)}°C
									</option>
								))}
							</Select>
						</Field>
						<Field label="GPU temperature sensor" hint="NVIDIA GPUs use nvidia-smi when available; AMD uses the amdgpu hwmon sensor.">
							<Select value={draft.gpu_sensor} onChange={(value) => patch({gpu_sensor: value})}>
								<option value="auto">Auto-detect</option>
								{gpuSensors.map((sensor) => (
									<option key={sensor.id} value={sensor.id}>
										{sensor.label} · {sensor.temp.toFixed(1)}°C
									</option>
								))}
							</Select>
						</Field>
						<div className="sensor-readout">
							<div>
								<Cpu size={15} />
								<span>CPU now</span>
								<strong>{live?.telemetry.cpu.temp !== null && live?.telemetry.cpu.temp !== undefined ? `${live.telemetry.cpu.temp.toFixed(1)}°C` : '—'}</strong>
							</div>
							<div>
								<Zap size={15} />
								<span>GPU now</span>
								<strong>{live?.telemetry.gpu?.temp !== null && live?.telemetry.gpu?.temp !== undefined ? `${live.telemetry.gpu.temp.toFixed(1)}°C` : '—'}</strong>
							</div>
						</div>
					</Card>
				</div>

				<div className="settings-column">
					<Card className="settings-card">
						<div className="section-head">
							<div>
								<div className="eyebrow">Quiet hours</div>
								<h2 className="section-title">Night schedule</h2>
							</div>
							<Moon size={18} className="muted-icon" />
						</div>
						<div className="inline-toggle inline-toggle--row">
							<Toggle checked={draft.night.enabled} onChange={(value) => patchNight({enabled: value})} label="Enable quiet hours" />
							<div>
								<strong>Dim or dark at night</strong>
								<span>Applies to mapped zones after webhook overrides expire.</span>
							</div>
						</div>
						<Field
							label="Timezone"
							hint="IANA timezone used for the schedule. Set this to your local zone; the container itself may run in UTC."
						>
							<input
								className="input"
								list="timezone-options"
								value={draft.timezone}
								onChange={(event) => patch({timezone: event.target.value})}
								placeholder="Europe/London"
							/>
							<datalist id="timezone-options">
								{[
									'Etc/UTC',
									'Europe/London',
									'Europe/Berlin',
									'Europe/Paris',
									'Europe/Madrid',
									'America/New_York',
									'America/Chicago',
									'America/Denver',
									'America/Los_Angeles',
									'Asia/Riyadh',
									'Asia/Dubai',
									'Asia/Kolkata',
									'Asia/Singapore',
									'Asia/Tokyo',
									'Australia/Sydney',
								].map((zone) => (
									<option key={zone} value={zone} />
								))}
							</datalist>
						</Field>
						<div className="editor-grid editor-grid--tight">
							<Field label="Starts">
								<input
									className="input"
									type="time"
									value={draft.night.start}
									onChange={(event) => patchNight({start: event.target.value})}
								/>
							</Field>
							<Field label="Ends">
								<input
									className="input"
									type="time"
									value={draft.night.end}
									onChange={(event) => patchNight({end: event.target.value})}
								/>
							</Field>
							<Field label="Behaviour">
								<Select value={draft.night.behaviour} onChange={(value) => patchNight({behaviour: value as 'dim' | 'off'})}>
									<option value="dim">Dim to colour</option>
									<option value="off">Switch off</option>
								</Select>
							</Field>
							<Field label="Night colour">
								<div className="colour-input">
									<input
										type="color"
										value={draft.night.color}
										onChange={(event) => patchNight({color: event.target.value})}
										aria-label="Night colour"
									/>
									<input
										className="input"
										value={draft.night.color}
										maxLength={7}
										onChange={(event) => patchNight({color: event.target.value})}
										aria-label="Night hex colour"
									/>
								</div>
							</Field>
						</div>
						{draft.night.behaviour === 'dim' ? (
							<RangeField
								label="Night brightness"
								value={draft.night.brightness}
								min={0}
								max={100}
								suffix="%"
								onChange={(value) => patchNight({brightness: value})}
							/>
						) : null}
						<div className="schedule-hint">
							<Clock3 size={14} />
							<span>
								{live?.night_active
									? 'Quiet hours are active right now.'
									: 'Quiet hours use the controller’s local timezone.'}
							</span>
						</div>
					</Card>

					<Card className="settings-card">
						<div className="section-head">
							<div>
								<div className="eyebrow">Host access</div>
								<h2 className="section-title">SMBus diagnostics</h2>
							</div>
							<Info size={18} className="muted-icon" />
						</div>
						<div className="diagnostic-grid">
							<div>
								<span>i2c-dev module</span>
								<Pill tone={diagnostics.i2c_dev_loaded ? 'mint' : 'amber'}>
									{diagnostics.i2c_dev_loaded ? 'loaded' : 'not loaded'}
								</Pill>
							</div>
							<div>
								<span>SMBus driver</span>
								<Pill tone={diagnostics.smbus_loaded ? 'mint' : 'amber'}>
									{diagnostics.smbus_loaded ? 'loaded' : 'not detected'}
								</Pill>
							</div>
							<div>
								<span>I2C adapters</span>
								<strong>{diagnostics.i2c_adapters.length}</strong>
							</div>
							<div>
								<span>hidraw nodes</span>
								<strong>{diagnostics.hidraw.length}</strong>
							</div>
						</div>
						<div className="chip-row">
							{diagnostics.i2c_adapters.slice(0, 10).map((adapter) => (
								<span className="hardware-tag" key={adapter}>
									{adapter}
								</span>
							))}
							{diagnostics.i2c_adapters.length === 0 ? <span className="muted">No adapters visible</span> : null}
						</div>
						{diagnostics.recommendations.length > 0 ? (
							<div className="recommendation-list">
								{diagnostics.recommendations.map((recommendation) => (
									<div key={recommendation} className="recommendation">
										<AlertTriangle size={14} />
										<span>{recommendation}</span>
									</div>
								))}
							</div>
						) : (
							<div className="recommendation recommendation--ok">
								<Check size={14} />
								<span>Host SMBus and HID interfaces look available.</span>
							</div>
						)}
						<div className="command-block">
							<Terminal size={15} />
							<code>sudo modprobe i2c-dev && sudo modprobe i2c-i801</code>
							<span>Intel host · use i2c-piix4 for AMD</span>
						</div>
						<Button variant="secondary" size="sm" onClick={rescan} disabled={rescanning} icon={<RefreshCw size={14} className={rescanning ? 'spin' : ''} />}>
							Rescan OpenRGB devices
						</Button>
					</Card>

					<Card className="settings-card">
						<div className="section-head">
							<div>
								<div className="eyebrow">Machine</div>
								<h2 className="section-title">Host information</h2>
							</div>
							<Shield size={18} className="muted-icon" />
						</div>
						<div className="kv-list">
							<KeyValue label="Hostname" value={diagnostics.host.hostname || '—'} />
							<KeyValue label="OS" value={diagnostics.host.os_name || '—'} />
							<KeyValue label="CPU" value={diagnostics.host.cpu_model || '—'} />
							<KeyValue label="Threads" value={String(diagnostics.host.cpu_cores || '—')} />
							<KeyValue label="Uptime" value={formatUptime(diagnostics.host.uptime)} />
							<KeyValue label="I2C buses" value={String(diagnostics.i2c_adapters.length)} />
							<KeyValue label="USB devices" value={String(diagnostics.usb_device_count)} />
						</div>
					</Card>

					<Card className="settings-card settings-card--danger">
						<div className="section-head">
							<div>
								<div className="eyebrow">Maintenance</div>
								<h2 className="section-title">Temporary overrides</h2>
							</div>
							<Trash2 size={18} className="muted-icon" />
						</div>
						<p className="muted-copy">
							Clear every webhook and test overlay immediately. The active telemetry mapping takes over on the next
							frame.
						</p>
						<Button variant="danger" size="sm" onClick={clearOverlays} disabled={clearing || !live?.overlays.length} icon={<Trash2 size={14} />}>
							{clearing ? 'Clearing…' : `Clear ${live?.overlays.length ?? 0} override(s)`}
						</Button>
					</Card>
				</div>
			</div>
		</div>
	)
}
