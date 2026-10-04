/**
 * The board's JSON wire form (`specs/aco-board.spec.md` ABRD-08/09/21): one
 * mirror of `GET /api/board`'s shape, field names included, so no codec
 * stands between this file and the server's own contract.
 */

export type Outcome = 'yes' | 'no' | 'later';

export interface ExpectationLine {
	index: number;
	text: string;
	question: string | null;
	example: string | null;
	picture: string | null;
	default: Outcome | null;
	ruling: Outcome | null;
	ruled_on: string | null;
	/** Bound to the repo it was read under (ABRD-21); opaque to this client. */
	fingerprint: string;
}

export interface BoardItem {
	number: number;
	title: string;
	lines: ExpectationLine[];
}

export interface RepoReading {
	name: string;
	/** aco's own failure sentence once this repo's read failed, else null. */
	error: string | null;
	items: BoardItem[];
}

export interface BoardResponse {
	repos: RepoReading[];
}

/** `POST /api/rule`'s body (`specs/aco-board.spec.md` ABRD-09): `fingerprint`
 * is the card's own, bound to `repo` as read (ABRD-21) -- never the line's
 * bare fingerprint. */
export interface DecisionRequest {
	repo: string;
	item: number;
	line: number;
	fingerprint: string;
	outcome: Outcome;
	note: string | null;
}

export interface DecisionResult {
	/** `aco_board.ports.DecisionStatus`'s three values, the only ones `POST
	 * /api/rule` ever answers with a 200. */
	status: 'ruled' | 'already_ruled' | 'failed';
	message: string | null;
}
