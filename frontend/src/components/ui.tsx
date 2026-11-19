import {useEffect, useId, useRef, useState, type ButtonHTMLAttributes, type CSSProperties, type ReactNode} from 'react'
import {createPortal} from 'react-dom'
import {Check, Copy, X} from 'lucide-react'

export function Card({
	children,
	className = '',
	interactive = false,
}: {
	children: ReactNode
	className?: string
	interactive?: boolean
}) {
	return <div className={`glass-card ${interactive ? 'glass-card--interactive' : ''} ${className}`}>{children}</div>
}

type ButtonVariant = 'primary' | 'secondary' | 'ghost' | 'danger' | 'quiet'
type ButtonSize = 'sm' | 'md' | 'lg'

export function Button({
	children,
	icon,
	variant = 'secondary',
	size = 'md',
	className = '',
	...props
}: ButtonHTMLAttributes<HTMLButtonElement> & {
	children?: ReactNode
	icon?: ReactNode
	variant?: ButtonVariant
	size?: ButtonSize
}) {
	return (
		<button className={`btn btn--${variant} btn--${size} ${className}`} {...props}>
			{icon ? <span className="btn__icon">{icon}</span> : null}
			{children ? <span>{children}</span> : null}
		</button>
	)
}

export function IconButton({
	label,
	children,
	className = '',
	...props
}: ButtonHTMLAttributes<HTMLButtonElement> & {label: string; children: ReactNode}) {
	return (
		<button className={`icon-btn ${className}`} aria-label={label} title={label} {...props}>
			{children}
		</button>
	)
}

export function Pill({
	children,
	tone = 'neutral',
	dot = false,
}: {
	children: ReactNode
	tone?: 'neutral' | 'mint' | 'amber' | 'red' | 'blue'
	dot?: boolean
}) {
	return (
		<span className={`pill pill--${tone}`}>
			{dot ? <span className="pill__dot" /> : null}
			{children}
		</span>
	)
}

export function StatusDot({online, pulse = true}: {online: boolean; pulse?: boolean}) {
	return <span className={`status-dot ${online ? 'status-dot--online' : 'status-dot--offline'} ${pulse ? 'status-dot--pulse' : ''}`} />
}

export function Toggle({
	checked,
	onChange,
	label,
	disabled = false,
}: {
	checked: boolean
	onChange: (value: boolean) => void
	label: string
	disabled?: boolean
}) {
	return (
		<button
			type="button"
			role="switch"
			aria-checked={checked}
			aria-label={label}
			disabled={disabled}
			className={`toggle ${checked ? 'toggle--on' : ''}`}
			onClick={() => onChange(!checked)}
		>
			<span className="toggle__thumb" />
		</button>
	)
}

export function Field({
	label,
	hint,
	children,
	htmlFor,
	className = '',
}: {
	label: string
	hint?: ReactNode
	children: ReactNode
	htmlFor?: string
	className?: string
}) {
	return (
		<div className={`field ${className}`}>
			<label className="field__label" htmlFor={htmlFor}>
				{label}
			</label>
			{children}
			{hint ? <div className="field__hint">{hint}</div> : null}
		</div>
	)
}

export function RangeField({
	label,
	value,
	min,
	max,
	step = 1,
	suffix = '',
	onChange,
	hint,
}: {
	label: string
	value: number
	min: number
	max: number
	step?: number
	suffix?: string
	onChange: (value: number) => void
	hint?: string
}) {
	const id = useId()
	return (
		<div className="range-field">
			<div className="range-field__head">
				<label htmlFor={id} className="field__label">
					{label}
				</label>
				<span className="range-field__value">
					{value}
					{suffix}
				</span>
			</div>
			<input
				id={id}
				type="range"
				min={min}
				max={max}
				step={step}
				value={value}
				onChange={(event) => onChange(Number(event.target.value))}
				className="range"
				style={{'--range-progress': `${((value - min) / (max - min)) * 100}%`} as CSSProperties}
			/>
			{hint ? <div className="field__hint">{hint}</div> : null}
		</div>
	)
}

