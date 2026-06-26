#!/usr/bin/env python3
"""Collect important AI news from reliable sources and email a Chinese brief.

The script intentionally uses only the Python standard library so it can run in
minimal automation environments such as GitHub Actions. It focuses on primary
sources, trusted AI/tech media, arXiv papers, and GitHub project activity from
the previous day in the configured timezone.
"""

from __future__ import annotations

import argparse
import html
import json
import os
import re
import smtplib
import sys
import textwrap
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import date, datetime, time as dt_time, timedelta, timezone
from email.message import EmailMessage
from email.utils import parsedate_to_datetime
from typing import Any
from zoneinfo import ZoneInfo


DEFAULT_TIMEZONE = "Asia/Shanghai"
DEFAULT_MAX_ITEMS = 12
USER_AGENT = (
    "news-for-me/1.0 (daily AI email brief)"
)


@dataclass(frozen=True)
class Source:
    name: str
    feed_url: str
    category: str
    reliability: int
    source_url: str
    image_hint: str
    requires_ai_match: bool = False


@dataclass(frozen=True)
class Config:
    recipient_email: str
    timezone_name: str
    report_date: date
    smtp_host: str
    smtp_port: int
    smtp_username: str
    smtp_password: str
    smtp_from: str
    dry_run: bool
    test_mode: bool
    output_path: str | None
    max_items: int
    fetch_article_images: bool


@dataclass
class NewsItem:
    title: str
    summary: str
    why_important: str
    url: str
    source_name: str
    source_url: str
    category: str
    published_at: datetime
    score: int
    description: str = ""
    image_url: str = ""
    image_source_url: str = ""
    image_note: str = ""
    extension_only: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


AI_SOURCES = [
    Source(
        "OpenAI News",
        "https://openai.com/news/rss.xml",
        "模型 / 产品发布",
        5,
        "https://openai.com/news/",
        "OpenAI News 文章首图或 OpenAI 官方新闻页封面。",
    ),
    Source(
        "Anthropic News",
        "https://raw.githubusercontent.com/Olshansk/rss-feeds/main/feeds/feed_anthropic_news.xml",
        "模型 / 产品发布",
        5,
        "https://www.anthropic.com/news",
        "Anthropic 官方新闻页文章首图；该 feed 由社区跟踪官方页面生成，原始链接仍指向 Anthropic。",
    ),
    Source(
        "Google AI Blog",
        "https://blog.google/technology/ai/rss/",
        "模型 / 产品发布",
        5,
        "https://blog.google/technology/ai/",
        "Google Blog 文章首图或 Google AI 栏目页封面。",
    ),
    Source(
        "Google DeepMind",
        "https://deepmind.google/blog/rss.xml",
        "研究 / 模型更新",
        5,
        "https://deepmind.google/blog/",
        "Google DeepMind 博客文章首图。",
    ),
    Source(
        "Microsoft AI Blog",
        "https://microsoft.ai/blog/feed/",
        "公司动态 / 产品发布",
        5,
        "https://microsoft.ai/blog/",
        "Microsoft AI Blog 文章首图。",
    ),
    Source(
        "Microsoft Research Blog",
        "https://www.microsoft.com/en-us/research/feed/",
        "研究 / 模型更新",
        4,
        "https://www.microsoft.com/en-us/research/blog/",
        "Microsoft Research Blog 文章首图、论文图或项目截图。",
        requires_ai_match=True,
    ),
    Source(
        "Meta AI Blog",
        "https://raw.githubusercontent.com/Olshansk/rss-feeds/main/feeds/feed_meta_ai.xml",
        "研究 / 开源项目",
        5,
        "https://ai.meta.com/blog/",
        "Meta AI 官方博客文章首图；该 feed 由社区跟踪官方页面生成，原始链接仍指向 Meta AI。",
    ),
    Source(
        "NVIDIA AI Blog",
        "https://blogs.nvidia.com/feed/",
        "算力 / 产业动态",
        5,
        "https://blogs.nvidia.com/",
        "NVIDIA AI Blog 文章首图或配套产品图。",
        requires_ai_match=True,
    ),
    Source(
        "Hugging Face Blog",
        "https://huggingface.co/blog/feed.xml",
        "开源项目 / 开发者生态",
        5,
        "https://huggingface.co/blog",
        "Hugging Face 文章首图、模型卡或项目截图。",
    ),
    Source(
        "Mistral AI News",
        "https://raw.githubusercontent.com/0xSMW/rss-feeds/main/feeds/feed_mistral_news.xml",
        "模型 / 产品发布",
        5,
        "https://mistral.ai/news/",
        "Mistral AI 官方新闻页文章首图；该 feed 由社区跟踪官方页面生成，原始链接仍指向 Mistral AI。",
    ),
    Source(
        "GitHub Blog AI",
        "https://github.blog/tag/ai/feed/",
        "开发者生态 / 开源项目",
        4,
        "https://github.blog/tag/ai/",
        "GitHub Blog 文章首图或项目仓库截图。",
    ),
    Source(
        "AWS Machine Learning Blog",
        "https://aws.amazon.com/blogs/machine-learning/feed/",
        "云服务 / 开发者生态",
        4,
        "https://aws.amazon.com/blogs/machine-learning/",
        "AWS Machine Learning Blog 文章首图或架构图。",
    ),
    Source(
        "TechCrunch AI",
        "https://techcrunch.com/category/artificial-intelligence/feed/",
        "投融资 / 公司动态",
        4,
        "https://techcrunch.com/category/artificial-intelligence/",
        "TechCrunch 文章首图或公司产品截图。",
    ),
    Source(
        "The Verge AI",
        "https://www.theverge.com/rss/ai-artificial-intelligence/index.xml",
        "产品 / 行业动态",
        4,
        "https://www.theverge.com/ai-artificial-intelligence",
        "The Verge 文章首图或产品截图。",
    ),
    Source(
        "MIT Technology Review AI",
        "https://www.technologyreview.com/topic/artificial-intelligence/feed/",
        "研究 / 监管 / 行业趋势",
        4,
        "https://www.technologyreview.com/topic/artificial-intelligence/",
        "MIT Technology Review 文章首图或相关图表。",
    ),
    Source(
        "VentureBeat AI",
        "https://venturebeat.com/category/ai/feed/",
        "企业 AI / 融资",
        3,
        "https://venturebeat.com/category/ai/",
        "VentureBeat 文章首图或公司产品截图。",
    ),
    Source(
        "The Batch",
        "https://raw.githubusercontent.com/Olshansk/rss-feeds/main/feeds/feed_the_batch.xml",
        "研究 / 行业周报",
        4,
        "https://www.deeplearning.ai/the-batch/",
        "The Batch 文章插图或原文配图；该 feed 由社区跟踪官方页面生成，原始链接仍指向 DeepLearning.AI。",
    ),
]


