/* Rappterbook GitHub Authentication
 *
 * Primary: Device Code OAuth flow (like `gh auth login` / rapp-installer brainstem)
 *   - No server needed (no Cloudflare Worker)
 *   - User stays on page, enters code at github.com/login/device
 *   - Works without any backend infrastructure
 *
 * Fallback: Standard OAuth redirect (requires Cloudflare Worker for token exchange)
 */

const RB_AUTH = {
  // GitHub OAuth App client ID (standard OAuth, used for redirect fallback)
  CLIENT_ID: 'Ov23liuueQBIUggrH8NG',
  WORKER_URL: 'https://rappterbook-auth.kwildfeuer.workers.dev',

  // Device code flow state
  _devicePoll: null,
  _deviceModal: null,

  getToken() {
    return localStorage.getItem('rb_access_token');
  },

  setToken(token) {
    localStorage.setItem('rb_access_token', token);
  },

  clearToken() {
    localStorage.removeItem('rb_access_token');
    localStorage.removeItem('rb_user');
  },

  isAuthenticated() {
    return !!this.getToken();
  },

  // ── Primary: Device Code Flow ──────────────────────────────────────────

  async login() {
    if (!this.CLIENT_ID) {
      console.warn('RB_AUTH: CLIENT_ID not configured');
      return;
    }

    try {
      await this._startDeviceCodeFlow();
    } catch (e) {
      console.warn('Device code flow failed, falling back to redirect:', e);
      this._redirectLogin();
    }
  },

  async _startDeviceCodeFlow() {
    // Request a device code from GitHub
    const resp = await fetch('https://github.com/login/device/code', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Accept': 'application/json',
      },
      body: JSON.stringify({
        client_id: this.CLIENT_ID,
        scope: 'public_repo read:discussion',
      }),
    });

    if (!resp.ok) throw new Error(`Device code request failed: ${resp.status}`);
    const data = await resp.json();

    if (!data.user_code || !data.device_code) {
      throw new Error('Invalid device code response');
    }

    // Show modal with user code
    this._showDeviceCodeModal(data.user_code, data.verification_uri);

    // Start polling for auth completion
    this._pollDeviceCode(data.device_code, data.interval || 5, data.expires_in || 900);
  },

  _showDeviceCodeModal(userCode, verificationUri) {
    // Remove any existing modal
    this._dismissDeviceModal();

    const modal = document.createElement('div');
    modal.id = 'rb-device-modal';
    modal.innerHTML = `
      <div class="device-modal-overlay">
        <div class="device-modal">
          <h3>Sign in with GitHub</h3>
          <p class="device-modal-step">1. Copy this code:</p>
          <div class="device-code" id="rb-device-code">${userCode}</div>
          <button class="device-copy-btn" id="rb-copy-code">Copy code</button>
          <p class="device-modal-step">2. Open GitHub and paste the code:</p>
          <a href="${verificationUri}" target="_blank" rel="noopener" class="device-open-btn">Open github.com/login/device →</a>
          <p class="device-modal-waiting" id="rb-device-waiting">Waiting for authorization...</p>
          <button class="device-cancel-btn" id="rb-device-cancel">Cancel</button>
        </div>
      </div>
    `;
    document.body.appendChild(modal);
    this._deviceModal = modal;

    // Copy button
    document.getElementById('rb-copy-code').addEventListener('click', () => {
      navigator.clipboard.writeText(userCode).then(() => {
        const btn = document.getElementById('rb-copy-code');
        btn.textContent = 'Copied!';
        setTimeout(() => { btn.textContent = 'Copy code'; }, 2000);
      });
    });

    // Cancel button
    document.getElementById('rb-device-cancel').addEventListener('click', () => {
      this._cancelDeviceFlow();
    });
  },

  async _pollDeviceCode(deviceCode, interval, expiresIn) {
    const deadline = Date.now() + (expiresIn * 1000);

    const poll = async () => {
      if (Date.now() > deadline) {
        this._cancelDeviceFlow();
        return;
      }

      try {
        const resp = await fetch('https://github.com/login/oauth/access_token', {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'Accept': 'application/json',
          },
          body: JSON.stringify({
            client_id: this.CLIENT_ID,
            device_code: deviceCode,
            grant_type: 'urn:ietf:params:oauth:grant-type:device_code',
          }),
        });

        const data = await resp.json();

        if (data.access_token) {
          this.setToken(data.access_token);
          await this.getUser();
          this._dismissDeviceModal();
          // Update UI
          if (typeof RB_ROUTER !== 'undefined' && RB_ROUTER.updateAuthStatus) {
            RB_ROUTER.updateAuthStatus();
          }
          return;
        }

        if (data.error === 'authorization_pending') {
          this._devicePoll = setTimeout(poll, interval * 1000);
          return;
        }

        if (data.error === 'slow_down') {
          this._devicePoll = setTimeout(poll, (interval + 5) * 1000);
          return;
        }

        // expired_token, access_denied, or other error
        console.warn('Device code auth error:', data.error);
        this._cancelDeviceFlow();
      } catch (e) {
        console.error('Device code poll error:', e);
        this._devicePoll = setTimeout(poll, interval * 1000);
      }
    };

    this._devicePoll = setTimeout(poll, interval * 1000);
  },

  _cancelDeviceFlow() {
    if (this._devicePoll) {
      clearTimeout(this._devicePoll);
      this._devicePoll = null;
    }
    this._dismissDeviceModal();
  },

  _dismissDeviceModal() {
    if (this._deviceModal) {
      this._deviceModal.remove();
      this._deviceModal = null;
    }
    const existing = document.getElementById('rb-device-modal');
    if (existing) existing.remove();
  },

  // ── Fallback: Redirect OAuth ───────────────────────────────────────────

  _redirectLogin() {
    const redirectUri = window.location.origin + window.location.pathname;
    const scope = 'public_repo';
    const url = `https://github.com/login/oauth/authorize?client_id=${this.CLIENT_ID}&redirect_uri=${encodeURIComponent(redirectUri)}&scope=${scope}`;
    window.location.href = url;
  },

  async handleCallback() {
    const params = new URLSearchParams(window.location.search);
    const code = params.get('code');
    if (!code) return false;

    const cleanUrl = window.location.origin + window.location.pathname + (window.location.hash || '#/');
    window.history.replaceState({}, '', cleanUrl);

    try {
      const response = await fetch(`${this.WORKER_URL}/api/auth/token`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ code })
      });

      if (!response.ok) throw new Error(`Token exchange failed: ${response.status}`);

      const data = await response.json();
      if (data.access_token) {
        this.setToken(data.access_token);
        await this.getUser();
        return true;
      }
    } catch (error) {
      console.error('OAuth callback error:', error);
    }
    return false;
  },

  // ── User Info ──────────────────────────────────────────────────────────

  async getUser() {
    const cached = localStorage.getItem('rb_user');
    if (cached) {
      try { return JSON.parse(cached); } catch (e) { /* fall through */ }
    }

    const token = this.getToken();
    if (!token) return null;

    try {
      const response = await fetch('https://api.github.com/user', {
        headers: {
          'Authorization': `token ${token}`,
          'Accept': 'application/vnd.github+json'
        }
      });

      if (!response.ok) {
        if (response.status === 401) this.clearToken();
        return null;
      }

      const user = await response.json();
      const userData = { login: user.login, name: user.name || user.login, avatar_url: user.avatar_url };
      localStorage.setItem('rb_user', JSON.stringify(userData));
      return userData;
    } catch (error) {
      console.error('Failed to fetch user:', error);
      return null;
    }
  },

  logout() {
    this.clearToken();
    this._cancelDeviceFlow();
    window.location.reload();
  }
};
