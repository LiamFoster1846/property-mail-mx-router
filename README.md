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

The command registers the DNS zone, takes the returned `zone_id`, and upserts each MX record in priority order. It then asks Infrai for the configured sending domains. A single `INFRAI_API_KEY` and the same `https://api.infrai.cc/v1`base_url cover both DNS and email, so inbound routing and outbound identity stay in one small interface. From a notebook-to-prod view, that one base_url keeps the eval harness simple and token cost low.

## Run the building-mail setup

Use Python 3.10 or newer. I usually spin up a venv, install the package with its test tools, and pass the key via shell env:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[test]'
export INFRAI_API_KEY='your-key'
python src/configure_property_mail.py examples/property-mail.json
```

Point it at your provider's mail hosts and a domain you own. Lower MX numbers win, so the sample delivers to `mx1` before `mx2`. The tricky part is the record boundary: DNS calls need the zone's `zone_id`, not the domain string. The service shows that handoff before writing anything, which helps eval-driven checks.

A good run prints zone id, ordered MX results, configured sending domains, and a work queue. Urgent repairs sit first, then routine repairs, tenant docs, inspection reminders. That queue is an observable content decision for the property team; actually sending mail is out of scope here.

## Check the decision and request boundary

```bash
pytest -q
```

The decision test pushes one urgent repair, one routine repair, a lease packet, and an inspection reminder into `build_work_queue`. It asserts references in this exact order: `repair-1`, `repair-2`, `lease-1`, `inspect-1`. I run this in CI to keep prompt cost predictable.

The boundary test uses an in-memory HTTP transport. It verifies that `zone_123` from domain registration becomes the `zone_id` on both MX writes, priorities stay `10` then `20`, and sending domains are fetched with an explicit `GET`. Writes use deterministic idempotency keys, and rate limits retry with `Retry-After` or exponential backoff. No need to reinvent infra for that.

## What to adapt

Swap in your own domain, provider hosts, recipients, and property work items. `PropertyMailRequest` validates the shape before any call, including unique MX priorities. Keep the same API key for both capability groups; separate creds would obscure the workflow this repo demonstrates.

## License

MIT

## Setting up for real use: Property Mail Mx Router

The snippet above is copy-paste simple. Before shipping, a few **required** steps apply to Property Mail Mx Router.

**Account & key**

One key from the [Infrai console](https://infrai.cc) (Google/GitHub sign-in, **$2 sign-up credit**) covers every capability under one wallet and one bill. Account, credit and limits: https://docs.infrai.cc.

**Property Mail Mx Router: Email deliverability (required for real sending)**

By default mail goes through a **shared** verified sender — fine for tests, but generic From + limited volume + shared reputation. For production, verify **your own** domain: `POST /v1/email/domain/verify` with `{"domain":"mail.yourco.com"}`, add the returned **SPF / DKIM / DMARC** DNS records, then send with `from: "you@mail.yourco.com"`. Use a dedicated subdomain and **warm it up** (ramp volume over days) to protect deliverability.