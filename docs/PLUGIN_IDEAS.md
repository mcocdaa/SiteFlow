# SiteFlow 后续插件与扩展创意备忘

> 状态：备忘 / 暂缓实施（Backlog）。本文集中记录已评估的后续插件与功能延展方向，当前暂无排期，按需取用。

## 1. 趣味交互与氛围类（优先落 `mcocdaa/siteflow-plugins`）

零改动 SiteFlow 核心代码、无外部 CDN、完全兼容现有 `BLOG_CSP` / `BOTTLE_CSP`，依托三层继承可做到全站默认开启、简历场景自动关闭。

| 方向 | 插件构想 | 要点与约束 |
|---|---|---|
| 鼠标与指针 | `custom_cursor`（自定义指针） | 多种预设风格（SVG 箭头、星标、小鱼、磁吸光环跟随），悬停可交互元素柔和变形 |
| 鼠标与指针 | `cursor_fx`（点击特效与拖尾） | 单插件切换模式：点击粒子烟花、水波涟漪、自定义飘字、移动星尘/气泡拖尾；Canvas 轻量绘制，切走标签页自动休眠 |
| 全屏氛围层 | `ambient_particles`（氛围飘落层） | 樱花、雪花、萤火虫、深海气泡（适配 `dafeiyu_theme`）、鼠标引力星座连线；支持密度与透明度滑块 |
| 卡片与标题 | `card_tilt_glow`（卡片 3D 扫光） | 空间/画廊卡片鼠标悬停 3D 微俯仰 + 跟随指针的高光扫过质感 |
| 卡片与标题 | `title_vibe`（动态标题彩蛋） | 空间副标题循环打字机，及切走浏览器标签页时临时切换趣味标题、切回自动恢复 |
| 角落小摆件 | `ambient_sound`（纯合成环境音） | 基于浏览器原生 Web Audio 实时合成雨声、海浪与轻按键音，零音频资源文件 |
| 角落小摆件 | `roaming_pet`（页底巡逻小宠） | 纯前端交互小肥鱼/像素猫（不接入 AI），在页底散步、追随鼠标、点击跳起冒泡 |
| 角落小摆件 | `corner_toy`（角落解压彩蛋） | 电子木鱼（点击飘字计数）、今日运势签筒、页面滚到底部彩带雨等轻玩具 |

### 通用实现约束

- 严格尊重系统 `prefers-reduced-motion`（检测到减弱动态效果时自动静默或停用粒子）。
- 触屏与粗指针设备（`pointer: coarse`）自动隐藏自定义指针并降级悬停特效。
- 打印与正式简历页面借助三层继承自动关闭氛围装饰，避免干扰导出与阅读。
- 不引入外部 CDN 脚本/字体，不使用卡通 Emoji，图标统一采用纯单色 SVG。

## 2. 功能体验与架构延展类（按需推进）

| 轨道 | 构想 | 核心价值与依托底座 |
|---|---|---|
| `siteflow-plugins` 体验包 | `post_toc`（文章悬浮目录） | 自动提取 `h2`/`h3` 生成吸顶目录与滚动高亮，移动端收起为浮动胶囊 |
| `siteflow-plugins` 体验包 | `image_lightbox`（原生图片灯箱） | 基于原生 `<dialog>` 实现博客插图与空间封面全屏预览、键盘左右切图与 `Esc` 关闭 |
| `siteflow-plugins` 体验包 | `command_palette`（`Cmd/Ctrl+K` 面板） | 复用 `/api/search`，整合章节跳转、亮暗主题切换、中英文切换与返回上级空间 |
| `siteflow-plugins` 主题包 | 纸媒风 / 终端风新主题 | 通过 `tokens`、`icon_overrides` 与 `title_deco` 进一步验证多风格三层继承效果 |
| 访客审核底座（`app/submissions.py`） | 通用 `footer` 留言板 / 匿名提问箱（AMA）/ 轻量 SVG 反应条 | 复用先审后发、防混淆禁链、IP 哈希限频与后台封禁能力；反应条仅用单色 SVG 与防刷计数 |
| `PageSurface` 消费能力（`app/surface.py`） | 通用 RSS / Atom / JSON Feed | 为所有声明 `has_items` 的页面自动生成订阅源与单色订阅入口，不硬编码页面类型 |
| `PageSurface` 消费能力（`app/surface.py`） | 一键「复制给 AI / `llms.txt`」 | 直接消费 `context("plugin")` 与 `items("plugin")`，自动遵守简历隐私控制与门禁规则 |
| 新内置应用（`app/plugins/`） | `moments`（碎碎念 / 更新日志） | 承接短动态、Changelog 与随笔摘录，实现 `surface()` 即可复用主题、看板娘与订阅能力 |
| 底座微杠杆 | 公共骨架安全暴露 `PageSurface` 只读 JSON | 仅向前端输出脱敏后的 `meta` 与 `items("plugin")` 公开字段，绝不泄密或提前暴露加锁外链真实 URL，让外部纯前端插件无需改动后端即可实现标签云、创作热力图与随机漫游 |
