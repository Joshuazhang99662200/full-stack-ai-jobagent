import { readFileSync, writeFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { dirname, join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const root = dirname(fileURLToPath(import.meta.url));
const samples = JSON.parse(readFileSync(join(root, 'samples.json'), 'utf8'));
const escaped = value => String(value).replace(/[&<>"']/g, char => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[char]));
const json = value => escaped(JSON.stringify(value, null, 2));
const compactJson = value => escaped(JSON.stringify(value, null, 2).replace(/\[\n\s+([^\[\]]*?)\n\s*\]/g, (_, inner) => '[' + inner.replace(/\n\s*/g, ' ') + ']'));
const short = digest => escaped(digest.slice(0, 20) + '…');
const job = Object.fromEntries(['source', 'source_job_id', 'title', 'company', 'location', 'jd_raw'].map(key => [key, samples.job[key]]));
const difference = samples.mechanical_diff.items[0];
const failed = { passed: samples.without_review.passed, issues: samples.without_review.issues.map(issue => issue.code) };
const passed = { passed: samples.with_fixture_review.passed, issues: samples.with_fixture_review.issues.map(issue => issue.code) };
const rows = Object.keys(samples.approval_before).map(key => {
  const changed = samples.rejection.details.changed.includes(key);
  return `<tr${changed ? ' class="changed"' : ''}><td data-label="绑定内容"><code>${key}</code></td><td data-label="获批版本"><code>${short(samples.approval_before[key])}</code></td><td data-label="当前版本"><code>${short(samples.approval_after[key])}</code></td><td data-label="核对结果" class="${changed ? 'status-fail' : 'same'}">${changed ? '已改变' : '一致'}</td></tr>`;
}).join('');

const html = `<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>CareerHarness 合成输出记录</title><meta name="description" content="从实际 Python CLI、复核与审批函数取得的合成测试输出。"><link rel="stylesheet" href="style.css"></head>
<body><main>
<figure class="sheet" id="overview" aria-labelledby="overview-title">
  <h1 id="overview-title">先取回完整 JD</h1>
  <p class="intro">下面是内置合成岗位的 CLI 输出节选。</p>
  <p class="command"><code>${escaped(samples.job_command)}</code></p>
  <pre class="output">${json(job)}</pre>
  <figcaption>来源为 <code>src/jobagent/connectors/fixtures/jobs.json</code>。读取不需要平台账号，也不会触发投递。</figcaption>
</figure>
<figure class="sheet" id="evidence" aria-labelledby="evidence-title">
  <h2 id="evidence-title">保留原文，也保留复核结果</h2>
  <p class="intro">同一个合成案例里的改写、证据与校验记录。</p>
  <div class="columns">
    <div>
      <h3 class="record-title">程序计算的文本差异</h3>
      <div class="diff"><div class="diff-line minus"><span class="sign">−</span><span>${escaped(difference.original)}</span></div><div class="diff-line plus"><span class="sign">+</span><span>${escaped(difference.optimized)}</span></div></div>
      <dl class="definition"><div><dt>改写操作</dt><dd><code>${escaped(difference.rewrite_operations.join(', '))}</code></dd></div><div><dt>对应岗位要求</dt><dd><code>${escaped(difference.requirement_ids.join(', '))}</code></dd></div></dl>
    </div>
    <div>
      <h3 class="record-title">被引用的证据</h3>
      <dl class="definition"><div><dt>证据编号</dt><dd><code class="instrument">${escaped(samples.evidence.id)}</code></dd></div><div><dt>原始陈述</dt><dd>${escaped(samples.evidence.statement)}</dd></div><div><dt>出处</dt><dd><code>${escaped(samples.evidence.source.reference)}</code></dd></div><div><dt>本人确认字段（合成夹具）</dt><dd><code class="human">user_confirmed: ${samples.evidence.user_confirmed}</code></dd></div></dl>
    </div>
  </div>
  <div class="verification"><div><h3 class="record-title">没有独立复核</h3><pre class="status-fail">${compactJson(failed)}</pre></div><div><h3 class="record-title">提供复核夹具后</h3><pre class="status-pass">${compactJson(passed)}</pre></div></div>
  <figcaption>由 <code>ResumeDiffBuilder</code> 和 <code>verify_draft</code> 实际计算。资料与复核结论均为测试夹具，不代表真实候选人或真实模型评审。</figcaption>
</figure>
<figure class="sheet" id="approval" aria-labelledby="approval-title">
  <h2 id="approval-title">正文改过，旧审批就失效</h2>
  <p class="intro">仅将合成消息中的 Hello 改为 Hi，再核对四份摘要。</p>
  <table class="ledger"><thead><tr><th scope="col">审批绑定的内容</th><th scope="col">获批版本</th><th scope="col">当前版本</th><th scope="col">核对结果</th></tr></thead><tbody>${rows}</tbody></table>
  <div class="error-result"><pre>${compactJson({code: samples.rejection.code, details: {changed: samples.rejection.details.changed}})}</pre></div>
  <figcaption>显示实际摘要的前缀，完整值保留在 <code>samples.json</code>。只运行本地合成校验，没有平台请求或真实发送授权。</figcaption>
</figure>
</main></body></html>`;
writeFileSync(join(root, 'figures.html'), html);

let require = createRequire(import.meta.url);
if (process.env.HALLMARK_PUPPETEER) require = createRequire(join(process.env.HALLMARK_PUPPETEER, 'package.json'));
const puppeteer = require('puppeteer-core');
const browser = await puppeteer.launch({executablePath: process.env.CHROME_PATH, headless: true});
try {
  const page = await browser.newPage();
  await page.setRequestInterception(true);
  page.on('request', request => /^https?:/.test(request.url()) ? request.abort() : request.continue());
  await page.goto(pathToFileURL(join(root, 'figures.html')).href);
  await page.evaluate(() => document.fonts.ready);
  for (const width of [1280, 375]) {
    await page.setViewport({width, height: 900, deviceScaleFactor: 2});
    for (const name of ['overview', 'evidence', 'approval']) {
      const suffix = width === 375 ? '-mobile' : '';
      const element = await page.$('#' + name);
      await element.screenshot({path: join(root, name + suffix + '.png')});
      console.log('Rendered ' + name + suffix + '.png');
    }
  }
} finally { await browser.close(); }
