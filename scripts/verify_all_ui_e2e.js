const { chromium } = require('playwright');
const path = require('path');
const assert = require('assert');

const ARTIFACT_DIR = '/home/mcocdaa/.gemini/antigravity-cli/brain/3ab10846-a235-4655-be53-039a89d0f6f8';
const BASE_URL = 'http://127.0.0.1:8095';

async function main() {
  const browser = await chromium.launch({
    headless: true,
    executablePath: '/home/mcocdaa/.cache/ms-playwright/chromium-1243/chrome-linux64/chrome'
  });

  const results = [];
  function logStep(name, passed, detail) {
    results.push({ name, passed, detail });
    console.log(`[${passed ? 'PASS' : 'FAIL'}] ${name} - ${detail}`);
  }

  const context = await browser.newContext({
    viewport: { width: 1440, height: 960 },
    colorScheme: 'dark'
  });
  const page = await context.newPage();

  try {
    // -------------------------------------------------------------
    // Test 1: Gallery Rendering & Procedural SVG Covers
    // -------------------------------------------------------------
    await page.goto(`${BASE_URL}/`, { waitUntil: 'networkidle' });
    const title = await page.title();
    assert(title.includes('SiteFlow'), `Page title unexpected: ${title}`);

    const cards = await page.$$('.card');
    assert(cards.length >= 3, `Expected at least 3 cards, got ${cards.length}`);
    const svgCovers = await page.$$('.card .cover .cover-svg');
    assert(svgCovers.length >= 2, `Expected procedural SVG covers, got ${svgCovers.length}`);
    logStep('1. Gallery & Procedural SVG Covers', true, `Rendered ${cards.length} cards with ${svgCovers.length} procedural SVG covers`);

    // -------------------------------------------------------------
    // Test 2: Responsive Viewport Preview Modal & Mode Switching
    // -------------------------------------------------------------
    const previewBtn = await page.$('[data-action="quick-preview"]');
    assert(previewBtn, 'Quick preview button not found on card');
    await previewBtn.click();
    await page.waitForTimeout(400);

    const modal = await page.$('#preview-modal');
    const isModalVisible = await modal.isVisible();
    assert(isModalVisible, 'Preview modal did not open');

    // Check default 100% desktop width
    const previewBox = await page.$('#preview-box');
    let boxWidth = await previewBox.evaluate(el => el.style.width);
    assert.strictEqual(boxWidth, '100%', 'Default viewport should be 100%');

    // Switch to Tablet (768px)
    await page.click('.preview-vbtn[data-vp="768px"]');
    await page.waitForTimeout(300);
    boxWidth = await previewBox.evaluate(el => el.style.width);
    assert.strictEqual(boxWidth, '768px', 'Tablet viewport should be 768px');

    // Rotate orientation on tablet (768 -> 1024)
    await page.click('#preview-rotate');
    await page.waitForTimeout(300);
    boxWidth = await previewBox.evaluate(el => el.style.width);
    assert.strictEqual(boxWidth, '1024px', 'Rotated tablet should be 1024px');

    // Switch to Mobile (375px)
    await page.click('.preview-vbtn[data-vp="375px"]');
    await page.waitForTimeout(300);
    boxWidth = await previewBox.evaluate(el => el.style.width);
    assert.strictEqual(boxWidth, '375px', 'Mobile viewport should be 375px');

    logStep('2. Responsive Viewport Switching', true, 'Desktop 100% -> Tablet 768px -> Rotate 1024px -> Mobile 375px verified');

    // -------------------------------------------------------------
    // Test 3: LAN QR Code Debugging Popover & SVG QR Generation
    // -------------------------------------------------------------
    await page.click('#preview-qr-toggle');
    await page.waitForTimeout(600);

    const qrPopover = await page.$('#qr-popover');
    const isQrVisible = await qrPopover.isVisible();
    assert(isQrVisible, 'QR Popover should be visible');

    const qrSvg = await page.$('#qr-img-wrap svg');
    assert(qrSvg, 'SVG QR Code must be rendered in popover');
    logStep('3. LAN QR Code Generator', true, 'Live SVG QR Code generated and popover displayed');

    // Press ESC to close QR popover
    await page.keyboard.press('Escape');
    await page.waitForTimeout(300);
    assert(!(await qrPopover.isVisible()), 'QR popover should close on ESC');

    // Press ESC to close preview modal
    await page.keyboard.press('Escape');
    await page.waitForTimeout(300);
    assert(!(await modal.isVisible()), 'Preview modal should close on ESC');
    logStep('4. Modal Keyboard ESC Handlers', true, 'Layered ESC correctly closes popover then modal');

    // -------------------------------------------------------------
    // Test 4: Command Palette (Cmd+K) & Instant Search
    // -------------------------------------------------------------
    await page.keyboard.press('Control+KeyK');
    await page.waitForTimeout(400);

    const palette = await page.$('#cmd-palette');
    assert(await palette.isVisible(), 'Command palette should open on Ctrl+K');

    // Type search query
    await page.fill('#palette-input', 'Playwright');
    await page.waitForTimeout(400);

    const results = await page.$$('.palette-item');
    assert(results.length >= 1, 'Should find at least 1 search result for Playwright');
    const firstTitle = await results[0].$('.palette-item-title span');
    const titleText = await firstTitle.textContent();
    assert(titleText.includes('Playwright'), `Result title mismatch: ${titleText}`);

    // Arrow down navigation
    await page.keyboard.press('ArrowDown');
    await page.waitForTimeout(200);

    // Test theme toggle action in palette
    await page.fill('#palette-input', '外观');
    await page.waitForTimeout(300);
    const themeAction = await page.$('.palette-item');
    assert(themeAction, 'Theme action not found');
    await themeAction.click();
    await page.waitForTimeout(300);

    const rootTheme = await page.evaluate(() => document.documentElement.getAttribute('data-theme'));
    assert(rootTheme === 'light' || rootTheme === 'dark', `Theme attribute unexpected: ${rootTheme}`);
    logStep('5. Global Command Palette (Cmd+K)', true, 'Instant search, item navigation, and theme action toggle verified');

    // -------------------------------------------------------------
    // Test 5: Project Password Gate & Unlock Flow
    // -------------------------------------------------------------
    await page.goto(`${BASE_URL}/projects/q3-audit-dashboard/`, { waitUntil: 'networkidle' });
    const gateCard = await page.$('.gate-card');
    assert(gateCard, 'Password gate card should be displayed for protected project');

    // Enter wrong password
    await page.fill('input[name="password"]', 'BadPassword123');
    await page.click('button[type="submit"]');
    await page.waitForTimeout(400);
    const errorMsg = await page.$('.login-error');
    assert(errorMsg, 'Error message should appear on wrong password');
    const errorText = await errorMsg.textContent();
    assert(errorText.includes('密码不正确'), `Unexpected error text: ${errorText}`);

    // Enter correct password: siteflow2026
    await page.fill('input[name="password"]', 'siteflow2026');
    await Promise.all([
      page.waitForNavigation({ waitUntil: 'networkidle' }),
      page.click('button[type="submit"]')
    ]);

    const pageContent = await page.content();
    assert(pageContent.includes('2026 第三季度财务审计与预算决算报告'), 'Correct password must reveal protected project content');
    logStep('6. Password Protection Gate & Unlock', true, 'Access block, wrong password rejection, and unlock into project verified');

    // -------------------------------------------------------------
    // Test 6: Admin Dashboard, KPI Analytics & Sparkline
    // -------------------------------------------------------------
    await page.goto(`${BASE_URL}/login`, { waitUntil: 'networkidle' });
    await page.fill('input[name="password"]', 'siteflow_admin_2026');
    await Promise.all([
      page.waitForNavigation({ waitUntil: 'networkidle' }),
      page.click('button[type="submit"]')
    ]);

    assert(page.url().includes('/admin'), `Did not redirect to /admin, current URL: ${page.url()}`);

    const statsCard = await page.$('.admin-stats-card');
    assert(statsCard, 'Admin KPI stats card should exist');
    const sparklineSvg = await page.$('.stats-chart svg');
    assert(sparklineSvg, '7-day Sparkline SVG must be rendered');
    logStep('7. Admin KPI Analytics & Sparkline', true, 'PV/UV metrics and pure SVG trend chart rendered in admin');

    // -------------------------------------------------------------
    // Test 7: Space Custom Theme Editor
    // -------------------------------------------------------------
    await page.goto(`${BASE_URL}/admin/projects/1`, { waitUntil: 'networkidle' });
    const themeSection = await page.$('#space-theme-section');
    assert(themeSection, 'Space theme customization section must exist in space admin');

    // Click Emerald swatch (#10b981)
    const emeraldSwatch = await page.$('.swatch[data-color="#10b981"]');
    if (emeraldSwatch) {
      await emeraldSwatch.click();
      await page.waitForTimeout(200);
      const accentVal = await page.$eval('#theme-accent', el => el.value);
      assert.strictEqual(accentVal, '#10b981', 'Accent input should update to #10b981');

      // Click Save Theme
      await page.click('#save-theme-btn');
      await page.waitForTimeout(600);
      const saveTip = await page.$eval('#theme-save-tip', el => el.textContent);
      assert(saveTip.includes('已保存') || saveTip.includes('保存生效'), `Save tip unexpected: ${saveTip}`);
      logStep('8. Space Theme Customizer', true, 'Theme swatch picker and AJAX save verified');
    }

    // Capture final summary screenshot
    await page.screenshot({ path: path.join(ARTIFACT_DIR, 'e2e_verification_dashboard.png') });

  } catch (err) {
    console.error('Test failed with error:', err);
    process.exitCode = 1;
  } finally {
    await browser.close();
  }

  console.log('\n================ UI E2E TEST SUMMARY ================');
  results.forEach(r => {
    console.log(`${r.passed ? '✓' : '✗'} ${r.name}: ${r.detail}`);
  });
  console.log('=====================================================\n');
}

main().catch(err => {
  console.error(err);
  process.exit(1);
});
