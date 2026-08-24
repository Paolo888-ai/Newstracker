from __future__ import annotations

import argparse
import html
import json
from pathlib import Path
from string import Template


ROOT = Path(__file__).resolve().parents[1]


def esc(value: object) -> str:
    return html.escape(str(value or ""), quote=True)


def render_article(article: dict) -> str:
    rendered = []
    for paragraph in article.get("analysis", []):
        label, separator, content = str(paragraph).partition("：")
        if separator and len(label) <= 8:
            rendered.append(f'<p><span class="analysis-label">{esc(label)}：</span>{esc(content)}</p>')
        else:
            rendered.append(f"<p>{esc(paragraph)}</p>")
    analysis = "".join(rendered)
    verdict = article.get("verdict")
    if verdict:
        analysis += f'<p class="verdict">{esc(verdict)}</p>'
    return f"""
    <article class="card" data-card tabindex="0">
      <h3 class="card-title">{esc(article.get('title'))}</h3>
      <p class="card-summary">{esc(article.get('summary'))}</p>
      <div class="card-meta">
        <span class="source">{esc(article.get('source'))}</span>
        <time>{esc(article.get('published_at'))}</time>
        <a class="link-btn" href="{esc(article.get('url'))}" target="_blank" rel="noopener noreferrer">原文 →</a>
      </div>
      <div class="card-body"><div class="deep-analysis">{analysis}</div></div>
    </article>"""


def render_domain(domain: dict, index: int) -> str:
    articles = "".join(render_article(item) for item in domain.get("articles", []))
    open_class = " open" if index == 0 else ""
    return f"""
    <section class="domain-section{open_class}" data-domain>
      <button class="domain-header" type="button" data-domain-toggle aria-expanded="{'true' if index == 0 else 'false'}">
        <span class="domain-title">{esc(domain.get('name'))}<small>{esc(domain.get('description'))}</small></span>
        <span class="domain-actions"><span class="count">{len(domain.get('articles', []))} 篇</span><span class="arrow">▼</span></span>
      </button>
      <div class="domain-body">{articles}</div>
    </section>"""


def render_lesson(lesson: dict) -> str:
    if not lesson:
        return ""
    sections = []
    for value in lesson.get("sections", []):
        label, separator, content = str(value).partition("：")
        if separator:
            sections.append(f'<p><span class="lesson-label">{esc(label)}：</span>{esc(content)}</p>')
        else:
            sections.append(f"<p>{esc(value)}</p>")
    example = f'<div class="lesson-box"><strong>举个例子</strong><p>{esc(lesson.get("example"))}</p></div>' if lesson.get("example") else ""
    question = f'<div class="lesson-question"><strong>想一想</strong><p>{esc(lesson.get("question"))}</p></div>' if lesson.get("question") else ""
    return f"""
    <article class="lesson-card">
      <div class="lesson-topline"><span class="lesson-category">{esc(lesson.get('category'))}</span><span>约 5 分钟</span></div>
      <h3>{esc(lesson.get('title'))}</h3>
      <p class="lesson-summary">{esc(lesson.get('summary'))}</p>
      <div class="lesson-content">{''.join(sections)}{example}{question}</div>
      <p class="lesson-disclaimer">{esc(lesson.get('disclaimer'))}</p>
    </article>"""


def render_report(data: dict, template_text: str) -> str:
    highlights = "".join(render_article(item) for item in data.get("highlights", []))
    domains = "".join(render_domain(item, index) for index, item in enumerate(data.get("domains", [])))
    failures = "".join(
        f'<li><strong>{esc(item.get("source"))}</strong>{esc(item.get("reason"))}</li>'
        for item in data.get("failures", [])
    )
    stats = data.get("stats", {})
    values = {
        "title": esc(data.get("title", "每日新闻简报")),
        "date": esc(data.get("date")),
        "subtitle": esc(data.get("subtitle", "过去 24 小时")),
        "article_count": esc(stats.get("articles", 0)),
        "domain_count": esc(len(data.get("domains", []))),
        "source_count": esc(stats.get("sources", 0)),
        "failure_count": esc(len(data.get("failures", []))),
        "business_lesson": render_lesson(data.get("business_lesson", {})),
        "highlights": highlights,
        "domains": domains,
        "failures": failures,
        "generated_at": esc(data.get("generated_at", "")),
    }
    return Template(template_text).safe_substitute(values)


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate the daily NewsTracker report")
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--template", type=Path, default=ROOT / "templates" / "report.html")
    args = parser.parse_args()

    data = json.loads(args.input.read_text(encoding="utf-8"))
    result = render_report(data, args.template.read_text(encoding="utf-8"))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(result, encoding="utf-8")
    print(f"Generated {args.output}")


if __name__ == "__main__":
    main()
