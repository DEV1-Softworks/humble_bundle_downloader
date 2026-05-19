# Humble Bundle Library Downloader

A small command-line tool to back up the files you have **already
purchased** in your own Humble Bundle library. It logs in (or reuses a
saved session), enumerates your orders, and downloads every available
file, organised into a tidy folder tree.

> [!WARNING]
> **Disclaimer — read before using.**
>
> This tool is intended **only** for creating personal backups of
> content **you have legitimately purchased** on your own Humble Bundle
> account. It is **not affiliated with, endorsed by, or supported by
> Humble Bundle**.
>
> Automated access may be contrary to the
> [Humble Bundle Terms of Service](https://www.humblebundle.com/terms).
> Bulk or aggressive scraping can get your account flagged or banned and
> may have legal consequences. You are solely responsible for how you
> use this software.
>
> To reduce risk:
> - Keep the default request delay (or increase it); do not hammer the
>   site.
> - Only download your own purchases. Never share account credentials,
>   session cookies, or downloaded content.
> - Run it infrequently — it is a backup tool, not a sync daemon.

## Features

- **Cookie-first authentication.** Reuse a saved session or paste a
  browser `_simpleauth_sess` cookie, so your password is never stored at
  rest. Password login is only an interactive last resort.
- **CSRF-aware login** with proper success/failure detection and 2FA
  (Humble Guard) support.
- **Atomic downloads.** Files stream to a `.part` file and are only
  renamed into place once complete (and size-verified when the size is
  known), so an interrupted run never leaves a truncated file that looks
  finished.
- **Resilient.** Per-file retries with exponential backoff; a failing
  order or file is logged and skipped instead of aborting the whole run.
- **Polite.** A configurable delay is inserted between requests.
- **Network timeouts** on every request, so a stalled connection can
  never hang the process forever.

## Requirements

- Python 3.11+
- Dependencies in [`requirements.txt`](requirements.txt)

## Setup

```bash
python -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env              # then edit .env
```

## Configuration

All configuration is via environment variables (a local `.env` file is
loaded automatically). See [`.env.example`](.env.example).

| Variable               | Required | Description                                                                 |
| ---------------------- | -------- | --------------------------------------------------------------------------- |
| `HUMBLE_SESSION_COOKIE`| No\*     | Value of the `_simpleauth_sess` cookie from a logged-in browser session.    |
| `HUMBLE_SESSION_FILE`  | No       | Where the authenticated session is cached (default `.humble_session.json`, created with `0600` permissions). |
| `HUMBLE_EMAIL`         | No\*     | Account email, used only for the interactive password-login fallback.       |
| `HUMBLE_2FA_CODE`      | No       | Pre-filled 2FA code for non-interactive runs. Normally left blank.          |
| `HUMBLE_DOWNLOAD_DIR`  | No       | Output directory (default `downloads`).                                     |
| `HUMBLE_REQUEST_DELAY` | No       | Seconds between HTTP requests (default `1.0`).                              |

\* You need **either** a session cookie/saved session **or** to complete
an interactive password login at least once. The password itself is
never read from the environment or `.env` — it is only prompted for.

### Getting your session cookie (recommended)

1. Log in to <https://www.humblebundle.com> in your browser.
2. Open developer tools → Application/Storage → Cookies.
3. Copy the value of the `_simpleauth_sess` cookie.
4. Put it in `.env` as `HUMBLE_SESSION_COOKIE=...`.

After the first successful run the session is cached to
`HUMBLE_SESSION_FILE`, so subsequent runs need no secret at all until it
expires.

## Usage

```bash
python -m src.cli
```

Authentication is attempted in this order:

1. A previously saved session file (no secret needed).
2. `HUMBLE_SESSION_COOKIE` from a logged-in browser.
3. Interactive email/password login (with 2FA prompt if required); the
   resulting session is then saved so the password is not needed again.

Downloads are written as:

```
<HUMBLE_DOWNLOAD_DIR>/<product>/<subproduct>/<platform>/<filename>
```

Re-running is safe: already-downloaded files (matching the expected
size, when known) are skipped.

## Development

```bash
pytest                 # run the test suite
black .                # format
```

See [`AGENTS.md`](AGENTS.md) for contribution conventions and
[`CHANGELOG.md`](CHANGELOG.md) for the change history.

## License

No license is granted. Provided as-is, for personal use only, with no
warranty. See the disclaimer above.
