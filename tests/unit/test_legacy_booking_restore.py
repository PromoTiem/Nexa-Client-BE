from unittest.mock import AsyncMock, patch

from app.application.services.legacy_booking_service import convert_submission


async def test_restored_conversion_dryrun_and_replay():
    pb = AsyncMock()
    pb.find_one_by_filter.return_value = {"config": {}}
    pb.list_records.return_value = {"items": []}
    row = {
        "type": "booking_submission",
        "property_id": "legacy",
        "site_id": "site",
        "metadata": {"service_id": "service"},
        "fields": [
            {"key": key, "value": value}
            for key, value in {
                "name": "Guest",
                "email": "guest@example.com",
                "date": "2026-10-19",
                "start_time": "10:00",
                "end_time": "11:00",
            }.items()
        ],
    }
    with patch(
        "app.application.services.transactional_service.TransactionalService._booking_slot",
        new_callable=AsyncMock,
    ):
        assert (
            await convert_submission(pb, "token", row, source="backfill")
            == "would_convert"
        )
        pb.create_record.assert_not_called()
        assert (
            await convert_submission(pb, "token", row, source="website", apply=True)
            == "converted"
        )
        written = pb.create_record.call_args.args[1]
        assert written["fields"] == row["fields"]
        pb.list_records.return_value = {"items": [{**written, "deleted_at": "now"}]}
        assert (
            await convert_submission(pb, "token", row, source="backfill", apply=True)
            == "existing"
        )
        assert pb.create_record.await_count == 1


async def test_incomplete_source_is_preserved():
    pb = AsyncMock()
    pb.find_one_by_filter.return_value = {"config": {}}
    pb.list_records.return_value = {"items": []}
    row = {
        "type": "booking_submission",
        "property_id": "legacy",
        "site_id": "site",
        "fields": [],
    }
    assert (
        await convert_submission(pb, "token", row, source="backfill", apply=True)
        == "incomplete"
    )
    pb.create_record.assert_not_called()
