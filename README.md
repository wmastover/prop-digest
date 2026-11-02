# Property Morning Digest

Emails a daily UK residential property digest around 6am UK time on weekdays, built from the RSS feeds in `feeds.yaml` and written by Claude via OpenRouter. Reply to a digest to change what you get: replies are folded into the preferences block at the bottom of `property-digest-agent.md`.

## Secrets

Add these under **Settings → Secrets and variables → Actions** (or `gh secret set -f .env`):

| Secret | What it is |
| --- | --- |
| `OPENROUTER_API_KEY` | OpenRouter API key |
| `GMAIL_ADDRESS` | Gmail account the digest is sent from |
| `GMAIL_APP_PASSWORD` | Gmail app password for that account |
| `DIGEST_TO` | Where the digest goes. Replies go to this address with `+digest` added, so it should be the same mailbox as `GMAIL_ADDRESS` for the feedback loop to see them |

Optional: `DIGEST_MODEL` (default `anthropic/claude-sonnet-5.5`) and `FEEDBACK_MODEL` (default `anthropic/claude-haiku-5.5`) as env vars.

## Gmail app password

1. Turn on 2-Step Verification for the Google account.
2. Go to <https://myaccount.google.com/apppasswords>, create an app password (any name, e.g. "Prop Digest").
3. Use the 16-character password as `GMAIL_APP_PASSWORD`. IMAP must be enabled (it is by default on current Gmail).

## Running

- **Manually:** Actions tab → *Property Morning Digest* → **Run workflow**.
- **Locally:** put the four values in `.env`, `pip install -r requirements.txt`, then `python digest.py --dry-run` (prints the subject and writes `preview.html`; sends nothing, skips feedback, saves no state).

State (`state/covered.json`, `state/last_run.txt`) and preference updates are committed back to the repo after each run.

## Clocks

The cron `30 5 * * 1-5` is in UTC and lands around 6am in UK winter time (Actions can run up to 30 minutes late). When UK clocks go forward in March, change it to `30 4 * * 1-5` in `.github/workflows/digest.yml`, and back again in October.