KEYWORD_WEIGHTS = {
    "release": 9,
    "released": 9,
    "launch": 9,
    "launched": 9,
    "announce": 8,
    "announced": 8,
    "introduce": 7,
    "introduced": 7,
    "model": 7,
    "reasoning": 7,
    "agent": 7,
    "agents": 7,
    "multimodal": 7,
    "benchmark": 6,
    "open source": 6,
    "open-source": 6,
    "github": 5,
    "api": 5,
    "developer": 4,
    "funding": 7,
    "raises": 7,
    "valuation": 6,
    "acquisition": 8,
    "partnership": 6,
    "regulation": 8,
    "regulator": 8,
    "policy": 7,
    "safety": 6,
    "lawsuit": 6,
    "chip": 6,
    "gpu": 6,
    "nvidia": 6,
    "inference": 5,
    "training": 5,
    "robot": 5,
    "robotics": 5,
    "生成式": 8,
    "模型": 8,
    "发布": 8,
    "上线": 8,
    "开源": 7,
    "融资": 7,
    "监管": 8,
    "政策": 7,
    "收购": 8,
    "合作": 6,
    "芯片": 6,
    "算力": 6,
}


AI_RELEVANCE_KEYWORDS = {
    "ai",
    "artificial intelligence",
    "llm",
    "large language",
    "language model",
    "model",
    "agent",
    "agents",
    "copilot",
    "gpt",
    "claude",
    "gemini",
    "llama",
    "mistral",
    "midjourney",
    "openai",
    "anthropic",
    "deepmind",
    "hugging face",
    "nvidia",
    "gpu",
    "chip",
    "inference",
    "training",
    "multimodal",
    "diffusion",
    "robot",
    "benchmark",
    "open source",
    "open-source",
    "rag",
    "模型",
    "大模型",
    "智能体",
    "生成式",
    "开源",
    "算力",
    "芯片",
    "推理",
    "训练",
}


LOW_VALUE_TITLE_PATTERNS = [
    r"\bdays?\s+left\s+to\s+save\b",
    r"\bsave\s+up\s+to\b",
    r"\bearly\s+bird\b",
    r"\bregister\s+(now|today)\b",
    r"\b(ticket|tickets|pass|passes)\b.*\b(save|discount|register|summit)\b",
    r"\bsponsored\b",
    r"\bwebinar\b.*\bregister\b",
    r"优惠",
    r"折扣",
    r"报名",
]


JARGON_GLOSSARY: dict[str, str] = {
    "MoE": "混合专家模型（Mixture of Experts），通过多个子模型按需激活以提升容量与推理效率。",
    "RLHF": "基于人类反馈的强化学习，用于让大模型输出更符合人类偏好与安全要求。",
    "RAG": "检索增强生成，在生成回答前先从外部知识库检索相关内容以提升准确性与时效性。",
    "LoRA": "低秩适配，一种轻量微调方法，用少量参数让预训练模型适应新任务。",
    "ASR": "自动语音识别，将语音信号转换为文本的技术。",
    "OCR": "光学字符识别，从图像中提取文字信息。",
    "VLM": "视觉语言模型，能同时理解图像与文本的多模态大模型。",
    "LLM": "大语言模型，基于海量文本训练、具备通用语言理解与生成能力的神经网络模型。",
    "GPT": "生成式预训练 Transformer，OpenAI 系列大语言模型的产品与技术代称。",
    "Transformer": "一种基于自注意力机制的神经网络架构，是现代大语言模型的基础。",
    "diffusion": "扩散模型，通过逐步去噪生成图像、视频等内容的主流生成式 AI 方法。",
    "embedding": "嵌入向量，将文本、图像等离散数据映射为可计算的连续向量表示。",
    "fine-tuning": "微调，在预训练模型基础上用特定数据继续训练以适应下游任务。",
    "inference": "推理，模型训练完成后用于实际预测或生成输出的运行阶段。",
    "token": "词元，大模型处理文本的最小单位，也是计费与上下文长度的计量单位。",
    "context window": "上下文窗口，模型单次可处理的输入与输出 token 总量上限。",
    "agentic": "智能体式，指 AI 能自主规划、调用工具并完成多步骤任务的能力范式。",
    "SOTA": "State of the Art，当前公开基准上的最优水平。",
    "benchmark": "基准测试，用标准化数据集与指标评估模型或系统性能。",
    "quantization": "量化，通过降低数值精度压缩模型体积并加速推理的技术。",
    "distillation": "知识蒸馏，让小模型学习大模型的行为以在更小算力下逼近性能。",
    "multimodal": "多模态，同时处理文本、图像、音频等多种数据类型的 AI 能力。",
    "AGI": "通用人工智能，能在广泛任务上达到或超越人类水平的 AI 目标概念。",
    "HNSW": "分层可导航小世界图，常用于向量数据库的高效近似最近邻检索。",
    "FP8": "8 位浮点格式，用于降低训练与推理显存占用的低精度数值格式。",
    "KV cache": "键值缓存，大模型自回归推理时缓存历史注意力状态以加速生成的技术。",
}

JARGON_TERM_PATTERNS: list[tuple[str, str]] = [
    (r"\bMoE\b", "MoE"),
    (r"\bRLHF\b", "RLHF"),
    (r"\bRAG\b", "RAG"),
    (r"\bLoRA\b", "LoRA"),
    (r"\bASR\b", "ASR"),
    (r"\bOCR\b", "OCR"),
    (r"\bVLM\b", "VLM"),
    (r"\bLLMs?\b", "LLM"),
    (r"\bGPT-?\d*\b", "GPT"),
    (r"\bTransformers?\b", "Transformer"),
    (r"\bdiffusion\b", "diffusion"),
    (r"\bembeddings?\b", "embedding"),
    (r"\bfine-?tuning\b", "fine-tuning"),
    (r"\binference\b", "inference"),
    (r"\btokens?\b", "token"),
    (r"context\s+window", "context window"),
    (r"\bagentic\b", "agentic"),
    (r"\bSOTA\b", "SOTA"),
    (r"\bbenchmarks?\b", "benchmark"),
    (r"\bquantization\b", "quantization"),
    (r"\bdistillation\b", "distillation"),
    (r"\bmultimodal\b", "multimodal"),
    (r"\bAGI\b", "AGI"),
    (r"\bHNSW\b", "HNSW"),
    (r"\bFP8\b", "FP8"),
    (r"\bKV\s+cache\b", "KV cache"),
]

