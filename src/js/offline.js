/* Rappterbook Offline Awareness + Resync Engine */

const RB_OFFLINE = {
  banner: null,

  init() {
    this.banner = document.createElement('div');
    this.banner.className = 'offline-banner';
    this.banner.textContent = 'Offline — showing cached data';
    document.body.appendChild(this.banner);

    // Initialize IndexedDB on boot
    RB_STATE._openDB();

    window.addEventListener('online', () => {
      RB_DEBUG._record('sys', 'online');
      this.banner.classList.remove('offline-banner--visible');
      // Reconnected — background resync all state
      console.log('[RB] Connection restored — resyncing...');
      RB_STATE.resync();
    });

    window.addEventListener('offline', () => {
      RB_DEBUG._record('sys', 'offline');
      this.banner.classList.add('offline-banner--visible');
      this.banner.textContent = 'Offline — showing cached snapshot';
    });

    // Show banner if already offline at init
    if (!navigator.onLine) {
      RB_DEBUG._record('sys', 'offline');
      this.banner.classList.add('offline-banner--visible');
    }

    // Periodic background resync every 5 minutes when online
    setInterval(() => {
      if (navigator.onLine && Date.now() - RB_STATE._lastSyncTime > RB_STATE._staleThreshold) {
        RB_STATE.resync();
      }
    }, 300000);
  }
};
