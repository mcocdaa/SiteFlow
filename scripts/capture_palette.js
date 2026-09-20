const { chromium } = require('playwright');
const path = require('path');

const ARTIFACT_DIR = '/home/mcocdaa/.gemini/antigravity-cli/brain/3ab10846-a235-4655-be53-039a89d0f6f8';
const BASE_URL = 'http://127.0.0.1:8092';

async function main() {
  const browser = await chromium.launch({
    headless: true,
    executablePath: '/home/mcocdaa/.cache/ms-playwright/chromium-1243/chrome-linux64/chrome'
  });

  // 1. Command Palette in Dark mode
  {
    const context = await browser.newContext({
      viewport: { width: 1440, height: 960 },
      colorScheme: 'dark'
    });
    const page = await context.newPage();
    await page.goto(`${BASE_URL}/`, { waitUntil: 'networkidle' });
    await page.waitForTimeout(400);

    // Trigger Cmd+K
    await page.keyboard.press('Control+KeyK');
    await page.waitForTimeout(500);

    // Type "Play" to filter
    await page.fill('#palette-input', 'Play');
    await page.waitForTimeout(300);

    await page.screenshot({ path: path.join(ARTIFACT_DIR, 'command_palette_dark.png') });
    console.log('Saved command_palette_dark.png');

    await context.close();
  }

  // 2. Command Palette in Light mode
  {
    const context = await browser.newContext({
      viewport: { width: 1440, height: 960 },
      colorScheme: 'light'
    });
    const page = await context.newPage();
    await page.goto(`${BASE_URL}/`, { waitUntil: 'networkidle' });
    await page.waitForTimeout(400);

    await page.keyboard.press('Control+KeyK');
    await page.waitForTimeout(500);

    await page.screenshot({ path: path.join(ARTIFACT_DIR, 'command_palette_light.png') });
    console.log('Saved command_palette_light.png');

    await context.close();
  }

  await browser.close();
}

main().catch(err => {
  console.error(err);
  process.exit(1);
});
