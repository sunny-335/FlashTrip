import { defineConfig } from "vitepress";

// 瞬旅 FlashTrip 官方文档站
// base 与后端挂载路径（/FlashTrip）保持一致，产物复制到镜像 static/docs。
export default defineConfig({
  lang: "zh-CN",
  base: "/FlashTrip/",
  title: "瞬旅 FlashTrip",
  description: "AI 驱动的自研多功能旅行规划应用 · 单镜像部署 · 官方文档",
  head: [["meta", { name: "theme-color", content: "#0e9f8e" }]],
  themeConfig: {
    nav: [
      { text: "快速开始", link: "/guide/quickstart" },
      { text: "功能指南", link: "/guide/itinerary" },
      { text: "设置说明", link: "/settings/map" },
      { text: "更新与 FAQ", link: "/guide/update" },
    ],
    sidebar: {
      "/guide/": [
        {
          text: "快速开始",
          items: [
            { text: "部署与安装", link: "/guide/quickstart" },
            { text: "安装向导", link: "/guide/wizard" },
            { text: "本地开发", link: "/guide/local-dev" },
          ],
        },
        {
          text: "功能指南",
          items: [
            { text: "行程规划", link: "/guide/itinerary" },
            { text: "地图", link: "/guide/map" },
            { text: "AI 助手", link: "/guide/ai" },
            { text: "费用预算", link: "/guide/expenses" },
            { text: "协作与分享", link: "/guide/collab" },
            { text: "天气与邮件", link: "/guide/weather-mail" },
            { text: "备份", link: "/guide/backup" },
          ],
        },
        {
          text: "更新与 FAQ",
          items: [
            { text: "版本更新", link: "/guide/update" },
            { text: "常见问题", link: "/guide/faq" },
          ],
        },
      ],
      "/settings/": [
        {
          text: "设置说明",
          items: [
            { text: "地图 Provider 配置", link: "/settings/map" },
            { text: "对象存储", link: "/settings/storage" },
            { text: "天气服务", link: "/settings/weather" },
            { text: "邮件（SMTP）", link: "/settings/mail" },
          ],
        },
      ],
    },
    socialLinks: [{ icon: "github", link: "https://github.com/sunny-335/flashtrip" }],
    outline: { level: [2, 3], label: "本页目录" },
    docFooter: { prev: "上一篇", next: "下一篇" },
    lastUpdated: { text: "最后更新", formatOptions: { dateStyle: "short", timeStyle: "short" } },
    search: { provider: "local", options: { translations: { button: { buttonText: "搜索文档", buttonAriaLabel: "搜索" } } } },
    footer: {
      message: "基于 MIT 协议发布 · 信息架构参考 TREK（未使用其源码）",
      copyright: "瞬旅 FlashTrip 文档",
    },
    returnToTopLabel: "回到顶部",
    sidebarMenuLabel: "菜单",
    darkModeSwitchLabel: "主题",
    lightModeSwitchTitle: "切换到浅色模式",
    darkModeSwitchTitle: "切换到深色模式",
  },
});
