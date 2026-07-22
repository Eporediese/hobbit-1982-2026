# Putting it on the internet

The game is a standard-library Python web server, so it runs anywhere that
runs Python or Docker. These notes cover Fly.io (a small always-reachable box,
suspends when idle so it costs pennies) and a plain `docker run` for anything
else.

Whatever you use, the same handful of environment variables configure it:

| Variable | What it does |
|---|---|
| `HOBBIT_PASSWORD` | The shared word. **Set this.** Without it the URL is open to anyone who finds it — including crawlers — and every stranger's turn spends your model credit. |
| `HOBBIT_SECRET` | Signs login tokens. Set it to any long random string so a restart doesn't log the family out. If unset, a restart makes everyone re-enter the word — annoying, not dangerous. |
| `HOBBIT_LLM_URL` / `_MODEL` / `_KEY` | The model that voices the companions (see the README). Unset, the game still plays with scripted companions. |
| `HOBBIT_LLM_FAST_MODEL` | Optional cheaper model for the turn-path goal picks. |
| `HOBBIT_PURIST` | `1` for the raw 1982 game. |

## The one rule that matters

**The model key is a secret. It never goes in a file you commit, and never in
`fly.toml`.** Every platform below takes it as a *secret* set from the command
line, which is stored encrypted and never appears in the repository. A key
committed to this public repo is a key published, and the only fix is to
rotate it.

Confirm before you deploy that no key is staged:

```
git grep -nE "sk-[A-Za-z0-9]{16,}" && echo "STOP — a key is tracked" || echo "clean"
```

## Fly.io

One-time setup:

```
fly launch --no-deploy          # reads fly.toml; creates the app + volume
```

Set the secrets (these are encrypted, not in the repo):

```
fly secrets set \
  HOBBIT_PASSWORD="a word the family will remember" \
  HOBBIT_SECRET="$(openssl rand -hex 32)" \
  HOBBIT_LLM_URL="https://api.ppq.ai" \
  HOBBIT_LLM_MODEL="claude-sonnet-5" \
  HOBBIT_LLM_KEY="<your ppq key>"
```

Then, and for every update after:

```
fly deploy
```

`fly.toml` is set to suspend the machine when idle and wake it on the next
visit, so an unused day costs almost nothing. Journeys live on a mounted
volume, so deploys don't wipe them.

## Plain Docker (any host)

```
docker build -t hobbit .
docker run -d --name hobbit -p 8080:8080 \
  -v hobbit_data:/data \
  -e HOBBIT_PASSWORD="a word" \
  -e HOBBIT_SECRET="$(openssl rand -hex 32)" \
  -e HOBBIT_LLM_URL="https://api.ppq.ai" \
  -e HOBBIT_LLM_MODEL="claude-sonnet-5" \
  -e HOBBIT_LLM_KEY="<your ppq key>" \
  hobbit
```

The `-v hobbit_data:/data` volume is what keeps the family's journeys across
container restarts. Without it, every restart is a new, empty world.

## Before you hand out the link

- Open it yourself and check `tools/check_llm.py` passed first, or the
  companions will be silently scripted.
- Visit on a phone. The page is built to work there, but see it for yourself.
- Give the family the URL **and the word** — the word isn't in the link.

## What this does not do

No accounts, no passwords per person, no HTTPS termination of its own (Fly and
most platforms add that in front). It's a game for people you trust, reachable
by a link and a shared word. If you ever want per-person logins or a shared
world, the session layer was built to grow into both — see `hobbit/sessions.py`.
