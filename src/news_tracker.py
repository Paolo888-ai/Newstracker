from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher
from pathlib import Path
from urllib.parse import urljoin, urlparse, urlunparse

import feedparser
import requests
from bs4 import BeautifulSoup
from dateutil import parser as date_parser

from generate_report import render_report


ROOT = Path(__file__).resolve().parents[1]
TZ = timezone(timedelta(hours=8))
UA = "NewsTracker/1.0 (+personal daily digest)"
DOMAINS = {
    "AI": ["ai", "人工智能", "大模型", "模型", "agent", "智能体", "openai", "deepseek", "llm", "机器学习"],
    "芯片与硬件": ["芯片", "半导体", "gpu", "nvidia", "英伟达", "算力", "硬件", "处理器", "服务器"],
    "机器人与具身": ["机器人", "具身", "自动驾驶", "robot", "humanoid", "无人机", "自动化"],
    "科技商业与创投": ["融资", "估值", "ipo", "收购", "投资", "创业", "财报", "商业", "公司"],
    "效率与数码生活": ["iphone", "ipad", "mac", "软件", "应用", "工具", "数码", "效率", "手机"]
}


@dataclass
class Article:
    title: str
    url: str
    source: str
    published: datetime
    summary: str = ""
    approximate_date: bool = False
    ai_analysis: list[str] | None = None
    ai_verdict: str | None = None
    ai_category: str | None = None
    ai_importance: int | None = None

    def output(self) -> dict:
        summary = clean_text(self.summary) or "原文未提供摘要，请点击链接查看详情。"
        return {
            "title": self.title,
            "url": self.url,
            "source": self.source,
            "published_at": self.published.astimezone(TZ).strftime("%Y-%m-%d %H:%M") + ("（时间近似）" if self.approximate_date else ""),
            "summary": summary[:220],
            "analysis": self.ai_analysis or [f"内容摘要：{summary[:500]}", "信息核验：以上内容来自原始页面的标题与摘要，重要结论请以原文为准。"],
            "verdict": self.ai_verdict or "阅读建议：点击原文查看完整上下文。"
        }


def clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", BeautifulSoup(value or "", "html.parser").get_text(" ")).strip()


def looks_mojibake(value: str) -> bool:
    """Detect common UTF-8 text decoded as a legacy single-byte encoding."""
    text = value or ""
    markers = ("ďź", "ĺ", "č", "ć", "ä¸", "çš", "â€", "Ã", "Â", "�")
    return sum(text.count(marker) for marker in markers) >= 2


def canonical_url(value: str) -> str:
    parsed = urlparse(value)
    return urlunparse((parsed.scheme, parsed.netloc.lower(), parsed.path.rstrip("/"), "", "", ""))


def parse_date(value: object) -> datetime | None:
    if not value:
        return None
    try:
        result = date_parser.parse(str(value))
        if result.tzinfo is None:
            result = result.replace(tzinfo=TZ)
        return result.astimezone(timezone.utc)
    except (ValueError, TypeError, OverflowError):
        return None


def get(url: str) -> requests.Response:
    response = requests.get(url, headers={"User-Agent": UA, "Accept-Language": "zh-CN,zh;q=.9,en;q=.7"}, timeout=25)
    response.raise_for_status()
    requested_host = urlparse(url).hostname or ""
    final_host = urlparse(response.url).hostname or ""
    requested_root = ".".join(requested_host.split(".")[-2:])
    final_root = ".".join(final_host.split(".")[-2:])
    if requested_root and final_root and requested_root != final_root:
        raise RuntimeError(f"站点重定向到了非预期域名 {final_host}")
    return response


def discover_feed(page_url: str, soup: BeautifulSoup) -> str | None:
    for link in soup.select('link[rel="alternate"]'):
        kind = (link.get("type") or "").lower()
        if "rss" in kind or "atom" in kind:
            return urljoin(page_url, link.get("href", ""))
    return None


