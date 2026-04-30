# GitHub Webhooks (B3a)

Dash's fleet supervisor runs every 12 minutes per tenant via cron, but most
of the work it cares about (PR opened, review submitted, issue commented)
is something GitHub can tell us in real time. Configuring webhooks lets the
supervisor react in seconds instead of waiting for the next cron tick.

The cron stays on as a safety net — if a webhook is dropped or the server
was down when the event fired, the next cron tick reconciles state.

## What you configure

In your GitHub App's settings:

1. **Webhook URL**: `https://<your-host>/api/integrations/github/webhook`
   (e.g. `https://dash-pm-demo-production.up.railway.app/api/integrations/github/webhook`)

2. **Webhook secret**: a strong random string. Save the same value as the
   `GITHUB_APP_WEBHOOK_SECRET` env var on your server.

3. **Subscribe to events**:
   - Issues
   - Issue comment
   - Pull request
   - Pull request review

4. **SSL verification**: enabled (default).

## What Dash does on each event

| Event                  | What Dash supervises                                    |
|------------------------|---------------------------------------------------------|
| `issues`               | Comment-mention invocations, agent-assigned issues      |
| `issue_comment`        | `@codex` / `@claude` mentions, refile triggers          |
| `pull_request`         | PR opened against a Dash issue (transitions to review)  |
| `pull_request_review`  | Human review may flip approve/request_changes state     |

For each relevant event:

1. HMAC-verify the `X-Hub-Signature-256` header against the secret.
2. Resolve `installation.id` → tenant via `integration_github_installations`.
3. Spawn a background thread that calls `supervisor.supervise_one(tenant_id,
   repo, issue_number, token)` — focused single-issue version of the cron.

GitHub's retry budget is ~10s, so we 200-ack immediately and run the work
async. Failures inside the thread are logged but never propagated back to
GitHub (a 5xx would just trigger needless retries).

## Failure modes (intentional)

| Condition                            | Response                          |
|--------------------------------------|-----------------------------------|
| `GITHUB_APP_WEBHOOK_SECRET` unset    | 503 (GitHub will retry — set it)  |
| Bad/missing signature                | 401                               |
| Unknown event type                   | 200 + `{"ignored": "<event>"}`    |
| Untracked installation               | 200 + `{"ignored": "untracked"}`  |
| Missing installation.id              | 400                               |
| Malformed JSON                       | 400                               |

The 200-on-untracked-installation is intentional: a user might install the
App into a workspace Dash doesn't track yet (e.g. before completing
onboarding). GitHub should not retry indefinitely in that case.

## Idempotency

The supervisor's handlers use canonical comment markers
(`## Dash Review`, `## Dash Refiled`, `## Dash Stalled`) to detect prior
actions, so handling the same event twice is a no-op. Cron + webhooks are
designed to coexist.

## Local testing

Use [smee.io](https://smee.io) or `gh webhook forward` to tunnel webhooks
to localhost:

```bash
gh webhook forward --repo=<owner>/<repo> --events=issues,issue_comment,pull_request,pull_request_review --url=http://localhost:3001/api/integrations/github/webhook
```
