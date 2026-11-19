import {useMemo, useState} from 'react'
import {
	Check,
	ExternalLink,
	KeyRound,
	Play,
	Plus,
	ShieldCheck,
	Terminal,
	Trash2,
	Webhook,
	Zap,
} from 'lucide-react'
import type {Bootstrap, Effect, Live, Preset, WebhookLog} from '../types'
import {
	Button,
	Card,
	CopyButton,
	EmptyState,
	Field,
	IconButton,
	Modal,
	Pill,
	RangeField,
	Select,
} from '../components/ui'
import {api, del, post} from '../lib/api'
import {effectLabel, timeAgo} from '../lib/util'

interface Props {
	bootstrap: Bootstrap
	live: Live | null
	onChanged: () => void
	notify: (message: string, tone?: 'success' | 'error' | 'info') => void
}

const EFFECTS: Effect[] = ['flash', 'pulse', 'breathe', 'solid', 'rainbow']

export function Webhooks({bootstrap, live, onChanged, notify}: Props) {
	const [showToken, setShowToken] = useState(false)
	const [eventName, setEventName] = useState('download_complete')
	const [colour, setColour] = useState('#3b82f6')
	const [effect, setEffect] = useState<Effect>('flash')
	const [duration, setDuration] = useState(6)
	const [brightness, setBrightness] = useState(100)
	const [target, setTarget] = useState<'managed' | 'all'>('all')
	const [sending, setSending] = useState(false)
	const [presetModal, setPresetModal] = useState(false)
	const [clearing, setClearing] = useState(false)

	const origin = typeof window === 'undefined' ? 'http://umbrel.local:4287' : window.location.origin
	const token = bootstrap.webhook.token
	const endpoint = `${origin}/api/webhook/${eventName || 'event_name'}`
	const curl = useMemo(() => {
		const body = JSON.stringify(
			{color: colour, effect, duration, brightness, target},
			null,
			2,
		).replace(/\n/g, '\n  ')
		return `curl -X POST '${endpoint}' \\\n  -H 'Authorization: Bearer ${token}' \\\n  -H 'Content-Type: application/json' \\\n  -d '${body}'`
	}, [endpoint, token, colour, effect, duration, brightness, target])

	const send = async () => {
		if (!/^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$/.test(eventName)) {
			notify('Event names may contain letters, numbers, dots, underscores, and hyphens', 'error')
			return
		}
		setSending(true)
		try {
			await api(`/api/webhook/${encodeURIComponent(eventName)}`, {
				method: 'POST',
				headers: {Authorization: `Bearer ${token}`},
				body: JSON.stringify({color: colour, effect, duration, brightness, target}),
			})
			notify(`Test webhook “${eventName}” delivered`, 'success')
			onChanged()
		} catch (error) {
			notify(error instanceof Error ? error.message : 'Webhook delivery failed', 'error')
		} finally {
			setSending(false)
		}
	}

	const clearLogs = async () => {
		setClearing(true)
		try {
			await del('/api/webhooks/logs')
			notify('Webhook log cleared', 'success')
			onChanged()
		} catch (error) {
			notify(error instanceof Error ? error.message : 'Could not clear logs', 'error')
		} finally {
			setClearing(false)
		}
	}

	const deletePreset = async (preset: Preset) => {
		try {
			await del(`/api/webhooks/presets/${encodeURIComponent(preset.event)}`)
			notify(`Preset “${preset.event}” removed`, 'success')
			onChanged()
		} catch (error) {
			notify(error instanceof Error ? error.message : 'Could not delete preset', 'error')
		}
	}

	const logs = bootstrap.logs
	const successful = logs.filter((log) => log.outcome === 'applied').length

	return (
		<div className="stack webhooks-page">
			<div className="webhook-hero">
				<Card className="token-card">
					<div className="token-card__head">
						<span className="token-card__icon">
							<KeyRound size={18} />
						</span>
						<div>
							<div className="eyebrow">Webhook bearer token</div>
							<h2>One token. Any event.</h2>
						</div>
						<Pill tone="mint" dot>
							required
						</Pill>
					</div>
					<div className="token-value">
						<code>{showToken ? token : `${token.slice(0, 8)}${'•'.repeat(28)}${token.slice(-4)}`}</code>
						<button type="button" className="text-link" onClick={() => setShowToken((value) => !value)}>
							{showToken ? 'hide' : 'reveal'}
						</button>
						<CopyButton value={token} label="Copy token" />
					</div>
					<p className="token-card__note">
						External services cannot use an Umbrel session cookie. The webhook route is the only public path; every
						request must carry this token. It is stable across restarts and app updates.
					</p>
					<div className="token-card__stats">
						<div>
							<span>Delivered</span>
							<strong>{successful}</strong>
						</div>
						<div>
							<span>Last event</span>
							<strong>{live?.last_webhook?.event ?? '—'}</strong>
						</div>
						<div>
							<span>Active overrides</span>
							<strong>{live?.overlays.length ?? 0}</strong>
						</div>
					</div>
				</Card>

				<Card className="request-card">
					<div className="section-head section-head--compact">
						<div>
							<div className="eyebrow">Request builder</div>
							<h2 className="section-title section-title--sm">Trigger a light override</h2>
						</div>
						<Terminal size={17} className="muted-icon" />
					</div>
					<div className="request-grid">
						<Field label="Event name" htmlFor="webhook-event">
							<input
								id="webhook-event"
								className="input"
								value={eventName}
								maxLength={64}
								onChange={(event) => setEventName(event.target.value)}
								placeholder="download_complete"
							/>
						</Field>
						<Field label="Colour">
							<div className="colour-input">
								<input
									type="color"
									value={colour}
									onChange={(event) => setColour(event.target.value)}
									aria-label="Webhook colour"
								/>
								<input className="input" value={colour} maxLength={7} onChange={(event) => setColour(event.target.value)} aria-label="Webhook hex colour" />
							</div>
						</Field>
						<Field label="Effect">
							<Select value={effect} onChange={(value) => setEffect(value as Effect)}>
								{EFFECTS.map((item) => (
									<option key={item} value={item}>
										{effectLabel(item)}
									</option>
								))}
							</Select>
						</Field>
						<Field label="Scope">
							<Select value={target} onChange={(value) => setTarget(value as 'managed' | 'all')}>
								<option value="all">All zones</option>
								<option value="managed">Managed zones only</option>
							</Select>
						</Field>
					</div>
					<RangeField
						label="Duration"
						value={duration}
						min={0.5}
						max={30}
						step={0.5}
						suffix="s"
						onChange={setDuration}
					/>
					<RangeField
						label="Brightness"
						value={brightness}
						min={0}
						max={100}
						step={5}
						suffix="%"
						onChange={setBrightness}
					/>
					<div className="request-endpoint">
						<span>POST</span>
						<code>{endpoint}</code>
					</div>
					<div className="request-actions">
						<Button variant="primary" onClick={send} disabled={sending} icon={<Play size={14} />}>
							{sending ? 'Sending…' : 'Send test webhook'}
						</Button>
						<CopyButton value={curl} label="Copy curl" />
					</div>
				</Card>
			</div>

			<Card className="curl-card">
				<div className="section-head section-head--compact">
					<div>
						<div className="eyebrow">Copy & paste</div>
						<h2 className="section-title section-title--sm">curl snippet</h2>
					</div>
					<CopyButton value={curl} label="Copy" />
				</div>
				<pre className="code-block">
					<code>{curl}</code>
				</pre>
				<div className="curl-card__footer">
					<span>
						<ShieldCheck size={14} /> Token-protected through the public `/api/webhook/*` route.
					</span>
					<span>
						<ExternalLink size={14} /> Works with Home Assistant, Jellyfin, qBittorrent, Uptime Kuma, Frigate, and CI.
					</span>
				</div>
			</Card>

			<div className="section-split">
				<Card className="section-card">
					<div className="section-head">
						<div>
							<div className="eyebrow">Reusable behaviours</div>
							<h2 className="section-title">Event presets</h2>
						</div>
						<Button variant="secondary" size="sm" icon={<Plus size={14} />} onClick={() => setPresetModal(true)}>
							New preset
						</Button>
					</div>
					{bootstrap.presets.length === 0 ? (
						<div className="empty-inline empty-inline--boxed">
							<Zap size={16} />
							<span>No presets. Add one to trigger lights with an empty webhook body.</span>
						</div>
					) : (
						<div className="preset-list">
							{bootstrap.presets.map((preset) => (
								<div className="preset-row" key={preset.event}>
									<span
										className="preset-row__swatch"
										style={{background: preset.color, boxShadow: `0 0 12px ${preset.color}66`}}
									/>
									<div className="preset-row__body">
										<code>{preset.event}</code>
										<span>
											{effectLabel(preset.effect)} · {preset.duration}s · {preset.brightness}%
										</span>
									</div>
									<button
										type="button"
										className="preset-row__send"
										onClick={() => {
											setEventName(preset.event)
											setColour(preset.color)
											setEffect(preset.effect)
											setDuration(preset.duration)
											setBrightness(preset.brightness)
											notify('Preset loaded into the request builder', 'info')
										}}
									>
										load
									</button>
									<IconButton label={`Delete ${preset.event}`} onClick={() => deletePreset(preset)}>
										<Trash2 size={14} />
									</IconButton>
								</div>
							))}
						</div>
					)}
				</Card>

				<Card className="section-card">
					<div className="section-head">
						<div>
							<div className="eyebrow">Delivery history</div>
							<h2 className="section-title">Webhook log</h2>
						</div>
						<Button variant="quiet" size="sm" onClick={clearLogs} disabled={clearing || logs.length === 0} icon={<Trash2 size={13} />}>
							Clear
						</Button>
					</div>
					{logs.length === 0 ? (
						<EmptyState
							icon={<Webhook size={24} />}
							title="No webhook calls yet"
							description="Send a test from the request builder or point an integration at the endpoint above."
						/>
					) : (
						<div className="log-list">
							{logs.slice(0, 12).map((log) => (
								<LogRow key={log.id} log={log} />
							))}
						</div>
					)}
				</Card>
			</div>

			<PresetModal
				open={presetModal}
				onClose={() => setPresetModal(false)}
				onSaved={() => {
					setPresetModal(false)
					onChanged()
				}}
				notify={notify}
			/>
		</div>
	)
}

