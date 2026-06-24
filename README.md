# news-for-me

Daily Twitter/X high-value information report automation.

## What it does

`twitter_daily_report.py`:

1. Reads a configurable Twitter/X account list.
2. Fetches each account's public tweets from yesterday's 00:00:00 to 23:59:59 in the configured timezone.
3. Filters out retweets, marketing/giveaway content, very short low-context replies, repeated text, and weak-topic tweets.
4. Keeps tweets related to technology, business, AI, products, investing, macro, policy, developer ecosystems, and industry trends.
5. Renders a Chinese email report with S/A/B importance levels and sends it to the configured recipient.

The script does not fabricate tweets, links, or metrics. If an account has no tweets or cannot be fetched, the report says so.

## Default configuration

- `TWITTER_ACCOUNTS`: `@aleabitoreddit,@justinsuntron,@wufantouzi,@sunyuchentron,@elonmusk,@readDonaldTrump`
- `RECIPIENT_EMAIL`: configured recipient address
- `TIMEZONE`: `Asia/Shanghai`
- `MAX_RESULTS_PER_ACCOUNT`: `200`

## Required environment variables

Twitter/X fetching:

- `APIFY_TOKEN`
- `APIFY_TWITTER_COOKIE` with at least `auth_token=...; ct0=...`

Email delivery:

- `SMTP_HOST`
- `SMTP_PORT` (usually `587` or `465`)
- `SMTP_USERNAME`
- `SMTP_PASSWORD`
- Optional: `SMTP_FROM`
- `RECIPIENT_EMAIL`

Compatibility aliases:

- `EMAIL_TO` can be used instead of `RECIPIENT_EMAIL`.
- `TWITTER_COOKIE` can be used instead of `APIFY_TWITTER_COOKIE`.

## Run locally

Dry run:

```bash
python3 twitter_daily_report.py --dry-run --output report.md
```

Send the email:

```bash
python3 twitter_daily_report.py
```

Generate a report for a specific local date:

```bash
python3 twitter_daily_report.py --date 2026-06-23 --dry-run
```

## Schedule

The included GitHub Actions workflow runs at `0 0 * * *` UTC, which is 08:00 in `Asia/Shanghai`.
