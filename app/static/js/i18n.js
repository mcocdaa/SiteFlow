(function () {
  "use strict";

  var STORAGE_KEY = "siteflow_lang";

  var DICT = {
    zh: {
      "common.search": "搜索",
      "common.admin_entry": "管理入口",
      "common.lang_tip": "切换为英文 / Switch to English",
      "common.back": "返回",
      "gallery.empty_title": "还没有作品",
      "gallery.empty_desc": "这里将展示你的 HTML、静态网站、外链作品与个人应用。",
      "gallery.empty_cta": "去管理台上传第一个作品",
      "space.empty_title": "这个空间还是空的",
      "space.empty_admin": "去管理台添加内容吧。",
      "space.empty_guest": "稍后再来看看。",
      "card.locked": "受密码保护",
      "card.preview": "视口预览",
      "card.pinned": "置顶",
      "preview.default_title": "作品预览",
      "preview.vp_desktop": "桌面端",
      "preview.vp_desktop_title": "桌面端 (100%)",
      "preview.vp_tablet": "平板 (768px)",
      "preview.vp_tablet_title": "平板 (768px)",
      "preview.vp_mobile": "手机 (375px)",
      "preview.vp_mobile_title": "手机 (375px)",
      "preview.rotate": "旋转屏幕 (横竖屏切换)",
      "preview.qr_btn": "真机调试",
      "preview.qr_tip": "局域网真机调试二维码",
      "preview.open_new_tab": "全屏打开",
      "preview.close_tip": "关闭 (Esc)",
      "preview.loading": "正在加载安全沙箱...",
      "preview.iframe_title": "预览视口",
      "preview.qr_title": "局域网真机调试",
      "preview.qr_loading": "生成二维码中...",
      "preview.qr_desc": "用手机与电脑连接同一局域网 / Wi-Fi 后扫码，即可在移动端真机预览调试。",
      "preview.qr_error": "二维码生成失败",
      "preview.qr_load_error": "无法加载",
      "palette.aria_label": "全局命令与搜索",
      "palette.placeholder": "搜索项目、空间或快捷命令...",
      "palette.close": "关闭搜索",
      "palette.hint_nav": "导航",
      "palette.hint_open": "打开",
      "palette.hint_close": "关闭",
      "palette.empty": "无匹配结果，尝试更换搜索关键词",
      "palette.group_actions": "快捷操作",
      "palette.group_projects": "空间与作品",
      "palette.cmd_theme_title": "切换外观模式 (浅色 / 暗色)",
      "palette.cmd_theme_desc": "在暗夜黑与清爽白外观之间无缝切换",
      "palette.cmd_lang_title": "切换界面语言 (中文 / EN)",
      "palette.cmd_lang_desc": "在中文与英文界面之间即时切换",
      "palette.cmd_gallery_title": "返回画廊首页",
      "palette.cmd_gallery_desc": "浏览聚合展示的所有静态作品与空间",
      "palette.cmd_admin_title": "进入管理控制台",
      "palette.cmd_admin_desc": "上传作品、配置空间主题与查看访问统计",
      "admin.crumb_admin": "管理",
      "admin.copy_api_key": "复制 API 密钥",
      "admin.copy_api_tip": "复制无头部署 API 密钥",
      "admin.logout": "退出登录",
      "admin.stats_today": "今日访问",
      "admin.stats_7d": "7天总访问",
      "admin.stats_trend": "7天趋势",
      "admin.stats_trend_tip": "过去 7 天 PV 趋势",
      "admin.section_apps": "应用",
      "admin.new_space": "新建空间",
      "admin.new_resume": "新建简历",
      "admin.new_blog": "新建博客",
      "admin.section_projects": "项目",
      "admin.section_add_content": "添加内容",
      "admin.drop_title": "拖拽 HTML 或 ZIP 到这里",
      "admin.drop_sub": "或点击选择文件 · 也可以在下方添加外链 / 新建应用",
      "admin.drop_sub_space": "或点击选择文件 · 也可以在下方添加外链 / 新建子应用",
      "admin.drop_sub_space_prefix": "添加到「",
      "admin.drop_sub_space_suffix": "」 · 也可以在下方添加外链 / 新建子应用",
      "admin.step_upload": "上传",
      "admin.step_audit": "安全沙箱审计",
      "admin.step_extract": "解压与嗅探",
      "admin.step_ready": "就绪",
      "admin.stage_prep": "准备上传...",
      "admin.link_placeholder": "https://example.com 作品链接",
      "admin.add_link": "添加链接",
      "admin.plugin_no_content": "暂无可编辑内容。",
      "admin.plugin_ext_hint": "插件应用可按插件提供的内容编辑器扩展。",
      "admin.open_app": "打开应用",
      "theme.section_title": "空间独立主题定制",
      "theme.head_title": "外观与视觉风格",
      "theme.head_sub": "定制此空间的独立强调色、字体风格与卡片圆角",
      "theme.label_accent": "强调色 (Accent Color)",
      "theme.swatch_indigo": "经典靛蓝",
      "theme.swatch_sky": "极客天蓝",
      "theme.swatch_emerald": "自然翡翠",
      "theme.swatch_amber": "温暖琥珀",
      "theme.swatch_rose": "现代玫瑰",
      "theme.swatch_violet": "极光紫",
      "theme.label_font": "字体风格 (Typography)",
      "theme.font_default": "默认无衬线 (System Sans)",
      "theme.font_sans": "现代无衬线 (Modern Sans)",
      "theme.font_serif": "典雅衬线 (Elegant Serif)",
      "theme.font_mono": "极客等宽 (Tech Monospace)",
      "theme.label_radius": "卡片圆角 (Card Border Radius)",
      "theme.radius_default": "默认圆角 (14px)",
      "theme.radius_0": "直角锐利 (0px)",
      "theme.radius_6": "微圆角 (6px)",
      "theme.radius_10": "适中圆角 (10px)",
      "theme.radius_14": "现代圆角 (14px)",
      "theme.radius_20": "圆润大圆角 (20px)",
      "theme.save_btn": "保存空间主题",
      "row.badge_locked": "密码锁",
      "row.meta_pinned": " · 置顶",
      "row.meta_hidden": " · 已隐藏",
      "row.manage": "进入管理",
      "row.view": "查看",
      "row.edit": "编辑",
      "row.pin": "置顶",
      "row.unpin": "取消置顶",
      "row.move_up": "上移",
      "row.move_down": "下移",
      "row.hide": "隐藏",
      "row.show": "显示",
      "row.delete": "删除",
      "row.label_title": "标题",
      "row.label_desc": "描述",
      "row.label_url": "链接",
      "row.label_password": "访问密码",
      "row.status_protected": "已保护",
      "row.pwd_placeholder_change": "输入新密码以修改（留空不变）",
      "row.pwd_placeholder_new": "留空公开访问（输入密码开启）",
      "row.label_cover": "封面",
      "row.choose_image": "选择图片",
      "row.no_file": "未选择",
      "row.clear_password": "清除密码保护",
      "row.save": "保存",
      "row.empty": "还没有内容。",
      "login.password_placeholder": "管理员密码",
      "login.submit": "登录",
      "gate.subtitle": "此作品已设置访问密码保护",
      "gate.password_placeholder": "请输入访问密码",
      "gate.unlock_btn": "解锁并访问",
      "gate.back_home": "返回画廊首页",
      "js.req_failed": "请求失败",
      "js.upload_prep": "正在准备上传制品...",
      "js.uploading": "正在上传制品 ({pct}%)...",
      "js.upload_audit": "执行安全沙箱审计（ZipBomb 防御与容错转码）...",
      "js.upload_extract": "结构嗅探与安全解压中...",
      "js.upload_failed": "上传失败",
      "js.upload_done": "制品安全就绪！正在同步画廊...",
      "js.network_error": "网络错误，上传中断",
      "js.theme_saved": "✓ 空间主题已保存生效",
      "js.new_space_default": "新建空间",
      "js.api_copied": "已复制密钥",
      "js.confirm_clear_pwd": "确定清除此作品的访问密码？清除后任何人均可公开直接访问。",
      "js.cover_failed": "封面上传失败",
      "js.confirm_delete": "确定删除该作品？文件将一并删除，不可恢复。",
      "resume.print_pdf": "打印 / 导出 PDF",
      "resume.sec_work": "工作经历",
      "resume.sec_education": "教育经历",
      "resume.sec_projects": "项目",
      "resume.sec_skills": "技能",
      "resume.preview": "预览",
      "resume.basic_info": "基本信息",
      "resume.field_name": "姓名",
      "resume.field_label": "职位 / 头衔",
      "resume.field_email": "邮箱",
      "resume.field_phone": "电话",
      "resume.field_url": "网站",
      "resume.field_city": "城市",
      "resume.field_region": "地区",
      "resume.field_country": "国家代码",
      "resume.field_summary": "简介",
      "resume.field_links": "链接（每行一条：名称|https://...）",
      "resume.add_entry": "添加",
      "resume.save_preview": "保存并查看",
      "resume.entry_num": "第 {n} 条",
      "resume.saving": "保存中…",
      "resume.save_failed": "保存失败",
      "resume.saved_at": "已保存 {time}",
      "resume.view_resume": "查看简历",
      "resume.col_company": "公司",
      "resume.col_position": "职位",
      "resume.col_start": "开始",
      "resume.col_end": "结束",
      "resume.col_url": "链接",
      "resume.col_summary": "摘要",
      "resume.col_highlights": "要点（每行一条）",
      "resume.col_institution": "学校",
      "resume.col_area": "专业",
      "resume.col_study_type": "学历",
      "resume.col_proj_name": "名称",
      "resume.col_proj_desc": "描述",
      "resume.col_keywords": "关键词（逗号分隔）",
      "resume.col_skill_name": "技能",
      "blog.chars_unit": "字",
      "blog.read_more": "阅读全文",
      "blog.empty": "还没有文章。",
      "blog.info_title": "博客信息",
      "blog.posts_heading": "文章",
      "blog.add_post": "添加文章",
      "blog.untitled": "（未命名）",
      "blog.collapse": "折叠",
      "blog.expand": "展开",
      "blog.post_num": "第 {n} 篇",
      "blog.preview_post": "预览这篇",
      "blog.view_blog": "查看博客",
      "blog.col_slug": "Slug（URL，可中文）",
      "blog.col_title": "标题",
      "blog.col_date": "日期（YYYY-MM-DD）",
      "blog.col_tags": "标签（逗号分隔）",
      "blog.col_summary": "摘要",
      "blog.col_body": "正文（Markdown）",
      "blog.back_to_list": "文章列表",
      "blog.prev_post": "上一篇",
      "blog.next_post": "下一篇"
    },
    en: {
      "common.search": "Search (⌘K)",
      "common.admin_entry": "Admin",
      "common.lang_tip": "Switch to Chinese / 切换为中文",
      "common.back": "Back",
      "gallery.empty_title": "No Projects Yet",
      "gallery.empty_desc": "Your static sites, HTML artifacts, external links, and apps will appear here.",
      "gallery.empty_cta": "Upload Your First Project in Admin",
      "space.empty_title": "This Space Is Empty",
      "space.empty_admin": "Add projects from the Admin Console.",
      "space.empty_guest": "Check back later.",
      "card.locked": "Password Protected",
      "card.preview": "Quick Preview",
      "card.pinned": "Pinned",
      "preview.default_title": "Artifact Preview",
      "preview.vp_desktop": "Desktop",
      "preview.vp_desktop_title": "Desktop (100%)",
      "preview.vp_tablet": "Tablet (768px)",
      "preview.vp_tablet_title": "Tablet (768px)",
      "preview.vp_mobile": "Mobile (375px)",
      "preview.vp_mobile_title": "Mobile (375px)",
      "preview.rotate": "Rotate Viewport",
      "preview.qr_btn": "LAN QR Preview",
      "preview.qr_tip": "LAN Mobile QR Preview",
      "preview.open_new_tab": "Open in New Tab",
      "preview.close_tip": "Close (Esc)",
      "preview.loading": "Loading sandboxed preview...",
      "preview.iframe_title": "Preview Viewport",
      "preview.qr_title": "LAN QR Preview",
      "preview.qr_loading": "Generating QR code...",
      "preview.qr_desc": "Connect your phone to the same LAN / Wi-Fi and scan to preview on a real device.",
      "preview.qr_error": "Failed to generate QR code",
      "preview.qr_load_error": "Unable to load",
      "palette.aria_label": "Global Command & Search Palette",
      "palette.placeholder": "Search sites, reports, spaces, or commands...",
      "palette.close": "Close Search",
      "palette.hint_nav": "Navigate",
      "palette.hint_open": "Open",
      "palette.hint_close": "Close",
      "palette.empty": "No matching results found",
      "palette.group_actions": "Quick Actions",
      "palette.group_projects": "Spaces & Projects",
      "palette.cmd_theme_title": "Toggle Theme (Light / Dark)",
      "palette.cmd_theme_desc": "Switch seamlessly between dark and light mode",
      "palette.cmd_lang_title": "Switch Language (中文 / EN)",
      "palette.cmd_lang_desc": "Toggle interface language between Chinese and English",
      "palette.cmd_gallery_title": "Back to Gallery",
      "palette.cmd_gallery_desc": "Browse all static sites, reports, and spaces",
      "palette.cmd_admin_title": "Open Admin Console",
      "palette.cmd_admin_desc": "Upload artifacts, customize space themes, and view analytics",
      "admin.crumb_admin": "Admin",
      "admin.copy_api_key": "API Key",
      "admin.copy_api_tip": "Copy Headless Deploy API Key",
      "admin.logout": "Sign Out",
      "admin.stats_today": "Today",
      "admin.stats_7d": "7-Day Total",
      "admin.stats_trend": "7-Day Trend",
      "admin.stats_trend_tip": "7-Day PV Trend",
      "admin.section_apps": "Apps",
      "admin.new_space": "New Space",
      "admin.new_resume": "New Resume",
      "admin.new_blog": "New Blog",
      "admin.section_projects": "Projects",
      "admin.section_add_content": "Add Content",
      "admin.drop_title": "Drop HTML or ZIP here",
      "admin.drop_sub": "Or click to browse files · Add external links or create apps below",
      "admin.drop_sub_space": "Or click to browse files · Add external links or sub-apps below",
      "admin.drop_sub_space_prefix": "Add to \"",
      "admin.drop_sub_space_suffix": "\" · Or add external links / sub-apps below",
      "admin.step_upload": "Upload",
      "admin.step_audit": "Security Audit",
      "admin.step_extract": "Extract & Inspect",
      "admin.step_ready": "Ready",
      "admin.stage_prep": "Preparing upload...",
      "admin.link_placeholder": "https://example.com project URL",
      "admin.add_link": "Add Link",
      "admin.plugin_no_content": "No editable content.",
      "admin.plugin_ext_hint": "Plugin apps can be extended with custom content editors.",
      "admin.open_app": "Open App",
      "theme.section_title": "Space Theme Customizer",
      "theme.head_title": "Appearance & Style",
      "theme.head_sub": "Customize accent color, typography, and card border radius for this space",
      "theme.label_accent": "Accent Color",
      "theme.swatch_indigo": "Classic Indigo",
      "theme.swatch_sky": "Geek Sky",
      "theme.swatch_emerald": "Emerald",
      "theme.swatch_amber": "Warm Amber",
      "theme.swatch_rose": "Modern Rose",
      "theme.swatch_violet": "Aurora Violet",
      "theme.label_font": "Typography",
      "theme.font_default": "System Sans (Default)",
      "theme.font_sans": "Modern Sans",
      "theme.font_serif": "Elegant Serif",
      "theme.font_mono": "Tech Monospace",
      "theme.label_radius": "Card Border Radius",
      "theme.radius_default": "Default (14px)",
      "theme.radius_0": "Sharp (0px)",
      "theme.radius_6": "Subtle (6px)",
      "theme.radius_10": "Medium (10px)",
      "theme.radius_14": "Modern (14px)",
      "theme.radius_20": "Large (20px)",
      "theme.save_btn": "Save Theme",
      "row.badge_locked": "Locked",
      "row.meta_pinned": " · Pinned",
      "row.meta_hidden": " · Hidden",
      "row.manage": "Manage",
      "row.view": "Open",
      "row.edit": "Edit",
      "row.pin": "Pin",
      "row.unpin": "Unpin",
      "row.move_up": "Move Up",
      "row.move_down": "Move Down",
      "row.hide": "Hide",
      "row.show": "Show",
      "row.delete": "Delete",
      "row.label_title": "Title",
      "row.label_desc": "Description",
      "row.label_url": "URL",
      "row.label_password": "Access Password",
      "row.status_protected": "Protected",
      "row.pwd_placeholder_change": "Enter new password to change (leave blank to keep)",
      "row.pwd_placeholder_new": "Leave blank for public access (enter password to lock)",
      "row.label_cover": "Cover",
      "row.choose_image": "Choose Image",
      "row.no_file": "No file chosen",
      "row.clear_password": "Clear Password",
      "row.save": "Save",
      "row.empty": "No items yet.",
      "login.password_placeholder": "Admin Password",
      "login.submit": "Sign In",
      "gate.subtitle": "This project is password-protected",
      "gate.password_placeholder": "Enter access password",
      "gate.unlock_btn": "Unlock & Continue",
      "gate.back_home": "Back to Gallery",
      "js.req_failed": "Request failed",
      "js.upload_prep": "Preparing artifact upload...",
      "js.uploading": "Uploading artifact ({pct}%)...",
      "js.upload_audit": "Running security sandbox audit (ZipBomb & encoding check)...",
      "js.upload_extract": "Inspecting structure & extracting safely...",
      "js.upload_failed": "Upload failed",
      "js.upload_done": "Artifact ready! Syncing gallery...",
      "js.network_error": "Network error, upload interrupted",
      "js.theme_saved": "✓ Theme saved",
      "js.new_space_default": "New Space",
      "js.api_copied": "Copied!",
      "js.confirm_clear_pwd": "Remove password protection from this project? Anyone will be able to access it.",
      "js.cover_failed": "Cover upload failed",
      "js.confirm_delete": "Delete this project and all its files permanently?",
      "resume.print_pdf": "Print / Export PDF",
      "resume.sec_work": "Work Experience",
      "resume.sec_education": "Education",
      "resume.sec_projects": "Projects",
      "resume.sec_skills": "Skills",
      "resume.preview": "Preview",
      "resume.basic_info": "Basic Information",
      "resume.field_name": "Full Name",
      "resume.field_label": "Role / Title",
      "resume.field_email": "Email",
      "resume.field_phone": "Phone",
      "resume.field_url": "Website",
      "resume.field_city": "City",
      "resume.field_region": "Region",
      "resume.field_country": "Country Code",
      "resume.field_summary": "Summary",
      "resume.field_links": "Profiles (one per line: Network|https://...)",
      "resume.add_entry": "Add",
      "resume.save_preview": "Save & Preview",
      "resume.entry_num": "Entry #{n}",
      "resume.saving": "Saving...",
      "resume.save_failed": "Failed to save",
      "resume.saved_at": "Saved at {time}",
      "resume.view_resume": "View Resume",
      "resume.col_company": "Company",
      "resume.col_position": "Position",
      "resume.col_start": "Start Date",
      "resume.col_end": "End Date",
      "resume.col_url": "URL",
      "resume.col_summary": "Summary",
      "resume.col_highlights": "Highlights (one per line)",
      "resume.col_institution": "Institution",
      "resume.col_area": "Major / Area",
      "resume.col_study_type": "Degree",
      "resume.col_proj_name": "Project Name",
      "resume.col_proj_desc": "Description",
      "resume.col_keywords": "Keywords (comma-separated)",
      "resume.col_skill_name": "Skill Category",
      "blog.chars_unit": "chars",
      "blog.read_more": "Read Article",
      "blog.empty": "No posts published yet.",
      "blog.info_title": "Blog Settings",
      "blog.posts_heading": "Posts",
      "blog.add_post": "New Post",
      "blog.untitled": "(Untitled)",
      "blog.collapse": "Collapse",
      "blog.expand": "Expand",
      "blog.post_num": "Post #{n}",
      "blog.preview_post": "Preview Post",
      "blog.view_blog": "View Blog",
      "blog.col_slug": "Slug (URL identifier)",
      "blog.col_title": "Title",
      "blog.col_date": "Date (YYYY-MM-DD)",
      "blog.col_tags": "Tags (comma-separated)",
      "blog.col_summary": "Summary",
      "blog.col_body": "Body (Markdown)",
      "blog.back_to_list": "All Posts",
      "blog.prev_post": "Previous",
      "blog.next_post": "Next"
    }
  };

  var AUTO_TEXT_MAP_EN = {
    "SiteFlow 制品画廊": "SiteFlow Gallery",
    "现代前端制品、自动化测试报告与微服务文档的安全沙箱展示平台": "Sandboxed portal for modern frontend artifacts, E2E test reports, and microservice docs",
    "一些想法，一些尝试，一些值得分享的作品。": "Ideas, experiments, and web artifacts worth sharing.",
    "前端架构与基础制品": "Frontend Architecture & Core Artifacts",
    "聚合核心 SPA 控制台、设计系统组件库与全站静态制品": "Aggregated core SPA consoles, design system libraries, and static web bundles",
    "AI 基础架构与微服务空间": "AI Infrastructure & Microservices Space",
    "聚合核心 LLM 推理网关控制台、分布式遥测仪表盘与全站静态制品": "Aggregated LLM inference gateway console, distributed telemetry dashboards, and static web bundles",
    "CloudMonitor 实时遥测控制台": "CloudMonitor Live Telemetry Console",
    "基于 Vite 编译打包的高性能微前端监控仪表盘": "High-performance micro-frontend monitoring dashboard built with Vite",
    "LLM Gateway 实时遥测控制台": "LLM Gateway Live Telemetry Console",
    "多模型路由负载均衡、Token 速率限制与 Prompt 缓存命中率实时监控面板": "Multi-model routing load balancer, token rate limiting, and prompt cache hit-rate dashboard",
    "Playwright 全链路回归测试报告": "Playwright E2E Regression Report",
    "自动化测试全量归档报告，包含 145 个用例轨迹跟踪与真机录屏": "Full automated test archive with 145 trace recordings and viewport captures",
    "CI 构建 #10842 全量归档报告，包含 150 个 E2E 用例轨迹跟踪与多视口断言审计": "CI Build #10842 full archive report with 150 E2E trace recordings and multi-viewport assertions",
    "LLM Agent 推理评测报告": "LLM Agent Reasoning Benchmark Report",
    "多模型推理准确率、Agent 工具调用成功率与 TTFT 延迟全量评测报告": "Multi-model reasoning accuracy, Agent tool-use pass rate, and TTFT latency benchmark report",
    "支付中心微服务 API 规范": "Payment Gateway Microservice API Spec",
    "基于 Redoc / OpenAPI 规范生成的交互式 API 参考手册": "Interactive API reference manual generated from OpenAPI v3.1 specs",
    "2026 Q3 财务审计与预算决算": "2026 Q3 Financial Audit & Budget",
    "核心商业机密项目，已开启专属访问密码保护隔离锁": "Confidential executive report protected by per-project password lock",
    "SiteFlow 开源仓库与文档": "SiteFlow Open-Source Repo & Docs",
    "GitHub 官方代码仓库、更新日志与 Docker 部署指南": "Official GitHub repository, changelog, and Docker deployment guide",
    "基于 Canvas 与 Web Audio 的赛博朋克霓虹 2048 游戏": "Cyberpunk neon 2048 game built with HTML5 Canvas and Web Audio",
    "AI 分析报告": "AI Analysis Report",
    "新建空间": "New Space",
    "新空间": "New Space",
    "简历": "Resume",
    "博客": "Blog",
    "未命名作品": "Untitled Project",
    "林深 · 首席系统架构师简历": "Lin Shen · Principal Systems Architect Resume",
    "12 年分布式系统、云原生沙箱与高并发微服务架构设计经验": "12+ years in distributed systems, cloud-native sandboxes, and high-concurrency microservices",
    "林深": "Lin Shen",
    "首席系统架构师": "Principal Systems Architect",
    "专注于大规模分布式系统、安全沙箱隔离引擎与高吞吐微服务网关架构，主导过多款开源云原生基础设施产品。": "Focused on large-scale distributed systems, secure sandbox isolation engines, and high-throughput microservice gateways.",
    "上海": "Shanghai",
    "中国": "China",
    "星云科技": "Nebula Tech",
    "至今": "Present",
    "负责下一代多租户云原生制品托管与零信任安全沙箱平台架构设计。": "Architected the next-generation multi-tenant cloud-native artifact hosting and zero-trust sandbox platform.",
    "主导设计零信任 CSP 沙箱与 ZipBomb 防御引擎，日均拦截 10 万+ 异常制品上传": "Architected zero-trust CSP sandbox and ZipBomb defense engine blocking 100k+ anomalous uploads daily",
    "构建高并发边缘静态分发网关，将全球 P99 响应延迟从 48ms 降至 9ms": "Built high-concurrency edge static delivery gateway reducing global P99 latency from 48ms to 9ms",
    "极光云基础设施": "Aurora Cloud Infrastructure",
    "高级分布式系统工程师": "Senior Distributed Systems Engineer",
    "核心参与容器调度网络与分布式遥测存储引擎研发。": "Core contributor to container scheduling networking and distributed telemetry storage engine.",
    "研发高吞吐时序遥测聚合管道，支撑每秒 500 万指标写入与亚秒级查询": "Developed high-throughput time-series telemetry pipeline supporting 5M metrics/sec ingestion and sub-second queries",
    "上海交通大学": "Shanghai Jiao Tong University",
    "计算机科学与技术": "Computer Science & Technology",
    "硕士": "M.S.",
    "SiteFlow 安全沙箱制品引擎": "SiteFlow Sandboxed Artifact Engine",
    "零构建、内联 SVG 视觉封面与单进程 SQLite WAL 驱动的静态制品托管画廊。": "Zero-build static artifact gallery powered by procedural SVG covers and single-process SQLite WAL.",
    "实现多编码嗅探转码、流式解压审计与空间独立主题定制系统": "Implemented multi-encoding sniffing, streaming extraction auditing, and per-space theme customization",
    "系统架构与后端": "Systems Architecture & Backend",
    "分布式系统": "Distributed Systems",
    "云原生与安全隔离": "Cloud Native & Security Isolation",
    "CSP 沙箱": "CSP Sandbox",
    "零信任架构": "Zero-Trust Architecture",
    "系统架构与工程实践专栏": "Systems Architecture & Engineering Blog",
    "关于零信任静态托管、安全沙箱隔离与现代前端工程化的深度技术笔记": "In-depth technical notes on zero-trust static hosting, sandbox isolation, and modern frontend engineering",
    "为什么现代静态制品托管需要零信任 CSP 沙箱与流式审计": "Why Modern Artifact Hosting Needs Zero-Trust CSP Sandboxes & Streaming Audits",
    "架构": "Architecture",
    "安全沙箱": "Security Sandbox",
    "工程实践": "Engineering",
    "深入剖析多租户 HTML 与 ZIP 制品托管中的 XSS 隔离、ZipBomb 防御以及编码自愈机制。": "Deep dive into XSS isolation, ZipBomb defense, and encoding auto-healing in multi-tenant HTML and ZIP hosting.",
    "在托管第三方或 CI 流水线自动生成的静态 HTML 制品时，传统的静态文件服务器往往面临两大核心风险：跨站脚本执行（XSS）污染主站会话与恶意压缩包（ZipBomb / 路径穿越）耗尽磁盘资源。": "When hosting third-party or CI-generated static HTML artifacts, traditional static file servers face two core risks: cross-site scripting (XSS) polluting the main session and malicious archives (ZipBombs / path traversal) exhausting disk resources.",
    "1. 严格的 CSP Sandbox 隔离": "1. Strict CSP Sandbox Isolation",
    "### 1. 严格的 CSP Sandbox 隔离": "### 1. Strict CSP Sandbox Isolation",
    "通过为静态制品响应头注入独立的 Content-Security-Policy 沙箱策略，我们可以在允许制品内部交互脚本正常运行的同时，阻断其对主站 Cookie 与管理员会话的读取权限。": "By injecting an isolated Content-Security-Policy sandbox header on artifact responses, interactive scripts inside artifacts run normally while being blocked from reading main-site cookies or admin sessions.",
    "2. 流式解压与膨胀比审计": "2. Streaming Extraction & Expansion Ratio Auditing",
    "### 2. 流式解压与膨胀比审计": "### 2. Streaming Extraction & Expansion Ratio Auditing",
    "在解压阶段对单文件膨胀比、总解压字节数与目录 Inode 上限进行实时熔断校验，确保任何异常压缩包在落盘前即被安全拦截。": "Real-time circuit-breaker checks on single-file expansion ratios, total extracted bytes, and inode limits during extraction ensure anomalous archives are safely blocked before hitting disk.",
    "单机十万级并发读写的 SQLite WAL 调优实践": "Tuning SQLite WAL for 100k+ Concurrent Reads and Writes on a Single Node",
    "数据库": "Database",
    "性能优化": "Performance",
    "无需引入沉重的外部数据库集群，通过 WAL 模式与内存映射实现微秒级元数据检索与 PV/UV 统计。": "Achieving microsecond metadata queries and PV/UV analytics with SQLite WAL and mmap without heavy external DB clusters.",
    "对于轻量级自托管平台而言，维护独立的外部数据库实例往往带来额外的运维负担。通过合理配置 SQLite 的 WAL 日志模式与同步级别，单机即可轻松支撑高并发读与高频统计写入。": "For lightweight self-hosted platforms, maintaining external DB clusters adds operational overhead. With proper SQLite WAL mode and sync settings, a single node easily handles high-concurrency reads and analytics writes.",
    "核心调优参数": "Core Tuning Parameters",
    "### 核心调优参数": "### Core Tuning Parameters",
    "开启 WAL 日志模式实现读写并发不阻塞": "Enable WAL journal mode for non-blocking concurrent reads and writes",
    "- 开启 WAL 日志模式实现读写并发不阻塞": "- Enable WAL journal mode for non-blocking concurrent reads and writes",
    "使用确定性唯一索引实现每日 PV / UV 的幂等原子累加": "Use deterministic unique indexes for idempotent atomic daily PV/UV increments",
    "- 使用确定性唯一索引实现每日 PV / UV 的幂等原子累加": "- Use deterministic unique indexes for idempotent atomic daily PV/UV increments",
    "密码不正确": "Incorrect password",
    "密码不正确，请重新输入": "Incorrect password, please try again",
    "尝试次数过多，请稍后再试": "Too many attempts, please try again later",
    "会话校验失败，请重试": "Session verification failed, please retry",
    "已经在边界": "Already at the boundary",
    "标题不能为空": "Title cannot be empty",
    "未找到该项目": "Project not found",
    "作品不存在": "Project not found",
    "父级不存在": "Parent not found",
    "只有可包含子项的应用可以嵌套": "Only container apps can be nested",
    "已达最大嵌套深度（3 层）": "Maximum nesting depth (3 levels) reached",
    "无效的项目标识（仅支持小写字母、数字、连字符和下划线，长度 1-64）": "Invalid project slug (lowercase letters, digits, hyphens, underscores, length 1-64)",
    "该标识已被非静态项目占用": "Slug is already taken by a non-static project",
    "只支持 .html / .htm / .zip 文件": "Only .html / .htm / .zip files are supported",
    "文件超出大小限制": "File exceeds size limit",
    "不支持的应用类型": "Unsupported app type",
    "链接必须以 http:// 或 https:// 开头": "URL must start with http:// or https://",
    "该类型不支持内容编辑": "This project type does not support content editing",
    "只有空间支持主题配置": "Only spaces support theme customization",
    "方向必须是 up 或 down": "Direction must be up or down",
    "封面不能超过 10MB": "Cover image cannot exceed 10MB",
    "压缩包文件数量超出限制": "Archive contains too many files",
    "压缩包包含不安全路径、符号链接或加密文件": "Archive contains unsafe paths, symlinks, or encrypted files",
    "压缩包包含重复路径": "Archive contains duplicate paths",
    "压缩包单文件解压膨胀比过高（疑似解压炸弹）": "Single-file expansion ratio too high (suspected zip bomb)",
    "解压大小超出限制": "Extracted size exceeds limit",
    "压缩包文件与目录总数超出 Inode 上限": "Total files and directories exceed inode limit",
    "压缩包解压膨胀比过高（疑似解压炸弹）": "Archive expansion ratio too high (suspected zip bomb)",
    "压缩包包含不安全路径": "Archive contains unsafe paths",
    "ZIP 中未找到 index.html": "index.html not found in ZIP archive",
    "压缩包损坏或格式不支持": "Corrupted archive or unsupported format",
    "图片格式不支持或尺寸过大": "Unsupported image format or dimensions too large",
    "无法读取封面图片": "Unable to read cover image",
    "简历内容不是合法 JSON": "Resume content is not valid JSON",
    "简历内容必须是 JSON 对象": "Resume content must be a JSON object",
    "博客内容不是合法 JSON": "Blog content is not valid JSON",
    "博客内容必须是 JSON 对象": "Blog content must be a JSON object"
  };

  var AUTO_TEXT_MAP_ZH = {};
  Object.keys(AUTO_TEXT_MAP_EN).forEach(function (zhKey) {
    var enVal = AUTO_TEXT_MAP_EN[zhKey];
    if (!AUTO_TEXT_MAP_ZH[enVal]) {
      AUTO_TEXT_MAP_ZH[enVal] = zhKey;
    }
  });
  AUTO_TEXT_MAP_ZH["New Space"] = "新建空间";

  var MONOGRAM_MAP_EN = {
    "前": "F",
    "支": "P",
    "我": "M",
    "测": "T",
    "简": "R",
    "博": "B",
    "新": "N",
    "未": "U",
    "林": "L",
    "系": "S"
  };

  function getLang() {
    try {
      var saved = localStorage.getItem(STORAGE_KEY);
      if (saved === "en" || saved === "zh") return saved;
    } catch (e) {}
    return "zh";
  }

  function t(key, vars) {
    var lang = getLang();
    var table = DICT[lang] || DICT.zh;
    var raw = table[key] !== undefined ? table[key] : (DICT.zh[key] || key);
    if (vars) {
      Object.keys(vars).forEach(function (k) {
        raw = raw.replace("{" + k + "}", String(vars[k]));
      });
    }
    return raw;
  }

  function toZhText(text) {
    if (!text) return text;
    var trimmed = text.trim();
    if (AUTO_TEXT_MAP_ZH[trimmed]) {
      return AUTO_TEXT_MAP_ZH[trimmed];
    }
    return text;
  }

  function translateText(text) {
    if (!text) return text;
    var lang = getLang();
    var trimmed = text.trim();
    if (lang === "en" && AUTO_TEXT_MAP_EN[trimmed]) {
      return AUTO_TEXT_MAP_EN[trimmed];
    }
    if (lang === "zh" && AUTO_TEXT_MAP_ZH[trimmed]) {
      return AUTO_TEXT_MAP_ZH[trimmed];
    }
    return text;
  }

  function translateValueText(rawVal, targetLang) {
    if (!rawVal) return rawVal;
    var map = targetLang === "en" ? AUTO_TEXT_MAP_EN : AUTO_TEXT_MAP_ZH;
    var trimmed = rawVal.trim();
    if (map[trimmed]) {
      return map[trimmed];
    }
    if (rawVal.indexOf("\n") !== -1) {
      var lines = rawVal.split("\n");
      var changedLine = false;
      var mappedLines = lines.map(function (line) {
        var lt = line.trim();
        if (lt && map[lt]) {
          changedLine = true;
          return map[lt];
        }
        return line;
      });
      if (changedLine) return mappedLines.join("\n");
    }
    if (rawVal.indexOf(",") !== -1 && rawVal.indexOf("\n") === -1) {
      var parts = rawVal.split(",");
      var changedPart = false;
      var mappedParts = parts.map(function (part) {
        var pt = part.trim();
        if (pt && map[pt]) {
          changedPart = true;
          return map[pt];
        }
        return part.trim();
      });
      if (changedPart) return mappedParts.join(", ");
    }
    return rawVal;
  }

  function applyI18n(langOverride) {
    var lang = langOverride || getLang();
    document.documentElement.lang = lang === "en" ? "en" : "zh-CN";
    document.documentElement.setAttribute("data-lang", lang);

    // 1. Update [data-i18n] text content
    document.querySelectorAll("[data-i18n]").forEach(function (el) {
      var key = el.getAttribute("data-i18n");
      if (!el.hasAttribute("data-zh-orig")) {
        el.setAttribute("data-zh-orig", el.textContent);
      }
      if (lang === "zh") {
        el.textContent = el.getAttribute("data-zh-orig") || t(key);
      } else {
        el.textContent = t(key);
      }
    });

    // 2. Update [data-i18n-placeholder]
    document.querySelectorAll("[data-i18n-placeholder]").forEach(function (el) {
      var key = el.getAttribute("data-i18n-placeholder");
      el.setAttribute("placeholder", t(key));
    });

    // 3. Update [data-i18n-title]
    document.querySelectorAll("[data-i18n-title]").forEach(function (el) {
      var key = el.getAttribute("data-i18n-title");
      el.setAttribute("title", t(key));
    });

    // 4. Update [data-i18n-aria-label]
    document.querySelectorAll("[data-i18n-aria-label]").forEach(function (el) {
      var key = el.getAttribute("data-i18n-aria-label");
      el.setAttribute("aria-label", t(key));
    });

    // 5. Update [data-i18n-tip]
    document.querySelectorAll("[data-i18n-tip]").forEach(function (el) {
      var key = el.getAttribute("data-i18n-tip");
      el.setAttribute("data-tip", t(key));
    });

    // 6. Update [data-i18n-auto] dynamic/seeded text nodes & blog markdown post body blocks
    document.querySelectorAll("[data-i18n-auto], .post-body h2, .post-body h3, .post-body p, .post-body li").forEach(function (el) {
      if (!el.hasAttribute("data-zh-orig")) {
        var initTxt = (el.textContent || "").trim();
        el.setAttribute("data-zh-orig", AUTO_TEXT_MAP_ZH[initTxt] || el.textContent);
      }
      var orig = (el.getAttribute("data-zh-orig") || "").trim();
      if (lang === "en" && AUTO_TEXT_MAP_EN[orig]) {
        el.textContent = AUTO_TEXT_MAP_EN[orig];
      } else if (lang === "zh") {
        el.textContent = AUTO_TEXT_MAP_ZH[orig] || el.getAttribute("data-zh-orig");
      }
    });

    // 6b. Update [data-i18n-auto-val] input/textarea values
    document.querySelectorAll("[data-i18n-auto-val]").forEach(function (el) {
      var cur = el.value || "";
      if (!el.dataset.zhOrigVal && cur) {
        el.dataset.zhOrigVal = translateValueText(cur, "zh");
      }
      var zhOrig = el.dataset.zhOrigVal || "";
      if (!zhOrig) return;
      var enTrans = translateValueText(zhOrig, "en");
      if (cur.trim() === zhOrig.trim() || cur.trim() === enTrans.trim()) {
        el.value = lang === "en" ? enTrans : zhOrig;
      }
    });

    // 7. Update card/row data-title attributes for preview modal
    document.querySelectorAll("[data-title]").forEach(function (el) {
      if (!el.hasAttribute("data-zh-title-orig")) {
        var rawAttr = (el.getAttribute("data-title") || "").trim();
        el.setAttribute("data-zh-title-orig", AUTO_TEXT_MAP_ZH[rawAttr] || rawAttr);
      }
      var origTitle = (el.getAttribute("data-zh-title-orig") || "").trim();
      if (lang === "en" && AUTO_TEXT_MAP_EN[origTitle]) {
        el.setAttribute("data-title", AUTO_TEXT_MAP_EN[origTitle]);
      } else if (lang === "zh") {
        el.setAttribute("data-title", AUTO_TEXT_MAP_ZH[origTitle] || origTitle);
      }
    });

    // 8. Update SVG cover monograms for known Chinese characters
    document.querySelectorAll(".cover-svg text").forEach(function (el) {
      if (!el.hasAttribute("data-zh-orig")) {
        var cur = (el.textContent || "").trim();
        if (MONOGRAM_MAP_EN[cur]) {
          el.setAttribute("data-zh-orig", cur);
        }
      }
      var origChar = el.getAttribute("data-zh-orig");
      if (origChar && MONOGRAM_MAP_EN[origChar]) {
        el.textContent = lang === "en" ? MONOGRAM_MAP_EN[origChar] : origChar;
      }
    });

    // 9. Update document.title
    if (!document.documentElement.hasAttribute("data-orig-doc-title")) {
      document.documentElement.setAttribute("data-orig-doc-title", document.title);
    }
    var origDocTitle = document.documentElement.getAttribute("data-orig-doc-title") || document.title;
    if (lang === "en") {
      var enTitle = origDocTitle
        .replace(" - 简历编辑 - ", " - Resume Editor - ")
        .replace(" - 博客编辑 - ", " - Blog Editor - ")
        .replace("管理 - ", "Admin - ")
        .replace(" - 管理 - ", " - Admin - ")
        .replace("登录 - ", "Sign In - ")
        .replace("访问受限 - ", "Protected - ");
      Object.keys(AUTO_TEXT_MAP_EN).forEach(function (zhStr) {
        if (enTitle.indexOf(zhStr) !== -1) {
          enTitle = enTitle.replace(zhStr, AUTO_TEXT_MAP_EN[zhStr]);
        }
      });
      document.title = enTitle;
    } else {
      document.title = origDocTitle;
    }

    // 10. Update language toggle button(s)
    document.querySelectorAll("#lang-toggle-btn, [data-action='toggle-lang']").forEach(function (btn) {
      btn.textContent = lang === "zh" ? "🌐 EN" : "🌐 中文";
      btn.removeAttribute("data-tip");
      btn.setAttribute("title", t("common.lang_tip"));
      btn.setAttribute("aria-label", t("common.lang_tip"));
    });
  }

  function setLang(lang) {
    var normalized = lang === "en" ? "en" : "zh";
    try {
      localStorage.setItem(STORAGE_KEY, normalized);
    } catch (e) {}
    applyI18n(normalized);
    window.dispatchEvent(new CustomEvent("siteflow:langchange", { detail: { lang: normalized } }));
  }

  function toggleLang() {
    var next = getLang() === "zh" ? "en" : "zh";
    setLang(next);
    return next;
  }

  document.addEventListener("click", function (e) {
    var btn = e.target.closest("#lang-toggle-btn, [data-action='toggle-lang']");
    if (btn) {
      e.preventDefault();
      if (btn.blur) btn.blur();
      toggleLang();
    }
  });

  window.SiteFlowI18n = {
    t: t,
    getLang: getLang,
    setLang: setLang,
    toggleLang: toggleLang,
    applyI18n: applyI18n,
    translateText: translateText,
    toZhText: toZhText
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", function () {
      applyI18n();
    });
  } else {
    applyI18n();
  }
})();
