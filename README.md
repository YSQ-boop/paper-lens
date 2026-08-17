# Paper Lens
,3cyOdFGvvpD27Ph%e
Paper Lens 是一个面向 Codex 的单篇论文阅读插件。它先生成一份适合快速浏览的报告，并可在同一个 `report.md` 中继续扩展为 reviewer-level 深读，避免快读与深读形成两份相互漂移的文档。

支持以下输入：

- arXiv ID，例如 `1706.03762`
- arXiv 论文链接
- 本地 PDF 的绝对路径

## 主要能力

- 默认生成 3–5 分钟可读完的快读报告
- 按需升级为包含公式、实验、相关工作和复现评估的深读报告
- 使用页码、章节、公式、图和表定位关键判断
- 从 arXiv 源码与原始 PDF 中提取可用于报告的图像
- 对本地 PDF 计算哈希并复用已有工作区
- 深读联网失败时保留原文分析，并明确标记外部证据不完整
- 报告语言跟随用户，保留必要的英文术语与符号

## 使用方式

在新的 Codex 任务中调用 `$paper-lens`：

```text
$paper-lens 快读 https://arxiv.org/abs/1706.03762
```

```text
$paper-lens 深读 /absolute/path/to/paper.pdf
```

快读完成后，可以在同一任务中继续：

```text
继续深读这篇论文
```

后续追问默认只在对话中回答。只有明确要求“写入报告”“补充到报告”或类似操作时，插件才会修改 `report.md`。

## 输出结构

每篇论文写入当前工作目录下的独立工作区：

```text
paper-reports/
└── <paper-key>_<title-slug>/
    ├── report.md
    ├── metadata.json
    ├── raw/
    ├── assets/
    ├── cache/
    └── logs/
```

- arXiv 论文使用基础 arXiv ID 作为 `paper-key`。
- 本地 PDF 使用文件 SHA-256 的前 12 位作为 `paper-key`。
- 快读与深读共用唯一的 `report.md`。

## 本地安装

本仓库是单插件源码仓库，不是 Codex marketplace 仓库。推荐将它克隆到个人插件目录：

```bash
git clone <your-repository-url> ~/plugins/paper-lens
```

默认个人 marketplace 位于 `~/.agents/plugins/marketplace.json`。若该文件尚不存在，可创建为：

```json
{
  "name": "personal",
  "interface": {
    "displayName": "Personal"
  },
  "plugins": [
    {
      "name": "paper-lens",
      "source": {
        "source": "local",
        "path": "./plugins/paper-lens"
      },
      "policy": {
        "installation": "AVAILABLE",
        "authentication": "ON_INSTALL"
      },
      "category": "Productivity"
    }
  ]
}
```

若 personal marketplace 已包含其他插件，只添加上面的 `paper-lens` 条目，不要覆盖原有内容。随后安装插件：

```bash
codex plugin add paper-lens@personal
```

安装后新建一个 Codex 任务，使 `$paper-lens` 被重新发现。

## Python 依赖

流水线使用 Python 3、PyMuPDF、Requests 和 Beautiful Soup。缺少依赖时运行：

```bash
bash skills/paper-lens/scripts/bootstrap.sh
```

脚本会在 `~/.cache/paper-lens/venv` 中创建隔离环境，不会修改当前项目的 Python 环境。它会打印可用于运行流水线和测试的 Python 路径。

统一的内部命令是：

```bash
python skills/paper-lens/scripts/paper_pipeline.py prepare \
  --input "<arXiv ID、arXiv URL 或本地 PDF>" \
  --mode quick \
  --output-root "$PWD/paper-reports" \
  --language zh
```

```bash
python skills/paper-lens/scripts/paper_pipeline.py validate \
  --workspace "<paper workspace>" \
  --mode quick
```

通常不需要手动执行这些命令，Codex 会依据 skill 工作流调用它们。

## 隐私与联网边界

- 本地 PDF 只会复制到本地 `paper-reports` 工作区，不会上传到翻译、OCR、转换或论文托管服务。
- 快读不检索外部相关文献，只使用论文原文和原始元数据。
- 深读可以使用论文标题或主题词检索相关文献，但不会上传本地 PDF。
- 若论文尚未公开或包含敏感信息，应避免联网检索，或仅生成基于原文的深读并标记为 `partial`。

## 当前限制

- 一次只处理一篇论文，不用于多论文综述或知识库建设。
- 不包含 OCR；纯扫描或图片型 PDF 需要先在本地完成 OCR。
- 不绕过付费墙、访问控制或受限下载。
- 不提供自定义面板、云同步或团队共享后端。

## 开发与测试

安装依赖后运行：

```bash
~/.cache/paper-lens/venv/bin/python -m unittest discover -s tests -v
```

校验 skill 和插件清单：

```bash
python3 ~/.codex/skills/.system/skill-creator/scripts/quick_validate.py skills/paper-lens
python3 ~/.codex/skills/.system/plugin-creator/scripts/validate_plugin.py .
```

项目结构：

```text
.
├── .codex-plugin/
│   └── plugin.json
├── skills/
│   └── paper-lens/
│       ├── SKILL.md
│       ├── agents/
│       ├── references/
│       ├── scripts/
│       └── requirements.txt
└── tests/
    └── test_pipeline.py
```

## Star History

[![Star History Chart](https://api.star-history.com/image?repos=YSQ-boop/paper-lens&type=Date)](https://www.star-history.com/?repos=YSQ-boop%2Fpaper-lens&type=date)
