#!/usr/bin/env python3
"""Fetch, filter, summarize, and email a daily Twitter/X report.

The script intentionally uses only the Python standard library so it can run in
minimal automation environments. It expects an Apify token and a Twitter/X
cookie for the actor `automation-lab/twitter-scraper`.
"""

from __future__ import annotations

import argparse
import html
import json
import os
import re
import smtplib
import sys
import time
import urllib.error
import urllib.request
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, datetime, time as dt_time, timedelta, timezone
from email.message import EmailMessage
from email.utils import parsedate_to_datetime
from typing import Any
from zoneinfo import ZoneInfo


DEFAULT_ACCOUNTS = [
    "@aleabitoreddit",
    "@justinsuntron",
    "@wufantouzi",
    "@sunyuchentron",
    "@elonmusk",
    "@readDonaldTrump",
]
DEFAULT_TIMEZONE = "Asia/Shanghai"
DEFAULT_ACTOR = "automation-lab~twitter-scraper"
DEFAULT_MAX_RESULTS_PER_ACCOUNT = 200

TOPIC_KEYWORDS = {
    "ai": "AI / 模型 / 算力",
    "artificial intelligence": "AI / 模型 / 算力",
    "llm": "AI / 模型 / 算力",
    "model": "AI / 模型 / 算力",
    "grok": "AI / 模型 / 算力",
    "xai": "AI / 模型 / 算力",
    "openai": "AI / 模型 / 算力",
    "anthropic": "AI / 模型 / 算力",
    "nvidia": "AI / 模型 / 算力",
    "gpu": "AI / 模型 / 算力",
    "api": "软件 / 开发者生态",
    "developer": "软件 / 开发者生态",
    "open source": "软件 / 开发者生态",
    "github": "软件 / 开发者生态",
    "launch": "产品发布 / 商业进展",
    "released": "产品发布 / 商业进展",
    "announce": "产品发布 / 商业进展",
    "product": "产品发布 / 商业进展",
    "tesla": "智能汽车 / 制造业",
    "spacex": "航天 / 商业化基础设施",
    "starship": "航天 / 商业化基础设施",
    "starlink": "航天 / 商业化基础设施",
    "x payments": "金融科技 / 支付",
    "crypto": "加密资产 / 区块链",
    "bitcoin": "加密资产 / 区块链",
    "btc": "加密资产 / 区块链",
    "ethereum": "加密资产 / 区块链",
    "tron": "加密资产 / 区块链",
    "usdt": "加密资产 / 区块链",
    "stablecoin": "加密资产 / 区块链",
    "sec": "政策 / 监管",
    "fed": "宏观 / 政策",
    "tariff": "宏观 / 政策",
    "inflation": "宏观 / 政策",
    "rate cut": "宏观 / 政策",
    "policy": "政策 / 监管",
    "regulation": "政策 / 监管",
    "market": "市场 / 投资",
    "investment": "市场 / 投资",
    "funding": "创业 / 融资",
    "ipo": "资本市场",
    "acquisition": "资本市场",
    "merger": "资本市场",
    "营收": "商业 / 财务",
    "融资": "创业 / 融资",
    "政策": "政策 / 监管",
    "监管": "政策 / 监管",
    "模型": "AI / 模型 / 算力",
    "开源": "软件 / 开发者生态",
    "产品": "产品发布 / 商业进展",
    "发布": "产品发布 / 商业进展",
    "投资": "市场 / 投资",
    "创业": "创业 / 融资",
    "开发者": "软件 / 开发者生态",
}

IMPORTANT_KEYWORDS = {
    "launch",
    "released",
    "announced",
    "rollout",
    "open source",
    "benchmark",
    "revenue",
    "earnings",
    "partnership",
    "acquisition",
    "ipo",
    "sec",
    "regulation",
    "policy",
    "law",
    "ban",
    "tariff",
    "funding",
    "raises",
    "breakthrough",
    "milestone",
    "roadmap",
    "api",
    "developer",
    "发布",
    "上线",
    "开源",
    "融资",
    "收购",
    "监管",
    "政策",
    "财报",
    "里程碑",
}

