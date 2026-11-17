import { render, screen } from '@testing-library/svelte';
import { expect, test } from 'vitest';
import FailureStrip from './FailureStrip.svelte';

test('[ABRD-153] names the card that was not saved and says why', () => {
	render(FailureStrip, { name: 'Jump', message: 'Das Board ist nicht erreichbar.' });

	expect(screen.getByText('Not saved: Jump')).toBeInTheDocument();
	expect(screen.getByText('Das Board ist nicht erreichbar.')).toBeInTheDocument();
});