def from_feed(source: dict, feed_url: str, now: datetime, cutoff: datetime) -> list[Article]:
    raw = get(feed_url).content
    feed = feedparser.parse(raw)
    sample = " ".join(str(entry.get("title", "")) for entry in feed.entries[:10])
    # Some feeds claim UTF-8 but contain one malformed byte. feedparser then
    # falls back to a legacy encoding and corrupts every Chinese title. Decode
    # the bytes as UTF-8 with local replacement so only the bad byte is lost.
    if looks_mojibake(sample) or str(feed.get("encoding", "")).lower() not in ("utf-8", "utf-8-sig"):
        repaired = feedparser.parse(raw.decode("utf-8", errors="replace"))
        repaired_sample = " ".join(str(entry.get("title", "")) for entry in repaired.entries[:10])
        if repaired.entries and not looks_mojibake(repaired_sample):
            feed = repaired
    if feed.bozo and not feed.entries:
        raise RuntimeError(f"Feed 无法解析: {feed.bozo_exception}")
    items = []
    for entry in feed.entries[:30]:
        published = parse_date(entry.get("published") or entry.get("updated"))
        if not published or not cutoff <= published <= now + timedelta(hours=2):
            continue
        title = clean_text(entry.get("title", ""))
        summary = clean_text(entry.get("summary", ""))
        url = canonical_url(entry.get("link", ""))
        if title and url and not looks_mojibake(title):
            if looks_mojibake(summary):
                summary = ""
            items.append(Article(title, url, source["name"], published, summary))
    return items


def page_candidates(source: dict, page_url: str, soup: BeautifulSoup, now: datetime) -> list[Article]:
    host = urlparse(page_url).netloc
    seen, items = set(), []
    selectors = "article a[href], main a[href], h1 a[href], h2 a[href], h3 a[href]"
    for anchor in soup.select(selectors):
        title = clean_text(anchor.get_text(" "))
        url = canonical_url(urljoin(page_url, anchor.get("href", "")))
        if len(title) < 12 or len(title) > 160 or urlparse(url).netloc != host or url in seen:
            continue
        if re.search(r"/(tag|topic|category|author|about|login)(/|$)", url, re.I):
            continue
        seen.add(url)
        items.append(Article(title, url, source["name"], now, "", True))
        if len(items) >= 12:
            break
    return items


def fetch_source(source: dict, now: datetime, cutoff: datetime) -> tuple[list[Article], str | None]:
    errors = []
    for page_url in [source["url"], source.get("fallback_url")]:
        if not page_url:
            continue
        try:
            response = get(page_url)
            soup = BeautifulSoup(response.text, "html.parser")
            feed_url = source.get("feed_url") or discover_feed(response.url, soup)
            if feed_url:
                return from_feed(source, feed_url, now, cutoff), None
            return page_candidates(source, response.url, soup, now), "未发现 RSS，按首页排序近似选取"
        except Exception as exc:  # keep other sources running
            errors.append(f"{type(exc).__name__}: {exc}")
    return [], "；".join(errors)[:400]


def dedupe(items: list[Article]) -> list[Article]:
    result = []
    for item in sorted(items, key=lambda x: x.published, reverse=True):
        normalized = re.sub(r"[^\w\u4e00-\u9fff]", "", item.title.lower())
        duplicate = False
        for existing in result:
            other = re.sub(r"[^\w\u4e00-\u9fff]", "", existing.title.lower())
            if item.url == existing.url or SequenceMatcher(None, normalized, other).ratio() >= .82:
                duplicate = True
                break
        if not duplicate:
            result.append(item)
    return result


def category(item: Article) -> str:
    if item.ai_category in DOMAINS:
        return item.ai_category
    text = f"{item.title} {item.summary}".lower()
    scores = {name: sum(1 for word in words if word in text) for name, words in DOMAINS.items()}
    return max(scores, key=scores.get) if max(scores.values()) else "科技商业与创投"