function LogRow({log}: {log: WebhookLog}) {
	const applied = log.outcome === 'applied'
	return (
		<div className="log-row">
			<span className={`log-row__dot ${applied ? 'is-ok' : 'is-warn'}`} />
			<div className="log-row__main">
				<code>{log.event}</code>
				<span>
					{log.detail.effect ? `${log.detail.effect} · ${log.detail.duration ?? '—'}s` : log.outcome}
					{log.detail.message ? ` · ${log.detail.message}` : ''}
				</span>
			</div>
			<div className="log-row__meta">
				<Pill tone={applied ? 'mint' : 'amber'}>{log.outcome}</Pill>
				<span>{log.source_ip}</span>
				<span>{timeAgo(log.created_at)}</span>
			</div>
		</div>
	)
}

function PresetModal({
	open,
	onClose,
	onSaved,
	notify,
}: {
	open: boolean
	onClose: () => void
	onSaved: () => void
	notify: (message: string, tone?: 'success' | 'error' | 'info') => void
}) {
	const [event, setEvent] = useState('')
	const [colour, setColour] = useState('#22d3ee')
	const [effect, setEffect] = useState<Effect>('flash')
	const [duration, setDuration] = useState(5)
	const [brightness, setBrightness] = useState(100)
	const [busy, setBusy] = useState(false)

	const save = async () => {
		setBusy(true)
		try {
			await post('/api/webhooks/presets', {
				event: event.trim(),
				color: colour,
				effect,
				duration,
				brightness,
			})
			notify('Webhook preset saved', 'success')
			onSaved()
		} catch (error) {
			notify(error instanceof Error ? error.message : 'Could not save preset', 'error')
		} finally {
			setBusy(false)
		}
	}

	return (
		<Modal
			open={open}
			onClose={onClose}
			title="New webhook preset"
			eyebrow="Reusable event behaviour"
			width="md"
			footer={
				<>
					<Button variant="quiet" onClick={onClose}>
						Cancel
					</Button>
					<Button variant="primary" onClick={save} disabled={busy || !event.trim()} icon={<Check size={14} />}>
						Save preset
					</Button>
				</>
			}
		>
			<div className="form-stack">
				<Field label="Event name" hint="A body-less POST to /api/webhook/<event> uses these values.">
					<input
						className="input"
						value={event}
						onChange={(changeEvent) => setEvent(changeEvent.target.value)}
						placeholder="backup_complete"
						maxLength={64}
					/>
				</Field>
				<Field label="Colour">
					<div className="colour-input">
						<input type="color" value={colour} onChange={(changeEvent) => setColour(changeEvent.target.value)} />
						<input className="input" value={colour} onChange={(changeEvent) => setColour(changeEvent.target.value)} maxLength={7} />
					</div>
				</Field>
				<Field label="Effect">
					<Select value={effect} onChange={(value) => setEffect(value as Effect)}>
						{EFFECTS.map((item) => (
							<option key={item} value={item}>
								{effectLabel(item)}
							</option>
						))}
					</Select>
				</Field>
				<RangeField label="Duration" value={duration} min={0.5} max={30} step={0.5} suffix="s" onChange={setDuration} />
				<RangeField label="Brightness" value={brightness} min={0} max={100} step={5} suffix="%" onChange={setBrightness} />
			</div>
		</Modal>
	)
}