LOW_VALUE_PATTERNS = [
    r"\bgm\b",
    r"\bgn\b",
    r"\blol\b",
    r"\blmao\b",
    r"\btrue\b",
    r"\byes\b",
    r"\bno\b",
    r"\bwow\b",
    r"^\W*$",
    r"抽奖",
    r"转发.*关注",
    r"giveaway",
    r"airdrop",
    r"promo code",
    r"limited offer",
]


@dataclass(frozen=True)
class Config:
    accounts: list[str]
    recipient_email: str
    timezone_name: str
    report_date: date
    apify_token: str
    twitter_cookie: str
    apify_actor: str
    max_results_per_account: int
    smtp_host: str
    smtp_port: int
    smtp_username: str
    smtp_password: str
    smtp_from: str
    dry_run: bool
    output_path: str | None


@dataclass
class Tweet:
    id: str
    author_username: str
    author_name: str
    created_at_utc: datetime
    created_at_local: datetime
    text: str
    url: str
    is_retweet: bool
    is_reply: bool
    is_quote: bool
    urls: list[str]
    media_urls: list[str]
    like_count: int
    retweet_count: int
    reply_count: int
    quote_count: int
    view_count: int
    raw: dict[str, Any]


@dataclass
class KeptItem:
    tweet: Tweet
    level: str
    score: int
    topics: list[str]
    explanation: str
    background: str
    judgment: str
    advice: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate a Twitter/X daily report.")
    parser.add_argument("--date", help="Report date in configured timezone, YYYY-MM-DD. Defaults to yesterday.")
    parser.add_argument("--dry-run", action="store_true", help="Print/write the report without sending email.")
    parser.add_argument("--output", help="Optional path to write the rendered email body.")
    return parser.parse_args()


def split_accounts(raw: str | None) -> list[str]:
    if not raw:
        return DEFAULT_ACCOUNTS[:]
    accounts = [part.strip() for part in re.split(r"[\n,]+", raw) if part.strip()]
    return accounts or DEFAULT_ACCOUNTS[:]


def clean_account(account: str) -> str:
    return account.strip().lstrip("@")


def env_first(*names: str, default: str = "") -> str:
    for name in names:
        value = os.getenv(name)
        if value:
            return value
    return default


def load_config(args: argparse.Namespace) -> Config:
    timezone_name = env_first("TIMEZONE", "TWITTER_TIMEZONE", default=DEFAULT_TIMEZONE)
    tz = ZoneInfo(timezone_name)
    if args.date:
        report_date = date.fromisoformat(args.date)
    else:
        report_date = datetime.now(tz).date() - timedelta(days=1)

    max_results_raw = env_first("MAX_RESULTS_PER_ACCOUNT", default=str(DEFAULT_MAX_RESULTS_PER_ACCOUNT))
    try:
        max_results = max(1, int(max_results_raw))
    except ValueError:
        max_results = DEFAULT_MAX_RESULTS_PER_ACCOUNT

    apify_token = env_first("APIFY_TOKEN")
    twitter_cookie = env_first("APIFY_TWITTER_COOKIE", "TWITTER_COOKIE")
    smtp_host = env_first("SMTP_HOST")
    smtp_username = env_first("SMTP_USERNAME", "SMTP_USER")
    smtp_password = env_first("SMTP_PASSWORD", "SMTP_PASS")
    smtp_from = env_first("SMTP_FROM", "EMAIL_FROM", default=smtp_username)
    smtp_port_raw = env_first("SMTP_PORT", default="587")
    try:
        smtp_port = int(smtp_port_raw)
    except ValueError:
        smtp_port = 587

    missing = []
    if not apify_token:
        missing.append("APIFY_TOKEN")
    if not twitter_cookie:
        missing.append("APIFY_TWITTER_COOKIE")
    recipient_email = env_first("RECIPIENT_EMAIL", "EMAIL_TO")
    if not recipient_email:
        missing.append("RECIPIENT_EMAIL")

    if not args.dry_run:
        for name, value in [
            ("SMTP_HOST", smtp_host),
            ("SMTP_USERNAME", smtp_username),
            ("SMTP_PASSWORD", smtp_password),
        ]:
            if not value:
                missing.append(name)
    if missing:
        raise RuntimeError("Missing required environment variables: " + ", ".join(missing))

    return Config(
        accounts=split_accounts(env_first("TWITTER_ACCOUNTS", "twitter_accounts")),
        recipient_email=recipient_email,
        timezone_name=timezone_name,
        report_date=report_date,
        apify_token=apify_token,
        twitter_cookie=twitter_cookie,
        apify_actor=env_first("APIFY_ACTOR", default=DEFAULT_ACTOR),
        max_results_per_account=max_results,
        smtp_host=smtp_host,
        smtp_port=smtp_port,
        smtp_username=smtp_username,
        smtp_password=smtp_password,
        smtp_from=smtp_from,
        dry_run=args.dry_run,
        output_path=args.output,
    )


