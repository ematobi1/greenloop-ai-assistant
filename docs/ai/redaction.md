# Secret redaction

`app/redaction.py` removes secrets from three places: text sent to a model, text a model sends back (streamed and stored), and structured log fields. Matches become `[REDACTED]`.

## What it catches

| Kind | Rule |
|---|---|
| Anthropic and OpenAI style keys | `sk-ant-...`, `sk-...` (20 or more characters) |
| GitHub tokens | `ghp_`, `gho_`, `ghu_`, `ghs_`, `ghr_`, `github_pat_` |
| AWS access key IDs | `AKIA` plus 16 characters |
| Slack tokens | `xox[abprs]-...` |
| JSON Web Tokens | three base64url parts starting `eyJ` |
| Private keys | PEM blocks, and any `BEGIN ... PRIVATE KEY` header |
| Bearer and Authorization values | `Bearer <value>`, `Authorization: <value>` |
| Labelled secrets | `api_key`, `secret`, `token`, `password`, `passwd`, `access_key`, `client_secret` followed by `=` or `:` and a value |
| The GreenLoop API token | Any 43-character URL-safe string whose SHA-256 equals the configured token hash. The server never holds the token itself. |
| Configured credentials | Exact values of variables named in `GREENLOOP_CLAUDE_CLI_ENV_PASSTHROUGH` |

## Limits

Redaction is pattern matching. It cannot know that a string is secret, only that it looks like one.

1. **Unrecognised formats pass through.** A secret with no known prefix, no label, and no matching hash is not caught. Examples: a bare database password, a password after a sentence such as "my login is hunter2hunter2", a key from a service not listed above, a card number, a recovery phrase.
2. **Labels are English.** A Spanish `contraseña: ...` is not caught.
3. **False positives are possible.** A sentence like `token: apple` becomes `token: [REDACTED]`. Short values (under 6 characters) are left alone to limit this.
4. **Obfuscation defeats it.** A secret split with spaces, encoded (base64, hex, reversed), or spelled out is not recognised. The model can also be asked to do this itself, so redaction of model output is a safety net, not a guarantee.
5. **Streaming has a short delay.** Output is held back by up to 32 characters, cut at whitespace, so a secret split across chunks is still matched. A secret longer than 8192 characters without whitespace is cut and can slip through.
6. **Stored user messages are not redacted.** What the user types is saved as typed and returned to the dashboard. Redaction applies to what leaves for the model and to logs. A secret pasted into chat therefore sits in the local SQLite file.
7. **Exact-value matching needs the value.** Only credentials named in configuration are known. A credential that GreenLoop never sees cannot be matched exactly.
8. **Length caps.** Keys are matched up to 200 characters, private key bodies up to 4096.

## What to rely on instead

Do not treat redaction as the protection. The controls that hold when it misses:

- The GreenLoop token and provider credentials are never placed in a prompt in the first place.
- The Claude CLI runs with every tool disabled and is verified at start (`docs/ai/providers.md`), so a model that sees a secret still cannot use it to act.
- The local database and `.env` are git-ignored and stay on this machine.

## Testing

`tests/test_redaction.py` covers each format, chunk sizes from 1 to 50 characters, label and value split across chunks, and the token-by-hash rule. Add a test for every new pattern, and for every leak that is found.
