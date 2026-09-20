const { chromium } = require('playwright');
const path = require('path');

const ARTIFACT_DIR = '/home/mcocdaa/.gemini/antigravity-cli/brain/3ab10846-a235-4655-be53-039a89d0f6f8';
const BASE_URL = 'http://127.0.0.1:8089';

async function main() {
  const browser = await chromium.launch({
    headless: true,
    executablePath: '/home/mcocdaa/.cache/ms-playwright/chromium-1243/chrome-linux64/chrome'
  });

  // 1. Admin Dashboard (Dark & Light)
  {
    const context = await browser.newContext({
      viewport: { width: 1440, height: 960 },
      colorScheme: 'dark'
    });
    const page = await context.newPage();

    console.log('Navigating to /login...');
    await page.goto(`${BASE_URL}/login`);
    await page.waitForSelector('input[name="password"]');
    await page.fill('input[name="password"]', 'siteflow_admin_2026');
    await Promise.all([
      page.waitForNavigation({ waitUntil: 'networkidle' }),
      page.click('button[type="submit"]')
    ]);

    console.log('Logged in, current URL:', page.url());
    if (!page.url().includes('/admin')) {
      await page.goto(`${BASE_URL}/admin`, { waitUntil: 'networkidle' });
    }

    await page.waitForTimeout(600);
    await page.screenshot({ path: path.join(ARTIFACT_DIR, 'admin_dashboard_dark.png') });
    console.log('Saved admin_dashboard_dark.png');

    await page.emulateMedia({ colorScheme: 'light' });
    await page.waitForTimeout(400);
    await page.screenshot({ path: path.join(ARTIFACT_DIR, 'admin_dashboard_light.png') });
    console.log('Saved admin_dashboard_light.png');

    await context.close();
  }

  // 2. Responsive Preview Modal & QR Code Popover
  {
    const context = await browser.newContext({
      viewport: { width: 1440, height: 960 },
      colorScheme: 'dark'
    });
    const page = await context.newPage();
    await page.goto(`${BASE_URL}/`, { waitUntil: 'networkidle' });
    await page.waitForTimeout(500);

    // Find quick preview button on card
    const previewBtn = await page.$('[data-action="quick-preview"]');
    if (previewBtn) {
      console.log('Triggering quick preview...');
      await previewBtn.click();
      await page.waitForTimeout(800);
      await page.screenshot({ path: path.join(ARTIFACT_DIR, 'preview_modal_full.png') });
      console.log('Saved preview_modal_full.png');

      // Switch to Tablet 768px
      const tabletBtn = await page.$('.preview-vbtn[data-vp="768px"]');
      if (tabletBtn) {
        await tabletBtn.click();
        await page.waitForTimeout(500);
        await page.screenshot({ path: path.join(ARTIFACT_DIR, 'preview_modal_tablet.png') });
        console.log('Saved preview_modal_tablet.png');
      }

      // Switch to Mobile 375px
      const mobileBtn = await page.$('.preview-vbtn[data-vp="375px"]');
      if (mobileBtn) {
        await mobileBtn.click();
        await page.waitForTimeout(500);
        await page.screenshot({ path: path.join(ARTIFACT_DIR, 'preview_modal_mobile.png') });
        console.log('Saved preview_modal_mobile.png');
      }

      // Click QR Code popover
      const qrToggle = await page.$('#preview-qr-toggle');
      if (qrToggle) {
        await qrToggle.click();
        await page.waitForTimeout(800);
        await page.screenshot({ path: path.join(ARTIFACT_DIR, 'preview_modal_qr.png') });
        console.log('Saved preview_modal_qr.png');
      }
    } else {
      console.warn('No [data-action="quick-preview"] found!');
    }

    await context.close();
  }

  await browser.close();
  console.log('All screenshots completed successfully!');
}

main().catch(err => {
  console.error('Error during capture:', err);
  process.exit(1);
});
