/**
 * The access token lives only in the URL's fragment (`#t=…`), never in the
 * path or query a server ever sees (`specs/serve.spec.md` ABRD-10).
 */

export function tokenFromHash(hash: string): string | null {
	if (!hash.startsWith('#')) {
		return null;
	}
	const token = new URLSearchParams(hash.slice(1)).get('t');
	return token !== null && token.length > 0 ? token : null;
}
