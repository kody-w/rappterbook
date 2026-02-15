/* Rappterbook GitHub OAuth Authentication */

const RB_AUTH = {
  // Configure these after creating your GitHub OAuth App and Cloudflare Worker
  WORKER_URL: 'https://rappterbook-auth.kwildfeuer.workers.dev',
  CLIENT_ID: 'Ov23liuueQBIUggrH8NG',

  /**
   * Get stored access token from localStorage.
   */
  getToken() {
    return localStorage.getItem('rb_access_token');
  },

  /**
   * Store access token in localStorage.
   */
  setToken(token) {
    localStorage.setItem('rb_access_token', token);
  },

  /**
   * Remove stored access token.
   */
  clearToken() {
    localStorage.removeItem('rb_access_token');
    localStorage.removeItem('rb_user');
  },

  /**
   * Check if user is authenticated.
   */
  isAuthenticated() {
    return !!this.getToken();
  },

  /**
   * Redirect to GitHub OAuth authorize page.
   */
  login() {
    if (!this.CLIENT_ID) {
      console.warn('RB_AUTH: CLIENT_ID not configured');
      return;
    }
    const redirectUri = window.location.origin + window.location.pathname;
    const scope = 'public_repo';
    const url = `https://github.com/login/oauth/authorize?client_id=${this.CLIENT_ID}&redirect_uri=${encodeURIComponent(redirectUri)}&scope=${scope}`;
    window.location.href = url;
  },

  /**
   * Handle OAuth callback — detect ?code= param, exchange for token.
   */
  async handleCallback() {
    const params = new URLSearchParams(window.location.search);
    const code = params.get('code');
    if (!code) return false;

    // Clean the URL — remove ?code= param
    const cleanUrl = window.location.origin + window.location.pathname + (window.location.hash || '#/');
    window.history.replaceState({}, '', cleanUrl);

    try {
      const response = await fetch(`${this.WORKER_URL}/api/auth/token`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ code })
      });

      if (!response.ok) {
        throw new Error(`Token exchange failed: ${response.status}`);
      }

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

  /**
   * Fetch authenticated user info from GitHub API.
   * Caches result in localStorage.
   */
  async getUser() {
    const cached = localStorage.getItem('rb_user');
    if (cached) {
      try {
        return JSON.parse(cached);
      } catch (e) {
        // fall through to fetch
      }
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
        if (response.status === 401) {
          this.clearToken();
        }
        return null;
      }

      const user = await response.json();
      const userData = { login: user.login, avatar_url: user.avatar_url };
      localStorage.setItem('rb_user', JSON.stringify(userData));
      return userData;
    } catch (error) {
      console.error('Failed to fetch user:', error);
      return null;
    }
  },

  /**
   * Log out — clear token and reload page.
   */
  logout() {
    this.clearToken();
    window.location.reload();
  }
};
