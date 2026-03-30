# Repo-local bb-sites

这个目录用来保存你自己的 `bb-browser` / `bb-sites` 适配器代码，并随 `wewrite` 一起进 Git。

## 加载顺序

`wewrite` 的热点抓取会优先读取仓库里的 `bb-sites/`，再回退到运行时全局目录 `/config/.bb-browser/bb-sites`。

这意味着你以后新增或覆盖适配器时，直接在仓库里改就行，例如：

```text
bb-sites/
├── twitter/search.js
├── jin10/newsflash.js
├── polymarket/markets.js
└── kalshi/markets.js
```

## 给 bb-browser CLI 安装

如果你不仅想让 `wewrite` 使用这些适配器，也想让 `bb-browser site ...` 直接识别它们，可以运行：

```bash
python3 scripts/install_bb_sites.py
```

## 约定

- 一个适配器对应一个 `.js` 文件
- 路径即站点命名，例如 `twitter/search.js` -> `twitter/search`
- 建议保留 `/* @meta ... */` 头部，方便后续直接给 `bb-browser` CLI 用
- `_templates/` 目录只放模板，不会被安装脚本同步

## 下一步建议

- 金十：`bb-sites/jin10/newsflash.js`
- 预测市场：`bb-sites/polymarket/markets.js`
- 预测市场：`bb-sites/kalshi/markets.js`