_WIKI_EXPLANATION_CACHE: dict[str, str | None] = {}

WHY_BY_CATEGORY = {
    "模型 / 产品发布": "可能改变模型能力、产品形态或开发者调用方式，值得 AI 从业者评估对现有工作流和产品路线的影响。",
    "研究 / 模型更新": "涉及模型能力、评测方法或研究方向变化，可作为后续技术选型和论文跟踪的线索。",
    "公司动态 / 产品发布": "反映头部平台公司的 AI 战略和商业化节奏，可能影响生态合作、采购和竞争格局。",
    "研究 / 开源项目": "对复现实验、模型微调、工具链建设和开源生态有直接参考价值。",
    "算力 / 产业动态": "算力、芯片和基础设施变化会影响训练/推理成本、供给节奏和应用落地速度。",
    "开发者生态 / 开源项目": "开发者工具和开源项目变化会影响工程实践、集成成本和团队效率。",
    "云服务 / 开发者生态": "云厂商能力更新会影响企业部署、成本控制、数据治理和平台选型。",
    "投融资 / 公司动态": "融资、估值和公司事件可反映资本对 AI 赛道的判断，也可能改变人才、合作和并购预期。",
    "产品 / 行业动态": "用户侧产品变化可帮助判断 AI 功能的主流落地场景和竞争重点。",
    "研究 / 监管 / 行业趋势": "研究趋势和监管动向会影响产品合规、安全评估和长期战略判断。",
    "企业 AI / 融资": "企业 AI 采用和融资动态有助于判断真实商业需求、销售周期和落地痛点。",
    "论文 / 研究": "论文可能提供新方法、数据集、基准或安全结论，适合作为研发和技术雷达素材。",
    "开源项目 / GitHub": "新项目或活跃项目可能沉淀为可复用工具，值得快速评估其许可证、维护者和社区反馈。",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate and email a Chinese AI daily report.")
    parser.add_argument("--date", help="Report date in configured timezone, YYYY-MM-DD. Defaults to yesterday.")
    parser.add_argument("--dry-run", action="store_true", help="Print/write the report without sending email.")
    parser.add_argument("--test", action="store_true", help="Mark the email subject and body as a test send.")
    parser.add_argument("--output", help="Optional path to write the rendered HTML email body.")
    parser.add_argument("--max-items", type=int, help=f"Maximum main news items. Default: {DEFAULT_MAX_ITEMS}.")
    return parser.parse_args()


def env_first(*names: str, default: str = "") -> str:
    for name in names:
        value = os.getenv(name)
        if value:
            return value
    return default


def parse_bool(value: str, default: bool) -> bool:
    if not value:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def load_config(args: argparse.Namespace) -> Config:
    timezone_name = env_first("TIMEZONE", "AI_NEWS_TIMEZONE", default=DEFAULT_TIMEZONE)
    tz = ZoneInfo(timezone_name)
    report_date = date.fromisoformat(args.date) if args.date else datetime.now(tz).date() - timedelta(days=1)
    smtp_port_raw = env_first("SMTP_PORT", default="587")
    try:
        smtp_port = int(smtp_port_raw)
    except ValueError:
        smtp_port = 587

    smtp_username = env_first("SMTP_USERNAME", "SMTP_USER")
    smtp_from = env_first("SMTP_FROM", "EMAIL_FROM", default=smtp_username)
    max_items_raw = str(args.max_items or env_first("AI_MAX_ITEMS", default=str(DEFAULT_MAX_ITEMS)))
    try:
        max_items = max(5, min(30, int(max_items_raw)))
    except ValueError:
        max_items = DEFAULT_MAX_ITEMS

    missing = []
    recipient_email = env_first("RECIPIENT_EMAIL", "EMAIL_TO")
    if not recipient_email:
        missing.append("RECIPIENT_EMAIL")

    smtp_host = env_first("SMTP_HOST")
    smtp_password = env_first("SMTP_PASSWORD", "SMTP_PASS")
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
        recipient_email=recipient_email,
        timezone_name=timezone_name,
        report_date=report_date,
        smtp_host=smtp_host,
        smtp_port=smtp_port,
        smtp_username=smtp_username,
        smtp_password=smtp_password,
        smtp_from=smtp_from,
        dry_run=args.dry_run,
        test_mode=args.test,
        output_path=args.output,
        max_items=max_items,
        fetch_article_images=parse_bool(env_first("AI_FETCH_ARTICLE_IMAGES", default="true"), True),
    )


def report_window(config: Config) -> tuple[datetime, datetime]:
    tz = ZoneInfo(config.timezone_name)
    start = datetime.combine(config.report_date, dt_time.min, tzinfo=tz)
    return start, start + timedelta(days=1)


def fetch_url(url: str, timeout: int = 30, headers: dict[str, str] | None = None) -> bytes:
    request_headers = {"User-Agent": USER_AGENT}
    if headers:
        request_headers.update(headers)
    request = urllib.request.Request(url, headers=request_headers)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


def fetch_text(url: str, timeout: int = 30, headers: dict[str, str] | None = None) -> str:
    data = fetch_url(url, timeout=timeout, headers=headers)
    return data.decode("utf-8", "replace")


def strip_html(value: str) -> str:
    value = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", value)
    value = re.sub(r"(?s)<[^>]+>", " ", value)
    return re.sub(r"\s+", " ", html.unescape(value)).strip()


def truncate(value: str, limit: int = 260) -> str:
    value = re.sub(r"\s+", " ", value).strip()
    if len(value) <= limit:
        return value
    return value[: limit - 1].rstrip() + "..."


def parse_datetime(value: str) -> datetime | None:
    if not value:
        return None
    value = value.strip()
    try:
        parsed = parsedate_to_datetime(value)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except (TypeError, ValueError, IndexError, OverflowError):
        pass
    try:
        normalized = value.replace("Z", "+00:00")
        parsed = datetime.fromisoformat(normalized)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except ValueError:
        return None


def child_text(element: ET.Element, names: set[str]) -> str:
    for child in list(element):
        tag = child.tag.rsplit("}", 1)[-1].lower()
        if tag in names and child.text:
            return child.text.strip()
    return ""


def child_attr(element: ET.Element, tag_names: set[str], attr_name: str) -> str:
    for child in list(element):
        tag = child.tag.rsplit("}", 1)[-1].lower()
        if tag in tag_names:
            value = child.attrib.get(attr_name)
            if value:
                return value.strip()
    return ""


