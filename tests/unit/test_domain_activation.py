from unittest.mock import AsyncMock, patch

from app.application.services.site_deployer import deploy_site


async def test_pending_domain_does_not_report_success():
    cf = AsyncMock()
    cf.get_domain.return_value = {"result": {"status": "pending"}}
    with (
        patch(
            "app.application.services.site_deployer.ensure_project",
            new_callable=AsyncMock,
        ),
        patch(
            "app.application.services.site_deployer.deploy_to_pages",
            new_callable=AsyncMock,
            return_value="https://demo.pages.dev",
        ),
        patch(
            "app.application.services.site_deployer.setup_dns", new_callable=AsyncMock
        ),
        patch(
            "app.application.services.site_deployer.add_custom_domain",
            new_callable=AsyncMock,
        ),
        patch(
            "app.application.services.site_deployer.asyncio.sleep",
            new_callable=AsyncMock,
        ),
    ):
        result = await deploy_site(
            {"index.html": b"demo"}, "demo", cf, "demo.example.com"
        )
    assert result["domain_setup_failed"] is True
    assert result["custom_domain"] is None
    assert cf.get_domain.await_count == 6


async def test_domain_becomes_active_on_retry():
    cf = AsyncMock()
    cf.get_domain.side_effect = [
        {"result": {"status": "pending"}},
        {"result": {"status": "active"}},
    ]
    with (
        patch(
            "app.application.services.site_deployer.ensure_project",
            new_callable=AsyncMock,
        ),
        patch(
            "app.application.services.site_deployer.deploy_to_pages",
            new_callable=AsyncMock,
            return_value="https://demo.pages.dev",
        ),
        patch(
            "app.application.services.site_deployer.setup_dns", new_callable=AsyncMock
        ),
        patch(
            "app.application.services.site_deployer.add_custom_domain",
            new_callable=AsyncMock,
        ),
        patch(
            "app.application.services.site_deployer.asyncio.sleep",
            new_callable=AsyncMock,
        ),
    ):
        result = await deploy_site(
            {"index.html": b"demo"}, "demo", cf, "demo.example.com"
        )
    assert result["domain_setup_failed"] is False
    assert result["custom_domain"] == "demo.example.com"
