import {useMemo, useState} from 'react'
import {
	Check,
	ChevronRight,
	Edit3,
	Layers3,
	Plus,
	RefreshCw,
	Search,
	Trash2,
	X,
} from 'lucide-react'
import type {Bootstrap, Device, Group, Live, TargetType, Zone} from '../types'
import {Button, Card, EmptyState, Field, IconButton, Modal, Pill} from '../components/ui'
import {DeviceGlyph, deviceTypeLabel} from '../components/DeviceGlyph'
import {LedStrip} from '../components/LedStrip'
import {del, post, put} from '../lib/api'

interface Props {
	bootstrap: Bootstrap
	live: Live | null
	onCreateMapping: (type: TargetType, id: string) => void
	onChanged: () => void
	notify: (message: string, tone?: 'success' | 'error' | 'info') => void
}

export function Devices({bootstrap, live, onCreateMapping, onChanged, notify}: Props) {
	const [search, setSearch] = useState('')
	const [groupModal, setGroupModal] = useState<{open: boolean; group?: Group}>({open: false})
	const [pendingDelete, setPendingDelete] = useState<Group | null>(null)
	const [busy, setBusy] = useState(false)
	const [rescanning, setRescanning] = useState(false)

	const filtered = useMemo(() => {
		const query = search.trim().toLowerCase()
		if (!query) return bootstrap.devices
		return bootstrap.devices.filter((device) => {
			const haystack = [device.name, device.vendor, device.type, device.serial]
				.join(' ')
				.toLowerCase()
			return haystack.includes(query) || device.zones.some((zone) => zone.name.toLowerCase().includes(query))
		})
	}, [bootstrap.devices, search])

	const mappingForZone = (zoneId: string) =>
		bootstrap.mappings.find((mapping) => mapping.target_type === 'zone' && mapping.target_id === zoneId)
	const mappingForDevice = (deviceKey: string) =>
		bootstrap.mappings.find((mapping) => mapping.target_type === 'device' && mapping.target_id === deviceKey)
	const mappingForGroup = (groupId: string) =>
		bootstrap.mappings.find((mapping) => mapping.target_type === 'group' && mapping.target_id === groupId)

	const rescan = async () => {
		setRescanning(true)
		try {
			await post('/api/devices/rescan')
			notify('OpenRGB rescan requested. Hardware updates will appear shortly.', 'info')
			window.setTimeout(onChanged, 2200)
		} catch (error) {
			notify(error instanceof Error ? error.message : 'Rescan failed', 'error')
		} finally {
			setRescanning(false)
		}
	}

	const deleteGroup = async () => {
		if (!pendingDelete) return
		setBusy(true)
		try {
			await del(`/api/groups/${pendingDelete.id}`)
			notify(`Group “${pendingDelete.name}” deleted`, 'success')
			setPendingDelete(null)
			onChanged()
		} catch (error) {
			notify(error instanceof Error ? error.message : 'Could not delete group', 'error')
		} finally {
			setBusy(false)
		}
	}

	const totalLeds = bootstrap.devices.reduce((sum, device) => sum + device.led_count, 0)
	const totalZones = bootstrap.devices.reduce((sum, device) => sum + device.zones.length, 0)
	const connected = Boolean(live?.hardware.connected)

	return (
		<div className="stack">
			<div className="page-toolbar">
				<div className="toolbar-stats">
					<div className="toolbar-stat">
						<span>Controllers</span>
						<strong>{bootstrap.devices.length}</strong>
					</div>
					<div className="toolbar-stat">
						<span>Zones</span>
						<strong>{totalZones}</strong>
					</div>
					<div className="toolbar-stat">
						<span>Addressable LEDs</span>
						<strong>{totalLeds}</strong>
					</div>
					<div className="toolbar-stat">
						<span>Groups</span>
						<strong>{bootstrap.groups.length}</strong>
					</div>
				</div>
				<div className="toolbar-actions">
					<div className="search-box">
						<Search size={15} />
						<input
							type="search"
							placeholder="Search devices or zones"
							value={search}
							onChange={(event) => setSearch(event.target.value)}
							aria-label="Search devices"
						/>
					</div>
					<Button
						variant="secondary"
						icon={<RefreshCw size={14} className={rescanning ? 'spin' : ''} />}
						onClick={rescan}
						disabled={rescanning}
					>
						Rescan
					</Button>
					<Button
						variant="primary"
						icon={<Plus size={14} />}
						onClick={() => setGroupModal({open: true})}
						disabled={bootstrap.devices.length === 0}
					>
						New group
					</Button>
				</div>
			</div>

			{!connected ? (
				<div className="notice notice--warning">
					<div className="notice__icon">
						<RefreshCw size={17} />
					</div>
					<div className="notice__body">
						<strong>Controller service is not connected</strong>
						<p>{live?.hardware.error ?? 'OpenRGB has not answered on its SDK port yet.'}</p>
					</div>
				</div>
			) : null}

			{filtered.length === 0 ? (
				<Card>
					<EmptyState
						icon={<Layers3 size={26} />}
						title={bootstrap.devices.length === 0 ? 'No lighting hardware discovered' : 'No matching devices'}
						description={
							bootstrap.devices.length === 0
								? 'Check that i2c-dev is loaded on the umbrelOS host, that the OpenRGB container is privileged, and that your USB HID devices are connected.'
								: 'Try a different name, vendor, or zone name.'
						}
						action={
							<Button variant="secondary" onClick={rescan} icon={<RefreshCw size={14} />}>
								Rescan hardware
							</Button>
						}
					/>
				</Card>
			) : (
				<div className="device-grid">
					{filtered.map((device) => (
						<DeviceCard
							key={device.key}
							device={device}
							colors={live?.zone_colors ?? {}}
							zoneMapping={mappingForZone}
							deviceMapping={mappingForDevice(device.key)}
							onMapZone={(zoneId) => onCreateMapping('zone', zoneId)}
							onMapDevice={() => onCreateMapping('device', device.key)}
						/>
					))}
				</div>
			)}

			<Card className="section-card">
				<div className="section-head">
					<div>
						<div className="eyebrow">Unified targets</div>
						<h2 className="section-title">Device groups</h2>
						<p className="section-subtitle">
							Join two or four RAM sticks, or several fan rings, into one target. A group mapping can mirror the
							same gauge or extend one meter across every member.
						</p>
					</div>
					<Button
						variant="secondary"
						size="sm"
						icon={<Plus size={14} />}
						onClick={() => setGroupModal({open: true})}
						disabled={bootstrap.devices.length === 0}
					>
						New group
					</Button>
				</div>
				{bootstrap.groups.length === 0 ? (
					<div className="empty-inline empty-inline--boxed">
						<Layers3 size={16} />
						<span>No groups yet. Select zones in a group to make a unified RAM or fan target.</span>
					</div>
				) : (
					<div className="group-grid">
						{bootstrap.groups.map((group) => (
							<GroupCard
								key={group.id}
								group={group}
								devices={bootstrap.devices}
								mapping={mappingForGroup(group.id)}
								onEdit={() => setGroupModal({open: true, group})}
								onDelete={() => setPendingDelete(group)}
								onMap={() => onCreateMapping('group', group.id)}
							/>
						))}
					</div>
				)}
			</Card>

			<GroupModal
				open={groupModal.open}
				group={groupModal.group}
				devices={bootstrap.devices}
				groups={bootstrap.groups}
				onClose={() => setGroupModal({open: false})}
				onSaved={() => {
					setGroupModal({open: false})
					onChanged()
				}}
				notify={notify}
			/>

			<Modal
				open={Boolean(pendingDelete)}
				onClose={() => setPendingDelete(null)}
				title={`Delete “${pendingDelete?.name ?? ''}”?`}
				eyebrow="Permanent action"
				width="sm"
				footer={
					<>
						<Button variant="quiet" onClick={() => setPendingDelete(null)}>
							Cancel
						</Button>
						<Button variant="danger" onClick={deleteGroup} disabled={busy} icon={<Trash2 size={14} />}>
							Delete group
						</Button>
					</>
				}
			>
				<p className="modal-copy">
					The group and any mapping that targets it will be removed. The underlying LEDs are not modified. This
					cannot be undone.
				</p>
			</Modal>
		</div>
	)
}