def report_window(config: Config) -> tuple[datetime, datetime]:
    tz = ZoneInfo(config.timezone_name)
    start = datetime.combine(config.report_date, dt_time.min, tzinfo=tz)
    end = start + timedelta(days=1)
    return start, end


def apify_request(config: Config, payload: dict[str, Any]) -> list[dict[str, Any]]:
    url = (
        f"https://api.apify.com/v2/acts/{config.apify_actor}/run-sync-get-dataset-items"
        f"?token={config.apify_token}&timeout=240&memory=256"
    )
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=300) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")
        raise RuntimeError(f"Apify request failed with HTTP {exc.code}: {body[:1000]}") from exc


def parse_tweet_datetime(created_at: str) -> datetime:
    parsed = parsedate_to_datetime(created_at)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def as_int(value: Any) -> int:
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return 0


def normalize_tweet(raw: dict[str, Any], local_tz: ZoneInfo) -> Tweet | None:
    tweet_id = str(raw.get("id") or "")
    created_at_raw = raw.get("createdAt")
    text = str(raw.get("text") or "").strip()
    username = str(raw.get("authorUsername") or "").strip()
    if not tweet_id or not created_at_raw or not text or not username:
        return None
    try:
        created_utc = parse_tweet_datetime(str(created_at_raw))
    except (TypeError, ValueError):
        return None

    return Tweet(
        id=tweet_id,
        author_username=username,
        author_name=str(raw.get("authorName") or username),
        created_at_utc=created_utc,
        created_at_local=created_utc.astimezone(local_tz),
        text=text,
        url=str(raw.get("url") or f"https://x.com/{username}/status/{tweet_id}"),
        is_retweet=bool(raw.get("isRetweet")),
        is_reply=bool(raw.get("isReply")),
        is_quote=bool(raw.get("isQuote")),
        urls=[str(item) for item in raw.get("urls") or []],
        media_urls=[str(item) for item in raw.get("mediaUrls") or []],
        like_count=as_int(raw.get("likeCount")),
        retweet_count=as_int(raw.get("retweetCount")),
        reply_count=as_int(raw.get("replyCount")),
        quote_count=as_int(raw.get("quoteCount")),
        view_count=as_int(raw.get("viewCount")),
        raw=raw,
    )


def fetch_account_tweets(config: Config, account: str) -> list[Tweet]:
    start, end = report_window(config)
    username = clean_account(account)
    query = f"from:{username} since_time:{int(start.timestamp())} until_time:{int(end.timestamp())}"
    payload = {
        "mode": "search",
        "searchTerms": [query],
        "maxResults": config.max_results_per_account,
        "twitterCookie": config.twitter_cookie,
    }
    raw_items = apify_request(config, payload)
    local_tz = ZoneInfo(config.timezone_name)
    tweets: list[Tweet] = []
    for raw in raw_items:
        tweet = normalize_tweet(raw, local_tz)
        if not tweet:
            continue
        if clean_account(tweet.author_username).lower() != username.lower():
            continue
        if start <= tweet.created_at_local < end:
            tweets.append(tweet)
    tweets.sort(key=lambda item: item.created_at_utc)
    return tweets


