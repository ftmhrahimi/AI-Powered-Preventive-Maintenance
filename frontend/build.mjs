// Production build: minifies index.html (markup, inline CSS, inline JS).
//
// Guarantees that keep behavior identical:
// - Top-level JS names are NOT mangled (94 inline on* handlers in the HTML
//   call global functions by name); only function-local names are shortened.
// - Whitespace is conservatively collapsed (never fully removed between
//   elements), so rendering is pixel-identical.
// - console.* calls and all comments are stripped (debug output only).
import { minify } from 'html-minifier-terser';
import { readFile, writeFile, mkdir } from 'fs/promises';

const html = await readFile('index.html', 'utf8');

const out = await minify(html, {
  removeComments: true,
  collapseWhitespace: true,
  conservativeCollapse: true,
  minifyCSS: true,
  minifyJS: {
    compress: {
      drop_console: true,
      drop_debugger: true,
      passes: 2,
    },
    mangle: true, // locals only; toplevel mangling stays OFF
    format: { comments: false },
  },
});

await mkdir('dist', { recursive: true });
await writeFile('dist/index.html', out);

const before = Buffer.byteLength(html);
const after = Buffer.byteLength(out);
console.log(
  `index.html: ${before} -> ${after} bytes (${(100 - (after / before) * 100).toFixed(1)}% smaller)`
);
