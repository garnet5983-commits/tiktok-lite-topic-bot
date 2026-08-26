#!/usr/bin/env python3
"""TikTok Lite / TikTok topic collector and LINE notifier.

The free prototype intentionally uses public search RSS feeds. It does not log
in to, scrape private areas of, or automate actions on X, Threads, or Instagram.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


LINE_PUSH_ENDPOINT = "https://api.line.me/v2/bot/message/push"
JST = ZoneInfo("Asia/Tokyo")
USER_AGENT = (
    "Mozilla/5.0 (compatible; TikTokLiteTopicBot/0.1; "
    "+https://github.com/)"
)
DIRECT_SOCIAL_DOMAINS = {
    "x.com",
    "twitter.com",
    "threads.net",
    "www.threads.net",
    "instagram.com",
    "www.instagram.com",
}


@dataclass
class Topic:
    id: str
    platform: str
    title: str
    url: str
    summary: str
    published_at: str | None
    search_provider: str
    score: int = 0


def clean_text(value: str | None) -> str:
    if not value:
        return ""
    value = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", value)
    value = re.sub(r"(?s)<[^>]+>", " ", value)
    value = html.unescape(value)
    return re.sub(r"\s+", " ", value).strip()


def normalize(value: str) -> str:
    value = unicodedata.normalize("NFKC", clean_text(value)).casefold()
    return re.sub(r"\s+", " ", value).strip()


def normalized_title_key(value: str) -> str:
    value = re.sub(r"https?://\S+", "", normalize(value))
    value = re.sub(r"[^0-9a-z\u3040-\u30ff\u3400-\u9fff]+", "", value)
    return value[:400]


def topic_id(platform: str, title: str, url: str) -> str:
    title_key = normalized_title_key(title)
    if not title_key:
        title_key = normalize(url)
    raw = f"{platform.casefold()}|{title_key}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:24]


def parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    value = value.strip()
    try:
        parsed = parsedate_to_datetime(value)
    except (TypeError, ValueError, OverflowError):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def child_text(node: ET.Element, names: set[str]) -> str:
    for child in list(node):
        local_name = child.tag.rsplit("}", 1)[-1].casefold()
        if local_name in names and child.text:
            return child.text.strip()
    return ""


def entry_link(node: ET.Element) -> str:
    for child in list(node):
        if child.tag.rsplit("}", 1)[-1].casefold() != "link":
            continue
        href = child.attrib.get("href", "").strip()
        if href:
            return href
        if child.text:
            return child.text.strip()
    return ""


def strip_platform_suffix(title: str) -> str:
    return re.sub(
        r"\s+(?:[-–—|]\s*)?(?:X|Twitter|Threads|Instagram)\s*$",
        "",
        title,
        flags=re.IGNORECASE,
    ).strip()


def parse_feed(
    xml_bytes: bytes,
    *,
    platform: str,
    search_provider: str,
    lookback_hours: int,
    now: datetime | None = None,
) -> list[Topic]:
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=lookback_hours)
    root = ET.fromstring(xml_bytes)
    entries = [
        node
        for node in root.iter()
        if node.tag.rsplit("}", 1)[-1].casefold() in {"item", "entry"}
    ]

    topics: list[Topic] = []
    for entry in entries:
        title = strip_platform_suffix(
            clean_text(child_text(entry, {"title"}))
        )
        url = entry_link(entry) or child_text(entry, {"guid", "id"})
        summary = clean_text(
            child_text(entry, {"description", "summary", "content"})
        )
        raw_date = child_text(
            entry, {"pubdate", "published", "updated", "date"}
        )
        published = parse_datetime(raw_date)

        if not title or not url:
            continue
        if published and published < cutoff:
            continue

        topics.append(
            Topic(
                id=topic_id(platform, title, url),
                platform=platform,
                title=title,
                url=url,
                summary=summary,
                published_at=published.isoformat() if published else None,
                search_provider=search_provider,
            )
        )
    return topics


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"{path} の内容はJSONオブジェクトにしてください")
    return data


def validate_config(config: dict[str, Any]) -> None:
    if not config.get("keywords"):
        raise ValueError("config.json の keywords が空です")
    if not config.get("platforms"):
        raise ValueError("config.json の platforms が空です")
    if not config.get("search_providers"):
        raise ValueError("config.json の search_providers が空です")
    if not any(item.get("enabled", True) for item in config["platforms"]):
        raise ValueError("有効なSNSがありません")
    if not any(item.get("enabled", True) for item in config["search_providers"]):
        raise ValueError("有効な公開検索がありません")


def build_query(keywords: list[str], domains: list[str]) -> str:
    quoted_terms = " OR ".join(f'"{term}"' for term in keywords)
    site_terms = " OR ".join(f"site:{domain}" for domain in domains)
    return f"({quoted_terms}) ({site_terms})"


def build_feed_url(provider_kind: str, query: str, lookback_hours: int) -> str:
    if provider_kind == "bing_web_rss":
        params = {
            "q": query,
            "format": "rss",
            "setlang": "ja-JP",
            "cc": "JP",
        }
        return "https://www.bing.com/search?" + urllib.parse.urlencode(params)
    if provider_kind == "google_news_rss":
        days = max(1, (lookback_hours + 23) // 24)
        params = {
            "q": f"{query} when:{days}d",
            "hl": "ja",
            "gl": "JP",
            "ceid": "JP:ja",
        }
        return "https://news.google.com/rss/search?" + urllib.parse.urlencode(
            params
        )
    raise ValueError(f"未対応の検索方式です: {provider_kind}")


def fetch_url(url: str, *, attempts: int = 3, timeout: int = 25) -> bytes:
    last_error: Exception | None = None
    for attempt in range(attempts):
        request = urllib.request.Request(
            url,
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "application/rss+xml, application/xml, text/xml",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return response.read()
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            last_error = error
            if attempt + 1 < attempts:
                time.sleep(2**attempt)
    raise RuntimeError(f"公開検索の取得に失敗しました: {last_error}")


def matches_required_terms(topic: Topic, required_terms: list[str]) -> bool:
    haystack = normalize(f"{topic.title} {topic.summary}")
    return any(normalize(term) in haystack for term in required_terms)


def matches_any_terms(topic: Topic, terms: list[str]) -> bool:
    if not terms:
        return True
    haystack = normalize(f"{topic.title} {topic.summary}")
    return any(normalize(term) in haystack for term in terms)


def matches_blocked_terms(topic: Topic, terms: list[str]) -> bool:
    if not terms:
        return False
    haystack = normalize(f"{topic.title} {topic.summary}")
    return any(normalize(term) in haystack for term in terms)


def is_social_profile_or_home_url(url: str) -> bool:
    """Reject social profile/home links; notifications should point to posts."""
    try:
        parsed = urllib.parse.urlparse(url)
    except ValueError:
        return False
    host = (parsed.hostname or "").casefold().removeprefix("www.")
    path = parsed.path.casefold()
    if host in {"x.com", "twitter.com"}:
        return "/status/" not in path
    if host == "instagram.com":
        return not path.startswith(("/p/", "/reel/", "/tv/"))
    if host == "threads.net":
        return "/post/" not in path and not path.startswith("/t/")
    return False


def direct_link_quality(url: str) -> int:
    try:
        host = urllib.parse.urlparse(url).hostname or ""
    except ValueError:
        return 0
    host = host.casefold()
    if host in DIRECT_SOCIAL_DOMAINS:
        return 3
    if host.endswith("google.com") or host.endswith("bing.com"):
        return 0
    return 1


def score_topic(topic: Topic, score_terms: dict[str, int], now: datetime) -> int:
    title = normalize(topic.title)
    body = normalize(f"{topic.title} {topic.summary}")
    score = direct_link_quality(topic.url)
    for term, weight in score_terms.items():
        normalized_term = normalize(term)
        if normalized_term in title:
            score += int(weight) * 2
        elif normalized_term in body:
            score += int(weight)

    published = parse_datetime(topic.published_at)
    if published:
        age_hours = max(0, (now - published).total_seconds() / 3600)
        if age_hours <= 6:
            score += 10
        elif age_hours <= 24:
            score += 5
        elif age_hours <= 48:
            score += 2
    return score


def merge_topic(current: Topic | None, candidate: Topic) -> Topic:
    if current is None:
        return candidate
    current_quality = direct_link_quality(current.url)
    candidate_quality = direct_link_quality(candidate.url)
    if candidate_quality > current_quality:
        candidate.summary = candidate.summary or current.summary
        candidate.published_at = candidate.published_at or current.published_at
        return candidate
    if len(candidate.summary) > len(current.summary):
        current.summary = candidate.summary
    if not current.published_at and candidate.published_at:
        current.published_at = candidate.published_at
    return current


def collect_topics(
    config: dict[str, Any], *, now: datetime | None = None
) -> tuple[list[Topic], list[str]]:
    now = now or datetime.now(timezone.utc)
    lookback_hours = int(config.get("lookback_hours", 48))
    required_terms = list(config.get("required_terms", ["TikTok", "ティックトック"]))
    interest_terms = list(config.get("required_interest_terms", []))
    blocked_terms = list(config.get("blocked_terms", []))
    min_score = int(config.get("min_score", 0))
    score_terms = {
        str(key): int(value)
        for key, value in config.get("score_terms", {}).items()
    }
    merged: dict[str, Topic] = {}
    errors: list[str] = []
    successful_requests = 0

    enabled_providers = [
        provider
        for provider in config["search_providers"]
        if provider.get("enabled", True)
    ]
    enabled_platforms = [
        platform
        for platform in config["platforms"]
        if platform.get("enabled", True)
    ]

    for platform in enabled_platforms:
        platform_name = str(platform["name"])
        query = build_query(list(config["keywords"]), list(platform["domains"]))
        for provider in enabled_providers:
            provider_name = str(provider["name"])
            try:
                url = build_feed_url(
                    str(provider["kind"]), query, lookback_hours
                )
                feed = fetch_url(url)
                parsed = parse_feed(
                    feed,
                    platform=platform_name,
                    search_provider=provider_name,
                    lookback_hours=lookback_hours,
                    now=now,
                )
                successful_requests += 1
                for topic in parsed:
                    if not matches_required_terms(topic, required_terms):
                        continue
                    if not matches_any_terms(topic, interest_terms):
                        continue
                    if matches_blocked_terms(topic, blocked_terms):
                        continue
                    if is_social_profile_or_home_url(topic.url):
                        continue
                    merged[topic.id] = merge_topic(merged.get(topic.id), topic)
            except Exception as error:  # Keep other sources running.
                errors.append(f"{platform_name}/{provider_name}: {error}")

    if enabled_platforms and enabled_providers and successful_requests == 0:
        details = " | ".join(errors[:3])
        raise RuntimeError(f"すべての公開検索が失敗しました。{details}")

    for topic in merged.values():
        topic.score = score_topic(topic, score_terms, now)
    topics = sorted(
        (topic for topic in merged.values() if topic.score >= min_score),
        key=lambda item: (item.score, item.published_at or "", item.id),
        reverse=True,
    )
    return topics, errors


def load_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"version": 1, "seen": {}, "last_successful_run": None}
    state = load_json(path)
    seen = state.get("seen", {})
    if isinstance(seen, list):
        seen = {str(item): "1970-01-01T00:00:00+00:00" for item in seen}
    if not isinstance(seen, dict):
        seen = {}
    state["version"] = 1
    state["seen"] = seen
    return state


def shorten(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    return value[: max(1, limit - 1)].rstrip() + "…"


def build_line_messages(
    topics: list[Topic],
    *,
    total_new: int,
    max_items: int,
    now: datetime,
) -> list[str]:
    selected = topics[:max_items]
    counts: dict[str, int] = {}
    for topic in topics:
        counts[topic.platform] = counts.get(topic.platform, 0) + 1
    count_text = "・".join(
        f"{name} {count}件" for name, count in counts.items()
    )
    header = (
        "📡 TikTok Lite・ポイ活 新着\n"
        f"新着 {total_new}件｜{count_text}\n"
    )
    footer = (
        f"\n確認：{now.astimezone(JST).strftime('%Y/%m/%d %H:%M')}\n"
        "※無料試作版：公開検索に掲載された投稿のみ"
    )
    if total_new > len(selected):
        footer = (
            f"\nほか {total_new - len(selected)}件は通知上限のため省略"
            + footer
        )

    messages: list[str] = []
    current = header
    for index, topic in enumerate(selected, start=1):
        entry = f"\n{index}.【{topic.platform}】{shorten(topic.title, 150)}\n{topic.url}\n"
        if len(current) + len(entry) > 4500:
            messages.append(current.rstrip())
            current = "📡 TikTok Lite・ポイ活 新着（続き）\n" + entry
        else:
            current += entry

    if len(current) + len(footer) > 4900:
        messages.append(current.rstrip())
        current = "📡 TikTok Lite・ポイ活 新着（続き）\n" + footer.lstrip()
    else:
        current += footer
    messages.append(current.rstrip())

    if len(messages) > 5:
        messages = messages[:5]
        messages[-1] = shorten(messages[-1], 4850) + "\n（表示上限に到達）"
    return messages


def line_credentials() -> tuple[str, str]:
    token = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", "").strip()
    user_id = os.environ.get("LINE_USER_ID", "").strip()
    if not token:
        raise RuntimeError(
            "GitHub Secrets に LINE_CHANNEL_ACCESS_TOKEN を登録してください"
        )
    if not re.fullmatch(r"U[0-9a-fA-F]{32}", user_id):
        raise RuntimeError(
            "GitHub Secrets の LINE_USER_ID を確認してください（Uから始まる33文字）"
        )
    return token, user_id


def send_line(messages: list[str]) -> None:
    if not messages or len(messages) > 5:
        raise RuntimeError("LINE通知は1〜5個のメッセージにしてください")
    if any(len(message.encode("utf-16-le")) // 2 > 5000 for message in messages):
        raise RuntimeError("LINE通知文が5000文字の上限を超えています")
    token, user_id = line_credentials()
    payload = json.dumps(
        {
            "to": user_id,
            "messages": [{"type": "text", "text": text} for text in messages],
        },
        ensure_ascii=False,
    ).encode("utf-8")
    request = urllib.request.Request(
        LINE_PUSH_ENDPOINT,
        data=payload,
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json; charset=utf-8",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=25) as response:
            if not 200 <= response.status < 300:
                raise RuntimeError(f"LINE通知に失敗しました（HTTP {response.status}）")
    except urllib.error.HTTPError as error:
        detail = clean_text(error.read(1000).decode("utf-8", errors="replace"))
        raise RuntimeError(
            f"LINE通知に失敗しました（HTTP {error.code}）: {detail}"
        ) from error
    except urllib.error.URLError as error:
        raise RuntimeError(f"LINE通知への接続に失敗しました: {error.reason}") from error


def write_json_atomic(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
    temporary.replace(path)


def update_state(
    state: dict[str, Any], topics: list[Topic], now: datetime, retention: int
) -> dict[str, Any]:
    timestamp = now.isoformat()
    seen: dict[str, str] = dict(state.get("seen", {}))
    for topic in topics:
        seen.setdefault(topic.id, timestamp)
    if len(seen) > retention:
        newest = sorted(seen.items(), key=lambda pair: pair[1], reverse=True)
        seen = dict(newest[:retention])
    return {
        "version": 1,
        "seen": seen,
        "last_successful_run": timestamp,
    }


def run(args: argparse.Namespace) -> int:
    now = datetime.now(timezone.utc)
    if args.test_line:
        send_line(
            [
                "✅ TikTok Lite話題BOT\n"
                "LINE通知の接続テストに成功しました。\n"
                f"確認：{now.astimezone(JST).strftime('%Y/%m/%d %H:%M')}"
            ]
        )
        print("LINE test notification sent successfully.")
        return 0

    config_path = Path(args.config)
    state_path = Path(args.state)
    latest_path = Path(args.latest)
    config = load_json(config_path)
    validate_config(config)
    state = load_state(state_path)

    if not args.dry_run:
        line_credentials()

    topics, partial_errors = collect_topics(config, now=now)
    seen_ids = set(state.get("seen", {}))
    new_topics = [topic for topic in topics if topic.id not in seen_ids]
    max_items = int(config.get("max_items_per_notification", 20))
    messages: list[str] = []

    if new_topics:
        messages = build_line_messages(
            new_topics,
            total_new=len(new_topics),
            max_items=max_items,
            now=now,
        )
        if args.dry_run:
            print("\n\n--- LINE MESSAGE ---\n\n".join(messages))
        else:
            send_line(messages)
    else:
        print("No new topics. LINE notification was skipped.")

    print(
        f"Collected={len(topics)} New={len(new_topics)} "
        f"PartialErrors={len(partial_errors)}"
    )
    for error in partial_errors:
        print(f"WARNING: {error}", file=sys.stderr)

    if args.dry_run:
        return 0

    updated_state = update_state(
        state,
        topics,
        now,
        retention=int(config.get("state_retention", 3000)),
    )
    latest = {
        "checked_at": now.isoformat(),
        "mode": "free_public_search",
        "total_found": len(topics),
        "new_found": len(new_topics),
        "line_notified": bool(new_topics),
        "partial_errors": partial_errors,
        "items": [asdict(topic) for topic in topics[:100]],
    }
    write_json_atomic(state_path, updated_state)
    write_json_atomic(latest_path, latest)
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="TikTok Lite話題収集LINE BOT")
    parser.add_argument("--config", default="config.json")
    parser.add_argument("--state", default="data/state.json")
    parser.add_argument("--latest", default="data/latest.json")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="LINE送信と状態更新を行わず、通知内容を表示します",
    )
    parser.add_argument(
        "--test-line",
        action="store_true",
        help="収集せず、LINE接続テストだけを行います",
    )
    return parser.parse_args(argv)


def main() -> None:
    try:
        raise SystemExit(run(parse_args()))
    except (RuntimeError, ValueError, ET.ParseError, json.JSONDecodeError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        raise SystemExit(1) from error


if __name__ == "__main__":
    main()