def importance(item: Article) -> int:
    if item.ai_importance is not None:
        return item.ai_importance
    text = f"{item.title} {item.summary}".lower()
    score = sum(2 for word in ("发布", "首发", "突破", "融资", "收购", "launch", "release", "research") if word in text)
    score += sum(1 for words in DOMAINS.values() for word in words if word in text)
    return score


def deepseek_request(api_key: str, articles: list[Article], model: str) -> list[dict]:
    records = [{
        "id": hashlib.sha256(item.url.encode()).hexdigest()[:12],
        "title": item.title,
        "source": item.source,
        "published_at": item.published.astimezone(TZ).isoformat(),
        "source_summary": clean_text(item.summary)[:1200]
    } for item in articles]
    system = """你是严谨的科技新闻编辑。只能依据用户提供的标题和来源摘要分析，不得补写材料中未出现的数字、人物、日期、性能或背景事实。输出必须是合法 json。
对每条新闻动态选择3至5个最适合的维度，例如：核心事实、技术亮点、务实落地、价值判断、上下文对比、信号意义、疑问解答、待验证事项、用户影响。不要机械地使用相同标签。
明确区分事实、媒体或厂商声称、分析判断。材料不足时写“原始摘要未提供”。一句话点评可以鲜明，但不得制造事实、政治动机或因果关系。
category只能是：AI、芯片与硬件、机器人与具身、科技商业与创投、效率与数码生活。importance是0至100整数。summary不超过90个汉字。analysis是字符串数组，每项格式为“标签：内容”。verdict不超过100个汉字。
返回格式：{"articles":[{"id":"...","summary":"...","category":"AI","importance":80,"analysis":["核心事实：..."],"verdict":"..."}]}。"""
    response = requests.post(
        "https://api.deepseek.com/chat/completions",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json={
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": "分析以下新闻并返回 json：\n" + json.dumps(records, ensure_ascii=False)}
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0.2,
            "max_tokens": 7000
        },
        timeout=120
    )
    response.raise_for_status()
    content = response.json()["choices"][0]["message"]["content"]
    return json.loads(content).get("articles", [])


def apply_ai_analysis(items: list[Article], failures: list[dict]) -> None:
    api_key = os.getenv("DEEPSEEK_API_KEY")
    if not api_key:
        print("DEEPSEEK_API_KEY not set; using rule-based summaries", flush=True)
        return
    model = os.getenv("DEEPSEEK_MODEL") or "deepseek-v4-flash"
    limit = max(1, int(os.getenv("AI_MAX_ARTICLES") or "20"))
    candidates = sorted(items, key=importance, reverse=True)[:limit]
    by_id = {hashlib.sha256(item.url.encode()).hexdigest()[:12]: item for item in candidates}
    try:
        for start in range(0, len(candidates), 5):
            batch = candidates[start:start + 5]
            print(f"DeepSeek analysis {start + 1}-{start + len(batch)} / {len(candidates)}...", flush=True)
            for result in deepseek_request(api_key, batch, model):
                item = by_id.get(str(result.get("id", "")))
                if not item:
                    continue
                summary = clean_text(str(result.get("summary", "")))
                analysis = [clean_text(str(value)) for value in result.get("analysis", []) if clean_text(str(value))]
                verdict = clean_text(str(result.get("verdict", "")))
                category_name = str(result.get("category", ""))
                try:
                    score = min(100, max(0, int(result.get("importance", 0))))
                except (TypeError, ValueError):
                    score = None
                if summary:
                    item.summary = summary
                if analysis:
                    item.ai_analysis = analysis[:5]
                if verdict:
                    item.ai_verdict = verdict
                if category_name in DOMAINS:
                    item.ai_category = category_name
                item.ai_importance = score
    except Exception as exc:
        failures.append({"source": "DeepSeek AI 分析", "reason": f"{type(exc).__name__}: {str(exc)[:300]}；已回退到规则摘要"})


