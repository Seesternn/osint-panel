# Security policy

## Reporting a vulnerability

Please **do not open a public issue** for security problems. Use GitHub's
[private vulnerability reporting](../../security/advisories/new) for this repository instead.
Include the version / commit, how to reproduce, and the impact. You'll get an answer as soon as possible.

## Security model

- The panel is meant to run **on your own computer**. By default it listens on `127.0.0.1` only, and the
  Docker setup publishes the port on `127.0.0.1` only.
- If you expose it on a network, set `PANEL_TOKEN`: every request then needs the token
  (`?token=` once in the browser, or the `X-Panel-Token` header for the API).
- API keys and case data are stored locally in the data folder (`settings.json`, `cases.db`, `evidence/`),
  never sent anywhere except to the service each key belongs to, and are excluded from git and Docker builds.
- Evidence capture refuses local / private network addresses, and archived HTML is only offered as a
  download — it is never rendered inside the panel.
- Plugins are Python code with full access to the panel: only install plugins you trust.

## Supported versions

Only the latest release on `main` receives fixes.