def extract_image_from_html(value: str, base_url: str) -> str:
    for pattern in [
        r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']',
        r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image["\']',
        r'<meta[^>]+name=["\']twitter:image["\'][^>]+content=["\']([^"\']+)["\']',
        r'<img[^>]+src=["\']([^"\']+)["\']',
    ]:
        match = re.search(pattern, value, flags=re.IGNORECASE)
        if match:
            return urllib.parse.urljoin(base_url, html.unescape(match.group(1)))
    return ""


def extract_feed_image(element: ET.Element, description: str, link: str) -> str:
    image = child_attr(element, {"thumbnail", "content"}, "url")
    if image:
        return urllib.parse.urljoin(link, image)
    for child in list(element):
        tag = child.tag.rsplit("}", 1)[-1].lower()
        content_type = child.attrib.get("type", "")
        if tag == "enclosure" and content_type.startswith("image/"):
            value = child.attrib.get("url", "")
            if value:
                return urllib.parse.urljoin(link, value)
    return extract_image_from_html(description, link)


def canonical_url(url: str) -> str:
    parsed = urllib.parse.urlsplit(url)
    return urllib.parse.urlunsplit((parsed.scheme, parsed.netloc.lower(), parsed.path.rstrip("/"), "", ""))


def normalize_title(value: str) -> str:
    value = strip_html(value).lower()
    return re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", value)


def contains_any(text: str, keywords: list[str]) -> bool:
    return any(keyword in text for keyword in keywords)


def chinese_signals(title: str, description: str) -> list[str]:
    text = f"{title} {strip_html(description)}".lower()
    signal_rules = [
        (["llm", "large language", "language model", "gpt", "claude", "gemini", "llama"], "大语言模型"),
        (["agent", "agents", "agentic", "copilot"], "AI 智能体/助手"),
        (["multimodal", "vision", "image", "video", "audio", "speech", "asr", "ocr"], "多模态能力"),
        (["chip", "processor", "gpu", "nvidia", "accelerator"], "AI 芯片与算力基础设施"),
        (["inference", "training", "serving", "deployment"], "模型训练与推理部署"),
        (["benchmark", "leaderboard", "eval", "evaluation"], "模型评测与基准"),
        (["open source", "open-source", "github", "repository", "repo"], "开源生态"),
        (["api", "developer", "sdk", "toolkit", "framework"], "开发者工具链"),
        (["funding", "raises", "valuation", "acquisition", "acquires", "investment"], "融资/并购与资本动向"),
        (["regulation", "regulator", "policy", "safety", "copyright", "lawsuit"], "监管、安全与版权风险"),
        (["health", "medical", "biology", "protein", "science", "research"], "AI for Science/医疗健康"),
        (["robot", "robotics", "autonomous"], "机器人与具身智能"),
        (["enterprise", "business", "customer", "production", "scale"], "企业级落地与规模化部署"),
        (["模型", "大模型"], "大模型"),
        (["智能体", "助手"], "AI 智能体/助手"),
        (["多模态", "语音", "图像", "视频", "视觉"], "多模态能力"),
        (["芯片", "算力", "推理", "训练"], "AI 芯片与算力基础设施"),
        (["开源", "仓库"], "开源生态"),
        (["融资", "收购", "投资"], "融资/并购与资本动向"),
        (["监管", "政策", "安全", "版权"], "监管、安全与版权风险"),
    ]
    signals: list[str] = []
    for keywords, signal in signal_rules:
        if contains_any(text, keywords) and signal not in signals:
            signals.append(signal)
    return signals[:3]


def signal_phrase(title: str, description: str) -> str:
    signals = chinese_signals(title, description)
    if not signals:
        return "AI 产品、技术或产业趋势"
    return "、".join(signals)


def action_phrase(title: str, description: str) -> str:
    text = f"{title} {strip_html(description)}".lower()
    if contains_any(text, ["funding", "raises", "valuation", "investment", "融资", "投资"]):
        return "披露融资或资本市场动态"
    if contains_any(text, ["acquisition", "acquires", "merger", "收购", "并购"]):
        return "披露并购或公司整合动态"
    if contains_any(
        text,
        [
            "release",
            "released",
            "launch",
            "launched",
            "announce",
            "announced",
            "introduce",
            "introduced",
            "introducing",
            "unveil",
            "unveiled",
            "reveals",
            "发布",
            "上线",
            "推出",
        ],
    ):
        return "发布产品、模型或技术更新"
    if contains_any(text, ["partner", "partnership", "collaborate", "collaboration", "合作"]):
        return "宣布合作进展"
    if contains_any(text, ["regulation", "regulator", "policy", "lawsuit", "监管", "政策", "诉讼"]):
        return "披露监管、政策或法律相关变化"
    if contains_any(text, ["benchmark", "leaderboard", "eval", "evaluation", "基准", "评测"]):
        return "发布评测或基准进展"
    if contains_any(text, ["open source", "open-source", "github", "开源"]):
        return "发布开源或开发者生态进展"
    return "发布一条重要动态"


def is_low_value_item(title: str, description: str) -> bool:
    text = f"{title} {strip_html(description)}".lower()
    return any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in LOW_VALUE_TITLE_PATTERNS)


def is_ai_related(title: str, description: str) -> bool:
    text = f"{title} {strip_html(description)}".lower()
    return any(keyword.lower() in text for keyword in AI_RELEVANCE_KEYWORDS)


def importance_score(source: Source, title: str, summary: str, published: datetime, report_date: date) -> int:
    text = f"{title} {summary}".lower()
    score = source.reliability * 10
    for keyword, weight in KEYWORD_WEIGHTS.items():
        if keyword.lower() in text:
            score += weight
    if source.reliability >= 5:
        score += 6
    if published.date() == report_date:
        score += 3
    if len(summary) > 80:
        score += 2
    return score


def truncate_at_sentence(value: str, limit: int = 320) -> str:
    value = re.sub(r"\s+", " ", strip_html(value)).strip()
    if not value:
        return ""
    if len(value) <= limit:
        return value
    chunk = value[:limit]
    for separator in ["。", ". ", "；", "; ", "！", "! "]:
        index = chunk.rfind(separator)
        if index > limit * 0.45:
            return chunk[: index + len(separator)].strip()
    return chunk.rstrip() + "..."


def detailed_summary_for(source: Source, title: str, description: str) -> str:
    clean_title = strip_html(title)
    clean_description = truncate_at_sentence(description, 320)
    action = action_phrase(clean_title, description)
    signals = signal_phrase(clean_title, description)
    parts = [f"{source.name} {action}"]
    if clean_description:
        parts.append(f"原文要点：{clean_description}")
    else:
        parts.append(f"主题为「{truncate(clean_title, 160)}」")
    parts.append(f"主要涉及：{signals}")
    parts.append("建议打开原文核对具体能力、适用范围和后续影响。")
    return "。".join(parts[:-1]) + "。" + parts[-1]


