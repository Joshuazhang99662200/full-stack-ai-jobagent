import { createRequire } from 'node:module';
import { dirname,join } from 'node:path';
import { fileURLToPath,pathToFileURL } from 'node:url';
const root=dirname(fileURLToPath(import.meta.url));
const require=createRequire(join(process.env.HALLMARK_PUPPETEER,'package.json'));
const puppeteer=require('puppeteer-core');
const browser=await puppeteer.launch({executablePath:process.env.CHROME_PATH,headless:true});
try {
 const page=await browser.newPage();
 await page.setRequestInterception(true);
 page.on('request',r=>/^https?:/.test(r.url())?r.abort():r.continue());
 await page.setViewport({width:375,height:900,deviceScaleFactor:2});
 await page.goto(pathToFileURL(join(root,'mobile.html')).href);
 await page.evaluate(()=>document.fonts.ready);
 const overflow=await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth || [...document.querySelectorAll('h1,h2,h3,p')].some(e=>e.scrollWidth>e.clientWidth+1));
 if(overflow)throw Error('Mobile diagram text overflows');
 const figure=await page.$('#mobile-workflow');
 console.log(await figure.boundingBox());
 await figure.screenshot({path:join(root,'workflow-mobile.png')});
} finally {await browser.close();}