function DeviceCard({
	device,
	colors,
	zoneMapping,
	deviceMapping,
	onMapZone,
	onMapDevice,
}: {
	device: Device
	colors: Record<string, string[]>
	zoneMapping: (zoneId: string) => Bootstrap['mappings'][number] | undefined
	deviceMapping: Bootstrap['mappings'][number] | undefined
	onMapZone: (zoneId: string) => void
	onMapDevice: () => void
}) {
	return (
		<Card className="device-card" interactive>
			<div className="device-card__head">
				<span className="device-card__icon">
					<DeviceGlyph type={device.type} size={20} />
				</span>
				<div className="device-card__title">
					<h3>{device.name}</h3>
					<div>
						<Pill tone="neutral">{deviceTypeLabel(device.type)}</Pill>
						<span className="device-card__index">#{device.index}</span>
					</div>
				</div>
				<Button variant="quiet" size="sm" onClick={onMapDevice} icon={<Layers3 size={13} />}>
					{deviceMapping ? 'Edit device map' : 'Map device'}
				</Button>
			</div>
			<div className="device-card__meta">
				<span>{device.vendor || 'Unknown vendor'}</span>
				<span>{device.led_count} LEDs</span>
				<span>{device.zones.length} zones</span>
				{device.serial ? <span title={device.serial}>SN {device.serial.slice(0, 12)}</span> : null}
			</div>
			<div className="device-card__zones">
				{device.zones.map((zone) => {
					const mapping = zoneMapping(zone.id)
					return (
						<ZoneRow
							key={zone.id}
							zone={zone}
							colors={colors[zone.id]}
							mapped={Boolean(mapping)}
							onMap={() => onMapZone(zone.id)}
						/>
					)
				})}
			</div>
			{deviceMapping ? (
				<div className="device-card__mapping">
					<Check size={13} />
					Device-wide mapping active
					<ChevronRight size={13} />
				</div>
			) : null}
		</Card>
	)
}

