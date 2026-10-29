/**
 * The board's JSON wire form (`specs/serve.spec.md` ABRD-08/09/21): one
 * mirror of `GET /api/board`'s shape, field names included, so no codec
 * stands between this file and the server's own contract.
 */

export type Outcome = 'yes' | 'no' | 'later';

/** A ruled yes/no line: read-only history the board shows and never writes (ABRD-34). */
export interface YesNoLine {
	index: number;
	text: string;
	question: string | null;
	example: string | null;
	picture: string | null;
	ruling: Outcome;
	ruled_on: string | null;
	/** Bound to the repo it was read under (ABRD-21); opaque to this client. */
	fingerprint: string;
}

type OptionLetter = 'A' | 'B' | 'C' | 'D';

export type DecisionKind =
	'product' | 'technical' | 'data_risk' | 'money' | 'access' | 'wording' | 'release';

export type Undo = 'reversible' | 'final';

interface CardOptionFields {
	letter: OptionLetter;
	name: string;
	effect: string;
	notice: string;
	cost: string;
	undo: Undo;
	undo_how: string;
	contract: string;
}

/** An option's RESULT picture, or the statement that it leaves the TODAY
 * picture as it is -- never both (`specs/serve.spec.md` ABRD-34). */
export type CardOption = CardOptionFields &
	({ picture: string; caption?: string } | { same_as_today: true });

export type RulingVia = 'board' | 'chat' | 'default';

/** An option line (`specs/serve.spec.md` ABRD-34): the one form `form`
 * names; a yes/no line carries no `form` at all. */
export interface OptionLine {
	index: number;
	form: 'options';
	text: string;
	question: string;
	problem: string;
	picture: string;
	caption: string;
	decision_kind: DecisionKind;
	area: string;
	topic: string;
	recommended: OptionLetter;
	reason: string;
	options: CardOption[];
	ruling: OptionLetter | 'other' | null;
	ruled_on: string | null;
	/** Who decided and how (ABRD-53), as aco stored it; null while open. */
	via: RulingVia | null;
	/** The operator's own answer, verbatim, exactly when `ruling` is `'other'` (ABRD-56). */
	other: string | null;
	/** The day the operator sent the open line back to its head (ABRD-62), else null. */
	returned_on: string | null;
	/** What the operator asked of the head; null when none or not returned. */
	returned_note: string | null;
	/** Bound to the repo it was read under (ABRD-21); opaque to this client. */
	fingerprint: string;
}

export type ExpectationLine = YesNoLine | OptionLine;

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

/** A line of a posted card (ABRD-77), as shown: `fingerprint` is the line's own,
 * bound to `repo` as read (ABRD-21). */
interface ShownCardLine {
	line: number;
	fingerprint: string;
}

interface PickedCardLine extends ShownCardLine {
	option: OptionLetter;
}

interface CardRequestHead {
	repo: string;
	item: number;
}

/** A card decided by a letter on every one of its lines (ABRD-77). */
export interface CardPicksRequest extends CardRequestHead {
	lines: PickedCardLine[];
}

/** The operator's own answer to the whole card: the trimmed text on every line (ABRD-77). */
export interface CardOtherRequest extends CardRequestHead {
	lines: ShownCardLine[];
	other: string;
}

/** The whole card sent back to its head with an optional note (ABRD-77). */
export interface CardUnclearRequest extends CardRequestHead {
	lines: ShownCardLine[];
	unclear: true;
	note: string | null;
}

/** `POST /api/rule`'s body (`specs/serve.spec.md` ABRD-09): always one card. */
export type DecisionRequest = CardPicksRequest | CardOtherRequest | CardUnclearRequest;

export interface DecisionResult {
	/** `aco.board.ports.DecisionStatus`'s four values, the only ones `POST
	 * /api/rule` ever answers with a 200. */
	status: 'ruled' | 'returned' | 'already_ruled' | 'failed';
	message: string | null;
}
