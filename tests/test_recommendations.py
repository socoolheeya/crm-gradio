from dataclasses import replace
from datetime import datetime

import pytest

from crm.recommendations import Recommendation, recommend_for_customer, validate_recommendation


def event(event_type, product="상품", category="뷰티", discount=0, tags=None,
          days_since=10, purchased=False, quantity=0, event_id="E1",
          membership="GOLD", price=10000, is_new=False):
    return {
        "event_id": event_id,
        "event_time": datetime(2026, 6, 10),
        "customer_id": "C1",
        "membership_grade": membership,
        "is_new_customer": is_new,
        "channel": "app",
        "event_type": event_type,
        "product_id": product,
        "product_name": product,
        "product_category": category,
        "product_price": price,
        "discount_rate": discount,
        "discounted_price": 10000 * (100 - discount) / 100,
        "quantity": quantity,
        "is_purchase": purchased,
        "coupon_downloaded": event_type == "coupon_download",
        "previous_purchase_count": 3,
        "days_since_last_purchase": days_since,
        "crm_tags": tags or [],
        "estimated_segment": "탐색고객",
    }


def test_cart_without_purchase_gets_abandonment_action():
    events = [event("add_to_cart", quantity=1)]
    result = recommend_for_customer(events, events, limit=1)[0]
    assert result.action == "장바구니 이탈 리마인드"
    assert any("장바구니" in reason for reason in result.evidence)


def test_dormant_discount_customer_gets_discounted_candidate():
    customer = [event("product_view", category="식품", tags=["휴면위험", "할인민감"], days_since=120)]
    catalog = [event("product_view", "정가 상품", "식품", 0, event_id="E2"),
               event("product_view", "할인 상품", "식품", 30, event_id="E3")]
    result = recommend_for_customer(customer, catalog, limit=1)[0]
    assert result.product_name == "할인 상품"
    assert result.action == "재활성화 쿠폰"


def test_scores_are_deterministic_and_normalized():
    events = [event("product_view", "A", event_id="E1"), event("wishlist_add", "B", event_id="E2")]
    first = recommend_for_customer(events, events)
    assert first == recommend_for_customer(events, events)
    assert all(0 <= item.score <= 100 for item in first)


def valid_recommendation():
    return Recommendation(
        product_id="P1",
        product_name="추천 상품",
        category="뷰티",
        score=80.0,
        action="관심 상품 리마인드",
        channel="app",
        evidence=("최근 상품을 조회했습니다",),
        message="추천 메시지",
    )


@pytest.mark.parametrize("field", ["product_id", "product_name", "category", "action", "channel", "message"])
def test_recommendation_rejects_blank_required_fields(field):
    with pytest.raises(ValueError, match=field):
        validate_recommendation(replace(valid_recommendation(), **{field: "  "}))


@pytest.mark.parametrize("score", [-0.1, 100.1, float("nan")])
def test_recommendation_rejects_invalid_score(score):
    with pytest.raises(ValueError, match="score"):
        validate_recommendation(replace(valid_recommendation(), score=score))


def test_recommendation_requires_non_blank_evidence():
    with pytest.raises(ValueError, match="evidence"):
        validate_recommendation(replace(valid_recommendation(), evidence=(" ",)))


def test_vip_profile_boosts_premium_candidate():
    customer = [event("product_view", "기존 관심 상품", membership="VIP")]
    catalog = [
        event("product_view", "A 일반 상품", event_id="E2", price=10000),
        event("product_view", "Z 프리미엄 상품", event_id="E3", price=300000),
    ]

    result = recommend_for_customer(customer, catalog, limit=1)

    assert result[0].product_name == "Z 프리미엄 상품"


def test_already_purchased_product_is_filtered_out():
    customer = [
        event("purchase", "구매 완료 상품", purchased=True, quantity=1, event_id="E1"),
        event("wishlist_add", "관심 상품", event_id="E2"),
    ]

    result = recommend_for_customer(customer, customer)

    assert result
    assert all(item.product_id != "구매 완료 상품" for item in result)


def test_unrelated_catalog_product_is_filtered_out():
    customer = [event("product_view", "관심 상품", category="뷰티", membership="BASIC")]
    catalog = [event("product_view", "무관 상품", category="식품", membership="BASIC", event_id="E2")]

    result = recommend_for_customer(customer, catalog, limit=3)

    assert [item.product_name for item in result] == ["관심 상품"]
