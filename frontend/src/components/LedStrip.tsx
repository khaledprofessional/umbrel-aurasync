import {useMemo} from 'react'

function brightness(hex: string): number {
	const match = /^#([0-9a-f]{6})$/i.exec(hex)
	if (!match) return 0
	const raw = match[1]
	return (parseInt(raw.slice(0, 2), 16) + parseInt(raw.slice(2, 4), 16) + parseInt(raw.slice(4, 6), 16)) / 765
}

export function LedStrip({
	colors,
	count,
	size = 'md',
	className = '',
	glow = true,
}: {
	colors?: string[]
	count?: number
	size?: 'xs' | 'sm' | 'md' | 'lg'
	className?: string
	glow?: boolean
}) {
	const total = Math.max(1, Math.min(count ?? colors?.length ?? 1, 220))
	const cells = useMemo(() => {
		const values = colors ?? []
		if (values.length >= total) return values.slice(0, total)
		return [...values, ...Array.from({length: total - values.length}, () => '#080b0d')]
	}, [colors, total])
	const dense = total > 44
	return (
		<div
			className={`led-strip led-strip--${size} ${dense ? 'led-strip--dense' : ''} ${className}`}
			aria-hidden="true"
		>
			{cells.map((colour, index) => {
				const level = brightness(colour)
				return (
					<span
						key={index}
						className="led-strip__cell"
						style={{
							backgroundColor: colour,
							opacity: level < 0.02 ? 0.55 : 1,
							boxShadow:
								glow && level > 0.08
									? `0 0 ${Math.round(4 + level * 13)}px ${colour}, 0 0 ${Math.round(2 + level * 5)}px ${colour}`
									: undefined,
						}}
					/>
				)
			})}
		</div>
	)
}

export function SpectrumBar({className = ''}: {className?: string}) {
	return (
		<div className={`spectrum-bar ${className}`} aria-hidden="true">
			<span style={{background: '#22d3ee'}} />
			<span style={{background: '#34d399'}} />
			<span style={{background: '#fbbf24'}} />
			<span style={{background: '#f97316'}} />
			<span style={{background: '#ef4444'}} />
		</div>
	)
}