def extract_jargon_terms(title: str, description: str) -> list[str]:
    text = f"{title} {strip_html(description)}"
    terms: list[str] = []
    for pattern, term in JARGON_TERM_PATTERNS:
        if re.search(pattern, text, flags=re.IGNORECASE) and term not in terms:
            terms.append(term)
        if len(terms) >= 2:
            break
    return terms[:2]


def lookup_wikipedia_summary(term: str, language: str) -> str | None:
    encoded = urllib.parse.quote(term.replace(" ", "_"))
    url = f"https://{language}.wikipedia.org/api/rest_v1/page/summary/{encoded}"
    try:
        payload = json.loads(fetch_text(url, timeout=2))
    except Exception:  # noqa: BLE001 - lookup failures should not block report generation.
        return None
    if payload.get("type") == "disambiguation":
        return None
    extract = str(payload.get("extract") or "").strip()
    if not extract:
        return None
    return truncate(extract, 120)


def lookup_term_explanation(term: str, wiki_budget: list[int]) -> str | None:
    if term in _WIKI_EXPLANATION_CACHE:
        return _WIKI_EXPLANATION_CACHE[term]

    explanation = JARGON_GLOSSARY.get(term)
    if not explanation and wiki_budget[0] > 0:
        wiki_budget[0] -= 1
        explanation = lookup_wikipedia_summary(term, "zh")
        if not explanation and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9\s\-/]*", term):
            explanation = lookup_wikipedia_summary(term, "en")

    _WIKI_EXPLANATION_CACHE[term] = explanation
    return explanation


def enrich_summary_with_glossary(summary: str, title: str, description: str, wiki_budget: list[int]) -> str:
    notes: list[str] = []
    for term in extract_jargon_terms(title, description):
        explanation = lookup_term_explanation(term, wiki_budget)
        if explanation:
            notes.append(f"{term} — {explanation}")
    if not notes:
        return summary
    return summary + "\n\n**术语说明**：" + "；".join(notes)


def headline_for(item: NewsItem) -> str:
    description = item.description or str(item.metadata.get("description", ""))
    action = action_phrase(item.title, description)
    signals = signal_phrase(item.title, description)
    short_title = truncate(strip_html(item.title), 120)
    return f"{item.source_name} {action}：{short_title}，主要涉及{signals}。"


def enrich_item_summaries(items: list[NewsItem], max_wiki_lookups: int = 6) -> None:
    wiki_budget = [max_wiki_lookups]
    for item in sorted(items, key=lambda current: current.score, reverse=True):
        description = item.description or str(item.metadata.get("description", ""))
        item.summary = enrich_summary_with_glossary(item.summary, item.title, description, wiki_budget)


def format_summary_html(summary: str) -> str:
    marker = "\n\n**术语说明**："
    if marker not in summary:
        return f"<p>{html.escape(summary)}</p>"
    main_text, glossary_text = summary.split(marker, 1)
    return (
        f"<p>{html.escape(main_text.strip())}</p>"
        f"<p><b>术语说明</b>：{html.escape(glossary_text.strip())}</p>"
    )


def why_for(source: Source, title: str, summary: str) -> str:
    base = WHY_BY_CATEGORY.get(source.category, "该事件可能影响 AI 产品、技术路线或产业判断，适合作为每日情报跟踪。")
    text = f"{title} {summary}".lower()
    extra = []
    if any(keyword in text for keyword in ["release", "launch", "released", "launched", "发布", "上线"]):
        extra.append("这是明确的发布/上线信号。")
    if any(keyword in text for keyword in ["open source", "open-source", "github", "开源"]):
        extra.append("开源或开发者生态相关内容有助于快速验证和复用。")
    if any(keyword in text for keyword in ["funding", "raises", "valuation", "融资"]):
        extra.append("融资信息可作为资本流向和赛道热度参考。")
    if source.category != "论文 / 研究" and any(
        keyword in text for keyword in ["regulation", "policy", "regulator", "监管", "政策"]
    ):
        extra.append("监管/政策变化可能影响产品合规和市场准入。")
    return " ".join([base, *extra]).strip()


def parse_feed_items(source: Source, xml_text: str, start: datetime, end: datetime, config: Config) -> list[NewsItem]:
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        raise RuntimeError(f"invalid feed XML: {exc}") from exc

    local_tz = ZoneInfo(config.timezone_name)
    entries = root.findall(".//item") or root.findall(".//{http://www.w3.org/2005/Atom}entry")
    items: list[NewsItem] = []
    for entry in entries:
        title = child_text(entry, {"title"})
        link = child_text(entry, {"link", "guid"})
        if not link:
            link = child_attr(entry, {"link"}, "href")
        description = child_text(entry, {"description", "summary", "content", "encoded"})
        if is_low_value_item(title, description):
            continue
        if (source.requires_ai_match or source.reliability <= 4) and not is_ai_related(title, description):
            continue
        published_raw = child_text(entry, {"pubdate", "published", "updated", "date"})
        published = parse_datetime(published_raw)
        if not title or not link or not published:
            continue
        published_local = published.astimezone(local_tz)
        if not (start <= published_local < end):
            continue

        image_url = extract_feed_image(entry, description, link)
        if not image_url and config.fetch_article_images:
            try:
                article_html = fetch_text(link, timeout=12)
                image_url = extract_image_from_html(article_html, link)
                time.sleep(0.15)
            except Exception:
                image_url = ""

        summary = detailed_summary_for(source, strip_html(title), description)
        item = NewsItem(
            title=strip_html(title),
            summary=summary,
            why_important=why_for(source, title, description),
            url=link,
            source_name=source.name,
            source_url=source.source_url,
            category=source.category,
            published_at=published,
            score=importance_score(source, title, description, published, config.report_date),
            description=strip_html(description),
            image_url=image_url,
            image_source_url=image_url or source.source_url,
            image_note=(
                "建议使用原文首图作为 16:9 缩略图。"
                if image_url
                else f"未能自动提取图片；可使用 {source.image_hint} 建议展示为 16:9 缩略图。"
            ),
        )
        items.append(item)
    return items


def collect_feed_items(config: Config) -> tuple[list[NewsItem], list[str]]:
    start, end = report_window(config)
    items: list[NewsItem] = []
    errors: list[str] = []
    for source in AI_SOURCES:
        try:
            xml_text = fetch_text(source.feed_url, timeout=25)
            source_items = parse_feed_items(source, xml_text, start, end, config)
            items.extend(source_items)
            time.sleep(0.25)
        except Exception as exc:  # noqa: BLE001 - per-source errors belong in the report footer.
            errors.append(f"{source.name}: {exc}")
    return items, errors


