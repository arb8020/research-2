# Source me: loads Cloudflare creds from ~/research-2/cloudflare.txt into env vars. Never prints them.
# Line layout: 4 account id, 7 api token, 10 R2 access key id, 12 R2 secret, 14 R2 S3 endpoint.
_cf="${CF_CREDS_FILE:-$HOME/research-2/cloudflare.txt}"
export CLOUDFLARE_ACCOUNT_ID="$(sed -n 4p "$_cf" | tr -d '[:space:]')"
export CLOUDFLARE_API_TOKEN="$(sed -n 7p "$_cf" | tr -d '[:space:]')"
export R2_ACCESS_KEY_ID="$(sed -n 10p "$_cf" | tr -d '[:space:]')"
export R2_SECRET_ACCESS_KEY="$(sed -n 12p "$_cf" | tr -d '[:space:]')"
export R2_S3_ENDPOINT="$(sed -n 14p "$_cf" | tr -d '[:space:]')"
unset _cf
