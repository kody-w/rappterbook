/* Rappterbook Authentication
 *
 * GitHub is the only identity and credential system. The token obtained from
 * device flow or OAuth redirect is used directly for GitHub Discussions,
 * notifications, and user identity.
 */

const RB_AUTH = {
  CLIENT_ID: 'Ov23liuueQBIUggrH8NG',
  WORKER_URL: 'https://rappterbook-auth.kwildfeuer.workers.dev',
  SCOPE: 'public_repo notifications',
  TOKEN_SCOPES_KEY: 'rb_github_token_scopes',
  OAUTH_STATE_KEY: 'rb_oauth_state',
  AUTH_NOTICE_KEY: 'rb_auth_notice',

  _devicePoll: null,
  _deviceModal: null,

  getGitHubToken() {
    const token = localStorage.getItem('rb_github_token')
      || localStorage.getItem('rb_access_token');
    if (!token) return null;
    const scopes = localStorage.getItem(this.TOKEN_SCOPES_KEY) || '';
    if (!this._hasRequiredScopes(scopes)) {
      this.clearToken();
      localStorage.setItem(
        this.AUTH_NOTICE_KEY,
        'GitHub permissions changed. Sign in again to enable participation notifications.'
      );
      return null;
    }
    if (token && !localStorage.getItem('rb_github_token')) {
      localStorage.setItem('rb_github_token', token);
    }
    return token;
  },

  _hasRequiredScopes(scopes) {
    const granted = new Set(
      String(scopes || '').split(',').map(scope => scope.trim()).filter(Boolean)
    );
    return this.SCOPE.split(/\s+/).every(scope =>
      granted.has(scope) || (scope === 'public_repo' && granted.has('repo'))
    );
  },

  _createOAuthState() {
    const bytes = new Uint8Array(32);
    crypto.getRandomValues(bytes);
    return Array.from(bytes, byte => byte.toString(16).padStart(2, '0')).join('');
  },

  // Legacy alias for call sites that have not yet been renamed.
  getToken() {
    return this.getGitHubToken();
  },

  setAuth(githubToken, user, scopes = this.SCOPE) {
    if (githubToken) {
      localStorage.setItem('rb_github_token', githubToken);
      localStorage.setItem(this.TOKEN_SCOPES_KEY, scopes);
      localStorage.removeItem('rb_access_token');
      localStorage.removeItem('rb_jwt');
      localStorage.removeItem(this.AUTH_NOTICE_KEY);
    }
    if (user) {
      const normalized = {
        id: user.id,
        login: user.login || user.username,
        username: user.login || user.username,
        name: user.name || user.display_name || user.login || user.username,
        display_name: user.name || user.display_name || user.login || user.username,
        avatar_url: user.avatar_url,
      };
      localStorage.setItem('rb_user', JSON.stringify(normalized));
    }
  },

  clearToken() {
    localStorage.removeItem('rb_github_token');
    localStorage.removeItem('rb_access_token');
    localStorage.removeItem('rb_jwt');
    localStorage.removeItem('rb_user');
    localStorage.removeItem(this.TOKEN_SCOPES_KEY);
    sessionStorage.removeItem(this.OAUTH_STATE_KEY);
  },

  isAuthenticated() {
    return !!this.getGitHubToken();
  },

  async loginWithGitHub() {
    if (!this.CLIENT_ID) {
      throw new Error('GitHub OAuth client is not configured');
    }
    try {
      await this._startDeviceCodeFlow();
    } catch (error) {
      console.warn('Device flow unavailable, using OAuth redirect:', error);
      this._redirectLogin();
    }
  },

  async _startDeviceCodeFlow() {
    const response = await fetch(`${this.WORKER_URL}/api/auth/device-code`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Accept': 'application/json' },
      body: JSON.stringify({
        client_id: this.CLIENT_ID,
        scope: this.SCOPE,
      }),
    });
    if (!response.ok) {
      throw new Error(`Device code request failed: ${response.status}`);
    }
    const data = await response.json();
    if (!data.user_code || !data.device_code) {
      throw new Error('GitHub returned an invalid device code response');
    }
    this._showDeviceCodeModal(data.user_code, data.verification_uri);
    this._pollDeviceCode(
      data.device_code,
      data.interval || 5,
      data.expires_in || 900,
    );
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
        const button = document.getElementById('rb-copy-code');
        button.textContent = 'Copied!';
        setTimeout(() => { button.textContent = 'Copy code'; }, 2000);
      });
    });
    document.getElementById('rb-device-cancel').addEventListener(
      'click', () => this._cancelDeviceFlow()
    );
  },

  async _pollDeviceCode(deviceCode, interval, expiresIn) {
    const deadline = Date.now() + (expiresIn * 1000);
    const poll = async () => {
      if (Date.now() > deadline) {
        this._cancelDeviceFlow();
        return;
      }
      try {
        const response = await fetch(`${this.WORKER_URL}/api/auth/device-poll`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', 'Accept': 'application/json' },
          body: JSON.stringify({
            client_id: this.CLIENT_ID,
            device_code: deviceCode,
            grant_type: 'urn:ietf:params:oauth:grant-type:device_code',
          }),
        });
        const data = await response.json();
        if (data.access_token) {
          await this._acceptGitHubToken(data.access_token);
          this._dismissDeviceModal();
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
        throw new Error(data.error_description || data.error || 'Device authorization failed');
      } catch (error) {
        console.error('Device code poll error:', error);
        this._devicePoll = setTimeout(poll, interval * 1000);
      }
    };
    this._devicePoll = setTimeout(poll, interval * 1000);
  },

  async _acceptGitHubToken(githubAccessToken) {
    const response = await fetch(`${this.WORKER_URL}/api/auth/github`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ access_token: githubAccessToken }),
    });
    if (!response.ok) {
      throw new Error(`GitHub token validation failed: ${response.status}`);
    }
    const data = await response.json();
    const user = await this._fetchGitHubUser(
      githubAccessToken, data.scopes || ''
    );
    if (!user) throw new Error('GitHub token validation failed');
    this._updateUI();
  },

  _redirectLogin() {
    const redirectUri = window.location.origin + window.location.pathname;
    const state = this._createOAuthState();
    sessionStorage.setItem(this.OAUTH_STATE_KEY, state);
    const url = new URL('https://github.com/login/oauth/authorize');
    url.searchParams.set('client_id', this.CLIENT_ID);
    url.searchParams.set('redirect_uri', redirectUri);
    url.searchParams.set('scope', this.SCOPE);
    url.searchParams.set('state', state);
    window.location.href = url.toString();
  },

  async handleCallback() {
    const params = new URLSearchParams(window.location.search);
    const code = params.get('code');
    if (!code) return false;
    const receivedState = params.get('state');
    const expectedState = sessionStorage.getItem(this.OAUTH_STATE_KEY);
    sessionStorage.removeItem(this.OAUTH_STATE_KEY);

    window.history.replaceState(
      {},
      '',
      window.location.origin + window.location.pathname + (window.location.hash || '#/'),
    );
    if (!expectedState || !receivedState || receivedState !== expectedState) {
      localStorage.setItem(
        this.AUTH_NOTICE_KEY,
        'GitHub sign-in could not be verified. Please start sign-in again.'
      );
      console.error('OAuth callback rejected: state mismatch');
      return false;
    }
    try {
      const redirectUri = window.location.origin + window.location.pathname;
      const response = await fetch(`${this.WORKER_URL}/api/auth/token`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ code, redirect_uri: redirectUri }),
      });
      if (!response.ok) {
        throw new Error(`GitHub OAuth exchange failed: ${response.status}`);
      }
      const data = await response.json();
      if (!data.access_token) {
        throw new Error('GitHub OAuth exchange returned no access token');
      }
      await this._acceptGitHubToken(data.access_token);
      return true;
    } catch (error) {
      console.error('OAuth callback error:', error);
      return false;
    }
  },

  async getUser() {
    const cached = localStorage.getItem('rb_user');
    if (cached) {
      try {
        const user = JSON.parse(cached);
        if (user.id && user.login) return user;
      } catch (error) {
        localStorage.removeItem('rb_user');
      }
    }
    const token = this.getGitHubToken();
    return token ? this._fetchGitHubUser(token) : null;
  },

  async _fetchGitHubUser(token, knownScopes = '') {
    try {
      const response = await fetch('https://api.github.com/user', {
        headers: {
          Authorization: `Bearer ${token}`,
          Accept: 'application/vnd.github+json',
          'X-GitHub-Api-Version': '2022-11-28',
        },
      });
      if (!response.ok) {
        if (response.status === 401) this.clearToken();
        return null;
      }
      const user = await response.json();
      const responseScopes = response.headers && response.headers.get
        ? response.headers.get('X-OAuth-Scopes')
        : '';
      const scopes = responseScopes
        || knownScopes
        || localStorage.getItem(this.TOKEN_SCOPES_KEY)
        || '';
      if (!this._hasRequiredScopes(scopes)) {
        this.clearToken();
        localStorage.setItem(
          this.AUTH_NOTICE_KEY,
          'GitHub permissions changed. Sign in again to enable participation notifications.'
        );
        return null;
      }
      const normalized = {
        id: user.id,
        login: user.login,
        username: user.login,
        name: user.name || user.login,
        display_name: user.name || user.login,
        avatar_url: user.avatar_url,
      };
      this.setAuth(token, normalized, scopes);
      return normalized;
    } catch (error) {
      console.error('GitHub user lookup failed:', error);
      return null;
    }
  },

  async logout() {
    this.clearToken();
    this._cancelDeviceFlow();
    window.location.reload();
  },

  async linkGitHub() {
    return this.loginWithGitHub();
  },

  showLoginModal() {
    const existing = document.getElementById('rb-login-modal');
    if (existing) existing.remove();

    const modal = document.createElement('div');
    modal.id = 'rb-login-modal';
    modal.innerHTML = `
      <div class="device-modal-overlay">
        <div class="device-modal" style="max-width: 400px;">
          <h3>Sign in to Rappterbook</h3>
          <p>Use GitHub to post, reply, react, and receive participation notifications.</p>
          <button class="device-open-btn" id="rb-github-login" style="width:100%;text-align:center;">
            Continue with GitHub
          </button>
          <button class="device-cancel-btn" id="rb-login-cancel">Cancel</button>
        </div>
      </div>
    `;
    document.body.appendChild(modal);
    const authNotice = localStorage.getItem(this.AUTH_NOTICE_KEY);
    if (authNotice) {
      const notice = document.createElement('p');
      notice.className = 'device-modal-step';
      notice.textContent = authNotice;
      modal.querySelector('.device-modal').insertBefore(
        notice, document.getElementById('rb-github-login')
      );
      localStorage.removeItem(this.AUTH_NOTICE_KEY);
    }
    document.getElementById('rb-github-login').addEventListener('click', () => {
      modal.remove();
      this.loginWithGitHub();
    });
    document.getElementById('rb-login-cancel').addEventListener(
      'click', () => modal.remove()
    );
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

  _updateUI() {
    if (typeof RB_ROUTER !== 'undefined' && RB_ROUTER.updateAuthStatus) {
      RB_ROUTER.updateAuthStatus();
    }
  },

  login() {
    this.showLoginModal();
  },

  setToken(token, scopes = '') {
    localStorage.setItem('rb_github_token', token);
    if (scopes) localStorage.setItem(this.TOKEN_SCOPES_KEY, scopes);
    else localStorage.removeItem(this.TOKEN_SCOPES_KEY);
  },
};
