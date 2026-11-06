# SlideCoach 部署与试用说明

SlideCoach 根据课程 PPTX / PDF 自动归纳少量核心考点，支持推荐复习、自选考点、问答和讲授自测，并记录回答、提示使用和来源依据。

这是 2026-11-07 整理的可独立部署版本，包含自动整理考点和出题引用编号修复。API 地址、模型名和密钥均未预填；仓库不包含已有账号、用户课件、数据库、私人服务器配置或虚拟环境。示例目录只包含项目自建的 TCP 教学课件。

## 1. 准备环境

推荐使用 Python 3.12 和 uv。前端不需要 Node.js，数据库使用 SQLite，不用另装数据库服务。

先安装 uv：[官方安装说明](https://docs.astral.sh/uv/getting-started/installation/)。安装后重新打开终端，运行 `uv --version` 确认可用。

克隆仓库或下载源码 ZIP，进入包含本 README 和 pyproject.toml 的项目根目录，然后执行：

```sh
git clone git@ipads.sjtu.edu.cn:HaoyuHe/slidecoach.git
cd slidecoach
```

使用源码 ZIP 的同学直接在解压后的项目根目录打开终端。安装环境：

```sh
uv python install 3.12
uv sync --locked --python 3.12
```

这些命令适用于 macOS、Linux 和 Windows PowerShell。首次安装需要联网下载 Python 和依赖；`.venv` 会在当前目录自动创建。依赖版本由 `uv.lock` 固定。

## 2. 配置自己的模型 API

复制配置模板。macOS / Linux：

```sh
cp .env.example .env
chmod 600 .env
```

Windows PowerShell：

```powershell
Copy-Item .env.example .env
```

用文本编辑器打开 `.env`，填写以下三个值：

```ini
SLIDECOACH_MODEL_URL=https://your-provider.example/v1
SLIDECOACH_MODEL=your-model-name
SLIDECOACH_API_KEY=your-own-api-key
```

上面是占位示例，不能直接调用。请向自己的服务商获取实际配置。地址应包含服务商要求的 `/v1` 或 `/api/v1` 前缀，但不要再加 `/chat/completions`；程序会自动拼接请求路径。模型须支持 OpenAI 兼容的 Chat Completions 接口和 JSON object 输出。

如果使用学校或单位内网 API，运行应用的电脑或服务器也必须处在相应网络环境中；仅浏览器能联网不代表后端能访问模型。

其他配置可先保持默认：

| 配置项 | 默认值 | 作用 |
| --- | --- | --- |
| `SLIDECOACH_PROVIDER` | `openai-compatible` | 使用兼容接口 |
| `SLIDECOACH_DATA` | `./data` | 保存本机账号、课件和复习记录 |
| `SLIDECOACH_RPM` | `10` | 每分钟请求上限，可调低；应用最高允许 10 |
| `SLIDECOACH_SECURE_COOKIE` | `0` | 本机 HTTP 使用 0；HTTPS 部署使用 1 |

API 密钥只保存在自己的 `.env`，不要发到群里或写入前端。以后重新打包分享时也要排除 `.env` 和 `data/`。

没有 API 时，可以暂时保留三个空值，先启动网页、创建账号和导入材料；自动整理考点、出题及评价需要配置有效 API，程序不会用演示答案冒充模型结果。

## 3. 启动应用

仍在项目根目录执行：

```sh
uv run --locked --env-file .env python -m uvicorn app.main:app --host 127.0.0.1 --port 8787 --workers 1 --no-access-log
```

打开 **http://127.0.0.1:8787**。终端保持运行，按 `Ctrl+C` 停止服务。修改 `.env` 后重新启动才会生效。

这里显式使用 `--env-file .env` 加载配置；单独运行 `python` 不会自动读取该文件。有关加载规则见 [uv 配置文档](https://docs.astral.sh/uv/concepts/configuration-files/#environment-variable-files)。

首次打开创建自己的账号，用户名至少 2 个字符、密码至少 8 个字符。没有预置管理员或共享密码。

## 4. 试用一轮完整复习

1. 在“我的课件”中下载示例 PPTX，再将它上传；也可以使用自己的 `.pptx` 或 `.pdf`。
2. 等待系统整理核心考点。正常文本无需逐页确认，可以点击“开始推荐复习”，或选择几个想巩固的考点。
3. 先独立回答，再按需请求提示、回看来源或查看完整解释。也可以切换到“讲给同学听”。
4. 点击“结束并回顾”，检查原回答、提示记录和下一步建议。发现评价有问题时可提出异议并申请复核。

每份材料不超过 25 MB / 100 页。短课件最多归纳两个考点，较长材料最多六个。页码仍作为依据保留在“查看来源”中。10 分钟默认推荐前两个考点，20 分钟推荐前三个；这些是学习安排，不是老师命题概率。

资料一经上传，应用会向你配置的模型发送必要文字摘录以整理考点。出题和评价还会发送本题材料及相关回答，请使用有权处理的课程材料。

## 5. 运行测试

```sh
uv run --locked python -m pytest -q
```

该分发版包含 **22 项自动化测试**。自动化测试使用临时数据库和模型测试替身，不需要有效 API 密钥，也不会消耗模型额度。真实服务是否可用，需再按上面的试用流程检查。

浏览器访问 `http://127.0.0.1:8787/api/health` 可检查应用是否运行。`model_configured: true` 只表示必要配置不为空，不表示鉴权已经成功。

## 6. 部署到自己的 Linux 服务器（可选）

先在服务器解压并完成前面的安装、配置和启动步骤。服务默认只监听服务器本机，可在自己的电脑建立 SSH 隧道：

```sh
ssh -N -L 127.0.0.1:8787:127.0.0.1:8787 your-user@your-server
```

将用户名和服务器地址换成自己的，然后在本机打开 http://127.0.0.1:8787。若本地端口已占用，可把命令左侧的 8787 改成 8788，再访问 http://127.0.0.1:8788。

需要后台运行时，包内提供 `deploy/slidecoach.service`。模板假定项目位于 `~/apps/slidecoach`，其中已经安装 `.venv` 并配置 `.env`；否则先修改模板里的路径。停止之前前台启动的进程后，执行：

```sh
mkdir -p ~/.config/systemd/user
cp deploy/slidecoach.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now slidecoach.service
systemctl --user status slidecoach.service
```

需要退出 SSH 后继续运行、随系统启动时，可执行 `loginctl enable-linger "$USER"`；服务器可能要求管理员授权。查看日志使用 `journalctl --user -u slidecoach.service -n 50`，更新配置后使用 `systemctl --user restart slidecoach.service`。

此模板用于个人或小组的私有试用。若提供公网访问，应另行配置 HTTPS、访问策略和备份。当前限流和模型互斥位于单进程内，请保持 `--workers 1`。

## 7. 数据、备份与当前边界

运行后，`data/slidecoach.sqlite3` 保存账号及复习记录，`data/uploads/` 保存上传文件。每位同学使用自己解压目录下的数据，和项目原服务器无关。

需要备份时先停止应用，再在项目目录运行：

```sh
uv run --locked python scripts/backup.py --data data --output backups
```

备份包含数据库和课件，恢复时也应停服并一起恢复。网页支持删除自己的课件或复习记录；这些删除无法通过界面撤销。

PPTX 提供文字和表格提取，原版式预览请使用 PDF。扫描件 OCR、复杂图表理解和长期复习调度暂未实现。模型选择来源编号后，程序回填真实原文；这能防止伪造引用，但不能保证模型解释在所有课程中都正确。回顾页会区分独立回答、帮助后完成和待核实结果。

## 常见问题

| 现象 | 处理方式 |
| --- | --- |
| 找不到 `uv` | 安装后重开终端，确认 `uv --version` 能运行 |
| 找不到 `.env` | 先复制 `.env.example`，并在项目根目录启动 |
| 显示“模型待配置” | 检查 URL、模型名、密钥是否均已填写，重启应用 |
| `.env` 修改后仍是旧配置 | 终端中已有的同名环境变量优先于 `.env`，检查后重新启动 |
| 模型鉴权失败 | 核对自己的密钥、模型调用名及网络访问条件 |
| 模型超时或 429 | 稍后重试；应用保留任务，不要连续重复点击 |
| 浏览器无法连接 | 检查终端服务是否仍运行；远程部署还需检查 SSH 隧道 |
| 8787 端口被占用 | 将启动命令中的 `--port` 改为 8788，浏览器使用相同端口 |
| 扫描件没有识别文字 | 使用带文本的 PDF，或在“修正识别内容”中补充文字 |

## 项目目录

```text
slidecoach/
  README.md             部署与试用说明
  .env.example          空白配置模板
  pyproject.toml        依赖声明与测试配置
  uv.lock               固定依赖版本
  app/                  后端、解析、考点与模型适配
  static/               网页界面
  sample/               自建教学示例
  tests/                自动化测试
  scripts/              示例生成和备份脚本
  deploy/               通用 Linux 用户服务模板
```

本仓库提供源码与自建样例，第三方依赖由安装工具另行下载；依赖的软件许可仍按各自项目条款执行。
