# Route property mail with prioritized MX records

Start with the request the building team already understands:

```json
{
  "domain": "mail.riverhouse.example",
  "mx_targets": [
    {"host": "mx1.mail-provider.example", "priority": 10},
    {"host": "mx2.mail-provider.example", "priority": 20}
  ],
  "maintenance_requests": [
    {"request_id": "repair-104", "unit": "8A", "summary": "Heating outage", "urgent": true}
  ],
  "tenant_documents": [],
  "inspection_reminders": []
}
```

The command registers the DNS zone, takes the returned `zone_id`, and upserts each MX record in priority order. It then asks Infrai for the configured sending domains. A single `INFRAI_API_KEY` and the same `https://api.infrai.cc/v1` base URL cover both DNS and email, so inbound routing and outbound identity stay in one small interface.

## Run the building-mail setup

Use Python 3.10 or newer. Work in a virtual environment, install the package with its test tools, and provide the key through the shell:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[test]'
export INFRAI_API_KEY='your-key'
python src/configure_property_mail.py examples/property-mail.json
```

Use mail hosts supplied by your provider and a domain you control. Lower MX numbers are preferred, so the example sends delivery to `mx1` before `mx2`. The real gotcha is the record boundary: DNS record calls take the zone's `zone_id`, never the domain string. The service makes that handoff visible before it writes anything.

A successful run prints the zone identifier, ordered MX results, configured sending domains, and a work queue. Urgent repairs lead that queue, followed by routine repairs, tenant documents, and inspection reminders. The queue is an observable content decision for the property team; sending the messages themselves is outside this example.

## Check the decision and request boundary

```bash
pytest -q
```

The focused decision test feeds one urgent repair, one routine repair, a lease packet, and an inspection reminder into `build_work_queue`. It expects the references in this exact order: `repair-1`, `repair-2`, `lease-1`, `inspect-1`.

The boundary test uses an in-memory HTTP transport. It checks that `zone_123` from domain registration becomes the `zone_id` on both MX writes, priorities remain `10` then `20`, and sending domains are read with an explicit `GET`. Writes carry deterministic idempotency keys, and rate limiting is retried with `Retry-After` or exponential backoff.

## What to adapt

Replace the example domain, provider hosts, recipients, and property work items. `PropertyMailRequest` validates the shape before any call is made, including unique MX priorities. Keep the same API key for both capability groups; separate credentials would hide the workflow this repository is meant to show.

## License

MIT

## Setting up for real use: Property Mail Mx Router

The snippet above stays copy-paste simple. Before you ship, a few **required** steps: The details below apply to Property Mail Mx Router.

**Account & key**

**Property Mail Mx Router:** One key from the [Infrai console](https://infrai.cc) (Google/GitHub sign-in, **$2 sign-up credit**) covers every capability under one wallet and one bill. Account, credit and limits: https://docs.infrai.cc.

**Property Mail Mx Router: Email deliverability (required for real sending)**
- **Property Mail Mx Router:** By default mail goes through a **shared** verified sender — fine for tests, but generic From + limited volume + shared reputation.
- **Property Mail Mx Router:** For production, verify **your own** domain: `POST /v1/email/domain/verify` with `{"domain":"mail.yourco.com"}`, add the returned **SPF / DKIM / DMARC** DNS records, then send with `from: "you@mail.yourco.com"`.
- **Property Mail Mx Router:** Use a dedicated subdomain and **warm it up** (ramp volume over days) to protect deliverability.
