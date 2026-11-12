import { readFileSync, readdirSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import type { Plugin } from 'vite';

// The house fonts have one owner, the design package. This plugin lays its font
// files, their licences and its `@font-face` rules into the build under
// `assets/fonts/` (a licence gains `.txt`: the repository tracks no file without a
// suffix), so the committed board serves them from its own origin and a
// Python-only install needs neither Node nor the package.
const FONTS_DIRECTORY = 'assets/fonts';
const LICENCE_FILE = /-LICENSE$/;
const FONT_FACE_RULES = /@font-face\s*\{[^}]*\}/g;

function designStaticDirectory(): string {
	return dirname(fileURLToPath(import.meta.resolve('overnightworks-design/design.css')));
}

export function houseFonts(): Plugin {
	const staticDirectory = designStaticDirectory();
	const fontsDirectory = join(staticDirectory, 'fonts');
	return {
		name: 'house-fonts',
		transformIndexHtml: () => [
			{
				tag: 'link',
				attrs: { rel: 'stylesheet', href: `./${FONTS_DIRECTORY}/fonts.css` },
				injectTo: 'head'
			}
		],
		generateBundle() {
			for (const name of readdirSync(fontsDirectory)) {
				this.emitFile({
					type: 'asset',
					fileName: `${FONTS_DIRECTORY}/${name.replace(LICENCE_FILE, '-LICENSE.txt')}`,
					source: readFileSync(join(fontsDirectory, name))
				});
			}
			const designStylesheet = readFileSync(join(staticDirectory, 'design.css'), 'utf8');
			const rules = (designStylesheet.match(FONT_FACE_RULES) ?? []).join('\n');
			this.emitFile({
				type: 'asset',
				fileName: `${FONTS_DIRECTORY}/fonts.css`,
				source: rules.replaceAll("url('fonts/", "url('")
			});
		}
	};
}
