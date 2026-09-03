# NewsTracker

每天自动收集、筛选并生成适合手机阅读的科技 / AI 日报。

页面深色主题、统计卡片、今日要点、领域折叠、文章深度解析及异常源清单。程序配置了 18 个中英文科技信息源，默认抓取最近 24 小时，并在每天北京时间 09:00 由 GitHub Actions 自动运行。

日报顶部包含一节约 5 分钟的“每日商业课”。课程按照商业、财务、股权、公司治理、融资、税务合规、合同与决策思维等主题循环，每天生成概念解释、数字案例、常见误区和思考题。课程仅用于通识学习，不构成法律、税务、投资或会计意见。

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


