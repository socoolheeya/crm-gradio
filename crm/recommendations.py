from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime
from math import isfinite
from typing import Any


@dataclass(frozen=True)
class Recommendation:
    product_id: str
    product_name: str
    category: str
    score: float
    action: str
    channel: str
    evidence: tuple[str, ...]
    message: str


WEIGHTS = {"purchase": 5, "add_to_cart": 4, "wishlist_add": 3, "product_view": 2, "search": 2}


def validate_recommendation(recommendation: Recommendation) -> Recommendation:
    for field in ("product_id", "product_name", "category", "action", "channel", "message"):
        value = getattr(recommendation, field)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{field} must be a non-blank string")

    score = recommendation.score
    if isinstance(score, bool) or not isinstance(score, (int, float)) or not isfinite(score) or not 0 <= score <= 100:
        raise ValueError("score must be a finite number between 0 and 100")

    evidence = recommendation.evidence
    if not evidence or any(not isinstance(reason, str) or not reason.strip() for reason in evidence):
        raise ValueError("evidence must contain non-blank strings")
    return recommendation


def _action(events: list[dict[str, Any]]) -> tuple[str, tuple[str, ...]]:
    types = {e["event_type"] for e in events}
    tags = {tag for e in events for tag in (e.get("crm_tags") or [])}
    purchased = any(e.get("is_purchase") for e in events)
    days = max((e.get("days_since_last_purchase") or 0 for e in events), default=0)
    if "add_to_cart" in types and not purchased:
        return "장바구니 이탈 리마인드", ("장바구니에 담은 후 구매하지 않았습니다",)
    if "coupon_download" in types and not purchased:
        return "쿠폰 만료 알림", ("쿠폰을 다운로드했지만 구매하지 않았습니다",)
    if "휴면위험" in tags or days >= 90:
        return "재활성화 쿠폰", (f"마지막 구매 후 {days}일이 경과했습니다",)
    if any(e.get("is_new_customer") for e in events):
        return "첫 구매 혜택", ("신규 고객입니다",)
    if any((e.get("membership_grade") in {"GOLD", "VIP"}) for e in events):
        return "교차판매 추천", ("우수 등급 고객의 관심 행동이 확인되었습니다",)
    return "관심 상품 리마인드", ("최근 관심 행동을 기반으로 선정했습니다",)


def _profile_bonus(product: dict[str, Any], events: list[dict[str, Any]], tags: set[str]) -> float:
    grades = {event.get("membership_grade") for event in events}
    price = float(product.get("product_price") or 0)
    discount = float(product.get("discount_rate") or 0)
    bonus = 0.0
    if "VIP" in grades and price >= 100_000:
        bonus += 2.5
    elif "GOLD" in grades and price >= 100_000:
        bonus += 1.0
    if any(event.get("is_new_customer") for event in events) and discount >= 10:
        bonus += 1.0
    if "휴면위험" in tags and discount >= 10:
        bonus += 1.5
    return bonus


def recommend_for_customer(events: list[dict[str, Any]], catalog_events: list[dict[str, Any]], limit: int = 3) -> list[Recommendation]:
    if not events:
        return []
    action, base_evidence = _action(events)
    preferred_categories = Counter(e.get("product_category") for e in events if e.get("product_category"))
    preferred = preferred_categories.most_common(1)[0][0] if preferred_categories else None
    tags = {tag for e in events for tag in (e.get("crm_tags") or [])}
    purchased_ids = {
        e.get("product_id") for e in events
        if e.get("product_id") and (e.get("is_purchase") or e.get("event_type") == "purchase")
    }
    channels = Counter(e.get("channel") for e in events if e.get("channel"))
    channel = channels.most_common(1)[0][0] if channels else "app"
    max_time = max((e.get("event_time") for e in events if isinstance(e.get("event_time"), datetime)), default=datetime.now())
    scored: dict[str, float] = defaultdict(float)
    products: dict[str, dict[str, Any]] = {}
    for e in events:
        pid = e.get("product_id")
        if not pid or pid in purchased_ids:
            continue
        products[pid] = e
        weight = WEIGHTS.get(e.get("event_type"), 1)
        if e.get("quantity", 0) > 0:
            weight = max(weight, 4)
        age = max(0, (max_time - e.get("event_time", max_time)).days) if isinstance(e.get("event_time"), datetime) else 0
        scored[pid] += weight * max(0.5, 1 - age / 60)
    for e in catalog_events:
        pid = e.get("product_id")
        if not pid or pid in purchased_ids:
            continue
        category_bonus = 2.0 if e.get("product_category") == preferred else 0.0
        discount_bonus = float(e.get("discount_rate") or 0) / 10 if "할인민감" in tags else 0.0
        profile_bonus = _profile_bonus(e, events, tags)
        if category_bonus + discount_bonus + profile_bonus <= 0:
            continue
        products[pid] = e
        scored[pid] += category_bonus + discount_bonus + profile_bonus
    if not scored:
        return []
    maximum = max(scored.values()) or 1
    results = []
    for pid, raw in sorted(scored.items(), key=lambda item: (-item[1], item[0]))[:limit]:
        product = products[pid]
        score = round(raw / maximum * 100, 1)
        name = product.get("product_name") or pid
        category = product.get("product_category") or "기타"
        message = f"{category}에 관심을 보여주신 고객님께 {name}을 추천드립니다. 지금 혜택을 확인해 보세요."
        results.append(validate_recommendation(
            Recommendation(pid, name, category, score, action, channel, base_evidence, message)
        ))
    return results
