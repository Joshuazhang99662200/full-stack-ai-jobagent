import { readFileSync, writeFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { dirname, join } from 'node:path';
import { createHash } from 'node:crypto';
import { fileURLToPath, pathToFileURL } from 'node:url';

const root = dirname(fileURLToPath(import.meta.url));
let require = createRequire(import.meta.url);
if (process.env.HALLMARK_PUPPETEER) require = createRequire(join(process.env.HALLMARK_PUPPETEER, 'package.json'));
const puppeteer = require('puppeteer-core');
const browser = await puppeteer.launch({ executablePath: process.env.CHROME_PATH, headless: true });
const outputs = {};
try {
  const page = await browser.newPage();
  await page.setRequestInterception(true);
  page.on('request', request => /^https?:/.test(request.url()) ? request.abort() : request.continue());
  await page.goto(pathToFileURL(join(root, 'workflow.html')).href);
  await page.evaluate(() => document.fonts.ready);
  for (const width of [1280, 375]) {
    await page.setViewport({ width, height: 900, deviceScaleFactor: 2 });
    const overflow = await page.evaluate(() => [...document.querySelectorAll('h1,h2,h3,p,dt,dd,.sequence>div,.triggers li')].filter(el => el.scrollWidth > el.clientWidth + 1).map(el => el.textContent));
    if (overflow.length) throw new Error(`Text overflow at ${width}: ${JSON.stringify(overflow)}`);
    for (const name of ['workflow', 'resume-exchange', 'feedback']) {
      const file = name + (width === 375 ? '-mobile' : '') + '.png';
      const element = await page.$('#' + name);
      const bounds = await element.boundingBox();
      await element.screenshot({ path: join(root, file) });
      outputs[file] = createHash('sha256').update(readFileSync(join(root, file))).digest('hex');
      console.log(`${file}: ${Math.round(bounds.width)} × ${Math.round(bounds.height)} CSS px`);
    }
  }
} finally { await browser.close(); }
const sources = {};
for (const file of ['workflow.html', 'workflow.css', 'render-workflow.mjs', '../../workflow-outline.md', '../../workflow-implementation.md']) {
  sources[file] = createHash('sha256').update(readFileSync(join(root, file), 'utf8').replace(/\r\n/g, '\n')).digest('hex');
}
writeFileSync(join(root, 'workflow-manifest.json'), JSON.stringify({ kind: 'workflow explanation, no invented metrics', source_hash_policy: 'UTF-8 text normalized to LF', sources, outputs }, null, 2) + '\n');
