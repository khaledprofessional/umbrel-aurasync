import {useCallback, useEffect, useRef, useState} from 'react'
import {AlertCircle, CheckCircle2, Info, Sparkles, X} from 'lucide-react'
import type {Bootstrap, Live, TargetType} from './types'
import type {Page} from './navigation'
import {api, post} from './lib/api'
import {Sidebar} from './components/Sidebar'
import {Topbar} from './components/Topbar'
import {Button, Field, Modal, RangeField, Select} from './components/ui'
import {Overview} from './pages/Overview'
import {Devices} from './pages/Devices'
import {Mappings} from './pages/Mappings'
import {Webhooks} from './pages/Webhooks'
import {Settings} from './pages/Settings'

type ToastTone = 'success' | 'error' | 'info'
interface Toast {
	id: number
	message: string
	tone: ToastTone
}

const COLOUR_PRESETS = ['#22d3ee', '#3b82f6', '#22c55e', '#fbbf24', '#f97316', '#ef4444', '#a78bfa', '#f472b6']

function pageFromHash(): Page {
	const hash = window.location.hash.replace('#', '')
	if (['overview', 'devices', 'mappings', 'webhooks', 'settings'].includes(hash)) {
		return hash as Page
	}
	return 'overview'
}

export default function App() {
	const [page, setPage] = useState<Page>(pageFromHash)
	const [bootstrap, setBootstrap] = useState<Bootstrap | null>(null)
	const [live, setLive] = useState<Live | null>(null)
	const [loading, setLoading] = useState(true)
	const [fatal, setFatal] = useState<string | null>(null)
	const [refreshing, setRefreshing] = useState(false)
	const [toasts, setToasts] = useState<Toast[]>([])
	const [flashOpen, setFlashOpen] = useState(false)
	const [prefill, setPrefill] = useState<{type: TargetType; id: string} | null>(null)
	const toastId = useRef(1)
	const timerIds = useRef<number[]>([])
	const hasBootstrap = useRef(false)

	const notify = useCallback((message: string, tone: ToastTone = 'info') => {
		const id = toastId.current++
		setToasts((current) => [...current.slice(-3), {id, message, tone}])
		const timer = window.setTimeout(() => {
			setToasts((current) => current.filter((toast) => toast.id !== id))
		}, 4600)
		timerIds.current.push(timer)
	}, [])

	useEffect(() => {
		return () => {
			for (const timer of timerIds.current) window.clearTimeout(timer)
			timerIds.current = []
		}
	}, [])

	const loadBootstrap = useCallback(async (quiet = false) => {
		if (!quiet) setRefreshing(true)
		try {
			const data = await api<Bootstrap>('/api/bootstrap')
			hasBootstrap.current = true
			setBootstrap(data)
			setFatal(null)
		} catch (error) {
			const message = error instanceof Error ? error.message : 'Could not reach the AuraSync API'
			if (!hasBootstrap.current) setFatal(message)
			else if (!quiet) notify(message, 'error')
		} finally {
			setLoading(false)
			if (!quiet) setRefreshing(false)
		}
	}, [notify])

	const loadLive = useCallback(async () => {
		try {
			const data = await api<Live>('/api/live')
			setLive(data)
		} catch {
			// Keep the last known frame; the topbar and connection pills show stale state.
		}
	}, [])

	useEffect(() => {
		void loadBootstrap()
		void loadLive()
		const interval = window.setInterval(() => {
			if (document.visibilityState === 'visible') void loadLive()
		}, 2000)
		const onVisible = () => {
			if (document.visibilityState === 'visible') void loadLive()
		}
		document.addEventListener('visibilitychange', onVisible)
		return () => {
			window.clearInterval(interval)
			document.removeEventListener('visibilitychange', onVisible)
		}
	}, [loadBootstrap, loadLive])

	useEffect(() => {
		const onHash = () => setPage(pageFromHash())
		window.addEventListener('hashchange', onHash)
		return () => window.removeEventListener('hashchange', onHash)
	}, [])

	const navigate = (next: Page) => {
		setPage(next)
		window.location.hash = next === 'overview' ? '' : next
		window.scrollTo({top: 0, behavior: 'smooth'})
	}

	const refresh = () => {
		void loadBootstrap()
		void loadLive()
	}

	const startMapping = (type: TargetType, id: string) => {
		setPrefill({type, id})
		navigate('mappings')
	}

	const consumedPrefill = useCallback(() => setPrefill(null), [])

	if (loading) {
		return (
			<div className="boot-screen">
				<div className="boot-screen__ring">
					<img src="/aura.svg" alt="" width={72} height={72} />
				</div>
				<div className="boot-screen__name">AuraSync</div>
				<div className="boot-screen__status">Bringing the light field online…</div>
			</div>
		)
	}

	if (!bootstrap) {
		return (
			<div className="boot-screen boot-screen--error">
				<AlertCircle size={34} />
				<div className="boot-screen__name">AuraSync could not start</div>
				<div className="boot-screen__status">{fatal ?? 'The API is unavailable.'}</div>
				<Button variant="primary" onClick={() => void loadBootstrap()}>
					Try again
				</Button>
			</div>
		)
	}

	return (
		<div className="app-shell">
			<Sidebar page={page} onNavigate={navigate} live={live} version={bootstrap.server.version} />
			<main className="main">
				<Topbar page={page} live={live} onRefresh={refresh} refreshing={refreshing} onFlash={() => setFlashOpen(true)} />
				<div className="page">
					{page === 'overview' ? (
						<Overview
							bootstrap={bootstrap}
							live={live}
							onNavigate={navigate}
							onCreateMapping={startMapping}
						/>
					) : null}
					{page === 'devices' ? (
						<Devices
							bootstrap={bootstrap}
							live={live}
							onCreateMapping={startMapping}
							onChanged={() => void loadBootstrap(true)}
							notify={notify}
						/>
					) : null}
					{page === 'mappings' ? (
						<Mappings
							bootstrap={bootstrap}
							live={live}
							prefill={prefill}
							onPrefillConsumed={consumedPrefill}
							onChanged={() => void loadBootstrap(true)}
							notify={notify}
						/>
					) : null}
					{page === 'webhooks' ? (
						<Webhooks
							bootstrap={bootstrap}
							live={live}
							onChanged={() => void loadBootstrap(true)}
							notify={notify}
						/>
					) : null}
					{page === 'settings' ? (
						<Settings
							bootstrap={bootstrap}
							live={live}
							onChanged={() => void loadBootstrap(true)}
							notify={notify}
						/>
					) : null}
				</div>
			</main>

			<FlashModal
				open={flashOpen}
				onClose={() => setFlashOpen(false)}
				notify={notify}
				onSent={() => void loadLive()}
			/>

			<div className="toast-stack" aria-live="polite">
				{toasts.map((toast) => (
					<div key={toast.id} className={`toast toast--${toast.tone}`}>
						{toast.tone === 'success' ? (
							<CheckCircle2 size={16} />
						) : toast.tone === 'error' ? (
							<AlertCircle size={16} />
						) : (
							<Info size={16} />
						)}
						<span>{toast.message}</span>
						<button
							type="button"
							onClick={() => setToasts((current) => current.filter((item) => item.id !== toast.id))}
							aria-label="Dismiss notification"
						>
							<X size={14} />
						</button>
					</div>
				))}
			</div>
		</div>
	)
}