def arxiv_url_for(report_date: date) -> str:
    stamp = report_date.strftime("%Y%m%d")
    query = f"(cat:cs.AI OR cat:cs.LG OR cat:cs.CL) AND submittedDate:[{stamp}0000 TO {stamp}2359]"
    params = {
        "search_query": query,
        "start": "0",
        "max_results": "30",
        "sortBy": "submittedDate",
        "sortOrder": "descending",
    }
    return "https://export.arxiv.org/api/query?" + urllib.parse.urlencode(params)


def collect_arxiv_items(config: Config) -> tuple[list[NewsItem], str | None]:
    source = Source(
        "arXiv",
        arxiv_url_for(config.report_date),
        "论文 / 研究",
        4,
        "https://arxiv.org/",
        "arXiv 论文页、PDF 首页截图，或论文中的核心架构图/结果表。",
    )
    try:
        xml_text = fetch_text(source.feed_url, timeout=30)
        root = ET.fromstring(xml_text)
    except Exception as exc:  # noqa: BLE001
        return [], f"arXiv: {exc}"

    start, end = report_window(config)
    local_tz = ZoneInfo(config.timezone_name)
    items: list[NewsItem] = []
    for entry in root.findall(".//{http://www.w3.org/2005/Atom}entry"):
        title = child_text(entry, {"title"})
        summary = child_text(entry, {"summary"})
        published = parse_datetime(child_text(entry, {"published", "updated"}))
        link = child_attr(entry, {"link"}, "href") or child_text(entry, {"id"})
        if not title or not summary or not published or not link:
            continue
        if not (start <= published.astimezone(local_tz) < end):
            continue
        score = importance_score(source, title, summary, published, config.report_date)
        if score < 50:
            continue
        clean_title = truncate(strip_html(title), 180)
        paper_summary = detailed_summary_for(source, clean_title, summary)
        items.append(
            NewsItem(
                title=f"论文：{clean_title}",
                summary=paper_summary,
                why_important=why_for(source, title, summary),
                url=link,
                source_name="arXiv",
                source_url=source.source_url,
                category=source.category,
                published_at=published,
                score=score,
                description=strip_html(summary),
                image_source_url=link,
                image_note="建议使用论文 PDF 首页截图，或截取论文中的核心方法图/结果表作为配图。",
                metadata={"kind": "paper"},
            )
        )
    items.sort(key=lambda item: item.score, reverse=True)
    return items[:3], None


def github_search_url(report_date: date) -> str:
    date_text = report_date.isoformat()
    query = f'(llm OR "artificial intelligence" OR "ai agent") created:{date_text}'
    params = {"q": query, "sort": "stars", "order": "desc", "per_page": "10"}
    return "https://api.github.com/search/repositories?" + urllib.parse.urlencode(params)


def collect_github_items(config: Config) -> tuple[list[NewsItem], str | None]:
    url = github_search_url(config.report_date)
    source = Source(
        "GitHub Search",
        url,
        "开源项目 / GitHub",
        3,
        "https://github.com/search",
        "GitHub 仓库 README 截图、项目 logo 或 Star 趋势图。",
    )
    try:
        headers = {"Accept": "application/vnd.github+json"}
        github_token = env_first("GITHUB_TOKEN", "GH_TOKEN")
        if github_token:
            headers["Authorization"] = f"Bearer {github_token}"
        payload = json.loads(fetch_text(url, timeout=30, headers=headers))
    except Exception as exc:  # noqa: BLE001
        return [], f"GitHub Search: {exc}"

    items: list[NewsItem] = []
    for repo in payload.get("items", [])[:8]:
        title = str(repo.get("full_name") or repo.get("name") or "").strip()
        link = str(repo.get("html_url") or "").strip()
        description = str(repo.get("description") or "").strip()
        created = parse_datetime(str(repo.get("created_at") or ""))
        stars = int(repo.get("stargazers_count") or 0)
        if not title or not link or not created:
            continue
        score = 38 + min(stars, 200) // 10
        if description:
            score += 4
        if any(keyword in f"{title} {description}".lower() for keyword in ["agent", "llm", "rag", "inference", "benchmark"]):
            score += 8
        if score < 42:
            continue
        repo_summary = detailed_summary_for(source, title, description)
        if stars:
            repo_summary = repo_summary.replace(
                "建议打开原文核对具体能力、适用范围和后续影响。",
                f"当前 Star 数为 {stars}。建议打开 README 核查功能定位、许可证、维护者和活跃度。",
            )
        items.append(
            NewsItem(
                title=f"开源项目：{title}",
                summary=repo_summary,
                why_important=WHY_BY_CATEGORY["开源项目 / GitHub"],
                url=link,
                source_name="GitHub",
                source_url=source.source_url,
                category=source.category,
                published_at=created,
                score=score,
                description=description,
                image_source_url=link,
                image_note="建议使用仓库 README 顶部截图、项目 logo 或 GitHub Star/活跃度截图作为配图。",
                metadata={"stars": stars},
            )
        )
    items.sort(key=lambda item: item.score, reverse=True)
    return items[:2], None


def deduplicate(items: list[NewsItem]) -> list[NewsItem]:
    by_key: dict[str, NewsItem] = {}
    for item in items:
        keys = [canonical_url(item.url), normalize_title(item.title)]
        existing = next((by_key[key] for key in keys if key in by_key), None)
        if existing is None or item.score > existing.score:
            for key in keys:
                by_key[key] = item
    unique: dict[int, NewsItem] = {}
    for item in by_key.values():
        unique[id(item)] = item
    return list(unique.values())


def rank_items(items: list[NewsItem]) -> list[NewsItem]:
    return sorted(items, key=lambda item: (item.score, item.published_at), reverse=True)


def collect_news(config: Config) -> tuple[list[NewsItem], list[NewsItem], list[str]]:
    feed_items, errors = collect_feed_items(config)
    arxiv_items, arxiv_error = collect_arxiv_items(config)
    github_items, github_error = collect_github_items(config)
    if arxiv_error:
        errors.append(arxiv_error)
    if github_error:
        errors.append(github_error)

    ranked = rank_items(deduplicate([*feed_items, *arxiv_items, *github_items]))
    main_items = ranked[: config.max_items]
    main_urls = {canonical_url(item.url) for item in main_items}
    extension_items = [item for item in ranked[config.max_items :] if canonical_url(item.url) not in main_urls]
    enrich_item_summaries([*main_items, *extension_items[:12]])
    return main_items, extension_items[:12], errors


def html_link(url: str, text: str) -> str:
    return f'<a href="{html.escape(url, quote=True)}">{html.escape(text)}</a>'


