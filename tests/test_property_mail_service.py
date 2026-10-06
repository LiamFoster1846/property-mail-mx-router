import httpx

from property_mail_service import InfraiClient, PropertyMailRequest, build_work_queue, configure_property_mail


def test_urgent_repairs_lead_the_property_mail_queue() -> None:
    request = PropertyMailRequest.model_validate(
        {
            "domain": "mail.example.test",
            "mx_targets": [{"host": "mx1.provider.test", "priority": 10}],
            "maintenance_requests": [
                {"request_id": "repair-2", "unit": "3B", "summary": "Leaking tap"},
                {"request_id": "repair-1", "unit": "8A", "summary": "No heat", "urgent": True},
            ],
            "tenant_documents": [
                {
                    "document_id": "lease-1",
                    "unit": "3B",
                    "title": "Renewal notice",
                    "recipient": "tenant@example.test",
                }
            ],
            "inspection_reminders": [
                {
                    "inspection_id": "inspect-1",
                    "unit": "8A",
                    "inspection_date": "2027-01-15",
                    "recipient": "tenant2@example.test",
                }
            ],
        }
    )

    queue = build_work_queue(request)

    assert [item.reference for item in queue] == ["repair-1", "repair-2", "lease-1", "inspect-1"]


def test_setup_uses_zone_id_for_mx_and_lists_sending_domains() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.path.endswith("/dns/domain/add"):
            return httpx.Response(200, json={"ok": True, "data": {"zone_id": "zone_123"}})
        if request.url.path.endswith("/dns/record/upsert"):
            body = __import__("json").loads(request.content)
            return httpx.Response(200, json={"ok": True, "data": body})
        return httpx.Response(
            200,
            json={"ok": True, "data": [{"domain": "sender.example.test", "status": "verified"}]},
        )

    client = InfraiClient("test-key", transport=httpx.MockTransport(handler))
    request = PropertyMailRequest(
        domain="mail.example.test",
        mx_targets=[
            {"host": "mx2.provider.test", "priority": 20},
            {"host": "mx1.provider.test", "priority": 10},
        ],
    )
    try:
        result = configure_property_mail(client, request)
    finally:
        client.close()

    assert result.zone_id == "zone_123"
    assert [record["priority"] for record in result.mx_records] == [10, 20]
    assert all(record["zone_id"] == "zone_123" for record in result.mx_records)
    assert seen[-1].method == "GET"
    assert seen[-1].url.path.endswith("/email/domain/list")
    assert all(request.headers.get("Authorization") == "Bearer test-key" for request in seen)
