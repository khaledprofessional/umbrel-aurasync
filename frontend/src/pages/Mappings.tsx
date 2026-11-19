import {useEffect, useMemo, useState} from 'react'
import {
	Activity,
	Check,
	CircleOff,
	Cpu,
	Edit3,
	HardDrive,
	Layers3,
	MemoryStick,
	Play,
	Plus,
	RefreshCw,
	Sparkles,
	Sun,
	Trash2,
	Zap,
} from 'lucide-react'
import type {
	Bootstrap,
	Live,
	Mapping,
	MappingInput,
	MappingParams,
	Mode,
	TargetType,
} from '../types'
import {
	Button,
	Card,
	EmptyState,
	Field,
	IconButton,
	Modal,
	Pill,
	RangeField,
	Segmented,
	Select,
	Toggle,
} from '../components/ui'
import {LedStrip} from '../components/LedStrip'
import {del, post, put} from '../lib/api'
import {
	clamp,
	defaultParams,
	modeDescription,
	modeLabel,
	parseHexInput,
	statusColour,
	targetTypeLabel,
} from '../lib/util'
import {
	mappingLedCount,
	previewMappingColors,
	targetZones,
	temperatureColour,
} from '../lib/preview'

interface Props {
	bootstrap: Bootstrap
	live: Live | null
	prefill: {type: TargetType; id: string} | null
	onPrefillConsumed: () => void
	onChanged: () => void
	notify: (message: string, tone?: 'success' | 'error' | 'info') => void
}

const MODES: Array<{mode: Mode; icon: typeof HardDrive}> = [
	{mode: 'storage', icon: HardDrive},
	{mode: 'temp_cpu', icon: Cpu},
	{mode: 'temp_gpu', icon: Zap},
	{mode: 'cpu_load', icon: Activity},
	{mode: 'ram_load', icon: MemoryStick},
	{mode: 'static', icon: Sparkles},
	{mode: 'off', icon: CircleOff},
]