def markdown_link(url: str, text: str) -> str:
    escaped_text = text.replace("[", "\\[").replace("]", "\\]")
    return f"[{escaped_text}]({url})"


def image_guidance_markdown(item: NewsItem) -> str:
    image_source = item.image_source_url or item.source_url or item.url
    if item.image_url:
        return (
            f"已在 HTML 邮件中嵌入图片；图片链接：{markdown_link(item.image_url, item.image_url)}。"
            f"{item.image_note} 图片来源：{markdown_link(image_source, image_source)}"
        )
    return f"{item.image_note} 图片来源/截图入口：{markdown_link(image_source, image_source)}"


def image_guidance_html(item: NewsItem) -> str:
    image_source = item.image_source_url or item.source_url or item.url
    if item.image_url:
        return (
            f"<p>已在 HTML 邮件中嵌入图片；"
            f"图片链接：{html_link(item.image_url, item.image_url)}。</p>"
            f"<p>{html.escape(item.image_note)} 图片来源：{html_link(image_source, image_source)}</p>"
        )
    return (
        f"<p>{html.escape(item.image_note)}</p>"
        f"<p>图片来源/截图入口：{html_link(image_source, image_source)}</p>"
    )


def render_markdown(config: Config, items: list[NewsItem], extension_items: list[NewsItem], errors: list[str]) -> str:
    start, end = report_window(config)
    subject_date = config.report_date.isoformat()
    lines = [
        f"# AI 日报：{subject_date}",
        "",
        f"统计窗口：{start:%Y-%m-%d %H:%M:%S %Z} 至 {(end - timedelta(seconds=1)):%Y-%m-%d %H:%M:%S %Z}",
    ]
    if config.test_mode:
        lines.extend(["", "测试说明：这是 AI 日报测试邮件，用于确认中文排版、图片展示和原始链接是否正常。"])

    lines.extend(["", "## 今日重点摘要"])
    if items:
        for item in items[: min(10, max(5, len(items)))]:
            lines.append(f"- **{item.category}**：{headline_for(item)}")
    else:
        lines.append("- 昨天未从配置的信息源中采集到足够可靠的 AI 重要事件。")

    lines.extend(["", "## 重要动态"])
    if items:
        for index, item in enumerate(items, 1):
            published_local = item.published_at.astimezone(ZoneInfo(config.timezone_name))
            lines.extend(
                [
                    f"### {index}. {markdown_link(item.url, item.title)}",
                    f"- 类别：{item.category}",
                    f"- 来源：{item.source_name}｜发布时间：{published_local:%Y-%m-%d %H:%M %Z}",
                    f"- 简短摘要：{item.summary}",
                    f"- 为什么重要：{item.why_important}",
                    f"- 原始信息链接：{markdown_link(item.url, item.url)}",
                    f"- 配图/展示建议：{image_guidance_markdown(item)}",
                    "",
                ]
            )
    else:
        lines.append("暂无符合条件的重要动态。")

    lines.extend(["", "## 延伸阅读"])
    reading_items = [*extension_items[:8]]
    if items:
        reading_items.extend(items[: min(4, len(items))])
    seen: set[str] = set()
    for item in reading_items:
        key = canonical_url(item.url)
        if key in seen:
            continue
        seen.add(key)
        lines.append(f"- {item.source_name}｜{markdown_link(item.url, item.title)}")
    if not seen:
        lines.append("- 暂无延伸阅读。")

    if errors:
        lines.extend(["", "## 采集备注"])
        for error in errors[:10]:
            lines.append(f"- {error}")
    lines.append("")
    lines.append("生成说明：本邮件按信息源可靠性、事件类型、关键词重要性和发布时间排序；建议对重大决策继续打开原文交叉核验。")
    return "\n".join(lines).strip() + "\n"


def render_item_card(item: NewsItem, index: int, config: Config) -> str:
    published_local = item.published_at.astimezone(ZoneInfo(config.timezone_name))
    image_block = ""
    if item.image_url:
        image_block = (
            '<a class="image-link" href="{url}"><img src="{src}" alt="{alt}"></a>'
        ).format(
            url=html.escape(item.url, quote=True),
            src=html.escape(item.image_url, quote=True),
            alt=html.escape(item.title, quote=True),
        )
    else:
        image_block = '<div class="image-placeholder">暂无可直接嵌入的配图，请参考下方图片来源和展示建议。</div>'
    image_caption = image_guidance_html(item)

    return f"""
    <article class="card">
      {image_block}
      <div class="card-body">
        <div class="meta"><span>{html.escape(item.category)}</span><span>{html.escape(item.source_name)}</span><span>{published_local:%Y-%m-%d %H:%M %Z}</span></div>
        <h3>{index}. {html_link(item.url, item.title)}</h3>
        <div class="section"><b>简短摘要</b>{format_summary_html(item.summary)}</div>
        <div class="section"><b>为什么重要</b><p>{html.escape(item.why_important)}</p></div>
        <div class="section"><b>原始信息链接</b><p>{html_link(item.url, item.url)}</p></div>
        <div class="section image-caption"><b>配图/展示建议</b>{image_caption}</div>
      </div>
    </article>
    """


