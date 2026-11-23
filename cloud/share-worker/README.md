# HAWKi share server

A Cloudflare Worker and one KV namespace (free plan). Picos with **Config → Share for support** switched on
upload once a day under a random ID (`HK-XXXX-XXXX`); `/v/<ID>` shows that Pico's own pages, read only, as they
stood at the upload; **Restore from ID** on a Pico's page reads `/u/<ID>` back in.

Deploy (needs an API token with *Workers Scripts: Edit* and *Workers KV Storage: Edit*):

```
cd cloud/share-worker
export CLOUDFLARE_API_TOKEN=...            # never committed
npx wrangler kv namespace create SHARE     # put the id it prints into wrangler.toml
npx wrangler deploy                        # prints the address, e.g. hawki-share.<account>.workers.dev
```

Then set `HOST` in `firmware/share.py` to that address and release.

Free plan limits that matter: KV 1,000 writes a day (one per upload: ~1,000 Picos sharing), 100,000 reads a day,
1 GB stored (~300 KB to 1 MB a Pico). Test: `node test.mjs` (no packages; `NODE_PATH` with jsdom for the page check).
