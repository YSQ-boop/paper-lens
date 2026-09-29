# Paper Lens

[![CI](https://github.com/YSQ-boop/paper-lens/actions/workflows/ci.yml/badge.svg)](https://github.com/YSQ-boop/paper-lens/actions/workflows/ci.yml)
[![License](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)
[![Codex plugin](https://img.shields.io/badge/Codex-plugin-111827)](https://developers.openai.com/plugins/)

Paper Lens is an open-source Codex plugin for trustworthy, source-grounded reading of one academic paper. It creates a fast first-pass report, then can deepen the same `report.md` into a reviewer-style analysis without splitting the evidence trail across separate documents.

[中文简介](#中文简介) · [Example report](examples/1706.03762v7/report.md) · [Roadmap](ROADMAP.md) · [Contributing](CONTRIBUTING.md)

## Why Paper Lens

General-purpose summaries are easy to generate and hard to audit. Paper Lens instead treats paper reading as an evidence workflow:

- substantive claims point to a page, section, equation, figure, or table;
- facts reported by the paper are distinguished from independent verification;
- missing evidence is labeled `not reported`, `not verified`, or `partial`;
- quick and deep reads update one durable report;
- the PDF binary remains local, and the plugin has no telemetry or hosted backend.

The core is a deterministic Python preparation and validation pipeline plus a Codex skill that performs the analysis. The pipeline resolves arXiv versions, extracts text and clean figures, builds a constrained report skeleton, and rejects incomplete or weakly grounded outputs.

## Quick start

Requirements: Codex with plugin support, Git, and Python 3.10+.

```bash
git clone https://github.com/YSQ-boop/paper-lens.git ~/plugins/paper-lens
```

Add the following entry to the `plugins` array in `~/.agents/plugins/marketplace.json` (preserve any existing entries):

```json
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
```

If the file does not exist yet, initialize it with `name`, `interface`, and an empty `plugins` array before adding the entry:

```json
{
  "name": "personal",
  "interface": {"displayName": "Personal"},
  "plugins": []
}
```

Install it and start a new Codex task:

```bash
codex plugin add paper-lens@personal
```

Then invoke the skill explicitly:

```text
$paper-lens quick-read https://arxiv.org/abs/1706.03762v7 in English
```

```text
$paper-lens 深读 /absolute/path/to/paper.pdf
```

After a quick read, `Continue with a deep review` extends the same report. Follow-up answers do not change the report unless you explicitly ask to save them.

## Output and trust boundary

Each paper gets one workspace under the current directory:

```text
paper-reports/<paper-key>_<title-slug>/
├── report.md          # the durable user-facing artifact
├── metadata.json      # provenance, status, warnings, hashes
├── raw/               # local copy of the source PDF / arXiv inputs
├── assets/            # normalized local PNG figures
├── cache/             # extracted text and structured page data
└── logs/              # preparation and validation results
```

Only `report.md` is intended as the normal deliverable. Cached paper material may be copyrighted or confidential and should not be committed. The repository's example includes only a hand-reviewed report and public bibliographic metadata—no paper PDF, source archive, extracted figures, or cache.

## Modes

| Mode | Evidence boundary | Intended result |
| --- | --- | --- |
| Quick | Original paper and public arXiv metadata only | A 3–5 minute overview with source-location anchors |
| Deep | Original paper plus verified primary literature when available | Claims–evidence matrix, formula explanation, experiment audit, critique, and reproducibility assessment |

Deep mode remains useful without web access. It marks external verification as `partial` instead of silently filling gaps.

### Formula and table grounding

Reports may discuss formulas and tables only when the discussion includes a source-location anchor such as an equation or table number, section, or page. The deterministic validator reports the exact line/block that is missing an anchor. Statements that explicitly say a formula or table is `not reported` / `未报告` remain valid, because absence is itself part of the evidence record.

## Privacy and security

- The pipeline does not upload the PDF binary to OCR, translation, conversion, or paper-hosting services. Codex necessarily reads relevant extracted text to generate the report; that model processing follows the user's configured Codex/OpenAI data controls.
- The project contains no analytics, tracking identifiers, remote logging, or hosted service.
- arXiv inputs download only the public abstract page, PDF, and—during deep mode—the source archive.
- Multi-file arXiv sources resolve safe relative `\input` and `\include` references without executing TeX; missing or cyclic references are recorded as warnings.
- Network responses and archive expansion are size-limited; extracted media is normalized to PNG before it can be embedded.
- Scanned and encrypted PDFs fail with an actionable message. Paper Lens does not bypass access controls or paywalls.

See [PRIVACY.md](PRIVACY.md) and [SECURITY.md](SECURITY.md) for the exact data and security boundaries.

## Development

Create the isolated runtime used by the skill:

```bash
bash skills/paper-lens/scripts/bootstrap.sh
```

The script prints the Python executable. With the default cache location:

```bash
~/.cache/paper-lens/venv/bin/python -m unittest discover -s tests -v
~/.cache/paper-lens/venv/bin/python skills/paper-lens/scripts/paper_pipeline.py --version
```

The deterministic pipeline can also be run directly:

```bash
~/.cache/paper-lens/venv/bin/python skills/paper-lens/scripts/paper_pipeline.py prepare \
  --input "1706.03762v7" --mode quick --output-root "$PWD/paper-reports" --language en
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for tests, validation, pull-request expectations, and the optional model evaluation suite.

## Project status

Paper Lens is early-stage and maintained in public. Current priorities are evaluator baselines, broader PDF coverage, report-contract stability, and documented real-world use. The project deliberately does not claim adoption or quality scores that have not been measured; [IMPACT.md](IMPACT.md) records dated public evidence.

## 中文简介

Paper Lens 是一个开源 Codex 单篇论文阅读插件。它把“可信、可核对”放在摘要速度之前：重要判断必须指向页码、章节、公式、图或表；证据缺失时明确标注“未报告 / 未验证 / 部分完成”；快读与深读持续写入同一份 `report.md`。

支持 arXiv ID、arXiv 链接和本地 PDF。默认快读只使用论文原文；深读可核验相关的一手文献。流水线不上传 PDF 文件本身，但 Codex 会读取相关的抽取文本来生成报告；项目不含遥测或自建云端后端。安装、命令和开发说明以上方英文文档为准，中文讨论和贡献同样欢迎。

## License

Licensed under the [Apache License 2.0](LICENSE).