function FlashModal({
	open,
	onClose,
	notify,
	onSent,
}: {
	open: boolean
	onClose: () => void
	notify: (message: string, tone?: ToastTone) => void
	onSent: () => void
}) {
	const [colour, setColour] = useState('#22d3ee')
	const [effect, setEffect] = useState<'solid' | 'flash' | 'pulse' | 'breathe' | 'rainbow'>('flash')
	const [duration, setDuration] = useState(5)
	const [brightness, setBrightness] = useState(100)
	const [target, setTarget] = useState<'managed' | 'all'>('all')
	const [busy, setBusy] = useState(false)

	const send = async () => {
		setBusy(true)
		try {
			await post('/api/test', {color: colour, effect, duration, brightness, target})
			notify('Test overlay sent to the light field', 'success')
			onSent()
			onClose()
		} catch (error) {
			notify(error instanceof Error ? error.message : 'Could not send test', 'error')
		} finally {
			setBusy(false)
		}
	}

	return (
		<Modal
			open={open}
			onClose={onClose}
			title="Send a test to the lights"
			eyebrow="Hardware preview"
			width="sm"
			footer={
				<>
					<Button variant="quiet" onClick={onClose}>
						Cancel
					</Button>
					<Button variant="primary" onClick={send} disabled={busy} icon={<Sparkles size={14} />}>
						{busy ? 'Sending…' : 'Light it up'}
					</Button>
				</>
			}
		>
			<div className="form-stack">
				<Field label="Colour">
					<div className="colour-swatches">
						{COLOUR_PRESETS.map((preset) => (
							<button
								key={preset}
								type="button"
								className={`colour-swatch ${colour.toLowerCase() === preset ? 'colour-swatch--active' : ''}`}
								style={{background: preset}}
								onClick={() => setColour(preset)}
								aria-label={`Use ${preset}`}
							/>
						))}
					</div>
					<div className="colour-input">
						<input type="color" value={colour} onChange={(event) => setColour(event.target.value)} />
						<input className="input" value={colour} maxLength={7} onChange={(event) => setColour(event.target.value)} />
					</div>
				</Field>
				<Field label="Effect">
					<Select value={effect} onChange={(value) => setEffect(value as typeof effect)}>
						<option value="flash">Flash</option>
						<option value="pulse">Pulse</option>
						<option value="breathe">Breathe</option>
						<option value="solid">Solid</option>
						<option value="rainbow">Rainbow</option>
					</Select>
				</Field>
				<Field label="Scope">
					<Select value={target} onChange={(value) => setTarget(value as 'managed' | 'all')}>
						<option value="all">All discovered zones</option>
						<option value="managed">Mapped zones only</option>
					</Select>
				</Field>
				<RangeField label="Duration" value={duration} min={1} max={30} suffix="s" onChange={setDuration} />
				<RangeField label="Brightness" value={brightness} min={0} max={100} suffix="%" onChange={setBrightness} />
			</div>
		</Modal>
	)
}