export function Mappings({bootstrap, live, prefill, onPrefillConsumed, onChanged, notify}: Props) {
	const [editor, setEditor] = useState<{open: boolean; mapping?: Mapping; target?: {type: TargetType; id: string}}>({
		open: false,
	})
	const [pendingDelete, setPendingDelete] = useState<Mapping | null>(null)
	const [busy, setBusy] = useState(false)

	useEffect(() => {
		if (!prefill) return
		const existing = bootstrap.mappings.find(
			(item) => item.target_type === prefill.type && item.target_id === prefill.id,
		)
		setEditor({open: true, mapping: existing, target: prefill})
		onPrefillConsumed()
	}, [prefill, onPrefillConsumed, bootstrap.mappings])

	const isTargetUsed = (type: TargetType, id: string) =>
		bootstrap.mappings.some((mapping) => mapping.target_type === type && mapping.target_id === id)

	const defaultTarget = (): {type: TargetType; id: string} | undefined => {
		const group = bootstrap.groups.find((item) => !isTargetUsed('group', item.id))
		if (group) return {type: 'group', id: group.id}
		const device = bootstrap.devices.find((item) => !isTargetUsed('device', item.key))
		if (device) return {type: 'device', id: device.key}
		for (const device of bootstrap.devices) {
			const zone = device.zones.find((item) => !isTargetUsed('zone', item.id))
			if (zone) return {type: 'zone', id: zone.id}
		}
		return undefined
	}

	const canCreate = Boolean(
		bootstrap.devices.length &&
			(bootstrap.groups.some((group) => !isTargetUsed('group', group.id)) ||
				bootstrap.devices.some((device) => !isTargetUsed('device', device.key)) ||
				bootstrap.devices.some((device) =>
					device.zones.some((zone) => !isTargetUsed('zone', zone.id)),
				)),
	)

	const toggleEnabled = async (mapping: Mapping) => {
		try {
			const payload: MappingInput = {
				target_type: mapping.target_type,
				target_id: mapping.target_id,
				mode: mapping.mode,
				params: mapping.params,
				enabled: !mapping.enabled,
			}
			await put(`/api/mappings/${mapping.id}`, payload)
			notify(`${mapping.target_label} ${mapping.enabled ? 'paused' : 'enabled'}`, 'success')
			onChanged()
		} catch (error) {
			notify(error instanceof Error ? error.message : 'Could not update mapping', 'error')
		}
	}

	const testMapping = async (mapping: Mapping) => {
		try {
			await post(`/api/mappings/${mapping.id}/test`, {duration: 8})
			notify(`Testing ${mapping.target_label} for 8 seconds`, 'success')
		} catch (error) {
			notify(error instanceof Error ? error.message : 'Could not start test', 'error')
		}
	}

	const deleteMapping = async () => {
		if (!pendingDelete) return
		setBusy(true)
		try {
			await del(`/api/mappings/${pendingDelete.id}`)
			notify('Mapping deleted', 'success')
			setPendingDelete(null)
			onChanged()
		} catch (error) {
			notify(error instanceof Error ? error.message : 'Could not delete mapping', 'error')
		} finally {
			setBusy(false)
		}
	}

	const activeCount = bootstrap.mappings.filter((mapping) => mapping.enabled).length
	const storageCount = bootstrap.mappings.filter((mapping) => mapping.mode === 'storage').length

	return (
		<div className="stack">
			<div className="page-toolbar">
				<div className="toolbar-stats">
					<div className="toolbar-stat">
						<span>Mappings</span>
						<strong>{bootstrap.mappings.length}</strong>
					</div>
					<div className="toolbar-stat">
						<span>Enabled</span>
						<strong>{activeCount}</strong>
					</div>
					<div className="toolbar-stat">
						<span>Storage gauges</span>
						<strong>{storageCount}</strong>
					</div>
					<div className="toolbar-stat">
						<span>Render rate</span>
						<strong>{live?.settings.fps ?? bootstrap.settings.fps} fps</strong>
					</div>
				</div>
				<div className="toolbar-actions">
					<Button
						variant="primary"
						icon={<Plus size={14} />}
						onClick={() => setEditor({open: true, target: defaultTarget()})}
						disabled={!canCreate}
					>
						Add mapping
					</Button>
				</div>
			</div>

			{bootstrap.mappings.length === 0 ? (
				<Card>
					<EmptyState
						icon={<Sparkles size={27} />}
						title="Bring the LEDs to life"
						description="Create a mapping to turn storage usage, CPU or GPU heat, or system load into light. Every zone and grouped target is independent."
						action={
							<Button
								variant="primary"
								onClick={() => setEditor({open: true, target: defaultTarget()})}
								icon={<Plus size={14} />}
								disabled={!canCreate}
							>
								Create first mapping
							</Button>
						}
					/>
				</Card>
			) : (
				<div className="mapping-grid">
					{bootstrap.mappings.map((mapping) => (
						<MappingCard
							key={mapping.id}
							mapping={mapping}
							bootstrap={bootstrap}
							live={live}
							onToggle={() => toggleEnabled(mapping)}
							onTest={() => testMapping(mapping)}
							onEdit={() => setEditor({open: true, mapping})}
							onDelete={() => setPendingDelete(mapping)}
						/>
					))}
				</div>
			)}

			{editor.open ? (
				<MappingEditor
					key={editor.mapping?.id ?? `${editor.target?.type}:${editor.target?.id}`}
					open
					mapping={editor.mapping}
					initialTarget={editor.target}
					bootstrap={bootstrap}
					live={live}
					onClose={() => setEditor({open: false})}
					onSaved={(test) => {
						setEditor({open: false})
						onChanged()
						if (test) notify('Mapping saved and test override started', 'success')
					}}
					notify={notify}
				/>
			) : null}

			<Modal
				open={Boolean(pendingDelete)}
				onClose={() => setPendingDelete(null)}
				title="Delete this mapping?"
				eyebrow="Permanent action"
				width="sm"
				footer={
					<>
						<Button variant="quiet" onClick={() => setPendingDelete(null)}>
							Cancel
						</Button>
						<Button variant="danger" onClick={deleteMapping} disabled={busy} icon={<Trash2 size={14} />}>
							Delete mapping
						</Button>
					</>
				}
			>
				<p className="modal-copy">
					{modeLabel(pendingDelete?.mode ?? 'off')} will be removed from{' '}
					<strong>{pendingDelete?.target_label}</strong>. Those LEDs will be darkened by the next render.
				</p>
			</Modal>
		</div>
	)
}