def render_html(config: Config, items: list[NewsItem], extension_items: list[NewsItem], errors: list[str]) -> str:
    start, end = report_window(config)
    subject_date = config.report_date.isoformat()
    summary_items = items[: min(10, max(5, len(items)))]
    summary_html = "\n".join(
        f'<li><span>{html.escape(item.category)}</span>{html.escape(headline_for(item))}</li>'
        for item in summary_items
    )
    if not summary_html:
        summary_html = "<li>昨天未从配置的信息源中采集到足够可靠的 AI 重要事件。</li>"
    test_banner = ""
    if config.test_mode:
        test_banner = (
            '<div class="test-banner">测试说明：这是 AI 日报测试邮件，用于确认中文排版、图片展示和原始链接是否正常。</div>'
        )

    cards = "\n".join(render_item_card(item, index, config) for index, item in enumerate(items, 1))
    if not cards:
        cards = '<div class="empty">暂无符合条件的重要动态。</div>'

    reading_items = [*extension_items[:8]]
    if items:
        reading_items.extend(items[: min(4, len(items))])
    seen: set[str] = set()
    reading_lines = []
    for item in reading_items:
        key = canonical_url(item.url)
        if key in seen:
            continue
        seen.add(key)
        reading_lines.append(f"<li>{html.escape(item.source_name)}｜{html_link(item.url, item.title)}</li>")
    if not reading_lines:
        reading_lines.append("<li>暂无延伸阅读。</li>")
    errors_html = ""
    if errors:
        errors_html = "<h2>采集备注</h2><ul>" + "".join(
            f"<li>{html.escape(error)}</li>" for error in errors[:10]
        ) + "</ul>"

    return f"""<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <style>
    body {{
      margin: 0;
      padding: 0;
      background: #eef2f7;
      color: #111827;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Arial, "PingFang SC", "Microsoft YaHei", sans-serif;
      line-height: 1.6;
    }}
    a {{ color: #2563eb; text-decoration: none; overflow-wrap: anywhere; }}
    .page {{ max-width: 920px; margin: 0 auto; padding: 28px 18px 42px; }}
    .hero {{
      padding: 30px;
      border-radius: 24px;
      color: #fff;
      background: linear-gradient(135deg, #111827 0%, #1d4ed8 58%, #06b6d4 100%);
      box-shadow: 0 18px 45px rgba(15, 23, 42, 0.22);
    }}
    .eyebrow {{ color: #bfdbfe; font-size: 12px; letter-spacing: 1.7px; text-transform: uppercase; font-weight: 800; }}
    h1 {{ margin: 8px 0 10px; font-size: 30px; line-height: 1.25; }}
    .window {{ color: #dbeafe; margin: 0; }}
    .test-banner {{
      margin: 16px 0 0;
      padding: 13px 16px;
      border-radius: 16px;
      background: #fffbeb;
      color: #92400e;
      border: 1px solid #fbbf24;
      font-weight: 800;
    }}
    h2 {{
      margin: 30px 0 14px;
      padding-left: 12px;
      border-left: 5px solid #2563eb;
      font-size: 20px;
      color: #0f172a;
    }}
    .summary {{
      padding: 18px 22px;
      border-radius: 20px;
      background: #fff;
      border: 1px solid #dbe3ef;
      box-shadow: 0 12px 30px rgba(15, 23, 42, 0.07);
    }}
    .summary li {{ margin: 9px 0; }}
    .summary span {{
      display: inline-block;
      margin-right: 8px;
      padding: 2px 8px;
      border-radius: 999px;
      background: #dbeafe;
      color: #1e40af;
      font-size: 12px;
      font-weight: 800;
    }}
    .card {{
      margin: 16px 0 22px;
      overflow: hidden;
      border-radius: 22px;
      background: #fff;
      border: 1px solid #dbe3ef;
      box-shadow: 0 14px 32px rgba(15, 23, 42, 0.08);
    }}
    .image-link {{ display: block; background: #0f172a; }}
    .image-link img {{
      display: block;
      width: 100%;
      max-height: 320px;
      object-fit: cover;
      border: 0;
    }}
    .image-placeholder {{
      padding: 14px 18px;
      background: #f8fafc;
      border-bottom: 1px solid #e5e7eb;
      color: #94a3b8;
      font-size: 13px;
      text-align: center;
    }}
    .card-body {{ padding: 20px; }}
    .meta {{ display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 10px; }}
    .meta span {{
      padding: 4px 9px;
      border-radius: 999px;
      background: #f1f5f9;
      color: #475569;
      font-size: 12px;
      font-weight: 800;
    }}
    .card h3 {{ margin: 8px 0 14px; font-size: 20px; color: #0f172a; line-height: 1.35; }}
    .section {{ margin-top: 12px; padding-top: 12px; border-top: 1px solid #eef2f7; }}
    .section b {{ color: #334155; }}
    .section p {{ margin: 5px 0 0; }}
    .image-caption p {{ color: #475569; font-size: 14px; }}
    .empty, .footer-note, ul.reading, .errors {{
      padding: 16px 20px;
      border-radius: 18px;
      background: #fff;
      border: 1px solid #e5e7eb;
    }}
    ul.reading li {{ margin: 8px 0; }}
    .footer-note {{ color: #475569; margin-top: 18px; }}
    @media (max-width: 640px) {{
      .page {{ padding: 18px 12px 30px; }}
      .hero {{ padding: 22px; border-radius: 20px; }}
      h1 {{ font-size: 24px; }}
      .card-body {{ padding: 16px; }}
    }}
  </style>
</head>
<body>
  <div class="page">
    <div class="hero">
      <div class="eyebrow">AI Intelligence Brief</div>
      <h1>AI 日报：{html.escape(subject_date)}</h1>
      <p class="window">统计窗口：{start:%Y-%m-%d %H:%M:%S %Z} 至 {(end - timedelta(seconds=1)):%Y-%m-%d %H:%M:%S %Z}</p>
    </div>
    {test_banner}
    <h2>今日重点摘要</h2>
    <ol class="summary">{summary_html}</ol>
    <h2>重要动态</h2>
    {cards}
    <h2>延伸阅读</h2>
    <ul class="reading">{''.join(reading_lines)}</ul>
    {errors_html}
    <div class="footer-note">生成说明：本邮件按信息源可靠性、事件类型、关键词重要性和发布时间排序；建议对重大决策继续打开原文交叉核验。</div>
  </div>
</body>
</html>"""


def render_report(config: Config, items: list[NewsItem], extension_items: list[NewsItem], errors: list[str]) -> tuple[str, str, str]:
    subject = f"【AI 日报】{config.report_date.isoformat()} 重要动态"
    if config.test_mode:
        subject = f"【测试】{subject}"
    markdown_body = render_markdown(config, items, extension_items, errors)
    html_body = render_html(config, items, extension_items, errors)
    return subject, markdown_body, html_body


def send_email(config: Config, subject: str, markdown_body: str, html_body: str) -> None:
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = config.smtp_from
    message["To"] = config.recipient_email
    message.set_content(markdown_body)
    message.add_alternative(html_body, subtype="html")

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


def write_output(path: str, html_body: str) -> None:
    with open(path, "w", encoding="utf-8") as file:
        file.write(html_body)


def main() -> int:
    args = parse_args()
    try:
        config = load_config(args)
        items, extension_items, errors = collect_news(config)
        subject, markdown_body, html_body = render_report(config, items, extension_items, errors)
        if config.output_path:
            write_output(config.output_path, html_body)
        if config.dry_run:
            print(subject)
            print(markdown_body)
        else:
            send_email(config, subject, markdown_body, html_body)
            print(f"Sent AI daily report to {config.recipient_email}: {subject}")
        print(
            json.dumps(
                {
                    "report_date": config.report_date.isoformat(),
                    "items": len(items),
                    "extension_items": len(extension_items),
                    "errors": errors,
                },
                ensure_ascii=False,
            )
        )
        return 0
    except Exception as exc:  # noqa: BLE001 - top-level command should print clean diagnostics.
        wrapped = "\n".join(textwrap.wrap(str(exc), width=100))
        print(f"ERROR: {wrapped}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
