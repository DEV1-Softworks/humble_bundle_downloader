# Changelog

All notable changes to this project are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- `README.md` with setup, configuration, usage, and a Humble Bundle
  Terms-of-Service / personal-use disclaimer.
- `pyproject.toml` with pytest configuration so the `src` package is
  importable when running the test suite.
- Cookie-based authentication: reuse a saved session or pass a browser
  `_simpleauth_sess` cookie so the account password is never stored at
  rest. Sessions are cached to a `0600` file and reused automatically.
- CSRF token handling for the login request and authoritative
  success/failure detection from the JSON response, including Humble
  Guard / two-factor handling and post-login verification.
- Network timeouts on every HTTP request (auth, library, order detail,
  and file downloads); timeouts surface as a clear `HumbleRequestError`.
- Atomic downloads via a `.part` file with size verification before the
  file is moved into place.
- Per-file retries with exponential backoff; failing orders/files are
  logged and skipped instead of aborting the whole run.
- Configurable politeness delay between requests
  (`HUMBLE_REQUEST_DELAY`, default `1.0s`).
- Progress and error logging via the standard `logging` module.
- Test coverage for authentication, timeout handling, filename
  derivation, path-traversal sanitisation, size verification, and
  error-resilient orchestration.

### Changed

- Package layout flattened to `src/` and test imports updated
  accordingly; the CLI is now run as `python -m src.cli`.
- Filenames are derived from the URL path only, so signed-URL query
  strings (`?gamekey=...&ttl=...`) no longer leak into filenames.
- The top-level download folder now uses the real product name from the
  order detail JSON (with the gamekey as a fallback) instead of an empty
  string.
- Path components are sanitised against directory traversal (`.`, `..`,
  leading dots) and control/reserved characters.

### Security

- The Humble Bundle account password is no longer read from the
  environment or `.env`; it is only ever prompted interactively as a
  last resort, and the resulting session is cached instead.
- Cached session files are created with owner-only (`0600`) permissions.
- `.humble_session.json` is git-ignored.

## [0.1.0] - Initial commit

### Added

- Initial Humble Bundle library downloader: HTTP client, download
  orchestration, and CLI.
