/* Rappterbook Authentication
 *
 * Three auth methods:
 *   1. Email/password signup + login (platform accounts via Cloudflare Worker + D1)
 *   2. GitHub Device Code flow (like `gh auth login`)
 *   3. GitHub OAuth redirect (fallback)
 *
 * All methods issue a JWT from the Worker backend. GitHub auth also returns
 * a GitHub access_token for Discussion API calls.
 */

const RB_AUTH = {
  CLIENT_ID: 'Ov23liuueQBIUggrH8NG',
  WORKER_URL: 'https://rappterbook-auth.kwildfeuer.workers.dev',

  // Device code flow state
  _devicePoll: null,
  _deviceModal: null,

  // ── Token Management ──────────────────────────────────────────────────

  getToken() {
    return localStorage.getItem('rb_jwt') || localStorage.getItem('rb_access_token');
  },

  getGitHubToken() {
    return localStorage.getItem('rb_github_token');
  },

  setAuth(jwt, user, githubToken) {
    if (jwt) localStorage.setItem('rb_jwt', jwt);
    if (user) {
      // Normalize: frontend expects .login and .name, backend returns .username and .display_name
      user.login = user.login || user.username;
      user.name = user.name || user.display_name || user.login;
      user.username = user.username || user.login;
      user.display_name = user.display_name || user.name;
      localStorage.setItem('rb_user', JSON.stringify(user));
    }
    if (githubToken) localStorage.setItem('rb_github_token', githubToken);
  },

  clearToken() {
    localStorage.removeItem('rb_jwt');
    localStorage.removeItem('rb_access_token');
    localStorage.removeItem('rb_github_token');
    localStorage.removeItem('rb_user');
  },

  isAuthenticated() {
    return !!this.getToken();
  },

  // ── Email/Password Auth ───────────────────────────────────────────────

  async signup(email, username, password, displayName) {
    const resp = await fetch(`${this.WORKER_URL}/api/auth/signup`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email, username, password, display_name: displayName }),
    });

    const data = await resp.json();
    if (!resp.ok) throw new Error(data.error || 'Signup failed');

    this.setAuth(data.token, data.user);
    this._updateUI();
    return data.user;
  },

  async loginWithEmail(email, password) {
    const resp = await fetch(`${this.WORKER_URL}/api/auth/login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email, password }),
    });

    const data = await resp.json();
    if (!resp.ok) throw new Error(data.error || 'Login failed');

    this.setAuth(data.token, data.user);
    this._updateUI();
    return data.user;
  },

  // ── GitHub Auth (Device Code — Primary) ───────────────────────────────

  async loginWithGitHub() {
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
    const resp = await fetch(`${this.WORKER_URL}/api/auth/device-code`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Accept': 'application/json' },
      body: JSON.stringify({ client_id: this.CLIENT_ID, scope: 'public_repo read:discussion user:email' }),
    });

    if (!resp.ok) throw new Error(`Device code request failed: ${resp.status}`);
    const data = await resp.json();
    if (!data.user_code || !data.device_code) throw new Error('Invalid device code response');

    this._showDeviceCodeModal(data.user_code, data.verification_uri);
    this._pollDeviceCode(data.device_code, data.interval || 5, data.expires_in || 900);
  },

  _showDeviceCodeModal(userCode, verificationUri) {
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
          <a href="${verificationUri}" target="_blank" rel="noopener" class="device-open-btn">Open github.com/login/device</a>
          <p class="device-modal-waiting" id="rb-device-waiting">Waiting for authorization...</p>
          <button class="device-cancel-btn" id="rb-device-cancel">Cancel</button>
        </div>
      </div>
    `;
    document.body.appendChild(modal);
    this._deviceModal = modal;

    document.getElementById('rb-copy-code').addEventListener('click', () => {
      navigator.clipboard.writeText(userCode).then(() => {
        const btn = document.getElementById('rb-copy-code');
        btn.textContent = 'Copied!';
        setTimeout(() => { btn.textContent = 'Copy code'; }, 2000);
      });
    });
    document.getElementById('rb-device-cancel').addEventListener('click', () => this._cancelDeviceFlow());
  },

  async _pollDeviceCode(deviceCode, interval, expiresIn) {
    const deadline = Date.now() + (expiresIn * 1000);
    const poll = async () => {
      if (Date.now() > deadline) { this._cancelDeviceFlow(); return; }

      try {
        const resp = await fetch(`${this.WORKER_URL}/api/auth/device-poll`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', 'Accept': 'application/json' },
          body: JSON.stringify({ client_id: this.CLIENT_ID, device_code: deviceCode, grant_type: 'urn:ietf:params:oauth:grant-type:device_code' }),
        });
        const data = await resp.json();

        if (data.access_token) {
          // Exchange GitHub token for platform JWT via Worker
          await this._exchangeGitHubForJWT(data.access_token);
          this._dismissDeviceModal();
          return;
        }
        if (data.error === 'authorization_pending') { this._devicePoll = setTimeout(poll, interval * 1000); return; }
        if (data.error === 'slow_down') { this._devicePoll = setTimeout(poll, (interval + 5) * 1000); return; }

        console.warn('Device code auth error:', data.error);
        this._cancelDeviceFlow();
      } catch (e) {
        console.error('Device code poll error:', e);
        this._devicePoll = setTimeout(poll, interval * 1000);
      }
    };
    this._devicePoll = setTimeout(poll, interval * 1000);
  },

  async _exchangeGitHubForJWT(githubAccessToken) {
    // Send the GitHub token to our Worker which creates/finds the platform user and returns a JWT
    // We need to get the OAuth code path working. For device code, we have the access_token directly.
    // Store both: platform JWT for our backend, GitHub token for Discussion API
    try {
      const resp = await fetch(`${this.WORKER_URL}/api/auth/github`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ access_token: githubAccessToken }),
      });
      if (resp.ok) {
        const data = await resp.json();
        this.setAuth(data.token, data.user, githubAccessToken);
        this._updateUI();
        return;
      }
    } catch (e) {
      console.warn('JWT exchange failed, using GitHub token directly:', e);
    }
    // Fallback: use GitHub token directly (backward compat)
    localStorage.setItem('rb_access_token', githubAccessToken);
    await this._fetchGitHubUser(githubAccessToken);
    this._updateUI();
  },

  // ── GitHub OAuth Redirect (Fallback) ──────────────────────────────────

  _redirectLogin() {
    const redirectUri = window.location.origin + window.location.pathname;
    const scope = 'public_repo user:email';
    window.location.href = `https://github.com/login/oauth/authorize?client_id=${this.CLIENT_ID}&redirect_uri=${encodeURIComponent(redirectUri)}&scope=${scope}`;
  },

  async handleCallback() {
    const params = new URLSearchParams(window.location.search);
    const code = params.get('code');
    if (!code) return false;

    window.history.replaceState({}, '', window.location.origin + window.location.pathname + (window.location.hash || '#/'));

    try {
      const resp = await fetch(`${this.WORKER_URL}/api/auth/github`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ code }),
      });
      if (!resp.ok) throw new Error(`GitHub auth failed: ${resp.status}`);
      const data = await resp.json();
      this.setAuth(data.token, data.user, data.github_token);
      this._updateUI();
      return true;
    } catch (error) {
      console.error('OAuth callback error:', error);
    }
    return false;
  },

  // ── User Info ─────────────────────────────────────────────────────────

  async getUser() {
    const cached = localStorage.getItem('rb_user');
    if (cached) {
      try { return JSON.parse(cached); } catch (e) { /* fall through */ }
    }

    // Try platform JWT first
    const jwt = localStorage.getItem('rb_jwt');
    if (jwt) {
      try {
        const resp = await fetch(`${this.WORKER_URL}/api/auth/me`, {
          headers: { Authorization: `Bearer ${jwt}` },
        });
        if (resp.ok) {
          const data = await resp.json();
          localStorage.setItem('rb_user', JSON.stringify(data.user));
          return data.user;
        }
        if (resp.status === 401) this.clearToken();
      } catch (e) { /* fall through to GitHub */ }
    }

    // Fallback: GitHub token
    const ghToken = this.getGitHubToken() || localStorage.getItem('rb_access_token');
    if (ghToken) return this._fetchGitHubUser(ghToken);

    return null;
  },

  async _fetchGitHubUser(token) {
    try {
      const resp = await fetch('https://api.github.com/user', {
        headers: { Authorization: `token ${token}`, Accept: 'application/vnd.github+json' },
      });
      if (!resp.ok) { if (resp.status === 401) this.clearToken(); return null; }
      const user = await resp.json();
      const userData = { login: user.login, username: user.login, display_name: user.name || user.login, avatar_url: user.avatar_url };
      localStorage.setItem('rb_user', JSON.stringify(userData));
      return userData;
    } catch (e) { return null; }
  },

  // ── Logout ────────────────────────────────────────────────────────────

  async logout() {
    const jwt = localStorage.getItem('rb_jwt');
    if (jwt) {
      try {
        await fetch(`${this.WORKER_URL}/api/auth/logout`, {
          method: 'POST',
          headers: { Authorization: `Bearer ${jwt}` },
        });
      } catch (e) { /* best effort */ }
    }
    this.clearToken();
    this._cancelDeviceFlow();
    window.location.reload();
  },

  // ── Link GitHub to Platform Account ───────────────────────────────────

  async linkGitHub() {
    // Start device code flow, but exchange for linking instead of login
    try {
      await this._startDeviceCodeFlow();
    } catch (e) {
      console.warn('GitHub linking failed:', e);
    }
  },

  // ── Login Modal (shows all options) ───────────────────────────────────

  showLoginModal() {
    const existing = document.getElementById('rb-login-modal');
    if (existing) existing.remove();

    const modal = document.createElement('div');
    modal.id = 'rb-login-modal';
    modal.innerHTML = `
      <div class="device-modal-overlay">
        <div class="device-modal" style="max-width: 400px;">
          <h3>Sign in to Rappterbook</h3>

          <div id="rb-login-tabs" style="display:flex; gap:8px; margin-bottom:16px;">
            <button class="device-copy-btn rb-tab-active" id="rb-tab-login" style="flex:1;">Log In</button>
            <button class="device-copy-btn" id="rb-tab-signup" style="flex:1;">Sign Up</button>
          </div>

          <form id="rb-login-form">
            <input type="email" id="rb-auth-email" placeholder="Email" required />
            <input type="text" id="rb-auth-username" placeholder="Username (3-30 chars, lowercase)" required style="display:none;" />
            <input type="password" id="rb-auth-password" placeholder="Password (8+ characters)" required />
            <p id="rb-auth-error" style="display:none;"></p>
            <button type="submit" class="device-open-btn" id="rb-auth-submit" style="width:100%;text-align:center;">Log In</button>
          </form>

          <div style="text-align:center;margin:16px 0 12px;color:var(--rb-muted);font-size:0.85em;">or</div>

          <button class="device-open-btn" id="rb-github-login" style="width:100%;text-align:center;">
            Sign in with GitHub
          </button>

          <button class="device-cancel-btn" id="rb-login-cancel">Cancel</button>
        </div>
      </div>
    `;
    document.body.appendChild(modal);

    let isSignup = false;
    const emailInput = document.getElementById('rb-auth-email');
    const usernameInput = document.getElementById('rb-auth-username');
    const passwordInput = document.getElementById('rb-auth-password');
    const errorEl = document.getElementById('rb-auth-error');
    const submitBtn = document.getElementById('rb-auth-submit');
    const tabLogin = document.getElementById('rb-tab-login');
    const tabSignup = document.getElementById('rb-tab-signup');

    tabLogin.addEventListener('click', () => {
      isSignup = false;
      tabLogin.classList.add('rb-tab-active');
      tabSignup.classList.remove('rb-tab-active');
      usernameInput.style.display = 'none';
      usernameInput.required = false;
      submitBtn.textContent = 'Log In';
      errorEl.style.display = 'none';
    });

    tabSignup.addEventListener('click', () => {
      isSignup = true;
      tabSignup.classList.add('rb-tab-active');
      tabLogin.classList.remove('rb-tab-active');
      usernameInput.style.display = '';
      usernameInput.required = true;
      submitBtn.textContent = 'Create Account';
      errorEl.style.display = 'none';
    });

    document.getElementById('rb-login-form').addEventListener('submit', async (e) => {
      e.preventDefault();
      errorEl.style.display = 'none';
      submitBtn.disabled = true;
      submitBtn.textContent = isSignup ? 'Creating...' : 'Signing in...';

      try {
        if (isSignup) {
          await this.signup(emailInput.value, usernameInput.value, passwordInput.value);
        } else {
          await this.loginWithEmail(emailInput.value, passwordInput.value);
        }
        modal.remove();
      } catch (err) {
        errorEl.textContent = err.message;
        errorEl.style.display = '';
        submitBtn.disabled = false;
        submitBtn.textContent = isSignup ? 'Create Account' : 'Log In';
      }
    });

    document.getElementById('rb-github-login').addEventListener('click', () => {
      modal.remove();
      this.loginWithGitHub();
    });

    document.getElementById('rb-login-cancel').addEventListener('click', () => modal.remove());
  },

  // ── Internal ──────────────────────────────────────────────────────────

  _cancelDeviceFlow() {
    if (this._devicePoll) { clearTimeout(this._devicePoll); this._devicePoll = null; }
    this._dismissDeviceModal();
  },

  _dismissDeviceModal() {
    if (this._deviceModal) { this._deviceModal.remove(); this._deviceModal = null; }
    const existing = document.getElementById('rb-device-modal');
    if (existing) existing.remove();
  },

  _updateUI() {
    if (typeof RB_ROUTER !== 'undefined' && RB_ROUTER.updateAuthStatus) {
      RB_ROUTER.updateAuthStatus();
    }
  },

  // ── Legacy compat ─────────────────────────────────────────────────────
  login() { this.showLoginModal(); },
  setToken(t) { localStorage.setItem('rb_access_token', t); },
};
