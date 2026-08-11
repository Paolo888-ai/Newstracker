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

    def output(self) -> dict:
        summary = clean_text(self.summary) or "原文未提供摘要，请点击链接查看详情。"
        return {
            "title": self.title,
            "url": self.url,
            "source": self.source,
            "published_at": self.published.astimezone(TZ).strftime("%Y-%m-%d %H:%M") + ("（时间近似）" if self.approximate_date else ""),
            "summary": summary[:220],
            "analysis": [f"内容摘要：{summary[:500]}", "信息核验：以上内容来自原始页面的标题与摘要，重要结论请以原文为准。"],
            "verdict": "阅读建议：点击原文查看完整上下文。"
        }


def clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", BeautifulSoup(value or "", "html.parser").get_text(" ")).strip()


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
    if feed.bozo and not feed.entries:
        raise RuntimeError(f"Feed 无法解析: {feed.bozo_exception}")
    items = []
    for entry in feed.entries[:30]:
        published = parse_date(entry.get("published") or entry.get("updated"))
        if not published or not cutoff <= published <= now + timedelta(hours=2):
            continue
        title = clean_text(entry.get("title", ""))
        url = canonical_url(entry.get("link", ""))
        if title and url:
            items.append(Article(title, url, source["name"], published, entry.get("summary", "")))
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
    text = f"{item.title} {item.summary}".lower()
    scores = {name: sum(1 for word in words if word in text) for name, words in DOMAINS.items()}
    return max(scores, key=scores.get) if max(scores.values()) else "科技商业与创投"


def importance(item: Article) -> int:
    text = f"{item.title} {item.summary}".lower()
    score = sum(2 for word in ("发布", "首发", "突破", "融资", "收购", "launch", "release", "research") if word in text)
    score += sum(1 for words in DOMAINS.values() for word in words if word in text)
    return score


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
