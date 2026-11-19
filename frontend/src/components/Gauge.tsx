import type {ReactNode} from 'react'

export function RingGauge({
	value,
	size = 116,
	stroke = 8,
	colour = '#7cf7d4',
	track = 'rgba(255,255,255,.06)',
	children,
	label,
}: {
	value: number
	size?: number
	stroke?: number
	colour?: string
	track?: string
	children?: ReactNode
	label?: string
}) {
	const clamped = Math.max(0, Math.min(1, Number.isFinite(value) ? value : 0))
	const radius = (size - stroke) / 2
	const circumference = 2 * Math.PI * radius
	const dash = circumference * clamped
	return (
		<div className="ring-gauge" style={{width: size, height: size}} aria-label={label}>
			<svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} aria-hidden="true">
				<circle cx={size / 2} cy={size / 2} r={radius} fill="none" stroke={track} strokeWidth={stroke} />
				<circle
					cx={size / 2}
					cy={size / 2}
					r={radius}
					fill="none"
					stroke={colour}
					strokeWidth={stroke}
					strokeLinecap="round"
					strokeDasharray={`${dash} ${circumference - dash}`}
					transform={`rotate(-90 ${size / 2} ${size / 2})`}
					style={{filter: `drop-shadow(0 0 7px ${colour}66)`}}
				/>
			</svg>
			<div className="ring-gauge__center">{children}</div>
		</div>
	)
}

export function Sparkline({
	values,
	colour = '#7cf7d4',
	height = 34,
	width = 120,
}: {
	values: number[]
	colour?: string
	height?: number
	width?: number
}) {
	const safe = values.length > 1 ? values : [0, values[0] ?? 0]
	const max = Math.max(1, ...safe)
	const min = Math.min(...safe)
	const span = Math.max(1, max - min)
	const points = safe
		.map((value, index) => {
			const x = (index / (safe.length - 1)) * width
			const y = height - 4 - ((value - min) / span) * (height - 8)
			return `${x.toFixed(1)},${y.toFixed(1)}`
		})
		.join(' ')
	return (
		<svg
			className="sparkline"
			viewBox={`0 0 ${width} ${height}`}
			preserveAspectRatio="none"
			width={width}
			height={height}
			aria-hidden="true"
		>
			<polyline points={points} fill="none" stroke={colour} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
		</svg>
	)
}