function ZoneRow({
	zone,
	colors,
	mapped,
	onMap,
}: {
	zone: Zone
	colors?: string[]
	mapped: boolean
	onMap: () => void
}) {
	return (
		<div className={`zone-row ${mapped ? 'zone-row--mapped' : ''}`}>
			<div className="zone-row__head">
				<div>
					<strong>{zone.name}</strong>
					<span>
						{zone.type} · {zone.led_count} LEDs
					</span>
				</div>
				<button type="button" className="zone-row__action" onClick={onMap}>
					{mapped ? 'Edit' : 'Map'}
				</button>
			</div>
			<LedStrip colors={colors} count={zone.led_count} size="sm" />
		</div>
	)
}

function GroupCard({
	group,
	devices,
	mapping,
	onEdit,
	onDelete,
	onMap,
}: {
	group: Group
	devices: Device[]
	mapping?: Bootstrap['mappings'][number]
	onEdit: () => void
	onDelete: () => void
	onMap: () => void
}) {
	const zoneLabels = useMemo(() => {
		const labels: Record<string, string> = {}
		for (const device of devices) {
			for (const zone of device.zones) {
				labels[zone.id] = `${device.name} · ${zone.name}`
			}
		}
		return labels
	}, [devices])
	return (
		<div className="group-card">
			<div className="group-card__head">
				<div>
					<h3>{group.name}</h3>
					<span>
						{group.zone_count} zones · {group.device_names.join(' + ') || 'isolated target'}
					</span>
				</div>
				<div className="group-card__tools">
					<IconButton label="Edit group" onClick={onEdit}>
						<Edit3 size={15} />
					</IconButton>
					<IconButton label="Delete group" onClick={onDelete}>
						<Trash2 size={15} />
					</IconButton>
				</div>
			</div>
			<div className="group-card__zones">
				{group.missing_zones.length > 0 ? (
					<Pill tone="amber">{group.missing_zones.length} missing zones</Pill>
				) : null}
				{group.zones.slice(0, 8).map((zoneId) => (
					<span className="zone-chip" key={zoneId} title={zoneLabels[zoneId] ?? zoneId}>
						{zoneLabels[zoneId] ?? zoneId}
					</span>
				))}
				{group.zones.length > 8 ? (
					<span className="zone-chip">+{group.zones.length - 8}</span>
				) : null}
			</div>
			<div className="group-card__foot">
				{mapping ? <Pill tone="mint">Mapped</Pill> : <span className="muted">Unmapped</span>}
				<Button variant="quiet" size="sm" onClick={onMap} icon={<ChevronRight size={13} />}>
					{mapping ? 'Edit mapping' : 'Create mapping'}
				</Button>
			</div>
		</div>
	)
}

