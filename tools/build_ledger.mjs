// 把 docs/ledger 打包成「單一 HTML 檔」的預覽版：樣式、程式、圖示全部內嵌，不需要載入其他檔案。
//
// 用法：node tools/build_ledger.mjs <輸出資料夾>
// 產出：
//   ledger.html           完整網頁，可以直接用瀏覽器打開
//   ledger-artifact.html  給 claude.ai 預覽頁用（平台會自己加上 <html>/<head>/<body>）
//
// 需要網路下載 esbuild（透過 npx，第一次會比較久）。
import { execFileSync } from 'node:child_process';
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const ESBUILD = 'esbuild@0.24.0';
const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const app = join(root, 'docs/ledger');
const outDir = resolve(process.argv[2] ?? join(root, 'build/ledger'));
mkdirSync(outDir, { recursive: true });

const js = execFileSync(
  'npx',
  ['--yes', ESBUILD, join(app, 'js/app.js'), '--bundle', '--format=iife', '--minify',
    '--target=es2020,safari15', '--define:__LEDGER_PREVIEW__=true', '--legal-comments=none'],
  { encoding: 'utf8', maxBuffer: 32 * 1024 * 1024 },
);
const css = readFileSync(join(app, 'css/style.css'), 'utf8');
const icon = `data:image/svg+xml;base64,${readFileSync(join(app, 'icons/icon.svg')).toString('base64')}`;
const html = readFileSync(join(app, 'index.html'), 'utf8');

const between = (s, a, b) => s.slice(s.indexOf(a) + a.length, s.indexOf(b));
const head = between(html, '<head>', '</head>');
const body = between(html, '<body>', '</body>');
const keep = (re) => head.match(re)?.[0] ?? '';

// </script> 出現在程式字串裡會提早結束 script 標籤，先跳脫
const safeJs = js.replace(/<\/script/gi, '<\\/script');

const inner = [
  keep(/<title>.*<\/title>/),
  keep(/<meta name="description"[^>]*>/),
  keep(/<meta name="theme-color"[^>]*>/),
  `<link rel="icon" href="${icon}" type="image/svg+xml">`,
  `<style>\n${css}\n</style>`,
  body.trim(),
  `<script>\n${safeJs}</script>`,
].filter(Boolean).join('\n');

writeFileSync(join(outDir, 'ledger-artifact.html'), `${inner}\n`);
writeFileSync(
  join(outDir, 'ledger.html'),
  `<!doctype html>\n<html lang="zh-Hant">\n<head>\n<meta charset="utf-8">\n` +
    `<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">\n` +
    `</head>\n<body>\n${inner}\n</body>\n</html>\n`,
);
console.log(`已輸出到 ${outDir}（程式 ${Math.round(js.length / 1024)} KB）`);
