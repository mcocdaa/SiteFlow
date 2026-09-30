const { chromium } = require('playwright');
const path = require('path');

const ARTIFACT_DIR = '/home/mcocdaa/.gemini/antigravity-cli/brain/3ab10846-a235-4655-be53-039a89d0f6f8';
const BASE_URL = 'http://127.0.0.1:18080';

async function main() {
  const browser = await chromium.launch({
    executablePath: '/home/mcocdaa/.cache/ms-playwright/chromium-1243/chrome-linux64/chrome',
    args: ['--no-sandbox', '--disable-setuid-sandbox']
  });

  // 1. Light Mode Palette Test
  console.log('--- Testing Light Mode Palette ---');
  const lightContext = await browser.newContext({
    viewport: { width: 1440, height: 900 },
    colorScheme: 'light'
  });
  const lightPage = await lightContext.newPage();
  await lightPage.goto(BASE_URL);
  await lightPage.waitForLoadState('networkidle');

  // Trigger Cmd+K
  await lightPage.click('#cmd-k-trigger');
  await lightPage.waitForSelector('#cmd-palette:not([hidden])');
  await lightPage.waitForTimeout(300); // Wait for fade in animation

  await lightPage.screenshot({
    path: path.join(ARTIFACT_DIR, 'palette_fixed_light.png'),
    fullPage: false
  });
  console.log('Saved palette_fixed_light.png');

  // Type search query '2048'
  await lightPage.fill('#palette-input', '2048');
  await lightPage.waitForTimeout(400); // wait for search debounce

  await lightPage.screenshot({
    path: path.join(ARTIFACT_DIR, 'palette_fixed_search.png'),
    fullPage: false
  });
  console.log('Saved palette_fixed_search.png');
  await lightContext.close();

  // 2. Dark Mode Palette Test
  console.log('--- Testing Dark Mode Palette ---');
  const darkContext = await browser.newContext({
    viewport: { width: 1440, height: 900 },
    colorScheme: 'dark'
  });
  const darkPage = await darkContext.newPage();
  await darkPage.goto(BASE_URL);
  await darkPage.waitForLoadState('networkidle');

  // Trigger Cmd+K
  await darkPage.click('#cmd-k-trigger');
  await darkPage.waitForSelector('#cmd-palette:not([hidden])');
  await darkPage.waitForTimeout(300);

  await darkPage.screenshot({
    path: path.join(ARTIFACT_DIR, 'palette_fixed_dark.png'),
    fullPage: false
  });
  console.log('Saved palette_fixed_dark.png');
  await darkContext.close();

  await browser.close();
  console.log('All palette verification screenshots captured successfully!');
}

main().catch(err => {
  console.error('Error during palette test:', err);
  process.exit(1);
});
