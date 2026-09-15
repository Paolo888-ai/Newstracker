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

LESSON_CORE = {
    "收入、利润与现金流的区别": "收入是卖出商品或服务形成的经营成果，利润是收入扣除成本费用后的会计结果，现金流则记录钱何时真正收进或付出。三者时间点不同，所以赚钱的公司也可能没现金。",
    "资产负债表在讲什么": "资产负债表是一张时点照片，恒等式是资产＝负债＋所有者权益。左边说明公司控制什么资源，右边说明这些资源的钱来自债权人还是股东。",
    "利润表与毛利率": "利润表记录一段期间的收入、成本和费用；毛利率＝（收入－直接成本）÷收入，用来观察产品本身留下多少空间支付运营费用并形成利润。",
    "现金流量表与企业生存": "现金流量表把现金变化分为经营、投资和融资活动。企业短期生存依靠可用现金，而不是账面利润；经营现金流持续为负通常需要外部融资补足。",
    "固定成本、变动成本与盈亏平衡点": "固定成本不随短期销量明显变化，变动成本随每份产品增加。盈亏平衡销量＝固定成本÷单件贡献毛利，表示至少卖多少才不亏。",
    "毛利率、净利率和贡献毛利": "毛利率看产品扣除直接成本后的空间，净利率看所有成本费用后的最终利润，贡献毛利用售价减单位变动成本，常用于定价和盈亏平衡分析。",
    "应收账款、账期与坏账风险": "应收账款是已经确认收入但尚未收到的钱。账期越长，占用的营运资金越多；客户不能付款时，账面收入还会转化为坏账损失。",
    "库存周转率为什么重要": "库存周转衡量货物变成销售的速度。周转太慢会占用现金、增加仓储和跌价风险；太快也可能意味着备货不足、错失订单。",
    "商业模式与价值创造": "商业模式回答为谁解决什么问题、如何交付价值以及如何收钱。好产品不等于好生意，收入结构、成本结构和重复购买共同决定生意能否持续。",
    "规模经济与边际成本": "规模经济指产量扩大后平均成本下降；边际成本是多生产一单位增加的成本。软件复制成本低，工厂则可能在产能饱和后边际成本重新上升。",
    "定价权从哪里来": "定价权来自客户难以替代、转换成本高、品牌信任、稀缺资源或显著差异化。能涨价不等于有定价权，涨价后仍能保住需求和利润才算。",
    "客户终身价值与获客成本": "客户终身价值估算一位客户在合作期贡献的毛利，获客成本是获得该客户投入的销售和营销费用。只有前者稳定高于后者，增长才可能创造价值。",
    "护城河与竞争优势": "护城河是竞争者难以复制并能长期保护超额收益的结构，例如网络效应、成本优势、品牌、专利或转换成本。短期领先和高增速本身不是护城河。",
    "网络效应与平台生意": "网络效应是用户增加会提升其他用户获得的价值。平台要同时处理多方供需、冷启动和治理；用户多但彼此没有增益，只能算规模，不算网络效应。",
    "股权、表决权与分红权": "股权是一组权利，通常包括表决、分红和剩余财产分配，但三者可以通过章程或不同类别股份进行差异化安排，持股比例不总是等同于控制力。",
    "创始团队如何讨论股权分配": "股权分配应综合早期投入、未来全职贡献、关键能力、承担风险和可替代性，并用归属期处理承诺未兑现的问题，而不是只按最初想法一次分完。",
    "股权稀释是怎么发生的": "公司增发新股融资或建立期权池时，原股东持股比例会下降。稀释不一定是损失：如果新资金让公司价值增长得更快，较小比例可能对应更高价值。",
    "期权池、归属期与离职回购": "期权池用于激励员工；归属期让权益随服务时间逐步获得；离职回购处理未归属或约定可回购的权益，三者共同减少员工提前离开却长期占股的问题。",
    "董事会、股东会与管理层的关系": "股东会决定所有者层面的重大事项，董事会负责战略监督和任免管理层，管理层负责日常经营。具体权限取决于当地法律、章程和授权安排。",
    "控股、实际控制人与一致行动人": "控股看持股或表决权优势，实际控制看谁能实质支配重大决策，一致行动人则通过协议或共同安排协同行使权利；三者可能重合，也可能不同。",
    "关联交易与利益冲突": "关联交易发生在存在控制、亲属或重大影响关系的主体之间。它不天然违法，但需要公允定价、充分披露和适当审批，否则可能把公司利益转移给特定个人。",
    "委托代理问题与激励机制": "出资人把经营交给管理者后，双方目标和信息可能不一致。监督、绩效薪酬、长期股权和问责机制用于降低代理成本，但错误指标也会诱发短视行为。",
    "融资估值与投资人回报": "融资估值决定投资人用多少钱换多少股权；投资回报还取决于退出价格、稀释、优先权和持有时间，融资时的高估值并不自动等于最终高回报。",
    "投前估值、投后估值与融资比例": "投后估值＝投前估值＋本轮投资额；新投资人的持股比例通常约等于投资额÷投后估值。还需注意期权池是否在投前扩充，因为它会影响谁承担稀释。",
    "清算优先权对创始人的影响": "清算优先权决定公司出售或清算时投资人是否先收回约定金额。退出价格不高时，它可能让普通股股东即使持有股份也分不到按比例计算的金额。",
    "债权融资与股权融资的取舍": "债权融资通常不稀释控制权，但需要还本付息并承受现金流压力；股权融资无需固定偿还，却让渡部分未来收益和治理权，选择取决于风险与现金流稳定性。",
    "合法税务筹划与逃税的边界": "税务筹划是在真实交易、完整凭证和法律允许的选择中安排业务；逃税则通过隐瞒收入、虚假交易或伪造资料减少税款。经济实质和如实申报是关键边界。",
    "增值税、企业所得税与个人所得税": "增值税主要围绕交易增值和进销项，企业所得税针对企业应纳税所得额，个人所得税针对个人取得的不同类型所得；纳税主体和计税基础并不相同。",
    "合同中的付款、违约与终止条款": "付款条款决定何时收钱，违约条款分配未履约成本，终止条款说明合作如何结束。只写合作内容却不写失败时怎么办，会把最大风险留到争议发生后。",
    "有限责任并不等于没有个人风险": "有限责任通常把股东损失限制在出资范围，但个人担保、抽逃出资、财产混同、违法行为或董事高管失职仍可能带来个人责任，具体规则取决于当地法律。",
    "机会成本与沉没成本": "机会成本是选择一个方案时放弃的最佳替代收益；沉没成本是已经发生且无法收回的投入。理性决策应比较未来增量收益与成本，而不是被过去投入绑架。",
    "信息不对称与逆向选择": "交易双方掌握的信息不同，会让高风险或低质量一方更愿意进入交易，形成逆向选择。认证、担保、审计、试用和分阶段付款可降低这种风险。",
    "复利、折现与货币时间价值": "复利让本金和已产生收益继续增长；折现把未来现金换算成今天的价值。时间、风险和可替代回报决定折现率，因此未来一百元通常不等于今天一百元。",
    "ROE、ROA与资本效率": "ROE衡量净利润相对股东权益，ROA衡量净利润相对总资产。高ROE可能来自经营优秀，也可能来自高负债，因此要结合利润率、周转率和杠杆一起看。",
    "为什么增长可能让公司更缺钱": "增长往往要求先采购、备货、招人或给予客户账期，现金先流出、收入和回款后发生。增长越快，营运资金缺口可能越大，即使利润表显示盈利。",
    "预算、预测与滚动复盘": "预算表达目标和资源承诺，预测基于最新信息估计结果，滚动复盘持续比较实际与预期并调整行动。把预算当预测，会让团队为了守数字而忽略现实变化。"
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


def lesson_fallback(topic: dict) -> dict:
    title = topic["topic"]
    core = LESSON_CORE.get(title, f"{title}是理解企业如何创造价值、分配收益和承担风险的一项基础概念。")
    if any(word in title for word in ("股权", "估值", "融资", "期权", "控制", "董事会", "股东会", "清算")):
        example = "甲乙创办公司，最初各持股60%和40%。公司融资200万元、投后估值1000万元，新投资人取得20%，甲乙分别稀释为48%和32%。比例下降，但若资金令公司价值增长，持股价值仍可能上升。"
        question = "为什么持股比例下降，不一定代表股东的经济利益减少？"
        answer = "先比较融资前后的持股价值，而不只看比例。若融资前公司值800万元，甲的60%值480万元；融资后投后估值1000万元，甲的48%仍值480万元。此后资金若推动估值上涨，甲的价值还会增加；但其表决影响力确实可能下降。"
    elif any(word in title for word in ("收入", "利润", "现金", "成本", "毛利", "应收", "库存", "ROE", "ROA", "复利", "折现", "预算")):
        example = "一家小店本月销售10万元，其中4万元尚未收款；商品成本4万元、工资租金3万元，并支付上月货款2万元。账面利润约3万元，但本月实际现金净增加可能只有1万元，说明利润和现金不是同一件事。"
        question = "这家公司明明有利润，为什么仍可能出现资金紧张？"
        answer = "利润按收入和成本的归属期计算，现金按实际收付计算。4万元应收账款还没到账，同时上月货款已经支付；若还要提前备货或偿还贷款，可用现金会进一步减少。因此需要同时看利润、回款速度和付款时间。"
    elif "税" in title:
        example = "公司选择法律明确允许的税收优惠，并保留真实合同、发票和业务记录，属于合规安排；如果虚构咨询合同把利润转走，交易没有真实服务和商业目的，就可能构成违法逃税。"
        question = "判断一项税务安排是否合法，最先应检查什么？"
        answer = "先检查交易是否真实、是否有合理商业目的、合同资金和发票是否一致，再核对当地法律是否允许相应优惠并如实申报。仅仅因为税负降低并不违法，但虚构业务、隐瞒收入和伪造凭证明显越界；具体方案应咨询持证税务专业人士。"
    else:
        example = "假设一家公司有两个方案：方案A能立即增加销量，但需要更长账期；方案B销量增长较慢，却能即时回款。判断时不能只看收入，还要比较毛利、现金占用、控制权和最坏情况下的损失。"
        question = "面对两个看似都能增长的方案，应该比较哪些利益和风险？"
        answer = "至少比较客户价值、毛利、现金回收时间、前期投入、失败损失和可逆性，再明确收益归谁、成本由谁承担。增长数字相同，现金占用和风险结构可能完全不同，因此不能只选收入更高的方案。"
    return {
        "title": title,
        "category": topic["category"],
        "summary": core[:90],
        "sections": [
            f"核心概念：{core}",
            "为什么重要：这个概念能帮助你判断企业表面的增长或利润，是否真正转化为可持续的价值和可控风险。",
            "分析方法：先找出参与者，再分别写出钱从哪里来、流向哪里，谁拥有决策权，谁获得收益，以及最坏结果由谁承担。",
            "常见误区：只看一个比例或结果数字，而忽略发生时间、交易条件、现金流和各方权利。"
        ],
        "example": example,
        "question": question,
        "answer": answer,
        "disclaimer": "学习内容仅作通识教育，不构成法律、税务、投资或会计意见。"
    }


def parse_json_object(content: str) -> dict:
    text = (content or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.I)
        text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start >= 0 and end > start:
            return json.loads(text[start:end + 1])
        raise


def generate_business_lesson(now: datetime, failures: list[dict]) -> dict:
    topics_path = ROOT / "config" / "business_lessons.json"
    topics = json.loads(topics_path.read_text(encoding="utf-8"))
    local_date = now.astimezone(TZ).date()
    topic = topics[local_date.toordinal() % len(topics)]
    fallback = lesson_fallback(topic)
    api_key = os.getenv("DEEPSEEK_API_KEY")
    if not api_key:
        return fallback

    system = """你是一位严谨、善于举例的商业通识老师，面向没有系统学过商业和财务的成年人。请围绕指定主题生成一节5分钟微课，并输出合法json。
要求：用通俗中文解释，但保留必要术语；案例必须是虚构、简单、数字可核算；明确人物之间的钱、权利、责任和风险；不假定读者已有专业知识；不提供个性化投资建议。
涉及税务时，只讲合法合规的税务筹划、基本原理和风险边界，绝不提供隐瞒收入、虚假交易、伪造凭证等逃税方法。涉及法律、会计或投资时必须提示各地规则可能不同，应咨询持证专业人士。
思考题必须能够根据本节内容推导；answer必须给出参考解答，展示2至4步推理。财务主题尽量给出计算过程；股权、治理或利益关系主题要说明谁受益、谁承担成本和风险。
返回格式：{"title":"...","category":"...","summary":"不超过70字","sections":["核心概念：...","为什么重要：...","利益关系：...","常见误区：..."],"example":"一个具体的数字案例，不超过220字","question":"一个思考题","answer":"参考解答或补充案例，不超过260字","disclaimer":"..."}。sections必须为3至5项。"""
    last_error: Exception | None = None
    for attempt in range(1, 4):
        try:
            response = requests.post(
                "https://api.deepseek.com/chat/completions",
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json={
                    "model": os.getenv("DEEPSEEK_MODEL") or "deepseek-v4-flash",
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": f"今天的主题：{topic['topic']}；课程分类：{topic['category']}。这是第{attempt}次生成，请只返回完整json对象。"}
                    ],
                    "response_format": {"type": "json_object"},
                    "temperature": 0.25,
                    "max_tokens": 3200
                },
                timeout=120
            )
            response.raise_for_status()
            choice = response.json()["choices"][0]
            if choice.get("finish_reason") == "length":
                raise ValueError("课程输出被截断")
            result = parse_json_object(choice["message"]["content"])
            sections = [clean_text(str(value)) for value in result.get("sections", []) if clean_text(str(value))]
            title = clean_text(str(result.get("title", "")))
            example = clean_text(str(result.get("example", "")))
            question = clean_text(str(result.get("question", "")))
            answer = clean_text(str(result.get("answer", "")))
            if not title or not 3 <= len(sections) <= 5 or not example or not question or not answer:
                raise ValueError("课程返回结构不完整")
            return {
                "title": title,
                "category": clean_text(str(result.get("category", topic["category"]))) or topic["category"],
                "summary": clean_text(str(result.get("summary", "")))[:180],
                "sections": sections,
                "example": example,
                "question": question,
                "answer": answer,
                "disclaimer": clean_text(str(result.get("disclaimer", fallback["disclaimer"]))) or fallback["disclaimer"]
            }
        except Exception as exc:
            last_error = exc
            print(f"Business lesson attempt {attempt}/3 failed: {type(exc).__name__}", flush=True)

    failures.append({"source": "每日商业课", "reason": f"连续3次生成失败（{type(last_error).__name__}: {str(last_error)[:220]}）；已使用完整本地课程"})
    return fallback


def build_report(items: list[Article], sources: list[dict], failures: list[dict], now: datetime, lesson: dict) -> dict:
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
        "business_lesson": lesson,
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
    lesson = report.get("business_lesson", {})
    lesson_text = f"今日商业课：{lesson.get('title')}\n\n" if lesson.get("title") else ""
    link_text = f"\n完整日报：{public_url}" if public_url else "\n完整日报已生成，请查看运行产物。"
    message = f"{report['title']}｜{report['date']}\n\n{lesson_text}{digest}{link_text}"

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
    lesson = generate_business_lesson(now, failures)
    report = build_report(articles, sources, failures, now, lesson)
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
