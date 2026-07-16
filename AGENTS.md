# cv-research-radar 开发约定

## 项目约定

- Python 版本为 3.12，源码使用 `src/` 布局，CLI 模块名为 `cv_radar`。
- 统一领域对象放在 `src/cv_radar/models.py`，所有信息源必须产出 `ResearchItem`。
- 配置使用严格 Pydantic 模型加载 YAML；新增字段必须同时更新模型、默认配置和测试。
- 保持同步、轻量实现；第一版不要引入任务队列、数据库、网页爬虫或浏览器框架。
- PDF 和 Markdown 两种报告统一写入 `reports/`，使用相同日期文件名。
- `reports/` 包含私人研究日报，必须保持在 `.gitignore` 中，禁止暂存、提交或发布。
- `review/` 包含候选摘要与订阅生成的分析，同样属于私人数据，必须保持忽略且不得发布。
- 报告使用中文，原始英文标题不得翻译或改写；每条推荐必须包含中文概览、亮点和新颖性说明。

## 常用命令

```bash
python -m pip install -e ".[dev]"
python -m pytest
python -m cv_radar validate-config
python -m cv_radar list-sources
python -m cv_radar run
python -m cv_radar run --date 2026-07-10 --fixture-dir tests/fixtures
python -m cv_radar prepare-review --date 2026-07-10 --fixture-dir tests/fixtures
python -m cv_radar finalize-review --date 2026-07-10
```

## 测试要求

- 修改解析器时必须添加最小真实形状 fixture，并覆盖正常响应与失败响应。
- 所有外部 API 测试必须使用 mock 或离线 fixture，测试套件不得访问网络。
- 修改去重、评分、报告或状态逻辑时，必须覆盖同日重复运行的幂等性。
- 提交前运行全量 `python -m pytest` 和 `python -m compileall -q src`。

## 外部信息源实现规范

- 信息源放入 `src/cv_radar/sources/`，其异常必须在来源边界内隔离。
- 复用 `ResilientHttpClient`；每个请求必须有显式超时、有限重试、指数退避、错误日志与请求间隔。
- 不得记录请求头、API Key 或完整认证 URL。
- 优先使用稳定 ID，保留原始响应中有助于追踪来源的字段到 `raw_metadata`。
- 单个条目补充失败时返回原对象；单个 Feed 失败时继续处理其余 Feed。

## 安全要求

- 密钥只从环境变量或 GitHub Secrets 读取，绝不写入代码、YAML、fixture、日志或报告。
- `.env` 必须保持忽略，只提交无值的 `.env.example`。
- 无 API 订阅审阅必须通过 `prepare-review` / `finalize-review` 交换文件；后台任务不得读取或调用 `OPENAI_API_KEY`。
- 不执行不受控网页抓取，不下载或分析完整 PDF。
- 新增外部请求前先确认服务条款、速率限制和可接受的 User-Agent。

## 提交前检查清单

- [ ] 配置校验通过。
- [ ] 全部测试与编译检查通过。
- [ ] 离线 fixture 流程成功，且重复运行不产生重复状态记录。
- [ ] PDF 日报和 Markdown 旁车都包含必需字段并明确 LLM 是否执行。
- [ ] PDF 已渲染为 PNG 检查过中文字体、分页、页码和链接排版。
- [ ] 没有 `.env`、密钥、缓存、临时文件或虚拟环境。
- [ ] 检查变更清单，确认只包含预期源码、配置、测试、文档、报告和状态。
