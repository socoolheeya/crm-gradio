from datetime import datetime

from crm.recommendations import recommend_for_customer


def event(event_type, product="상품", category="뷰티", discount=0, tags=None,
          days_since=10, purchased=False, quantity=0, event_id="E1"):
    return {
        "event_id": event_id,
        "event_time": datetime(2026, 6, 10),
        "customer_id": "C1",
        "membership_grade": "GOLD",
        "is_new_customer": False,
        "channel": "app",
        "event_type": event_type,
        "product_id": product,
        "product_name": product,
        "product_category": category,
        "product_price": 10000,
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
