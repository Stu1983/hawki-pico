# HAWKi online backup server

A Cloudflare Worker and one KV namespace (free plan). Picos with **Config → Online backup** turned on upload
once a day under a random ID (`HK-XXXX-XXXX`), so their history survives the Pico dying: **Restore from a backup ID**
on a new Pico's page reads `/u/<ID>` back in. The same ID lets someone helping see that Pico's own pages, read only,
as they stood at the upload: `/v/<ID>`.

Deploy (needs an API token with *Workers Scripts: Edit* and *Workers KV Storage: Edit*):

```
cd cloud/share-worker
export CLOUDFLARE_API_TOKEN=...            # never committed
npx wrangler kv namespace create SHARE     # put the id it prints into wrangler.toml
npx wrangler deploy                        # prints the address, e.g. hawki-share.<account>.workers.dev
```

Who can start a backup: set the invite codes (a secret, never in the repo), one per person so each can be cancelled:

```
npx wrangler secret put INVITES            # e.g.  me=7QM2-XFD9,dave=K3P8-W2AA   ('*' = anyone; unset = nobody new)
```

Taking a name out stops that person's backups (what is there can still be restored). At most `MAX_IDS` backups
(a var in wrangler.toml, default 20) and 8 uploads per backup a day.

For the Picos: either set `HOST` in `firmware/share.py` and release, or type the address under
Config → Online backup → Backup server on each Pico.

Free plan limits that matter: KV 1,000 writes a day (one per upload; a Pico sends three a day), 100,000 reads a day,
1 GB stored (~300 KB to 1 MB a Pico). Over a limit, requests fail until midnight UTC: the free plan never bills. Test: `node test.mjs [upload.json]` (no packages; `NODE_PATH` with jsdom for the page check).
