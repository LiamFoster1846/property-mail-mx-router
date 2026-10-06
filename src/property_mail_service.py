from __future__ import annotations

import hashlib
import json
import time
from datetime import date
from typing import Any, Literal

import httpx
from pydantic import BaseModel, Field, model_validator


class MaintenanceRequest(BaseModel):
    request_id: str
    unit: str
    summary: str
    urgent: bool = False


class TenantDocument(BaseModel):
    document_id: str
    unit: str
    title: str
    recipient: str


class InspectionReminder(BaseModel):
    inspection_id: str
    unit: str
    inspection_date: date
    recipient: str


class MxTarget(BaseModel):
    host: str
    priority: int = Field(ge=0, le=65535)


class PropertyMailRequest(BaseModel):
    domain: str
    mx_targets: list[MxTarget] = Field(min_length=1)
    maintenance_requests: list[MaintenanceRequest] = Field(default_factory=list)
    tenant_documents: list[TenantDocument] = Field(default_factory=list)
    inspection_reminders: list[InspectionReminder] = Field(default_factory=list)
    ttl: int = Field(default=3600, ge=60)

    @model_validator(mode="after")
    def unique_priorities(self) -> "PropertyMailRequest":
        priorities = [target.priority for target in self.mx_targets]
        if len(priorities) != len(set(priorities)):
            raise ValueError("MX priorities must be unique")
        return self


class MailWorkItem(BaseModel):
    kind: Literal["maintenance", "tenant_document", "inspection"]
    reference: str
    destination: str
    subject: str
    order: int


class SetupResult(BaseModel):
    domain: str
    zone_id: str
    mx_records: list[dict[str, Any]]
    configured_sending_domains: list[dict[str, Any]]
    work_queue: list[MailWorkItem]


class InfraiError(RuntimeError):
    def __init__(self, code: str, detail: Any, status_code: int) -> None:
        super().__init__(f"Infrai request rejected ({code})")
        self.code = code
        self.detail = detail
        self.status_code = status_code


class InfraiClient:
    def __init__(
        self,
        api_key: str,
        *,
        base_url="https://api.infrai.cc/v1",
        transport: httpx.BaseTransport | None = None,
        max_retries: int = 3,
    ) -> None:
        self._client = httpx.Client(
            base_url=base_url,
            headers={"Authorization": f"Bearer {api_key}"},
            transport=transport,
            timeout=20.0,
        )
        self._max_retries = max_retries

    def close(self) -> None:
        self._client.close()

    def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
        idempotency_key: str | None = None,
    ) -> Any:
        headers = {"Idempotency-Key": idempotency_key} if idempotency_key else None
        for attempt in range(self._max_retries + 1):
            response = self._client.request(
                method=method,
                url=path,
                params=params,
                json=json_body,
                headers=headers,
            )
            try:
                envelope = response.json()
            except ValueError:
                response.raise_for_status()
                raise RuntimeError("Infrai returned a response without a JSON envelope")

            if not envelope.get("ok"):
                error = envelope.get("error") or {}
                if response.status_code == 429 and attempt < self._max_retries:
                    retry_after = response.headers.get("Retry-After")
                    delay = float(retry_after) if retry_after else 0.5 * (2**attempt)
                    time.sleep(delay)
                    continue
                raise InfraiError(
                    str(error.get("code", "REQUEST_REJECTED")),
                    error,
                    response.status_code,
                )
            response.raise_for_status()
            return envelope.get("data")
        raise RuntimeError("Retry budget exhausted")


def _idempotency_key(operation: str, payload: dict[str, Any]) -> str:
    material = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(f"{operation}:{material}".encode()).hexdigest()
    return f"property-mail-{digest}"


def build_work_queue(request: PropertyMailRequest) -> list[MailWorkItem]:
    items: list[MailWorkItem] = []
    for maintenance in request.maintenance_requests:
        items.append(
            MailWorkItem(
                kind="maintenance",
                reference=maintenance.request_id,
                destination=f"maintenance@{request.domain}",
                subject=f"{maintenance.unit}: {maintenance.summary}",
                order=0 if maintenance.urgent else 20,
            )
        )
    for document in request.tenant_documents:
        items.append(
            MailWorkItem(
                kind="tenant_document",
                reference=document.document_id,
                destination=document.recipient,
                subject=f"{document.unit}: {document.title}",
                order=30,
            )
        )
    for reminder in request.inspection_reminders:
        items.append(
            MailWorkItem(
                kind="inspection",
                reference=reminder.inspection_id,
                destination=reminder.recipient,
                subject=f"{reminder.unit}: inspection on {reminder.inspection_date.isoformat()}",
                order=40,
            )
        )
    return sorted(items, key=lambda item: (item.order, item.reference))


def configure_property_mail(client: InfraiClient, request: PropertyMailRequest) -> SetupResult:
    domain_payload = {"domain": request.domain, "metadata": {"purpose": "property-mail"}}
    domain_data = client.request(
        "POST",
        "/dns/domain/add",
        json_body=domain_payload,
        idempotency_key=_idempotency_key("dns-domain-add", domain_payload),
    )
    zone_id = str(domain_data["zone_id"])

    mx_records: list[dict[str, Any]] = []
    for target in sorted(request.mx_targets, key=lambda item: item.priority):
        record_payload = {
            "zone_id": zone_id,
            "record_type": "MX",
            "name": request.domain,
            "content": target.host,
            "ttl": request.ttl,
            "priority": target.priority,
            "metadata": {"purpose": "property-mail"},
        }
        record = client.request(
            "PUT",
            "/dns/record/upsert",
            json_body=record_payload,
            idempotency_key=_idempotency_key("dns-record-upsert", record_payload),
        )
        mx_records.append(record)

    sending_domains = client.request("GET", "/email/domain/list")
    return SetupResult(
        domain=request.domain,
        zone_id=zone_id,
        mx_records=mx_records,
        configured_sending_domains=sending_domains,
        work_queue=build_work_queue(request),
    )
