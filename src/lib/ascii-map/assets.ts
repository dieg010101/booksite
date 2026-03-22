export async function loadImage(src: string): Promise<HTMLImageElement> {
	const img = new Image();
	img.src = src;
	await img.decode();
	return img;
}
