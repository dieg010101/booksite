import type { AsciiMapOptions } from './types';

function seeded(x: number, y: number): number {
	const n = x * 374761393 + y * 668265263;
	const s = Math.sin(n) * 43758.5453123;
	return s - Math.floor(s);
}

export function renderAsciiMap(params: {
	ctx: CanvasRenderingContext2D;
	mask: ImageData;
	width: number;
	height: number;
	opts: AsciiMapOptions;
}) {
	const { ctx, mask, width, height, opts } = params;
	ctx.save();
	ctx.fillStyle = opts.background;
	ctx.fillRect(0, 0, width, height);
	ctx.font = `${opts.fontSize}px ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace`;
	ctx.fillStyle = opts.color;
	ctx.globalAlpha = opts.opacity;
	ctx.textBaseline = 'top';
	const step = Math.max(4, Math.floor(opts.step));
	const chars = opts.chars.length ? opts.chars : '01';
	const data = mask.data;

	for (let y = 0; y < height; y += step) {
		for (let x = 0; x < width; x += step) {
			const i = (y * width + x) * 4;
			const a = data[i + 3];
			const isLand = a > 16;
			if (!isLand) continue;
			const rnd = seeded(x, y);
			const idx = Math.floor(rnd * chars.length);
			ctx.fillText(chars[idx], x, y);
		}
	}

	ctx.restore();
}
