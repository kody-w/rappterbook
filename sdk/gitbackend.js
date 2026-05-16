/**
 * GitBackend SDK — Use GitHub as a full backend for any application.
 *
 * GitHub is abstracted away. You get: auth, database, messaging,
 * storage, encryption, realtime subscriptions, and hosting.
 * Zero dependencies. Works in browser and Node.
 *
 * Usage:
 *   const app = GitBackend.init({ owner: 'you', repo: 'my-app', token: 'ghp_...' });
 *   const users = await app.db.collection('users').list();
 *   await app.db.collection('users').set('user-1', { name: 'Alice' });
 *   await app.messages.send('alerts', 'Server is down');
 *   app.db.collection('users').subscribe(data => console.log('changed:', data));
 *
 * Infrastructure mapping:
 *   Database     → JSON files in state/ directory
 *   Messaging    → GitHub Issues with labels
 *   Auth         → GitHub OAuth / PAT
 *   Storage      → Repository file contents
 *   Realtime     → Polling raw.githubusercontent.com
 *   Encryption   → AES-GCM via Web Crypto / Node crypto
 *   Hosting      → GitHub Pages (docs/)
 *   Compute      → GitHub Actions (workflows/)
 *   Branches     → Environments (main=prod, dev=staging)
 *
 * @version 1.0.0
 * @license MIT
 */

