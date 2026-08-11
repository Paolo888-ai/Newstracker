# NewsTracker

每天自动收集、筛选并生成适合手机阅读的科技 / AI 日报。

页面参考原有飞书版本，保留深色主题、统计卡片、今日要点、领域折叠、文章深度解析及异常源清单。程序配置了 18 个中英文科技信息源，默认抓取最近 24 小时，并在每天北京时间 09:00 由 GitHub Actions 自动运行。

## 本地预览

```powershell
python -m venv .venv
.\.venv\Scripts\pip install -r requirements.txt
.\.venv\Scripts\python src\news_tracker.py --no-notify
python -m http.server 8000 --directory public
```

浏览器打开 `http://localhost:8000`。

## 数据流

```text
信息源 -> 抓取 -> 规范化 -> 去重 -> 筛选/摘要 -> report.json -> HTML 日报 -> 手机通知
```

## 云端部署与 iPhone 推送

1. 将项目推送到 GitHub 仓库。
2. 在仓库 `Settings → Pages` 中，将 Source 设为 **GitHub Actions**。
3. 在 `Settings → Secrets and variables → Actions` 新建 Secret：
   - `BARK_URL`：Bark App 给出的完整推送地址。
   - `DEEPSEEK_API_KEY`：可选；填写后启用动态新闻分析和一句话点评。
   - `FEISHU_WEBHOOK`：可选；如需同步到飞书，填写机器人 Webhook。
4. 新建变量 `REPORT_BASE_URL`，值为 GitHub Pages 地址，例如 `https://用户名.github.io/仓库名`。
5. 打开 Actions，手动运行一次 `Daily technology news` 验证；之后每天北京时间 09:00 自动执行。

Webhook 和 Bark 地址都是密钥，不要写入配置文件或提交到 Git。

### DeepSeek AI 分析

添加 `DEEPSEEK_API_KEY` 后，程序会根据新闻类型动态生成核心事实、技术亮点、落地价值、对比判断、待验证事项和一句话点评。默认分析重要度最高的 20 条；可通过仓库变量调整：

- `DEEPSEEK_MODEL`：默认 `deepseek-v4-flash`。
- `AI_MAX_ARTICLES`：默认 `20`，数值越大调用量越高。

如果 DeepSeek 暂时不可用、余额不足或返回异常，程序会记录失败原因并自动退回规则版日报，Bark 推送不会因此中断。

每天生成 `public/report_YYYYMMDD.html`，同时更新 `public/index.html`。单个来源失败只会进入日报底部的异常清单，不会阻断其他来源。
