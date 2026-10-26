import { render, screen, within } from '@testing-library/svelte';
import { expect, test } from 'vitest';
import { PICTURE } from '../test-support/board';
import EnlargeablePicture from './EnlargeablePicture.svelte';

function decode(source: string): string {
	return Buffer.from(source.slice(source.indexOf(',') + 1), 'base64').toString('utf-8');
}

test('the picture is a button named Enlarge picture holding one image of the picture', () => {
	render(EnlargeablePicture, { picture: PICTURE, alt: 'The song stays open.', caption: undefined });

	const button = screen.getByRole('button', { name: 'Enlarge picture' });
	const image = within(button).getByRole('img');
	expect(image).toHaveAttribute('alt', 'The song stays open.');
	const source = image.getAttribute('src') ?? '';
	expect(source.startsWith('data:image/svg+xml;base64,')).toBe(true);
	expect(decode(source)).toBe(PICTURE);
});

test('a given caption appears below the picture and none is drawn without one', () => {
	const { container, rerender } = render(EnlargeablePicture, {
		picture: PICTURE,
		alt: 'alt text',
		caption: 'Today the song is lost.'
	});

	const caption = screen.getByText('Today the song is lost.', { selector: 'p' });
	expect(caption).toHaveClass('caption');
	expect(screen.getByRole('button', { name: 'Enlarge picture' }).nextElementSibling).toBe(caption);

	rerender({ picture: PICTURE, alt: 'alt text', caption: undefined });
	expect(container.querySelector('p.caption')).toBeNull();
});

test('the closed dialog is named Picture at full width and holds no image and no Close button', () => {
	render(EnlargeablePicture, { picture: PICTURE, alt: 'alt text', caption: 'cap' });

	const dialog = screen.getByRole('dialog', { hidden: true });
	expect(dialog).toHaveAttribute('aria-label', 'Picture at full width');
	expect(within(dialog).queryAllByRole('img', { hidden: true })).toHaveLength(0);
	expect(within(dialog).queryAllByRole('button', { hidden: true })).toHaveLength(0);
});

test('a thumbnail holds one aria-hidden enlarge mark and a plain picture holds none', () => {
	const { container, unmount } = render(EnlargeablePicture, {
		picture: PICTURE,
		alt: 'alt text',
		caption: undefined,
		thumbnail: true
	});

	const marks = container.querySelectorAll('button svg');
	expect(marks).toHaveLength(1);
	expect(marks[0]).toHaveAttribute('aria-hidden', 'true');
	unmount();

	const plain = render(EnlargeablePicture, {
		picture: PICTURE,
		alt: 'alt text',
		caption: undefined
	});
	expect(plain.container.querySelectorAll('svg')).toHaveLength(0);
});

test('a hostile picture, alt and caption render as text and one image', () => {
	const hostile = '<img src=x onerror=alert(1)>';

	const { container } = render(EnlargeablePicture, {
		picture: '<svg onload="alert(1)"><script>alert(2)</script></svg>',
		alt: hostile,
		caption: hostile,
		thumbnail: true
	});

	expect(container.querySelectorAll('img')).toHaveLength(1);
	expect(container.querySelectorAll('script, svg:not([aria-hidden="true"])')).toHaveLength(0);
	expect(container.querySelector('[onload], [onerror]')).toBeNull();
	expect(screen.getByText(hostile, { selector: 'p' })).toBeInTheDocument();
});
