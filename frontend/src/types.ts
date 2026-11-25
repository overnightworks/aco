/**
 * The board's JSON wire form (`specs/serve.spec.md` ABRD-08/09/21): one
 * mirror of `GET /api/board`'s shape, field names included, so no codec
 * stands between this file and the server's own contract. Each line is
 * `aco rulings --json`'s line (`specs/rulings.spec.md`); an option line
 * adds `fingerprint`.
 */

export type Outcome = 'yes' | 'no' | 'later';

/** A ruled yes/no line: read-only history the board shows and never writes
 * (ABRD-34). Its card fields are absent when unset (RUL-06). */
export interface YesNoLine {
	index: number;
	text: string;
	question?: string;
	example?: string;
	picture?: string;
	ruling: Outcome;
	ruled_on: string;
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
 * picture as it is, or neither -- never both (`specs/serve.spec.md` ABRD-34). */
export type CardOption = CardOptionFields &
	(
		| { picture: string; caption?: string; same_as_today?: never }
		| { same_as_today: true; picture?: never; caption?: never }
		| { picture?: never; caption?: never; same_as_today?: never }
	);

export type RulingVia = 'board' | 'chat' | 'default';

/** An option line (`specs/serve.spec.md` ABRD-34): the one form `form`
 * names; a yes/no line carries no `form` at all. */
export interface OptionLine {
	index: number;
	form: 'options';
	text: string;
	/** The day its head asked it (RUL-19); null only on a ruled line stored without it. */
	asked_on: string | null;
	/** The card as it reads now (RUL-14). */
	card_hash: string;
	/** The card its ruling was made on (RUL-14); null while open. */
	stored_card_hash: string | null;
	question: string;
	problem: string;
	/** The TODAY picture and its caption; a caption comes only with a picture. */
	picture?: string;
	caption?: string;
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

/** A ruled option line: a ruling always comes with its date and its `via`
 * (BODY-86). */
export interface RuledOptionLine extends OptionLine {
	ruling: OptionLetter | 'other';
	ruled_on: string;
	via: RulingVia;
}

/** A ruled line, of either form; it always carries its date (BODY-32, BODY-86). */
export type RuledLine = YesNoLine | RuledOptionLine;

export interface BoardItem {
	number: number;
	title: string;
	lines: ExpectationLine[];
}

/** The counts of one top-level container or of a whole repo; `percent` is
 * `null` while nothing is planned (ABRD-131). */
export interface ProgressCounts {
	closed: number;
	/** Of `closed`, the children a trunk commit's trailer names as landed (ABRD-136). */
	landed: number;
	planned: number;
	open: number;
	uncut: number;
	percent: number | null;
}

/** One size class of the lanes left: `size` is `null` for lanes with no declared size, and
 * `basis` says whether the class was priced from its own finished items or pooled (ABRD-143). */
interface PricedClass {
	size: 'S' | 'M' | 'L' | null;
	lanes: number;
	basis: 'measured' | 'pooled';
	samples: number;
}

/** The agent work left as a range in whole seconds; `samples` counts the pooled finished
 * items (ABRD-145). */
export interface WorkRange {
	error: null;
	low_seconds: number;
	high_seconds: number;
	samples: number;
	classes: PricedClass[];
}

/** Why a container has no range: the sentence, and no figures (ABRD-144). */
export interface NoWorkRange {
	error: string;
}

/** A closed child of the repository with the lane time and fix rounds its lane records state;
 * `null` is unknown, `recorded` false that no lane record names it (ABRD-147 to ABRD-150). */
export interface ClosedChild {
	number: number;
	title: string;
	wall_seconds: number | null;
	fix_rounds: number | null;
	recorded: boolean;
}

export interface ProgressContainer extends ProgressCounts {
	number: number;
	title: string;
	/** The container's open children that wait on the operator (ABRD-137). */
	waiting: number;
	/** The open children not waiting on the operator plus the uncut rows (ABRD-140). */
	lanes_left: number;
	/** `null` while no lane is left. */
	estimate: WorkRange | NoWorkRange | null;
	/** The closed children of this repository by number (ABRD-147). */
	closed_children: ClosedChild[];
}

/** A repo's progress read (ABRD-132): the sum of its top-level containers. */
export interface ProgressRead extends ProgressCounts {
	error: null;
	/** The items waiting on the operator. */
	waiting: number;
	containers: ProgressContainer[];
}

/** A repo whose progress could not be read: the sentence, and no counts (ABRD-134). */
interface ProgressUnknown {
	error: string;
}

/** What every step waiting on the operator lists (ABRD-157): `step` is its one line. */
interface StepBase {
	number: number;
	title: string;
	step: string;
	answer: string | null;
	/** The step as listed, bound to its repo, item and card (ABRD-163); an answer posts it back. */
	fingerprint: string;
}

/** A step whose paste keeps the tool's rules: one command or one link, and the card's other
 * fields. */
export interface PasteStepRead extends StepBase {
	form: 'paste';
	purpose: string;
	paste: string;
	paste_kind: 'command' | 'link';
	expected: string;
	actions: null;
}

/** A stored older step, or a table-less one: each field is `null` where the stored `step`
 * table lacks it. */
export interface OldStepRead extends StepBase {
	form: 'old';
	purpose: string | null;
	paste: string | null;
	paste_kind: null;
	expected: string | null;
	actions: string | null;
}

/** A step waiting on the operator (ABRD-157). */
export type StepRead = PasteStepRead | OldStepRead;

export interface RepoReading {
	name: string;
	/** aco's own failure sentence once this repo's read failed, else null. */
	error: string | null;
	items: BoardItem[];
	/** `null` once this repo's read failed. */
	progress: ProgressRead | ProgressUnknown | null;
	/** The members' steps waiting on the operator, newest first (ABRD-157). */
	steps: StepRead[];
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

/** `POST /api/rule`'s 200 (`aco.board.ports.DecisionStatus`'s four values): a
 * stored card carries the written item as `GET /api/board` lists it, a refusal
 * only its sentence. A `note` comes beside the item when the answer needs a word
 * (ABRD-129). */
export type DecisionResult =
	| { status: 'ruled' | 'returned'; message: null; item: BoardItem; note?: string }
	| { status: 'already_ruled' | 'failed'; message: string | null };

/** `POST /api/step`'s body (ABRD-164): `yes` carries no `text`, `no` and `report` do. */
export interface StepRequest {
	repo: string;
	item: number;
	fingerprint: string;
	result: 'yes' | 'no' | 'report';
	text?: string;
}

/** `POST /api/step`'s 200 (ABRD-166..172): a stored answer carries no item, and a `note` when
 * the label stayed (ABRD-169); a refusal only its sentence. */
export interface StepResult {
	status: 'answered' | 'failed';
	message: string | null;
	note?: string;
}