export function Select({
	value,
	onChange,
	children,
	id,
	className = '',
}: {
	value: string
	onChange: (value: string) => void
	children: ReactNode
	id?: string
	className?: string
}) {
	return (
		<div className={`select-wrap ${className}`}>
			<select id={id} className="input select" value={value} onChange={(event) => onChange(event.target.value)}>
				{children}
			</select>
		</div>
	)
}

export function Modal({
	open,
	onClose,
	title,
	eyebrow,
	children,
	footer,
	width = 'md',
}: {
	open: boolean
	onClose: () => void
	title: string
	eyebrow?: string
	children: ReactNode
	footer?: ReactNode
	width?: 'sm' | 'md' | 'lg'
}) {
	const panelRef = useRef<HTMLDivElement>(null)
	useEffect(() => {
		if (!open) return
		const onKey = (event: KeyboardEvent) => {
			if (event.key === 'Escape') onClose()
		}
		document.addEventListener('keydown', onKey)
		const previous = document.body.style.overflow
		document.body.style.overflow = 'hidden'
		const focusTimer = window.setTimeout(() => {
			const first = panelRef.current?.querySelector<HTMLElement>(
				'input, select, textarea, button:not(.modal__close)',
			)
			first?.focus()
		}, 30)
		return () => {
			document.removeEventListener('keydown', onKey)
			document.body.style.overflow = previous
			window.clearTimeout(focusTimer)
		}
	}, [open, onClose])

	if (!open) return null
	return createPortal(
		<div className="modal-backdrop" onMouseDown={(event) => event.target === event.currentTarget && onClose()}>
			<div ref={panelRef} className={`modal modal--${width}`} role="dialog" aria-modal="true" aria-label={title}>
				<div className="modal__head">
					<div>
						{eyebrow ? <div className="eyebrow">{eyebrow}</div> : null}
						<h2 className="modal__title">{title}</h2>
					</div>
					<IconButton label="Close dialog" onClick={onClose} className="modal__close">
						<X size={18} />
					</IconButton>
				</div>
				<div className="modal__body">{children}</div>
				{footer ? <div className="modal__footer">{footer}</div> : null}
			</div>
		</div>,
		document.body,
	)
}

export function EmptyState({
	icon,
	title,
	description,
	action,
}: {
	icon: ReactNode
	title: string
	description: string
	action?: ReactNode
}) {
	return (
		<div className="empty-state">
			<div className="empty-state__icon">{icon}</div>
			<h3>{title}</h3>
			<p>{description}</p>
			{action ? <div className="empty-state__action">{action}</div> : null}
		</div>
	)
}

export function Spinner({label = 'Loading'}: {label?: string}) {
	return (
		<div className="spinner-wrap" role="status" aria-label={label}>
			<span className="spinner" />
		</div>
	)
}

export function KeyValue({label, value}: {label: string; value: ReactNode}) {
	return (
		<div className="key-value">
			<span>{label}</span>
			<strong>{value}</strong>
		</div>
	)
}

export function Segmented<T extends string>({
	value,
	options,
	onChange,
	label,
}: {
	value: T
	options: Array<{value: T; label: string; icon?: ReactNode}>
	onChange: (value: T) => void
	label: string
}) {
	return (
		<div className="segmented" role="group" aria-label={label}>
			{options.map((option) => (
				<button
					key={option.value}
					type="button"
					className={`segmented__item ${value === option.value ? 'segmented__item--active' : ''}`}
					onClick={() => onChange(option.value)}
					aria-pressed={value === option.value}
				>
					{option.icon}
					<span>{option.label}</span>
				</button>
			))}
		</div>
	)
}

export function CopyButton({value, label = 'Copy'}: {value: string; label?: string}) {
	const [copied, setCopied] = useState(false)
	const copy = async () => {
		try {
			await navigator.clipboard.writeText(value)
		} catch {
			const textarea = document.createElement('textarea')
			textarea.value = value
			document.body.appendChild(textarea)
			textarea.select()
			document.execCommand('copy')
			textarea.remove()
		}
		setCopied(true)
		window.setTimeout(() => setCopied(false), 1800)
	}
	return (
		<Button
			variant="quiet"
			size="sm"
			onClick={copy}
			icon={copied ? <Check size={13} /> : <Copy size={13} />}
		>
			{copied ? 'Copied' : label}
		</Button>
	)
}