def visible_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def shorten(text: str, limit: int = 180) -> str:
    text = visible_text(text)
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "..."


def keyword_matches(text: str, keyword: str) -> bool:
    """Match English keywords by token/phrase, Chinese keywords by substring."""
    keyword = keyword.lower()
    if any(ord(char) > 127 for char in keyword):
        return keyword in text
    escaped = re.escape(keyword)
    if " " in keyword:
        return re.search(rf"(?<![a-z0-9]){escaped}(?![a-z0-9])", text) is not None
    return re.search(rf"(?<![a-z0-9]){escaped}(?![a-z0-9])", text) is not None


def detect_topics(text: str) -> list[str]:
    lower = text.lower()
    topics: list[str] = []
    for keyword, topic in TOPIC_KEYWORDS.items():
        if keyword_matches(lower, keyword) and topic not in topics:
            topics.append(topic)
    return topics


def low_value_reason(tweet: Tweet, topics: list[str]) -> str | None:
    text = visible_text(tweet.text)
    lower = text.lower()
    if tweet.is_retweet:
        return "纯转发或转推内容"
    if tweet.is_reply and len(text) < 100 and not tweet.urls and not tweet.media_urls:
        return "回复内容缺少上下文"
    if any(re.search(pattern, lower, flags=re.IGNORECASE) for pattern in LOW_VALUE_PATTERNS):
        if len(text) < 80 and not tweet.urls and not tweet.media_urls:
            return "短句、情绪表达或缺少上下文"
        if re.search(r"giveaway|airdrop|抽奖|转发.*关注", lower, flags=re.IGNORECASE):
            return "抽奖、营销或广告内容"
    if len(text) < 45 and not tweet.urls and not tweet.media_urls and not tweet.is_quote:
        return "无上下文短句"
    if not topics:
        return "与目标主题关联弱或信息密度不足"
    if re.search(r"\b(lie|liar|fraud|garbage|insane|killed millions)\b", lower) and not (
        tweet.urls or {"政策 / 监管", "宏观 / 政策", "市场 / 投资"} & set(topics)
    ):
        return "情绪化争论或口水战"
    return None


def score_tweet(tweet: Tweet, topics: list[str]) -> int:
    text = visible_text(tweet.text)
    lower = text.lower()
    score = 0
    if topics:
        score += 2
    if tweet.urls:
        score += 1
    if tweet.media_urls:
        score += 1
    if tweet.is_quote:
        score += 1
    if any(keyword_matches(lower, keyword) for keyword in IMPORTANT_KEYWORDS):
        score += 2
    if len(text) >= 120:
        score += 1
    if tweet.view_count >= 1_000_000 or tweet.like_count >= 10_000:
        score += 1
    if tweet.view_count >= 5_000_000 or tweet.like_count >= 50_000:
        score += 1
    if tweet.is_reply:
        score -= 2
    if len(text) < 50 and not tweet.urls and not tweet.media_urls:
        score -= 1
    return score


def classify_level(score: int, tweet: Tweet, topics: list[str]) -> str:
    if score >= 6 and topics:
        return "S"
    if score >= 4:
        return "A"
    return "B"


def account_background(username: str) -> str:
    user = clean_account(username).lower()
    if user == "elonmusk":
        return "Elon Musk 是 Tesla、SpaceX、xAI 和 X 的关键人物，其公开信息常影响智能汽车、航天、AI 与社交平台方向。"
    if user in {"justinsuntron", "sunyuchentron"}:
        return "孙宇晨与 TRON 生态、加密资产和稳定币相关话题关联较高，需要重点区分一手信息与营销表达。"
    if user == "wufantouzi":
        return "该账号偏投资与市场观察，适合关注其中有数据、案例或明确逻辑链的内容。"
    if user == "aleabitoreddit":
        return "该账号需要结合具体推文内容判断价值；本报告仅基于公开推文本身筛选。"
    if user == "readdonaldtrump":
        return "该账号涉及美国政治信息时，需关注其对政策、监管、宏观预期和市场情绪的潜在影响。"
    return "未补充额外背景；仅基于该推文本身判断。"


