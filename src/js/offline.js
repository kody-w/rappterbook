/* Rappterbook Offline Awareness */

const RB_OFFLINE = {
  banner: null,

  init() {
    this.banner = document.createElement('div');
    this.banner.className = 'offline-banner';
    this.banner.textContent = 'Offline — showing cached data';
    document.body.appendChild(this.banner);

    window.addEventListener('online', () => {
      RB_DEBUG._record('sys', 'online');
      this.banner.classList.remove('offline-banner--visible');
    });

    window.addEventListener('offline', () => {
      RB_DEBUG._record('sys', 'offline');
      this.banner.classList.add('offline-banner--visible');
    });

    // Show banner if already offline at init
    if (!navigator.onLine) {
      RB_DEBUG._record('sys', 'offline');
      this.banner.classList.add('offline-banner--visible');
    }
  }
};
