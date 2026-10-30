import { readFileSync, writeFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { createHash } from 'node:crypto';
import { dirname, join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const root = dirname(fileURLToPath(import.meta.url));
let require = createRequire(import.meta.url);
if (process.env.HALLMARK_PUPPETEER) require = createRequire(join(process.env.HALLMARK_PUPPETEER, 'package.json'));
const puppeteer = require('puppeteer-core');
const browser = await puppeteer.launch({ executablePath: process.env.CHROME_PATH, headless: true });
const outputs = {};
const sha = file => createHash('sha256').update(readFileSync(join(root, file))).digest('hex');
try {
  const page = await browser.newPage();
  await page.setRequestInterception(true);
  page.on('request', request => /^https?:/.test(request.url()) ? request.abort() : request.continue());
  for (const width of [1280, 375]) {
    await page.setViewport({ width, height: 1000, deviceScaleFactor: 2 });
    await page.goto(pathToFileURL(join(root, 'workflow.html')).href);
    await page.evaluate(() => document.fonts.ready);
    const defects = await page.evaluate(() => [...document.querySelectorAll('.node')].flatMap(node => {
      const box = node.getBoundingClientRect();
      return [...node.querySelectorAll('h2,p')].filter(text => {
        const rect = text.getBoundingClientRect();
        return rect.bottom > box.bottom + 1 || rect.right > box.right + 1 || text.scrollWidth > text.clientWidth + 1;
      }).map(text => text.textContent);
    }));
    if (defects.length) throw new Error(`Overflow at ${width}: ${JSON.stringify(defects)}`);
    const target = await page.$('#workflow');
    const bounds = await target.boundingBox();
    const file = width === 375 ? 'workflow-mobile.png' : 'workflow.png';
    await target.screenshot({ path: join(root, file) });
    outputs[file] = sha(file);
    console.log(`${file}: ${Math.round(bounds.width)} × ${Math.round(bounds.height)} CSS px`);
  }
} finally { await browser.close(); }
const sources = Object.fromEntries(['workflow.html', 'workflow.css', 'tokens.css', 'base.css', 'render.mjs', '../../workflow-outline.md', '../../workflow-implementation.md'].map(file => [file, sha(file)]));
writeFileSync(join(root, 'manifest.json'), JSON.stringify({ theme: 'Blueprint', type: 'repository fonts retained', data: 'workflow explanation; no numerical metrics', sources, outputs }, null, 2) + '\n');