def build_explanation(tweet: Tweet, topics: list[str]) -> str:
    topic_text = "; ".join(topics)
    text = tweet.text
    lower = text.lower()
    if "AI / 模型 / 算力" in topics:
        if any(keyword_matches(lower, key) for key in ["photonics", "laser", "nvidia", "gpu", "cpo"]):
            return "作者在讨论 AI 算力产业链中的光通信、激光器或芯片供应瓶颈，并把它与相关公司机会联系起来。"
        return "作者在讨论 AI 产品、模型或算力生态的变化，属于需要跟踪的技术/产品信号。"
    if "市场 / 投资" in topics or "资本市场" in topics:
        return "作者在表达市场或投资判断，并引用公司、指数、利率预期或交易数据作为依据。"
    if "宏观 / 政策" in topics or "政策 / 监管" in topics:
        return "作者在讨论宏观政策、监管或政治信息对市场预期的潜在影响。"
    if "产品发布 / 商业进展" in topics:
        return "作者提到产品、合作或商业进展，重点在于其是否能转化为实际收入、用户增长或生态影响。"
    if "加密资产 / 区块链" in topics:
        return "作者在讨论加密资产或区块链生态信息，需关注是否有链上数据、官方公告或监管变化支撑。"
    if topics:
        return f"这条推文与{topic_text}相关，提供了可继续核验的观点、案例或一手线索。"
    return "这条推文提供了一条可核验的一手信息或链接，但主题相关性需要结合原文继续判断。"


def build_background(tweet: Tweet, topics: list[str]) -> str:
    base = account_background(tweet.author_username)
    if topics:
        return f"{base} 本条涉及{'; '.join(topics)}，判断时应优先看原文链接、数据来源和后续官方确认。"
    return base


def build_judgment(level: str, tweet: Tweet, topics: list[str]) -> str:
    if level == "S":
        return "该信息可能影响行业判断或后续决策，建议继续跟踪后续公告、数据验证和市场反馈。"
    if level == "A":
        return "该信息具备明确参考价值，适合纳入观察列表，并与同类公司、产品或政策变化交叉验证。"
    if topics:
        return "该信息有一定参考价值，但当前影响有限，适合作为趋势或账号动向的补充信号。"
    return "该信息量有限，保留原因主要是包含可追溯来源；暂不宜据此形成强判断。"


def build_advice(level: str) -> str:
    if level == "S":
        return "值得深入阅读并持续跟踪。"
    if level == "A":
        return "可以加入观察列表。"
    return "暂时了解即可。"


def filter_and_summarize(tweets: list[Tweet]) -> tuple[list[KeptItem], Counter[str]]:
    kept: list[KeptItem] = []
    filtered_reasons: Counter[str] = Counter()
    seen_texts: set[str] = set()

    for tweet in tweets:
        normalized_text = visible_text(tweet.text).lower()
        duplicate_key = re.sub(r"https?://\S+", "", normalized_text).strip()
        if duplicate_key in seen_texts:
            filtered_reasons["重复表达或高度相似内容"] += 1
            continue
        seen_texts.add(duplicate_key)

        topics = detect_topics(tweet.text)
        reason = low_value_reason(tweet, topics)
        if reason:
            filtered_reasons[reason] += 1
            continue

        score = score_tweet(tweet, topics)
        if score < 3:
            filtered_reasons["与目标主题关联弱或信息密度不足"] += 1
            continue

        level = classify_level(score, tweet, topics)
        kept.append(
            KeptItem(
                tweet=tweet,
                level=level,
                score=score,
                topics=topics,
                explanation=build_explanation(tweet, topics),
                background=build_background(tweet, topics),
                judgment=build_judgment(level, tweet, topics),
                advice=build_advice(level),
            )
        )

    level_order = {"S": 0, "A": 1, "B": 2}
    kept.sort(
        key=lambda item: (
            level_order[item.level],
            -item.score,
            -item.tweet.view_count,
            item.tweet.created_at_utc,
        )
    )
    return kept, filtered_reasons


