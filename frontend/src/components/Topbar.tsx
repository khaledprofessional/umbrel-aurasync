import {Clock3, Moon, RefreshCw, Sparkles, Zap} from 'lucide-react'
import type {Live} from '../types'
import {PAGE_META, type Page} from '../navigation'
import {Button, StatusDot} from './ui'
import {timeAgo} from '../lib/util'

export function Topbar({
	page,
	live,
	onRefresh,
	onFlash,
	refreshing,
}: {
	page: Page
	live: Live | null
	onRefresh: () => void
	onFlash: () => void
	refreshing: boolean
}) {
	const meta = PAGE_META[page]
	const connected = Boolean(live?.hardware.connected)
	const activeOverlay = live?.overlays?.[0]
	return (
		<header className="topbar">
			<div className="topbar__title">
				<div className="eyebrow">{meta.eyebrow}</div>
				<h1>{meta.title}</h1>
				<p>{meta.subtitle}</p>
			</div>
			<div className="topbar__actions">
				<div className="topbar__status">
					<span className="topbar__live">
						<StatusDot online={connected} />
						{connected ? 'Live' : 'Disconnected'}
					</span>
					{live?.night_active ? (
						<span className="topbar__meta">
							<Moon size={13} /> Quiet hours
						</span>
					) : activeOverlay ? (
						<span className="topbar__meta topbar__meta--alert">
							<Zap size={13} /> {activeOverlay.event_name ?? 'Test override'}
						</span>
					) : (
						<span className="topbar__meta">
							<Clock3 size={13} /> {live?.frame.last_frame_at ? timeAgo(live.frame.last_frame_at) : 'waiting'}
						</span>
					)}
				</div>
				<Button
					variant="quiet"
					size="sm"
					icon={<RefreshCw size={14} className={refreshing ? 'spin' : ''} />}
					onClick={onRefresh}
					disabled={refreshing}
				>
					Refresh
				</Button>
				<Button variant="primary" size="sm" icon={<Sparkles size={14} />} onClick={onFlash}>
					Test lights
				</Button>
			</div>
		</header>
	)
}