function MappingCard({
	mapping,
	bootstrap,
	live,
	onToggle,
	onTest,
	onEdit,
	onDelete,
}: {
	mapping: Mapping
	bootstrap: Bootstrap
	live: Live | null
	onToggle: () => void
	onTest: () => void
	onEdit: () => void
	onDelete: () => void
}) {
	const ledCount = mappingLedCount(mapping, bootstrap.devices, bootstrap.groups)
	const colors = live?.zone_colors
	const targetZoneList = targetZones(mapping, bootstrap.devices, bootstrap.groups)
	const liveColors = targetZoneList.flatMap((zone) => colors?.[zone.id] ?? [])
	const preview = previewMappingColors(
		mapping,
		bootstrap.devices,
		bootstrap.groups,
		live?.telemetry ?? bootstrap.telemetry,
		live?.settings ?? bootstrap.settings,
		44,
	)
	const swatch =
		mapping.mode === 'storage'
			? statusColour(100 - (live?.summary.storage?.used_percent ?? 0))
			: mapping.mode === 'temp_cpu' || mapping.mode === 'temp_gpu'
				? temperatureColour(
						(mapping.mode === 'temp_cpu' ? live?.telemetry.cpu.temp : live?.telemetry.gpu?.temp) ?? 45,
						mapping.params.low,
						mapping.params.high,
					)
				: mapping.params.color
	const multi = targetZoneList.length > 1
	return (
		<Card className={`mapping-card ${mapping.enabled ? '' : 'mapping-card--disabled'}`}>
			<div className="mapping-card__head">
				<span className="mapping-card__swatch" style={{background: swatch, boxShadow: `0 0 18px ${swatch}55`}} />
				<div className="mapping-card__title">
					<h3>{mapping.target_label}</h3>
					<span>
						{targetTypeLabel(mapping.target_type)}
						{multi ? ` · ${targetZoneList.length} zones` : ''} · {ledCount} LEDs
					</span>
				</div>
				<Toggle checked={mapping.enabled} onChange={onToggle} label={`Toggle ${mapping.target_label}`} />
			</div>
			<div className="mapping-card__mode">
				<Pill tone={mapping.mode === 'storage' ? 'mint' : 'neutral'}>{modeLabel(mapping.mode)}</Pill>
				{multi ? <Pill tone="neutral">{mapping.params.layout === 'extend' ? 'extended bar' : 'mirrored'}</Pill> : null}
				{!mapping.target_exists ? <Pill tone="amber">target missing</Pill> : null}
				{!mapping.enabled ? <Pill tone="neutral">paused</Pill> : null}
			</div>
			<div className="mapping-card__preview">
				<LedStrip colors={mapping.enabled && liveColors.length ? liveColors : preview} count={Math.min(ledCount || 24, 44)} size="md" />
			</div>
			<div className="mapping-card__meta">
				<span>
					{mapping.mode === 'storage'
						? mapping.params.path || `global ${bootstrap.settings.storage_path}`
						: mapping.mode === 'temp_cpu' || mapping.mode === 'temp_gpu'
							? `${mapping.params.low}–${mapping.params.high}°C`
							: mapping.mode === 'static'
								? mapping.params.color
								: `brightness ${mapping.params.brightness}%`}
				</span>
				<span>{mapping.params.reverse ? 'top → bottom' : 'bottom → top'}</span>
			</div>
			<div className="mapping-card__actions">
				<Button variant="quiet" size="sm" onClick={onTest} icon={<Play size={13} />} disabled={!mapping.enabled}>
					Test
				</Button>
				<Button variant="quiet" size="sm" onClick={onEdit} icon={<Edit3 size={13} />}>
					Edit
				</Button>
				<IconButton label="Delete mapping" onClick={onDelete}>
					<Trash2 size={15} />
				</IconButton>
			</div>
		</Card>
	)
}