def format_count(counter: Counter[str], key: str) -> int:
    return int(counter.get(key, 0))


def render_item(item: KeptItem, index: int | None = None) -> str:
    tweet = item.tweet
    prefix = f"{index}. " if index is not None else "- "
    metrics = (
        f"互动：{tweet.like_count} 赞 / {tweet.retweet_count} 转发 / "
        f"{tweet.reply_count} 回复 / {tweet.view_count} 浏览"
    )
    lines = [
        f"{prefix}[{item.level}] @{tweet.author_username} | {tweet.created_at_local:%Y-%m-%d %H:%M:%S %Z}",
        f"  原文：{tweet.text}",
        f"  链接：{tweet.url}",
        f"  {metrics}",
        f"  中文解释：{item.explanation}",
        f"  背景补充：{item.background}",
        f"  延伸判断：{item.judgment}",
        f"  我的建议：{item.advice}",
    ]
    return "\n".join(lines)


def render_report(
    config: Config,
    tweets_by_account: dict[str, list[Tweet]],
    kept: list[KeptItem],
    filtered_reasons: Counter[str],
    fetch_errors: dict[str, str],
) -> tuple[str, str]:
    total_tweets = sum(len(items) for items in tweets_by_account.values())
    level_counts = Counter(item.level for item in kept)
    report_date = config.report_date.isoformat()
    subject = f"【Twitter 日报】{report_date} 高价值信息摘要"
    start, end = report_window(config)

    no_tweet_accounts = [account for account, tweets in tweets_by_account.items() if not tweets and account not in fetch_errors]
    capped_accounts = [
        account
        for account, tweets in tweets_by_account.items()
        if len(tweets) >= config.max_results_per_account
    ]

    lines = [
        f"# {subject}",
        "",
        f"统计窗口：{start:%Y-%m-%d %H:%M:%S %Z} 至 {(end - timedelta(seconds=1)):%Y-%m-%d %H:%M:%S %Z}",
        "",
        "## 1. 今日摘要",
        f"- 总共扫描账号数：{len(config.accounts)}",
        f"- 总推文数：{total_tweets}",
        f"- 保留高价值推文数：{len(kept)}",
        f"- S/A/B 数量：S {format_count(level_counts, 'S')} / A {format_count(level_counts, 'A')} / B {format_count(level_counts, 'B')}",
    ]
    if no_tweet_accounts:
        lines.append("- 昨天无公开推文账号：" + ", ".join(no_tweet_accounts))
    if fetch_errors:
        lines.append("- 抓取异常账号：" + "; ".join(f"{account}: {error}" for account, error in fetch_errors.items()))
    if capped_accounts:
        lines.append(
            "- 注意：以下账号达到单账号抓取上限，可能需要调高 MAX_RESULTS_PER_ACCOUNT 复核："
            + ", ".join(capped_accounts)
        )

    lines.extend(["", "## 2. 最重要的 3 条"])
    if kept:
        for index, item in enumerate(kept[:3], 1):
            lines.append(render_item(item, index=index))
            lines.append("")
    else:
        lines.append("今天没有保留到符合规则的高价值推文。")

    lines.extend(["", "## 3. 详细内容"])
    if kept:
        for level in ["S", "A", "B"]:
            level_items = [item for item in kept if item.level == level]
            lines.append(f"### {level} 级")
            if not level_items:
                lines.append("- 无")
            else:
                for item in level_items:
                    lines.append(render_item(item))
                    lines.append("")
    else:
        lines.append("- 无高价值内容。")

    lines.extend(["", "## 4. 被过滤内容概述"])
    if filtered_reasons:
        for reason, count in filtered_reasons.most_common():
            lines.append(f"- {reason}：{count} 条")
    else:
        lines.append("- 未过滤内容。")

    lines.extend(["", "## 5. 今日结论"])
    if kept:
        topic_counts = Counter(topic for item in kept for topic in item.topics)
        for topic, count in topic_counts.most_common(5):
            lines.append(f"- {topic} 是今天较值得关注的方向，相关保留内容 {count} 条。")
        if format_count(level_counts, "S") == 0:
            lines.append("- 今天没有 S 级信号，整体更适合作为观察素材，而非直接形成重大判断。")
        if fetch_errors:
            lines.append("- 部分账号抓取异常，相关结论需要在恢复访问后补充复核。")
    else:
        lines.extend(
            [
                "- 今天未发现足够高价值的产品、技术、政策或投资信号。",
                "- 被过滤内容主要集中在短句、回复、营销或主题关联弱的信息。",
                "- 建议继续保持观察，不为了凑数量保留低密度内容。",
            ]
        )

    body = "\n".join(lines).strip() + "\n"
    return subject, body


