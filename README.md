# news-for-me

Daily Chinese Twitter/X intelligence email automation.

## What it does

`twitter_daily_report.py`:

1. Uses `Asia/Shanghai` by default and reports on "yesterday" from 00:00:00 to 23:59:59.
2. Reads the configured Twitter/X account list and fetches public tweets from the reporting window.
3. Filters out low-density replies, pure retweets, marketing/giveaways, repeated content, and off-topic posts.
4. Keeps tweets with value for technology, business, AI, products, investing, macro, policy, industry trends, or developer ecosystems.
5. Generates a Chinese email with S/A/B importance levels, original tweet details, explanation, background, extended judgment, and advice.
6. Sends both plain-text Markdown and styled HTML email through SMTP.

The script does not invent tweets, links, data, or background. If an account cannot be fetched, the email includes the account-level collection error.

## Default configuration

- `TWITTER_ACCOUNTS`: `@aleabitoreddit,@justinsuntron,@wufantouzi,@sunyuchentron,@readDonaldTrump`
- `RECIPIENT_EMAIL`: configured through environment variables or repository secrets
- `TIMEZONE`: `Asia/Shanghai`
- `MAX_RESULTS_PER_ACCOUNT`: `200`

## Required environment variables

Twitter/X collection:

- `APIFY_TOKEN`
- `APIFY_TWITTER_COOKIE` or `TWITTER_COOKIE`
- Optional: `TWITTER_ACCOUNTS` as a comma- or newline-separated account list

Email delivery:

- `SMTP_HOST`
- `SMTP_PORT` (usually `587` or `465`)
- `SMTP_USERNAME`
- `SMTP_PASSWORD`
- Optional: `SMTP_FROM`
- Optional: `RECIPIENT_EMAIL` or `EMAIL_TO`

GitHub Actions uses repository secrets/variables with the same names. The workflow is configured to run at `0 0 * * *` UTC, which is 08:00 in Beijing.

## Run locally

Dry run and write Markdown output:

```bash
python3 twitter_daily_report.py --dry-run --output report.md
```

Send the email:

```bash
python3 twitter_daily_report.py
```

Send a test email with a test marker in the subject:

```bash
python3 twitter_daily_report.py --test
```

Generate a report for a specific Beijing date:

```bash
python3 twitter_daily_report.py --date 2026-06-25 --dry-run
```