function MappingEditor({
	open,
	mapping,
	initialTarget,
	bootstrap,
	live,
	onClose,
	onSaved,
	notify,
}: {
	open: boolean
	mapping?: Mapping
	initialTarget?: {type: TargetType; id: string}
	bootstrap: Bootstrap
	live: Live | null
	onClose: () => void
	onSaved: (test: boolean) => void
	notify: (message: string, tone?: 'success' | 'error' | 'info') => void
}) {
	const [draft, setDraft] = useState<MappingInput>(() => ({
		target_type: mapping?.target_type ?? initialTarget?.type ?? (bootstrap.groups[0] ? 'group' : 'device'),
		target_id:
			mapping?.target_id ??
			initialTarget?.id ??
			bootstrap.groups[0]?.id ??
			bootstrap.devices[0]?.key ??
			bootstrap.devices[0]?.zones[0]?.id ??
			'',
		mode: mapping?.mode ?? 'storage',
		params: mapping?.params ?? defaultParams(),
		enabled: mapping?.enabled ?? true,
	}))
	const [busy, setBusy] = useState<null | 'save' | 'test'>(null)

	const setParams = (patch: Partial<MappingParams>) => {
		setDraft((current) => ({...current, params: {...current.params, ...patch}}))
	}

	const usedTargets = useMemo(() => {
		const set = new Set<string>()
		for (const item of bootstrap.mappings) {
			if (mapping && item.id === mapping.id) continue
			set.add(`${item.target_type}:${item.target_id}`)
		}
		return set
	}, [bootstrap.mappings, mapping])

	const options = useMemo(() => {
		if (draft.target_type === 'group') {
			return bootstrap.groups.map((group) => ({
				value: group.id,
				label: `${group.name} · ${group.zone_count} zone${group.zone_count === 1 ? '' : 's'}`,
				used: usedTargets.has(`group:${group.id}`),
			}))
		}
		if (draft.target_type === 'device') {
			return bootstrap.devices.map((device) => ({
				value: device.key,
				label: `${device.name} · ${device.zones.length} zone${device.zones.length === 1 ? '' : 's'}`,
				used: usedTargets.has(`device:${device.key}`),
			}))
		}
		return bootstrap.devices.flatMap((device) =>
			device.zones.map((zone) => ({
				value: zone.id,
				label: `${device.name} · ${zone.name} · ${zone.led_count} LEDs`,
				used: usedTargets.has(`zone:${zone.id}`),
			})),
		)
	}, [bootstrap.devices, bootstrap.groups, draft.target_type, usedTargets])

	useEffect(() => {
		if (!options.some((option) => option.value === draft.target_id && !option.used)) {
			const next = options.find((option) => !option.used)
			if (next) setDraft((current) => ({...current, target_id: next.value}))
		}
	}, [options, draft.target_id])

	const targetLabel =
		options.find((option) => option.value === draft.target_id)?.label ??
		mapping?.target_label ??
		draft.target_id
	const targetAvailable = options.some(
		(option) => option.value === draft.target_id && !option.used,
	)

	const zonesForDraft = useMemo(
		() => targetZones({target_type: draft.target_type, target_id: draft.target_id}, bootstrap.devices, bootstrap.groups),
		[bootstrap.devices, bootstrap.groups, draft.target_type, draft.target_id],
	)
	const ledCount = zonesForDraft.reduce((sum, zone) => sum + zone.led_count, 0)
	const previewMapping: Mapping = {
		id: mapping?.id ?? 'preview',
		target_type: draft.target_type,
		target_id: draft.target_id,
		mode: draft.mode,
		params: draft.params,
		enabled: draft.enabled,
		target_exists: true,
		target_label: targetLabel,
	}
	const preview = previewMappingColors(
		previewMapping,
		bootstrap.devices,
		bootstrap.groups,
		live?.telemetry ?? bootstrap.telemetry,
		live?.settings ?? bootstrap.settings,
		48,
	)

	const save = async (test: boolean) => {
		if (!draft.target_id || !targetAvailable) {
			notify('Choose a target that does not already have a mapping', 'error')
			return
		}
		setBusy(test ? 'test' : 'save')
		try {
			let saved: Mapping
			if (mapping) {
				const result = await put<{mapping: Mapping}>(`/api/mappings/${mapping.id}`, draft)
				saved = result.mapping
			} else {
				const result = await post<{mapping: Mapping}>('/api/mappings', draft)
				saved = result.mapping
			}
			if (test) {
				await post(`/api/mappings/${saved.id}/test`, {duration: 8})
			}
			onSaved(test)
		} catch (error) {
			notify(error instanceof Error ? error.message : 'Could not save mapping', 'error')
		} finally {
			setBusy(null)
		}
	}

	const multi = zonesForDraft.length > 1
	const showColour = draft.mode === 'static' || draft.mode === 'cpu_load' || draft.mode === 'ram_load'
	const isTemperature = draft.mode === 'temp_cpu' || draft.mode === 'temp_gpu'
	const isStorage = draft.mode === 'storage'
	const isLoad = draft.mode === 'cpu_load' || draft.mode === 'ram_load'
	const isIdle = draft.mode === 'off'

	return (
		<Modal
			open={open}
			onClose={onClose}
			title={mapping ? 'Edit mapping' : 'New light mapping'}
			eyebrow={mapping ? mapping.target_label : 'Bind telemetry to light'}
			width="lg"
			footer={
				<>
					<span className="modal-footer-note">
						{ledCount} LEDs · {draft.target_type}
					</span>
					<Button variant="quiet" onClick={onClose}>
						Cancel
					</Button>
					<Button
						variant="secondary"
						onClick={() => save(true)}
						disabled={busy !== null || !targetAvailable}
						icon={<Play size={14} />}
					>
						{busy === 'test' ? 'Testing…' : 'Save & test'}
					</Button>
					<Button
						variant="primary"
						onClick={() => save(false)}
						disabled={busy !== null || !targetAvailable}
						icon={<Check size={14} />}
					>
						{busy === 'save' ? 'Saving…' : 'Save mapping'}
					</Button>
				</>
			}
		>
			<div className="mapping-editor">
				<div className="editor-section">
					<div className="editor-section__head">
						<span className="step-badge">01</span>
						<div>
							<h3>Target</h3>
							<p>One zone, a whole controller, or a unified group.</p>
						</div>
					</div>
					<div className="editor-grid">
						<Field label="Target kind">
							<Segmented
								label="Target kind"
								value={draft.target_type}
								onChange={(value) => setDraft((current) => ({...current, target_type: value, target_id: ''}))}
								options={[
									{value: 'group', label: 'Group', icon: <Layers3 size={14} />},
									{value: 'device', label: 'Device', icon: <Cpu size={14} />},
									{value: 'zone', label: 'Zone', icon: <Sun size={14} />},
								]}
							/>
						</Field>
						<Field label="Target" htmlFor="mapping-target">
							<Select
								id="mapping-target"
								value={draft.target_id}
								onChange={(value) => setDraft((current) => ({...current, target_id: value}))}
							>
								<option value="" disabled>
									Select a free target…
								</option>
								{options.map((option) => (
									<option key={option.value} value={option.value} disabled={option.used}>
										{option.label}
										{option.used ? ' — already mapped' : ''}
									</option>
								))}
							</Select>
						</Field>
					</div>
					{multi ? (
						<div className="inline-option">
							<div>
								<strong>Fill behaviour</strong>
								<span>Mirror the same gauge on every zone, or extend one bar across the group.</span>
							</div>
							<Segmented
								label="Fill behaviour"
								value={draft.params.layout}
								onChange={(value) => setParams({layout: value})}
								options={[
									{value: 'mirror', label: 'Mirror'},
									{value: 'extend', label: 'Extend'},
								]}
							/>
						</div>
					) : null}
				</div>

				<div className="editor-section">
					<div className="editor-section__head">
						<span className="step-badge">02</span>
						<div>
							<h3>Mode</h3>
							<p>What should this target express?</p>
						</div>
					</div>
					<div className="mode-grid">
						{MODES.map(({mode, icon: Icon}) => (
							<button
								type="button"
								key={mode}
								className={`mode-tile ${draft.mode === mode ? 'mode-tile--active' : ''}`}
								onClick={() =>
									setDraft((current) => ({
										...current,
										mode,
										params: {
											...current.params,
											path: mode === 'storage' ? current.params.path : current.params.path,
										},
									}))
								}
								aria-pressed={draft.mode === mode}
							>
								<span className="mode-tile__icon">
									<Icon size={18} />
								</span>
								<strong>{modeLabel(mode)}</strong>
							</button>
						))}
					</div>
					<p className="mode-help">{modeDescription(draft.mode)}</p>
				</div>

				<div className="editor-section">
					<div className="editor-section__head">
						<span className="step-badge">03</span>
						<div>
							<h3>Appearance</h3>
							<p>Fine-tune thresholds, direction, and intensity.</p>
						</div>
					</div>
					<div className="editor-grid">
						{showColour ? (
							<Field label="Colour" hint="Used for static light and CPU/RAM load.">
								<div className="colour-input">
									<input
										type="color"
										value={/^#[0-9a-f]{6}$/i.test(draft.params.color) ? draft.params.color : '#22d3ee'}
										onChange={(event) => setParams({color: event.target.value})}
										aria-label="Mapping colour"
									/>
									<input
										className="input"
										value={draft.params.color}
										onChange={(event) => {
											const value = parseHexInput(event.target.value)
											setParams({color: value})
										}}
										maxLength={7}
										aria-label="Hex colour"
									/>
								</div>
							</Field>
						) : null}
						{isStorage ? (
							<Field
								label="Storage path"
								hint={`Leave empty to follow the global path (${bootstrap.settings.storage_path}).`}
							>
								<input
									className="input"
									list="mount-options"
									value={draft.params.path ?? ''}
									placeholder={bootstrap.settings.storage_path}
									onChange={(event) => setParams({path: event.target.value || null})}
								/>
								<datalist id="mount-options">
									{bootstrap.mounts.map((mount) => (
										<option key={mount.path} value={mount.path}>
											{mount.path}
										</option>
									))}
								</datalist>
							</Field>
						) : null}
						{isTemperature ? (
							<>
								<Field label="Sensor range">
									<div className="split-inputs">
										<label>
											<span>Cool at</span>
											<input
												className="input"
												type="number"
												min={0}
												max={120}
												value={draft.params.low}
												onChange={(event) => setParams({low: Number(event.target.value)})}
											/>
											<span>°C</span>
										</label>
										<label>
											<span>Hot at</span>
											<input
												className="input"
												type="number"
												min={1}
												max={140}
												value={draft.params.high}
												onChange={(event) => setParams({high: Number(event.target.value)})}
											/>
											<span>°C</span>
										</label>
									</div>
								</Field>
								<Field label="Visual">
									<Select value={draft.params.visual} onChange={(value) => setParams({visual: value as MappingParams['visual']})}>
										<option value="solid">Solid thermal colour</option>
										<option value="bar">Temperature fill bar</option>
									</Select>
								</Field>
							</>
						) : null}
						{isLoad ? (
							<>
								<Field label="Visual">
									<Select value={draft.params.visual} onChange={(value) => setParams({visual: value as MappingParams['visual']})}>
										<option value="auto">Auto (fill or brightness)</option>
										<option value="fill">Fill bar</option>
										<option value="brightness">Brightness</option>
										<option value="breathe">Breathing</option>
									</Select>
								</Field>
								{draft.params.visual === 'breathe' ? (
									<Field label="Breathing speed" hint="Load increases the breathing rate automatically.">
										<input
											className="input"
											type="number"
											min={0.1}
											max={4}
											step={0.1}
											value={draft.params.speed}
											onChange={(event) => setParams({speed: clamp(Number(event.target.value), 0.1, 4)})}
										/>
									</Field>
								) : null}
							</>
						) : null}
						{isStorage ? (
							<Field label="Critical pulse">
								<div className="inline-toggle">
									<Toggle
										checked={draft.params.critical_pulse}
										onChange={(value) => setParams({critical_pulse: value})}
										label="Pulse below five percent free"
									/>
									<span>Pulse when less than 5% free remains.</span>
								</div>
							</Field>
						) : null}
					</div>
					<div className="editor-grid editor-grid--tight">
						<RangeField
							label="Colour intensity"
							value={draft.params.brightness}
							min={0}
							max={100}
							step={1}
							suffix="%"
							onChange={(value) => setParams({brightness: value})}
						/>
						<div className="inline-toggle inline-toggle--row">
							<Toggle
								checked={draft.params.reverse}
								onChange={(value) => setParams({reverse: value})}
								label="Reverse fill direction"
							/>
							<div>
								<strong>Reverse fill</strong>
								<span>Light from the far end instead of index 0.</span>
							</div>
						</div>
						<div className="inline-toggle inline-toggle--row">
							<Toggle
								checked={draft.params.show_unlit}
								onChange={(value) => setParams({show_unlit: value})}
								label="Show unlit LEDs"
							/>
							<div>
								<strong>Ghost unlit LEDs</strong>
								<span>Leave a faint trace of the gauge beyond the fill.</span>
							</div>
						</div>
					</div>
				</div>

				<div className="editor-preview">
					<div className="editor-preview__head">
						<div>
							<div className="eyebrow">Preview</div>
							<h3>{targetLabel}</h3>
						</div>
						<div className="editor-preview__meta">
							{isIdle ? 'Output dark' : `${ledCount} LEDs`} · {draft.params.reverse ? 'reversed' : 'index 0 first'}
						</div>
					</div>
					<div className="preview-stage">
						<LedStrip colors={preview} count={Math.min(Math.max(ledCount, 16), 48)} size="lg" />
					</div>
					<div className="preview-caption">
						<span>
							<Sparkles size={13} /> Live preview uses the latest telemetry sample.
						</span>
						<span>
							<RefreshCw size={13} /> Hardware test runs for 8 seconds.
						</span>
					</div>
				</div>
			</div>
		</Modal>
	)
}
