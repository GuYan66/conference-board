# AI 顶会信息看板

一个面向 AI 研究者的顶会信息看板，覆盖 12 个顶会（NeurIPS / ICML / ICLR / AAAI / IJCAI / CVPR / ICCV / ECCV / NAACL / WSDM / WWW / ICRA），展示关键时间节点与投稿倒计时。

## 快速开始

### 查看网站
双击 `index.html` 即可在浏览器中打开，无需任何服务器或环境配置。

### 更新数据
会议 deadline 偶有变动，建议定期运行抓取脚本刷新数据：

```bash
# 首次使用：创建虚拟环境并安装依赖（仅需一次）
.venv/Scripts/python.exe -m pip install -r scripts/requirements.txt

# 抓取最新数据（约 30 秒，会访问 8 个会议官网）
.venv/Scripts/python.exe scripts/scraper.py
```

脚本会自动：
- 抓取各会议官网的 Important Dates 页面
- 解析时间节点（投稿截止、Rebuttal、结果通知、Camera Ready、会议日期）
- 选择投稿未截止的届次（若均已截止则取最近一届）
- 输出 `data/conferences.json`（主数据）、`js/data-inline.js`（内联数据，保证双击可用）、`data/review.md`（人工校验清单）

## 功能

- **投稿倒计时看板**：每个会议卡片实时显示距投稿截止还剩多少天
- **最近截止高亮**：页面顶部突出显示 3 个即将截止的会议（红/橙/蓝色条分级）
- **筛选与排序**：按类别（AI/ML、CV）、状态（投稿中、已截止）筛选，按截止日期或会议名排序
- **时间节点列表**：摘要截止、投稿截止、Rebuttal、结果通知、Camera Ready、会议日期
- **置信度标记**：从官网直接解析的数据标记为"已确认"，回退数据标记"!"待人工核对

## 数据源

| 会议 | 数据来源 | 解析方式 |
|------|---------|---------|
| NeurIPS / ICML / ICLR / CVPR / ECCV / ICCV | 各会议官网 Dates 页（researchr CMS） | `<td title>` 结构化解析 |
| AAAI / IJCAI | aaai.org / {year}.ijcai.org | 长日期 + 关键词上下文匹配 |
| NAACL / WSDM / WWW / ICRA | 各会议官网 | 长日期 + 关键词上下文匹配；官网解析失败时回退 ccf-deadlines |

时区统一为 AoE (Anywhere on Earth, UTC-12)。

## 人工校验

每次抓取后查看 `data/review.md`，其中列出：
- 抓取失败的会议（需手动补录）
- 缺失字段（如地点信息在 Dates 页面通常没有）
- 低置信度字段（标记"!"，建议核对官网）

## 文件结构

```
conference-board/
├── index.html              # 主页面（双击打开）
├── css/style.css           # 样式
├── js/
│   ├── app.js              # 渲染、筛选、倒计时逻辑
│   └── data-inline.js      # 抓取脚本生成（window.CONF_DATA）
├── data/
│   ├── conferences.json    # 主数据
│   └── review.md           # 人工校验清单
└── scripts/
    ├── scraper.py          # 主抓取脚本
    ├── config.yml          # 12 会议配置
    ├── requirements.txt    # Python 依赖
    └── parsers/            # 解析器
        ├── researchr.py    # researchr CMS 系
        ├── cvf.py          # CVF 系（复用 researchr）
        └── standalone.py   # 独立站（AAAI/IJCAI）
```

## 扩展新会议

在 `scripts/config.yml` 中添加一条配置即可（若新会议官网属于 researchr CMS 或类似结构）：

```yaml
  - id: sigkdd
    title: KDD
    full_name: ACM SIGKDD Conference on Knowledge Discovery and Data Mining
    category: AI-ML
    parser: standalone
    biennial: null
    url_template: "https://kdd.org/{year}/"
```

若官网结构特殊，在 `scripts/parsers/` 新增解析器模块并在 config 指定。

## 技术说明

- **前端**：纯静态 HTML/CSS/JS，无外部依赖，离线可用
- **双击可用**：脚本生成 `data-inline.js` 内联注入数据，规避 `file://` 协议下 fetch 的 CORS 限制
- **倒计时**：前端 JS 每分钟实时计算，基于本地时间与 AoE 截止时间的差值
- **Python**：requests + BeautifulSoup4 + lxml + PyYAML，依赖极轻