def markdown_to_html(markdown_text: str) -> str:
    escaped_lines = []
    for line in markdown_text.splitlines():
        if line.startswith("# "):
            escaped_lines.append(f"<h1>{html.escape(line[2:])}</h1>")
        elif line.startswith("## "):
            escaped_lines.append(f"<h2>{html.escape(line[3:])}</h2>")
        elif line.startswith("### "):
            escaped_lines.append(f"<h3>{html.escape(line[4:])}</h3>")
        elif line.startswith("- "):
            escaped_lines.append(f"<p>{html.escape(line)}</p>")
        elif not line:
            escaped_lines.append("<br>")
        else:
            escaped_lines.append(f"<p>{html.escape(line)}</p>")
    return "<html><body>" + "\n".join(escaped_lines) + "</body></html>"


def send_email(config: Config, subject: str, body: str) -> None:
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = config.smtp_from
    message["To"] = config.recipient_email
    message.set_content(body)
    message.add_alternative(markdown_to_html(body), subtype="html")

    if config.smtp_port == 465:
        with smtplib.SMTP_SSL(config.smtp_host, config.smtp_port, timeout=60) as smtp:
            smtp.login(config.smtp_username, config.smtp_password)
            smtp.send_message(message)
    else:
        with smtplib.SMTP(config.smtp_host, config.smtp_port, timeout=60) as smtp:
            smtp.ehlo()
            smtp.starttls()
            smtp.ehlo()
            smtp.login(config.smtp_username, config.smtp_password)
            smtp.send_message(message)


def collect_tweets(config: Config) -> tuple[dict[str, list[Tweet]], dict[str, str]]:
    tweets_by_account: dict[str, list[Tweet]] = {}
    errors: dict[str, str] = {}
    for account in config.accounts:
        normalized = "@" + clean_account(account)
        try:
            tweets_by_account[normalized] = fetch_account_tweets(config, account)
            # Be polite to the actor/API and avoid bursty sequential runs.
            time.sleep(1)
        except Exception as exc:  # noqa: BLE001 - email report should include per-account failures.
            tweets_by_account[normalized] = []
            errors[normalized] = str(exc)
    return tweets_by_account, errors


def write_output(path: str, body: str) -> None:
    with open(path, "w", encoding="utf-8") as file:
        file.write(body)


def main() -> int:
    args = parse_args()
    try:
        config = load_config(args)
        tweets_by_account, errors = collect_tweets(config)
        all_tweets = [tweet for tweets in tweets_by_account.values() for tweet in tweets]
        kept, filtered_reasons = filter_and_summarize(all_tweets)
        subject, body = render_report(config, tweets_by_account, kept, filtered_reasons, errors)

        if config.output_path:
            write_output(config.output_path, body)

        if config.dry_run:
            print(subject)
            print(body)
        else:
            send_email(config, subject, body)
            print(f"Sent report to {config.recipient_email}: {subject}")
            print(
                json.dumps(
                    {
                        "accounts": len(config.accounts),
                        "tweets": len(all_tweets),
                        "kept": len(kept),
                        "levels": Counter(item.level for item in kept),
                        "errors": errors,
                    },
                    ensure_ascii=False,
                    default=dict,
                )
            )
        return 0
    except Exception as exc:  # noqa: BLE001 - top-level command should print clean diagnostics.
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
