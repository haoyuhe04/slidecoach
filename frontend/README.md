# Vercel 前端部署

这部分只发布网页与 `/api` 转发规则。FastAPI、SQLite、课件文件和模型配置继续运行在自己的后端服务器。

## 部署设置

从 GitHub 导入本仓库，选择以下配置：

| 项目 | 值 |
| --- | --- |
| Root Directory | `frontend` |
| Framework Preset | `Other` |
| Build Command | `node build.mjs` |
| Install Command | 留空，使用仓库配置跳过安装 |
| Output Directory | 保持默认；构建生成 `.vercel/output` |
| Include source files outside Root Directory | 开启，构建需读取 `../static/` |

在 Vercel 的构建环境变量中设置 `SLIDECOACH_BACKEND_ORIGIN`，值为后端的公网 HTTPS 源地址，例如 `https://backend.example.com`。不要加 `/api` 路径。此处不需要模型 API 密钥。

部署会生成一个 `vercel.app` 地址。前端从同一个地址请求 `/api`，Vercel 再转发到后端；Cookie 为当前前端域名的 Cookie，不需要在网页内跨域登录。

## 后端设置

后端继续只监听 `127.0.0.1:8787`。通过 Cloudflare Tunnel 等工具为这个端口提供公网 HTTPS 入口。

设置后端环境变量 `SLIDECOACH_ALLOWED_ORIGINS` 为完整的前端源地址，例如：

```ini
SLIDECOACH_ALLOWED_ORIGINS=https://your-project.vercel.app,https://backend.example.com
```

程序只接受明确列出的 HTTPS 源，不接受通配符。通过这些源注册或登录时，程序设置带 `Secure`、`HttpOnly` 和 `SameSite=Lax` 的会话 Cookie。本机同源访问可继续使用原有配置。更新环境变量后重启后端服务。

如要从临时 Vercel 预览地址登录，也需明确加入该地址，不能直接允许所有 `vercel.app` 项目。API 响应禁止 CDN 缓存，账号、材料和学习记录均保留原有权限检查。

## 免费隧道试用

安装 Cloudflare 官方 `cloudflared` 后，可在服务器执行：

```sh
cloudflared tunnel --no-autoupdate --protocol http2 --url http://127.0.0.1:8787 --http-host-header 127.0.0.1:8787
```

命令会显示一个 `trycloudflare.com` 地址，将它填入 Vercel 的 `SLIDECOACH_BACKEND_ORIGIN`。仓库也提供用户服务模板 `deploy/slidecoach-tunnel.service`，可按现有部署方式托管。

Quick Tunnel 用于免费试用，没有可用性保证；进程重新启动后地址可能变化。变化后需要更新 Vercel 环境变量并重新部署前端。固定公网地址应使用有域名的正式隧道或提供固定地址的服务。

## 验证

先打开前端域名的 `/api/health`，确认能到达后端。再创建自己的账号，上传课件，完成考点整理、问答或讲授反馈，并重新登录检查记录。前端部署成功不代表后端模型调用已经通过。

本方案使用外部源转发，不在 Vercel Function 内解析课件；仍需实测部署平台的上传与请求超时边界。不要通过给网页添加模型密钥来绕过网络或后端配置问题。
