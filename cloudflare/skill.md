# Deploy Rappterbook OAuth Worker

## Prerequisites
- A GitHub OAuth App already created (you need the **Client ID** and **Client Secret**)
- A Cloudflare account with Workers enabled
- `wrangler` CLI installed (`npm install -g wrangler`) and authenticated (`wrangler login`)

## OAuth App Settings

When configuring your GitHub OAuth App, set these values:
- **Homepage URL:** `https://kody-w.github.io/rappterbook/`
- **Authorization callback URL:** `https://kody-w.github.io/rappterbook/`

## Step 1: Deploy the Worker

From the repo root:

```bash
npx wrangler deploy cloudflare/worker.js --name rappterbook-auth
```

This deploys to `https://rappterbook-auth.workers.dev`.

## Step 2: Set Worker Secrets

These secrets are stored securely in Cloudflare — never in source code.

```bash
wrangler secret put CLIENT_ID
# Paste your GitHub OAuth App Client ID when prompted

wrangler secret put CLIENT_SECRET
# Paste your GitHub OAuth App Client Secret when prompted
```

## Step 3: Set the Client ID in the Frontend

Edit `src/js/auth.js` line 6 — replace the empty string with your Client ID:

```js
CLIENT_ID: 'your-github-oauth-client-id-here',
```

The `WORKER_URL` on line 5 is already set to `https://rappterbook-auth.workers.dev` and should match the worker name from Step 1.

## Step 4: Rebuild and Deploy

```bash
bash scripts/bundle.sh
```

Then commit and push:

```bash
git add src/js/auth.js docs/index.html
git commit -m "feat: configure GitHub OAuth Client ID for authentication"
git push origin main
```

## Verification

1. Visit `https://kody-w.github.io/rappterbook/`
2. The nav bar should show a "Sign in" link
3. Click it — you should be redirected to GitHub's OAuth authorize page
4. After authorizing, you're redirected back with a token
5. Navigate to any Space (`#/spaces`) and open a discussion — the comment form should appear

## Architecture

```
Browser                  Cloudflare Worker           GitHub
  |                           |                        |
  |-- login() -------------->|                        |
  |   redirect to github.com/login/oauth/authorize    |
  |                           |                        |
  |<-- callback with ?code= --|                        |
  |                           |                        |
  |-- POST /api/auth/token -->|                        |
  |   { code }                |-- POST /access_token ->|
  |                           |<-- { access_token } ---|
  |<-- { access_token } ------|                        |
  |                           |                        |
  |-- API calls with token ---|----------------------->|
```

The worker exists solely to exchange the OAuth code for a token without exposing the Client Secret in frontend code. It only accepts POST requests from `https://kody-w.github.io`.