function GroupModal({
	open,
	group,
	devices,
	groups,
	onClose,
	onSaved,
	notify,
}: {
	open: boolean
	group?: Group
	devices: Device[]
	groups: Group[]
	onClose: () => void
	onSaved: () => void
	notify: (message: string, tone?: 'success' | 'error' | 'info') => void
}) {
	const [name, setName] = useState(group?.name ?? '')
	const [selected, setSelected] = useState<string[]>(group?.zones ?? [])
	const [search, setSearch] = useState('')
	const [busy, setBusy] = useState(false)

	// Reset local form whenever a different group (or a fresh create) is opened.
	const modalKey = group?.id ?? 'new'
	const [lastKey, setLastKey] = useState(modalKey)
	if (open && lastKey !== modalKey) {
		setLastKey(modalKey)
		setName(group?.name ?? '')
		setSelected(group?.zones ?? [])
		setSearch('')
	}

	const unavailable = useMemo(() => {
		const owned = new Set<string>()
		for (const item of groups) {
			if (item.id === group?.id) continue
			for (const zone of item.zones) owned.add(zone)
		}
		return owned
	}, [groups, group?.id])

	const toggle = (zoneId: string) => {
		if (unavailable.has(zoneId)) return
		setSelected((current) =>
			current.includes(zoneId) ? current.filter((item) => item !== zoneId) : [...current, zoneId],
		)
	}

	const save = async () => {
		if (!name.trim()) {
			notify('Give the group a name first', 'error')
			return
		}
		if (selected.length === 0) {
			notify('Select at least one LED zone', 'error')
			return
		}
		setBusy(true)
		try {
			if (group) {
				await put(`/api/groups/${group.id}`, {name: name.trim(), zones: selected})
				notify('Group updated', 'success')
			} else {
				await post('/api/groups', {name: name.trim(), zones: selected})
				notify('Group created', 'success')
			}
			onSaved()
		} catch (error) {
			notify(error instanceof Error ? error.message : 'Could not save group', 'error')
		} finally {
			setBusy(false)
		}
	}

	const filteredDevices = useMemo(() => {
		const query = search.trim().toLowerCase()
		if (!query) return devices
		return devices.filter((device) =>
			[device.name, device.vendor, ...device.zones.map((zone) => zone.name)]
				.join(' ')
				.toLowerCase()
				.includes(query),
		)
	}, [devices, search])

	return (
		<Modal
			open={open}
			onClose={onClose}
			title={group ? 'Edit group' : 'Create a device group'}
			eyebrow="Unified LED target"
			width="lg"
			footer={
				<>
					<span className="modal-footer-note">{selected.length} zones selected</span>
					<Button variant="quiet" onClick={onClose}>
						Cancel
					</Button>
					<Button variant="primary" onClick={save} disabled={busy} icon={<Check size={14} />}>
						{group ? 'Save group' : 'Create group'}
					</Button>
				</>
			}
		>
			<div className="group-modal">
				<Field label="Group name" htmlFor="group-name">
					<input
						id="group-name"
						className="input"
						value={name}
						maxLength={64}
						onChange={(event) => setName(event.target.value)}
						placeholder="Front RAM · unified meter"
					/>
				</Field>
				<div className="group-modal__toolbar">
					<div className="search-box search-box--wide">
						<Search size={15} />
						<input
							type="search"
							value={search}
							onChange={(event) => setSearch(event.target.value)}
							placeholder="Filter zones"
							aria-label="Filter zones"
						/>
					</div>
					<div className="selection-chips">
						{selected.slice(0, 5).map((id) => {
							const zone = devices.flatMap((device) => device.zones).find((item) => item.id === id)
							return (
								<span className="selection-chip" key={id}>
									{zone?.name ?? id}
									<button type="button" onClick={() => toggle(id)} aria-label={`Remove ${zone?.name ?? id}`}>
										<X size={12} />
									</button>
								</span>
							)
						})}
						{selected.length > 5 ? <span className="selection-chip">+{selected.length - 5}</span> : null}
					</div>
				</div>
				<div className="zone-picker">
					{filteredDevices.map((device) => (
						<div className="zone-picker__device" key={device.key}>
							<div className="zone-picker__device-head">
								<DeviceGlyph type={device.type} size={16} />
								<strong>{device.name}</strong>
								<span>{device.type}</span>
							</div>
							<div className="zone-picker__zones">
								{device.zones.map((zone) => {
									const checked = selected.includes(zone.id)
									const disabled = unavailable.has(zone.id)
									return (
										<button
											key={zone.id}
											type="button"
											className={`zone-option ${checked ? 'zone-option--checked' : ''} ${
												disabled ? 'zone-option--disabled' : ''
											}`}
											onClick={() => toggle(zone.id)}
											disabled={disabled}
										>
											<span className="zone-option__check">{checked ? <Check size={12} /> : null}</span>
											<span className="zone-option__body">
												<strong>{zone.name}</strong>
												<small>
													{zone.led_count} LEDs{disabled ? ' · in another group' : ''}
												</small>
											</span>
										</button>
									)
								})}
							</div>
						</div>
					))}
				</div>
			</div>
		</Modal>
	)
}
