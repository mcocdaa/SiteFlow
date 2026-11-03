const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const base = process.env.SITEFLOW_TEST_URL || 'http://127.0.0.1:8096';
const password = process.env.SITEFLOW_TEST_PASSWORD;
const artifacts = process.env.SITEFLOW_TEST_ARTIFACTS || '/tmp/siteflow-ui-artifacts';
assert(password, '需要 SITEFLOW_TEST_PASSWORD，且测试服务必须使用独立数据目录');

async function main() {
  fs.mkdirSync(artifacts, { recursive: true });
  const browser = await chromium.launch({
    headless: true,
    executablePath: process.env.CHROMIUM_PATH || undefined
  });
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  page.on('dialog', dialog => dialog.accept());
  try {
    await page.goto(base + '/login');
    await page.locator('input[name="password"]').fill(password);
    await Promise.all([page.waitForURL(base + '/admin'), page.locator('button[type="submit"]').click()]);
    async function checkLocaleButtons() {
      const state = await page.locator('[data-testid="locale-toggle"]').evaluateAll(buttons => buttons.map(button => ({
        svg: button.querySelectorAll('svg.icon').length,
        label: button.querySelector('.lang-label')?.textContent,
        emoji: button.textContent.includes('🌐')
      })));
      assert(state.length > 0, '页面必须有语言切换按钮');
      state.forEach(button => {
        assert.equal(button.svg, 1, '语言切换使用一个 SVG 图标');
        assert(['EN', '中文'].includes(button.label), '语言按钮文案必须正确');
        assert.equal(button.emoji, false, '语言按钮不能使用表情图标');
      });
    }
    await checkLocaleButtons();
    await page.locator('#lang-toggle-btn svg').click();
    await checkLocaleButtons();
    await page.locator('#lang-toggle-btn').click();
    await checkLocaleButtons();
    assert.equal(await page.locator('.content-choices .btn').count(), 5, '所有添加方式使用统一入口');
    await page.locator('[data-panel="upload-panel"]').click();
    assert.equal(await page.locator('#file-input').getAttribute('multiple'), '', '支持多选');
    let failOnce = true;
    await page.route('**/api/admin/projects/upload', async route => {
      if (failOnce) {
        failOnce = false;
        await route.fulfill({ status: 503, contentType: 'application/json', body: '{"ok":false,"error":"测试上传失败"}' });
      } else await route.continue();
    });
    const stamp = Date.now();
    await page.locator('#file-input').setInputFiles([
      { name: '批量一-' + stamp + '.html', mimeType: 'text/html', buffer: Buffer.from('<h1>批量一</h1>') },
      { name: '批量二-' + stamp + '.zip', mimeType: 'application/zip', buffer: Buffer.from('UEsDBBQAAAAIADIcXl3shaAlDAAAAAwAAAAKAAAAaW5kZXguaHRtbLPJMLSL8gyw0QfSAFBLAQIUAxQAAAAIADIcXl3shaAlDAAAAAwAAAAKAAAAAAAAAAAAAACAAQAAAABpbmRleC5odG1sUEsFBgAAAAABAAEAOAAAADQAAAAAAA==', 'base64') }
    ]);
    await page.waitForFunction(() => !document.querySelector('#retry-uploads').hidden);
    assert.equal(await page.locator('#upload-results .upload-result').count(), 2);
    assert.equal(await page.locator('#upload-results .is-error').count(), 1, '失败文件有明确提示');
    await page.locator('#retry-uploads').click();
    await page.waitForFunction(() => !document.querySelector('#dropzone').disabled && document.querySelector('#retry-uploads').hidden);
    assert.equal(await page.locator('#project-list .row').count(), 2, '重试只处理失败文件');
    await page.unroute('**/api/admin/projects/upload');
    const transfer = await page.evaluateHandle(stamp => {
      const transfer = new DataTransfer();
      transfer.items.add(new File(['<h1>拖拽一</h1>'], '拖拽一-' + stamp + '.html', { type: 'text/html' }));
      transfer.items.add(new File(['<h1>拖拽二</h1>'], '拖拽二-' + stamp + '.html', { type: 'text/html' }));
      return transfer;
    }, stamp);
    await page.locator('#dropzone').dispatchEvent('drop', { dataTransfer: transfer });
    await page.waitForFunction(() => document.querySelectorAll('#project-list .row').length === 4);
    await page.screenshot({ path: path.join(artifacts, 'admin-desktop.png'), fullPage: true });
    console.log('通过：统一入口、多选、批量拖拽、失败重试不重复创建');

    const rowId = await page.locator('#project-list .row').first().getAttribute('data-id');
    const row = () => page.locator('.row[data-id="' + rowId + '"]');
    const image = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII=', 'base64');
    async function setCover() {
      await row().locator('[data-action="edit"]').last().click();
      await row().locator('input[name="cover"]').setInputFiles({ name: 'cover.png', mimeType: 'image/png', buffer: image });
      await Promise.all([page.waitForEvent('load'), row().locator('[data-action="save"]').click()]);
      return row().locator('img.thumb').getAttribute('src');
    }
    const firstCover = await setCover();
    const secondCover = await setCover();
    assert.notEqual(firstCover, secondCover, '封面地址变化以避开旧缓存');
    await row().locator('img.thumb').click();
    await Promise.all([page.waitForEvent('load'), row().locator('[data-action="remove-cover"]').click()]);
    assert.equal(await row().locator('img.thumb').count(), 0, '恢复默认封面');
    console.log('通过：封面连续替换、点击封面编辑、恢复默认封面');

    await page.locator('[data-panel="link-panel"]').click();
    await page.locator('#link-url').fill(base + '/healthz');
    await Promise.all([page.waitForEvent('load'), page.locator('#link-url').press('Enter')]);
    assert.equal(await page.locator('#project-list .row[data-type="link"]').count(), 1, '链接入口支持回车添加');
    await Promise.all([page.waitForURL(/\/admin\/projects\/\d+$/), page.locator('[data-action="create-app"][data-type="space"]').click()]);
    assert.equal(await page.locator('#space-theme-section').count(), 0, '空间外观设置已移除');
    assert.equal(await page.locator('.content-choices .btn').count(), 5, '空间与根管理台使用相同添加入口');
    await page.locator('[data-panel="upload-panel"]').click();
    await page.locator('#file-input').setInputFiles([
      { name: '空间内一.html', mimeType: 'text/html', buffer: Buffer.from('<h1>空间内一</h1>') },
      { name: '空间内二.html', mimeType: 'text/html', buffer: Buffer.from('<h1>空间内二</h1>') }
    ]);
    await page.waitForFunction(() => document.querySelectorAll('#project-list .row').length === 2);
    const childIds = await page.locator('#project-list .row').evaluateAll(rows => rows.map(row => Number(row.dataset.id)));
    await page.goto(base + '/admin');
    for (const id of childIds) assert.equal(await page.locator('.row[data-id="' + id + '"]').count(), 0, '空间子项不能出现在根列表');
    console.log('通过：链接添加、空间内统一入口及批量上传的归属');

    await Promise.all([page.waitForURL(/\/admin\/projects\/\d+$/), page.locator('[data-action="create-app"][data-type="blog"]').click()]);
    const blogUrl = page.url();
    await page.locator('#f-title').fill('博客信息测试');
    await page.locator('#f-description').fill('更新博客描述');
    await Promise.all([page.waitForEvent('load'), page.locator('#blog-settings button').click()]);
    assert.equal(await page.locator('#f-title').inputValue(), '博客信息测试', '博客信息能正常保存');
    await page.locator('a[href$="/posts/new"]').click();
    const postTitle = '浏览器测试文章-' + stamp;
    await page.locator('[name="title"]').fill(postTitle);
    await page.locator('[name="body"]').fill('# 正文\n\n保存失败时这段内容仍应保留。');
    await page.route('**/api/admin/projects/*/posts', route => route.fulfill({ status: 500, contentType: 'text/html', body: 'server failure' }));
    await page.locator('#save-post').click();
    await page.waitForFunction(() => document.querySelector('#save-state').classList.contains('is-error'));
    assert((await page.locator('#save-state').textContent()).includes('保存失败'));
    assert((await page.locator('[name="body"]').inputValue()).includes('这段内容仍应保留'));
    await page.screenshot({ path: path.join(artifacts, 'blog-save-error.png'), fullPage: true });
    await page.unroute('**/api/admin/projects/*/posts');
    await page.route('**/api/admin/projects/*/posts', route => route.abort());
    await page.locator('#save-post').click();
    await page.waitForFunction(() => document.querySelector('#save-state').textContent.includes('网络连接失败'));
    await page.unroute('**/api/admin/projects/*/posts');
    await page.locator('#save-post').click();
    await page.locator('#post-saved').waitFor({ state: 'visible' });
    assert((await page.locator('#saved-post-title').textContent()).includes(postTitle));
    await page.locator('#view-post').click();
    assert((await page.locator('body').textContent()).includes('保存失败时这段内容仍应保留'));
    await page.goto(blogUrl);
    await page.locator('.post-edit-link').click();
    await page.locator('[name="body"]').fill('修改后的正文');
    await page.screenshot({ path: path.join(artifacts, 'blog-editor-desktop.png'), fullPage: true });
    await page.locator('#save-post').click();
    await page.locator('#post-saved').waitFor({ state: 'visible' });
    await page.locator('#continue-post').click();
    assert.equal(await page.locator('[name="body"]').inputValue(), '修改后的正文');
    const editUrl = page.url();
    await page.getByTestId('locale-toggle').click();
    await checkLocaleButtons();
    assert.equal(await page.locator('#save-post').textContent(), 'Save post');
    assert.equal(await page.locator('[name="title"]').inputValue(), postTitle, '切换语言不能改写文章内容');
    await page.getByTestId('locale-toggle').click();
    await page.goto(blogUrl + '/posts/new');
    await page.locator('[name="title"]').fill(postTitle);
    await page.locator('[name="body"]').fill('重复网址标识测试');
    await page.locator('#save-post').click();
    await page.waitForFunction(() => document.querySelector('#save-state').textContent.includes('重复'));
    assert.equal(await page.locator('[name="body"]').inputValue(), '重复网址标识测试');
    await page.goto(editUrl);
    await page.setViewportSize({ width: 390, height: 844 });
    assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), '手机编辑器不能横向溢出');
    await page.screenshot({ path: path.join(artifacts, 'blog-editor-mobile.png'), fullPage: true });
    await page.goto(base + '/admin');
    assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), '手机管理台不能横向溢出');
    await page.screenshot({ path: path.join(artifacts, 'admin-mobile.png'), fullPage: true });
    await page.setViewportSize({ width: 1440, height: 1000 });
    await page.emulateMedia({ colorScheme: 'dark' });
    await page.waitForTimeout(250);
    await page.screenshot({ path: path.join(artifacts, 'admin-dark.png'), fullPage: true });
    console.log('通过：独立文章编辑、HTTP/网络错误提示与输入保留、保存与继续编辑、中英切换、手机布局');
    assert.deepEqual(errors, [], '浏览器控制台不能有脚本异常');
  } finally {
    await browser.close();
  }
}

main().catch(error => { console.error(error); process.exitCode = 1; });
