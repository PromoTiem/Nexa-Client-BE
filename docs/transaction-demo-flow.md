# Order and booking API demo flow

This candidate implements the authenticated operator flow with simulated
payments. Prices are entered by an authorized operator, not fetched from a
payment provider or catalog. No money is charged by fake checkout.

## Order -> fake payment -> fulfillment

Use an owner/admin bearer token on each request.

1. `POST /sites/{site_id}/orders`

```json
{"currency":"USD","customer_name":"Demo customer","items":[{"property_id":"service_demo","quantity":2,"unit_price":15.5}]}
```

Returns a pending order, its items, and calculated total `31`.
`POST /orders/{order_id}/items` adds an item; `DELETE /order_items/{item_id}`
removes an item and recalculates the total. The last item cannot be removed.
Items can only change while pending with no unresolved payment.

2. `POST /orders/{order_id}/fake-payment`

```json
{"idempotency_key":"demo_checkout_0001"}
```

Returns a payment with `method: "fake"`, `status: "completed"`, and
`metadata.simulated: true`. The server calculates the amount and marks the
order paid. Reusing this key returns the same payment. A retry repairs an order
status write that failed after payment creation. Calls for one order serialize
on the application's shared-host lock; this is not multi-host idempotency.
The payment response explicitly says no money was charged.

3. `PATCH /orders/{order_id}` with `{"status":"fulfilled"}` completes it.

Alternatively PATCH `{"status":"cancelled"}` while pending or paid. For a
fake-paid order, its simulated payment becomes cancelled too. Real completed
payments must be resolved separately. Directly PATCHing pending -> paid is
rejected; use the payment flow. Terminal orders cannot be resurrected.

`GET /orders/{order_id}`, `GET /sites/{site_id}/orders`, and
`GET /orders/{order_id}/payments` expose progress. Detail reads include all item
and payment pages. Manual payment recording remains a separate existing API;
it is not a real gateway integration.

## Booking -> confirmation -> completion/cancellation

1. Optionally configure `POST /sites/{site_id}/availability`:

```json
{"property_id":"service_demo","day_of_week":"monday","start_time":"09:00","end_time":"17:00","max_bookings":1,"is_active":true}
```

Weekdays are lowercase English names. Times are `HH:MM`, on the same day.
Capacity `0` means unlimited. Once a service has availability records, a booking
must fit entirely inside an active window and respect its concurrent capacity.
With no availability records, manual scheduling is allowed. Existing bookings
are not automatically moved or cancelled when weekly hours change.

2. `POST /sites/{site_id}/bookings`:

```json
{"property_id":"service_demo","customer_name":"Demo guest","customer_email":"demo@example.com","date":"2026-10-19","start_time":"10:00","end_time":"11:00","fields":[]}
```

The property must be a published `spa_service` on this site. Invalid dates,
time ranges, emails, unavailable hours, and full slots are rejected. Pending
and confirmed bookings consume capacity; cancelled bookings release it.
Dates/times are site-local wall-clock values; no timezone conversion is done.

3. `PATCH /bookings/{booking_id}` with `{"status":"confirmed"}`, then
   `{"status":"completed"}`. Pending/confirmed can instead become cancelled.
   Completion cannot skip confirmation. Terminal bookings cannot be rescheduled.

GET list/detail endpoints return the linked service and customer/dynamic fields.
Pending/cancelled bookings can be soft-deleted; confirmed bookings must first be
cancelled, and completed history is retained. Availability supports list, create,
update, and delete through the existing endpoints.

## Failure behavior and scope

- Order creation remains hidden until all items persist. Interrupted creation
  leaves retained draft data for diagnosis rather than exposing a partial order.
  Automated cleanup/recovery of those hidden drafts is not implemented.
- Booking/availability mutations take the shared site lock and recheck lifecycle.
- Fake payments and order mutations serialize per order. Database-atomic writes,
  multi-host coordination, and direct PocketBase authorization remain separate
  from these application checks.
- This is the authenticated backend flow. No frontend screens, public booking
  dual-write/backfill changes, production schema migration, or deployment are
  included. The legacy schema script still needs the timestamp and zero/false
  corrections documented by the ownership design before deployment.

## Verification

```bash
TMPDIR=/tmp/opencode NEXA_TEST_POCKETBASE_BINARY=/path/to/pocketbase \
  python3 -m pytest tests/flows -q -o addopts=''
python3 -m pytest tests/unit -q -o addopts=''
```

Seven HTTP/service/persistence flow tests passed on fresh PocketBase 0.39.0,
including concurrent fake-payment retries, payment partial-write repair,
concurrent capacity checks, cancellation/fulfillment, invalid bookings,
role/tenant/lifecycle checks, and hidden partial order creation. **384 unit
tests passed.** The flow fixtures inject identity and use a disposable superuser
persistence client with corrected minimal schema; they do not certify production
login, caller-token collection rules, or deployed migration compatibility.
