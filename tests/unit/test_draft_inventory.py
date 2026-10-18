import copy

from scripts.inventory_order_drafts import classify


def test_inventory_does_not_treat_deleted_orders_as_recoverable():
    order = {
        "id": "r",
        "order_id": "o",
        "customer_email": "private@example.com",
        "metadata": {"_creation": {"state": "complete", "fingerprint": "hash"}},
    }
    before = copy.deepcopy(order)
    report = classify(order, [], [])
    assert report["category"] == "deleted_completed_order_do_not_restore"
    assert "private@example.com" not in str(report)
    assert order == before


def test_inventory_demands_manual_review_for_financial_records():
    order = {
        "id": "r",
        "order_id": "o",
        "metadata": {"_creation": {"state": "building", "fingerprint": "hash"}},
    }
    assert classify(order, [], [])["category"] == "keyed_creation_retry_required"
    assert (
        classify(order, [], [{"id": "p"}])["category"]
        == "payment_present_manual_review"
    )
    assert (
        classify({"id": "r", "order_id": "o"}, [], [])["category"]
        == "legacy_unkeyed_manual_review"
    )