(function (root, factory) {
  if (typeof module !== 'undefined' && module.exports) {
    module.exports = factory();
  } else {
    root.GitBackend = factory();
  }
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';

  // ─── UTILS ────────────────────────────────────────────────

  const isNode = typeof process !== 'undefined' && process.versions && process.versions.node;

  async function fetchJSON(url, opts = {}) {
    const headers = { 'Accept': 'application/vnd.github.v3+json', ...opts.headers };
    const res = isNode
      ? await nodeFetch(url, { ...opts, headers })
      : await fetch(url, { ...opts, headers });
    if (!res.ok) {
      const body = await res.text().catch(() => '');
      const err = new Error(`GitBackend: ${res.status} ${res.statusText} — ${url}`);
      err.status = res.status;
      err.body = body;
      throw err;
    }
    const text = await res.text();
    return text ? JSON.parse(text) : null;
  }

  // Node.js fetch polyfill (stdlib only — uses https module)
  function nodeFetch(url, opts = {}) {
    return new Promise((resolve, reject) => {
      const https = require('https');
      const parsed = new URL(url);
      const req = https.request({
        hostname: parsed.hostname,
        path: parsed.pathname + parsed.search,
        method: opts.method || 'GET',
        headers: opts.headers || {},
      }, (res) => {
        let data = '';
        res.on('data', chunk => data += chunk);
        res.on('end', () => resolve({
          ok: res.statusCode >= 200 && res.statusCode < 300,
          status: res.statusCode,
          statusText: res.statusMessage,
          text: () => Promise.resolve(data),
          json: () => Promise.resolve(JSON.parse(data)),
        }));
      });
      req.on('error', reject);
      if (opts.body) req.write(opts.body);
      req.end();
    });
  }

  function base64Encode(str) {
    if (isNode) return Buffer.from(str).toString('base64');
    return btoa(unescape(encodeURIComponent(str)));
  }

  function base64Decode(str) {
    if (isNode) return Buffer.from(str, 'base64').toString('utf8');
    return decodeURIComponent(escape(atob(str)));
  }

  // ─── CORE ─────────────────────────────────────────────────

  function createApp(config) {
    const { owner, repo, token, branch = 'main', stateDir = 'state', pollInterval = 15000 } = config;
    const API = 'https://api.github.com';
    const RAW = `https://raw.githubusercontent.com/${owner}/${repo}/${branch}`;

    function authHeaders() {
      const h = { 'Accept': 'application/vnd.github.v3+json' };
      if (token) h['Authorization'] = `token ${token}`;
      return h;
    }

    async function api(endpoint, opts = {}) {
      const url = endpoint.startsWith('http') ? endpoint : `${API}/${endpoint}`;
      return fetchJSON(url, {
        ...opts,
        headers: { ...authHeaders(), ...opts.headers, ...(opts.body ? { 'Content-Type': 'application/json' } : {}) },
        body: opts.body ? (typeof opts.body === 'string' ? opts.body : JSON.stringify(opts.body)) : undefined,
      });
    }

    async function raw(path) {
      const url = `${RAW}/${path}?t=${Date.now()}`;
      return fetchJSON(url);
    }

    // ─── DATABASE ─────────────────────────────────────────

    function collection(name) {
      const filePath = `${stateDir}/${name}.json`;
      let _subscribers = [];
      let _lastData = null;
      let _pollTimer = null;

      async function _readRaw() {
        try { return await raw(filePath); }
        catch (e) { if (e.status === 404) return null; throw e; }
      }

      async function _readAPI() {
        try {
          const res = await api(`repos/${owner}/${repo}/contents/${filePath}?ref=${branch}`);
          return { content: JSON.parse(base64Decode(res.content)), sha: res.sha };
        } catch (e) { if (e.status === 404) return null; throw e; }
      }

      async function _write(data) {
        const existing = await _readAPI();
        const content = base64Encode(JSON.stringify(data, null, 2));
        const body = {
          message: `db: update ${name}`,
          content,
          branch,
        };
        if (existing) body.sha = existing.sha;
        return api(`repos/${owner}/${repo}/contents/${filePath}`, { method: 'PUT', body });
      }

      return {
        /** Get the entire collection as an object */
        async get() {
          return _readRaw();
        },

        /** List all items. If the collection is {items: {...}}, returns the items object */
        async list() {
          const data = await _readRaw();
          if (!data) return {};
          // Auto-detect: if there's a key matching the collection name, return that
          if (data[name]) return data[name];
          // If there's a top-level object with string keys → it's the items
          const keys = Object.keys(data).filter(k => !k.startsWith('_'));
          if (keys.length === 1 && typeof data[keys[0]] === 'object') return data[keys[0]];
          return data;
        },

        /** Get a single item by ID */
        async getById(id) {
          const items = await this.list();
          return items[id] || null;
        },

        /** Set a single item by ID (merge into collection) */
        async set(id, value) {
          const data = (await _readRaw()) || {};
          // Find the items key
          const itemsKey = data[name] ? name : Object.keys(data).find(k => !k.startsWith('_') && typeof data[k] === 'object') || name;
          if (!data[itemsKey]) data[itemsKey] = {};
          data[itemsKey][id] = { ...value, _updated: new Date().toISOString() };
          if (!data._meta) data._meta = {};
          data._meta.updated_at = new Date().toISOString();
          return _write(data);
        },

        /** Delete an item by ID */
        async delete(id) {
          const data = (await _readRaw()) || {};
          const itemsKey = data[name] ? name : Object.keys(data).find(k => !k.startsWith('_') && typeof data[k] === 'object') || name;
          if (data[itemsKey] && data[itemsKey][id]) {
            delete data[itemsKey][id];
            data._meta = data._meta || {};
            data._meta.updated_at = new Date().toISOString();
            return _write(data);
          }
        },

        /** Query items with a filter function */
        async query(filterFn) {
          const items = await this.list();
          const results = {};
          for (const [id, item] of Object.entries(items)) {
            if (filterFn(item, id)) results[id] = item;
          }
          return results;
        },

        /** Replace the entire collection */
        async replace(data) {
          return _write(data);
        },

        /** Subscribe to changes (polls raw.githubusercontent.com) */
        subscribe(callback, interval) {
          _subscribers.push(callback);
          if (!_pollTimer) {
            const poll = async () => {
              try {
                const data = await _readRaw();
                const serialized = JSON.stringify(data);
                if (serialized !== _lastData) {
                  _lastData = serialized;
                  _subscribers.forEach(fn => fn(data));
                }
              } catch (e) { /* silent poll failure */ }
            };
            poll();
            _pollTimer = setInterval(poll, interval || pollInterval);
          }
          // Return unsubscribe function
          return () => {
            _subscribers = _subscribers.filter(fn => fn !== callback);
            if (_subscribers.length === 0 && _pollTimer) {
              clearInterval(_pollTimer);
              _pollTimer = null;
            }
          };
        },
      };
    }

    // ─── MESSAGING ────────────────────────────────────────

    const messages = {
      /** Send a message to a channel (creates a GitHub Issue with label) */
      async send(channel, text, opts = {}) {
        const title = opts.title || (text.length > 60 ? text.slice(0, 60) + '...' : text);
        return api(`repos/${owner}/${repo}/issues`, {
          method: 'POST',
          body: { title, body: text, labels: [`msg:${channel}`, ...(opts.labels || [])] },
        });
      },

      /** List messages in a channel */
      async list(channel, opts = {}) {
        const state = opts.state || 'open';
        const limit = opts.limit || 20;
        const issues = await api(`repos/${owner}/${repo}/issues?labels=msg:${channel}&state=${state}&per_page=${limit}&sort=created&direction=desc`);
        return (issues || []).map(i => ({
          id: i.number,
          title: i.title,
          body: i.body,
          author: i.user?.login,
          state: i.state,
          created: i.created_at,
          updated: i.updated_at,
          comments: i.comments,
          url: i.html_url,
        }));
      },

      /** Reply to a message (comment on an issue) */
      async reply(messageId, text) {
        return api(`repos/${owner}/${repo}/issues/${messageId}/comments`, {
          method: 'POST',
          body: { body: text },
        });
      },

      /** Close a message (close the issue) */
      async close(messageId, comment) {
        if (comment) await this.reply(messageId, comment);
        return api(`repos/${owner}/${repo}/issues/${messageId}`, {
          method: 'PATCH',
          body: { state: 'closed' },
        });
      },

      /** Subscribe to new messages in a channel */
      subscribe(channel, callback, interval) {
        let lastSeen = null;
        const poll = async () => {
          try {
            const msgs = await this.list(channel, { limit: 5 });
            if (msgs.length && msgs[0].created !== lastSeen) {
              lastSeen = msgs[0].created;
              callback(msgs);
            }
          } catch (e) { /* silent */ }
        };
        poll();
        const timer = setInterval(poll, interval || pollInterval);
        return () => clearInterval(timer);
      },
    };

    // ─── STORAGE ──────────────────────────────────────────

    const storage = {
      /** Read a file from the repo */
      async read(path) {
        try {
          const res = await api(`repos/${owner}/${repo}/contents/${path}?ref=${branch}`);
          return base64Decode(res.content);
        } catch (e) {
          if (e.status === 404) return null;
          throw e;
        }
      },

      /** Read a file as raw (no base64, via raw.githubusercontent.com) */
      async readRaw(path) {
        const url = `${RAW}/${path}?t=${Date.now()}`;
        const res = isNode ? await nodeFetch(url) : await fetch(url);
        if (!res.ok) { if (res.status === 404) return null; throw new Error(`${res.status}`); }
        return res.text();
      },

      /** Write a file to the repo */
      async write(path, content, message) {
        let sha;
        try {
          const existing = await api(`repos/${owner}/${repo}/contents/${path}?ref=${branch}`);
          sha = existing.sha;
        } catch (e) { /* new file */ }

        const body = {
          message: message || `write: ${path}`,
          content: base64Encode(content),
          branch,
        };
        if (sha) body.sha = sha;
        return api(`repos/${owner}/${repo}/contents/${path}`, { method: 'PUT', body });
      },

      /** Delete a file */
      async remove(path, message) {
        try {
          const existing = await api(`repos/${owner}/${repo}/contents/${path}?ref=${branch}`);
          return api(`repos/${owner}/${repo}/contents/${path}`, {
            method: 'DELETE',
            body: { message: message || `delete: ${path}`, sha: existing.sha, branch },
          });
        } catch (e) { if (e.status !== 404) throw e; }
      },

      /** List files in a directory */
      async ls(path = '') {
        try {
          const res = await api(`repos/${owner}/${repo}/contents/${path}?ref=${branch}`);
          if (Array.isArray(res)) return res.map(f => ({ name: f.name, path: f.path, size: f.size, type: f.type }));
          return [{ name: res.name, path: res.path, size: res.size, type: res.type }];
        } catch (e) { if (e.status === 404) return []; throw e; }
      },

      /** List all files in repo (recursive) */
      async tree() {
        const res = await api(`repos/${owner}/${repo}/git/trees/${branch}?recursive=1`);
        return (res.tree || []).filter(f => f.type === 'blob').map(f => ({ path: f.path, size: f.size }));
      },
    };

    // ─── AUTH ─────────────────────────────────────────────

    const auth = {
      /** Get the authenticated user */
      async me() {
        if (!token) return null;
        return api('user');
      },

      /** Check if token has required scopes */
      async checkScopes() {
        if (!token) return [];
        const res = isNode
          ? await nodeFetch(`${API}/user`, { headers: authHeaders() })
          : await fetch(`${API}/user`, { headers: authHeaders() });
        const scopes = (isNode ? res.headers?.['x-oauth-scopes'] : res.headers.get('x-oauth-scopes')) || '';
        return scopes.split(',').map(s => s.trim()).filter(Boolean);
      },

      /** Generate an OAuth URL for browser-based login */
      oauthURL(clientId, redirectUri, scopes = ['repo']) {
        return `https://github.com/login/oauth/authorize?client_id=${clientId}&redirect_uri=${encodeURIComponent(redirectUri)}&scope=${scopes.join(',')}`;
      },
    };

    // ─── CRYPTO ───────────────────────────────────────────

    const crypto_mod = {
      /** Encrypt text with a password (AES-GCM) */
      async encrypt(text, password) {
        if (isNode) return this._encryptNode(text, password);
        const enc = new TextEncoder();
        const keyMaterial = await crypto.subtle.importKey('raw', enc.encode(password), 'PBKDF2', false, ['deriveKey']);
        const key = await crypto.subtle.deriveKey(
          { name: 'PBKDF2', salt: enc.encode(`${owner}/${repo}`), iterations: 100000, hash: 'SHA-256' },
          keyMaterial, { name: 'AES-GCM', length: 256 }, false, ['encrypt']
        );
        const iv = crypto.getRandomValues(new Uint8Array(12));
        const ct = await crypto.subtle.encrypt({ name: 'AES-GCM', iv }, key, enc.encode(text));
        const buf = new Uint8Array(iv.length + ct.byteLength);
        buf.set(iv); buf.set(new Uint8Array(ct), iv.length);
        return 'ENC:' + btoa(String.fromCharCode(...buf));
      },

      /** Decrypt text with a password */
      async decrypt(text, password) {
        if (!text || !text.startsWith('ENC:')) return text;
        if (isNode) return this._decryptNode(text, password);
        try {
          const enc = new TextEncoder();
          const keyMaterial = await crypto.subtle.importKey('raw', enc.encode(password), 'PBKDF2', false, ['deriveKey']);
          const key = await crypto.subtle.deriveKey(
            { name: 'PBKDF2', salt: enc.encode(`${owner}/${repo}`), iterations: 100000, hash: 'SHA-256' },
            keyMaterial, { name: 'AES-GCM', length: 256 }, false, ['decrypt']
          );
          const raw = Uint8Array.from(atob(text.slice(4)), c => c.charCodeAt(0));
          const iv = raw.slice(0, 12);
          const ct = raw.slice(12);
          const pt = await crypto.subtle.decrypt({ name: 'AES-GCM', iv }, key, ct);
          return new TextDecoder().decode(pt);
        } catch (e) { return '[decryption failed]'; }
      },

      _encryptNode(text, password) {
        const c = require('crypto');
        const salt = Buffer.from(`${owner}/${repo}`);
        const key = c.pbkdf2Sync(password, salt, 100000, 32, 'sha256');
        const iv = c.randomBytes(12);
        const cipher = c.createCipheriv('aes-256-gcm', key, iv);
        let enc = cipher.update(text, 'utf8');
        enc = Buffer.concat([enc, cipher.final()]);
        const tag = cipher.getAuthTag();
        return 'ENC:' + Buffer.concat([iv, enc, tag]).toString('base64');
      },

      _decryptNode(text, password) {
        try {
          const c = require('crypto');
          const salt = Buffer.from(`${owner}/${repo}`);
          const key = c.pbkdf2Sync(password, salt, 100000, 32, 'sha256');
          const buf = Buffer.from(text.slice(4), 'base64');
          const iv = buf.slice(0, 12);
          const tag = buf.slice(-16);
          const enc = buf.slice(12, -16);
          const decipher = c.createDecipheriv('aes-256-gcm', key, iv);
          decipher.setAuthTag(tag);
          let dec = decipher.update(enc);
          dec = Buffer.concat([dec, decipher.final()]);
          return dec.toString('utf8');
        } catch (e) { return '[decryption failed]'; }
      },
    };

    // ─── BRANCHES (environments) ──────────────────────────

    const branches = {
      /** List all branches */
      async list() {
        const res = await api(`repos/${owner}/${repo}/branches?per_page=30`);
        return (res || []).map(b => b.name);
      },

      /** Create a branch from another branch */
      async create(name, from = 'main') {
        const ref = await api(`repos/${owner}/${repo}/git/refs/heads/${from}`);
        return api(`repos/${owner}/${repo}/git/refs`, {
          method: 'POST',
          body: { ref: `refs/heads/${name}`, sha: ref.object.sha },
        });
      },

      /** Delete a branch */
      async remove(name) {
        return api(`repos/${owner}/${repo}/git/refs/heads/${name}`, { method: 'DELETE' });
      },

      /** Create a pull request */
      async pr(head, base, title, body) {
        return api(`repos/${owner}/${repo}/pulls`, {
          method: 'POST',
          body: { title, body: body || '', head, base: base || 'main' },
        });
      },

      /** Merge a pull request */
      async merge(prNumber) {
        return api(`repos/${owner}/${repo}/pulls/${prNumber}/merge`, {
          method: 'PUT',
          body: { merge_method: 'merge' },
        });
      },
    };

    // ─── ACTIONS (compute) ────────────────────────────────

    const actions = {
      /** Trigger a workflow dispatch */
      async trigger(workflow, inputs = {}, ref = 'main') {
        return api(`repos/${owner}/${repo}/actions/workflows/${workflow}/dispatches`, {
          method: 'POST',
          body: { ref, inputs },
        });
      },

      /** List recent workflow runs */
      async runs(workflow, limit = 5) {
        const res = await api(`repos/${owner}/${repo}/actions/workflows/${workflow}/runs?per_page=${limit}`);
        return (res.workflow_runs || []).map(r => ({
          id: r.id,
          status: r.status,
          conclusion: r.conclusion,
          created: r.created_at,
          url: r.html_url,
        }));
      },
    };

    // ─── PAGES (hosting) ──────────────────────────────────

    const pages = {
      /** Get Pages status */
      async status() {
        try {
          return await api(`repos/${owner}/${repo}/pages`);
        } catch (e) { return null; }
      },

      /** Enable Pages */
      async enable(source = { branch: 'main', path: '/docs' }) {
        return api(`repos/${owner}/${repo}/pages`, {
          method: 'POST',
          body: { source },
        });
      },

      /** Get the Pages URL */
      url() {
        return `https://${owner}.github.io/${repo}/`;
      },
    };

    // ─── APP OBJECT ───────────────────────────────────────

    return {
      config: { owner, repo, branch, stateDir },
      db: { collection },
      messages,
      storage,
      auth,
      crypto: crypto_mod,
      branches,
      actions,
      pages,
      api,
      raw,
    };
  }

  // ─── PUBLIC API ─────────────────────────────────────────

  return {
    /** Initialize a GitBackend app */
    init: createApp,

    /** Version */
    version: '1.0.0',
  };
});
