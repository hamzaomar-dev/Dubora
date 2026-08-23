# Security Notes

Dubora Desktop contains **no AI provider API key**.

Provider credentials belong only on the Dubora AI Gateway server as environment secrets. Do not bundle them in Python, JavaScript, `.env` files shipped to users, GitHub, or the EXE.

The gateway validates payload size, limits request frequency, and does not return provider credentials. For a large public launch, replace the in-memory limiter with a shared persistent limiter (for example Redis), add monitoring/spending alerts, and add authentication if abuse risk requires it.

If a provider key existed in an older distributed project copy, revoke/rotate it before using the gateway.