def build_report(items: list[Article], sources: list[dict], failures: list[dict], now: datetime) -> dict:
    grouped = {name: [] for name in DOMAINS}
    for item in items:
        grouped[category(item)].append(item.output())
    highlights = sorted(items, key=importance, reverse=True)[:10]
    return {
        "title": "科技 / AI 资讯日报",
        "date": now.astimezone(TZ).strftime("%Y-%m-%d"),
        "subtitle": "过去 24 小时 · 自动去重 · 按重要度筛选",
        "generated_at": now.astimezone(TZ).strftime("%Y-%m-%d %H:%M Asia/Shanghai"),
        "stats": {"articles": len(items), "sources": len(sources)},
        "highlights": [item.output() for item in highlights],
        "domains": [{"name": name, "description": " / ".join(words[:3]), "articles": grouped[name]} for name, words in DOMAINS.items()],
        "failures": failures
    }


def post_json(url: str, payload: dict) -> dict:
    response = requests.post(url, json=payload, timeout=20)
    response.raise_for_status()
    return response.json() if response.content else {}


def notify(report: dict, public_url: str | None, failures: list[dict]) -> None:
    points = report["highlights"][:8]
    digest = "\n".join(f"{i}. {item['title']}（{item['source']}）" for i, item in enumerate(points, 1))
    link_text = f"\n完整日报：{public_url}" if public_url else "\n完整日报已生成，请查看运行产物。"
    message = f"{report['title']}｜{report['date']}\n\n{digest}{link_text}"

    bark_url = os.getenv("BARK_URL")
    if bark_url:
        try:
            post_json(bark_url, {"title": f"科技 / AI 日报 · {report['date']}", "body": message[:3500], "url": public_url or "", "group": "NewsTracker"})
        except Exception as exc:
            failures.append({"source": "Bark 推送", "reason": str(exc)[:300]})

    feishu = os.getenv("FEISHU_WEBHOOK")
    if feishu:
        try:
            result = post_json(feishu, {"msg_type": "text", "content": {"text": message[:15000]}})
            if result.get("code", 0) != 0:
                failures.append({"source": "飞书推送", "reason": json.dumps(result, ensure_ascii=False)[:300]})
        except Exception as exc:
            failures.append({"source": "飞书推送", "reason": str(exc)[:300]})


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sources", type=Path, default=ROOT / "config" / "sources.json")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "public")
    parser.add_argument("--hours", type=int, default=24)
    parser.add_argument("--no-notify", action="store_true")
    args = parser.parse_args()

    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=args.hours)
    sources = json.loads(args.sources.read_text(encoding="utf-8"))
    articles, failures = [], []
    for source in sources:
        print(f"Fetching {source['name']}...", flush=True)
        found, warning = fetch_source(source, now, cutoff)
        articles.extend(found)
        if warning:
            failures.append({"source": source["name"], "reason": warning})

    articles = dedupe(articles)
    apply_ai_analysis(articles, failures)
    report = build_report(articles, sources, failures, now)
    date_key = now.astimezone(TZ).strftime("%Y%m%d")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    json_path = args.output_dir / f"report_{date_key}.json"
    html_path = args.output_dir / f"report_{date_key}.html"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    template = (ROOT / "templates" / "report.html").read_text(encoding="utf-8")
    html_path.write_text(render_report(report, template), encoding="utf-8")
    shutil.copyfile(html_path, args.output_dir / "index.html")

    base = os.getenv("REPORT_BASE_URL", "").rstrip("/")
    public_url = f"{base}/report_{date_key}.html" if base else None
    if not args.no_notify:
        notify(report, public_url, failures)
        if len(failures) != len(report["failures"]):
            report["failures"] = failures
            json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            html_path.write_text(render_report(report, template), encoding="utf-8")
            shutil.copyfile(html_path, args.output_dir / "index.html")
    print(f"Generated {html_path} with {len(articles)} articles")


if __name__ == "__main__":
    main()
