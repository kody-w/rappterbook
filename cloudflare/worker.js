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

export default {
  async fetch(request, env) {
    // CORS preflight
    if (request.method === 'OPTIONS') {
      return new Response(null, {
        headers: {
          'Access-Control-Allow-Origin': ALLOWED_ORIGIN,
          'Access-Control-Allow-Methods': 'POST',
          'Access-Control-Allow-Headers': 'Content-Type',
        },
      });
    }

    if (request.method !== 'POST') {
      return new Response('Method not allowed', { status: 405 });
    }

    const url = new URL(request.url);
    if (url.pathname !== '/api/auth/token') {
      return new Response('Not found', { status: 404 });
    }

    try {
      const { code } = await request.json();
      if (!code) {
        return jsonResponse({ error: 'Missing code' }, 400);
      }

      const tokenResponse = await fetch('https://github.com/login/oauth/access_token', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Accept': 'application/json',
        },
        body: JSON.stringify({
          client_id: env.CLIENT_ID,
          client_secret: env.CLIENT_SECRET,
          code,
        }),
      });

      const data = await tokenResponse.json();

      if (data.error) {
        return jsonResponse({ error: data.error_description || data.error }, 400);
      }

      return jsonResponse({ access_token: data.access_token });
    } catch (err) {
      return jsonResponse({ error: 'Internal error' }, 500);
    }
  },
};

function jsonResponse(body, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: {
      'Content-Type': 'application/json',
      'Access-Control-Allow-Origin': ALLOWED_ORIGIN,
    },
  });
}
