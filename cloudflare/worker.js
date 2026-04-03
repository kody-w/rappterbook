/**
 * Rappterbook OAuth Token Exchange Worker
 *
 * Deploy to Cloudflare Workers. Set these secrets:
 *   wrangler secret put CLIENT_ID
 *   wrangler secret put CLIENT_SECRET
 *
 * Allowed origin should match your GitHub Pages URL.
 */

const ALLOWED_ORIGIN = 'https://kody-w.github.io';

function corsHeaders() {
  return {
    'Access-Control-Allow-Origin': ALLOWED_ORIGIN,
    'Access-Control-Allow-Methods': 'POST, OPTIONS',
    'Access-Control-Allow-Headers': 'Content-Type, Authorization',
  };
}

function jsonResponse(body, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: {
      'Content-Type': 'application/json',
      ...corsHeaders(),
    },
  });
}

export default {
  async fetch(request, env) {
    // CORS preflight
    if (request.method === 'OPTIONS') {
      return new Response(null, { headers: corsHeaders() });
    }

    if (request.method !== 'POST') {
      return new Response('Method not allowed', { status: 405 });
    }

    const url = new URL(request.url);

    // ── Device Code: proxy to GitHub (browsers can't call this directly) ──
    if (url.pathname === '/api/auth/device-code') {
      try {
        const body = await request.json();
        const resp = await fetch('https://github.com/login/device/code', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', 'Accept': 'application/json' },
          body: JSON.stringify(body),
        });
        const data = await resp.json();
        return jsonResponse(data, resp.status);
      } catch (err) {
        return jsonResponse({ error: 'Device code request failed' }, 502);
      }
    }

    // ── Device Poll: proxy token polling to GitHub ──
    if (url.pathname === '/api/auth/device-poll') {
      try {
        const body = await request.json();
        const resp = await fetch('https://github.com/login/oauth/access_token', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', 'Accept': 'application/json' },
          body: JSON.stringify(body),
        });
        const data = await resp.json();
        return jsonResponse(data, resp.status);
      } catch (err) {
        return jsonResponse({ error: 'Token poll failed' }, 502);
      }
    }

    // ── GitHub Token Exchange: receive access_token, return user info ──
    if (url.pathname === '/api/auth/github') {
      try {
        const { access_token } = await request.json();
        if (!access_token) return jsonResponse({ error: 'Missing access_token' }, 400);

        // Fetch GitHub user profile
        const userResp = await fetch('https://api.github.com/user', {
          headers: { 'Authorization': `Bearer ${access_token}`, 'Accept': 'application/json', 'User-Agent': 'Rappterbook' },
        });
        if (!userResp.ok) return jsonResponse({ error: 'GitHub user fetch failed' }, 401);
        const user = await userResp.json();

        return jsonResponse({
          token: access_token,
          user: { login: user.login, name: user.name || user.login, avatar_url: user.avatar_url },
        });
      } catch (err) {
        return jsonResponse({ error: 'GitHub auth failed' }, 500);
      }
    }

    // ── OAuth Code Exchange (legacy redirect flow) ──
    if (url.pathname === '/api/auth/token') {
      try {
        const { code } = await request.json();
        if (!code) return jsonResponse({ error: 'Missing code' }, 400);

        const tokenResponse = await fetch('https://github.com/login/oauth/access_token', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', 'Accept': 'application/json' },
          body: JSON.stringify({
            client_id: env.CLIENT_ID,
            client_secret: env.CLIENT_SECRET,
            code,
          }),
        });
        const data = await tokenResponse.json();
        if (data.error) return jsonResponse({ error: data.error_description || data.error }, 400);
        return jsonResponse({ access_token: data.access_token });
      } catch (err) {
        return jsonResponse({ error: 'Internal error' }, 500);
      }
    }

    return new Response('Not found', { status: 404 });
  },
};
