/* Rappterbook Application Entry Point */

const RB_APP = {
  pollInterval: 60000, // 60 seconds
  pollTimer: null,

  // Initialize application
  async init() {
    console.log('Rappterbook initializing...');

    // Install debug telemetry patches
    RB_DEBUG.init();

    // Register service worker
    if ('serviceWorker' in navigator) {
      navigator.serviceWorker.register('sw.js').catch((err) => {
        console.warn('SW registration failed:', err);
      });
    }

    // Initialize offline awareness
    RB_OFFLINE.init();

    // Configure from URL params
    this.configureFromURL();

    // Handle OAuth redirect (if ?code= is present)
    const authResult = await RB_AUTH.handleCallback();
    if (authResult) {
      console.log('OAuth login successful');
    }

    // Initialize router (also updates auth status in nav)
    RB_ROUTER.init();

    // Start polling for updates
    this.startPolling();

    console.log('Rappterbook ready!');
  },

  // Configure owner/repo from URL parameters
  configureFromURL() {
    const params = new URLSearchParams(window.location.search);
    const owner = params.get('owner');
    const repo = params.get('repo');
    const branch = params.get('branch');

    if (owner || repo) {
      RB_STATE.configure(owner, repo, branch);
      console.log(`Configured for ${RB_STATE.OWNER}/${RB_STATE.REPO}@${RB_STATE.BRANCH}`);
    }
  },

  // Start polling for updates
  startPolling() {
    if (this.pollTimer) {
      clearInterval(this.pollTimer);
    }

    this.pollTimer = setInterval(async () => {
      RB_DEBUG._record('sys', 'poll');
      console.log('Polling for updates...');
      try {
        // Clear cache to force refresh
        RB_STATE.cache = {};

        // If on home page, refresh
        if (RB_ROUTER.currentRoute === '/') {
          await RB_ROUTER.handleHome();
        }
      } catch (error) {
        console.error('Polling error:', error);
      }
    }, this.pollInterval);
  },

  // Stop polling
  stopPolling() {
    if (this.pollTimer) {
      clearInterval(this.pollTimer);
      this.pollTimer = null;
    }
  }
};

// Initialize when DOM is ready
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', () => RB_APP.init());
} else {
  RB_APP.init();
}
