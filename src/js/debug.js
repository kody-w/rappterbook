/* Rappterbook Debug Telemetry */

const RB_DEBUG = {
  _version: 1,
  _maxEvents: 500,
  _events: [],
  _startTime: Date.now(),
  _patched: false,
  level: 'normal', // 'normal' | 'verbose' | 'quiet'

  // Record an event into the ring buffer
  _record(kind, detail, extra) {
    if (this.level === 'quiet') return;
    const entry = {
      t: Date.now() - this._startTime,
      kind: kind,
      detail: detail
    };
    if (extra && this.level === 'verbose') {
      entry.extra = extra;
    }
    this._events.push(entry);
    if (this._events.length > this._maxEvents) {
      this._events.shift();
    }
  },

  // Boot: install global listeners immediately (no dependency on other modules)
  _boot() {
    this._record('sys', 'debug loaded');

    // Global error handler
    window.onerror = (message, source, lineno, colno, error) => {
      const shortSrc = source ? source.split('/').pop() : '';
      this._record('err', `error: ${message} (${shortSrc}:${lineno})`);
    };

    // Unhandled promise rejections
    window.addEventListener('unhandledrejection', (event) => {
      const reason = event.reason;
      const msg = reason instanceof Error ? reason.message : String(reason);
      this._record('err', 'unhandled-reject: ' + msg);
    });

    // Document-level click listener (capture phase)
    document.addEventListener('click', (event) => {
      const el = event.target;
      const parts = [];

      // Tag name
      const tag = el.tagName.toLowerCase();
      parts.push(tag);

      // Class names (first two)
      if (el.className && typeof el.className === 'string') {
        const classes = el.className.split(/\s+/).filter(Boolean).slice(0, 2);
        if (classes.length) parts[0] = tag + '.' + classes.join('.');
      }

      // Href for links
      if (el.href) {
        const href = el.getAttribute('href') || '';
        parts.push('href=' + href);
      }

      // Text content (truncated)
      const text = (el.textContent || '').trim().slice(0, 30);
      if (text) parts.push('"' + text + '"');

      this._record('click', parts.join(' '));
    }, true);
  },

  // Init: apply monkey-patches once all modules are loaded
  init() {
    if (this._patched) return;
    this._patched = true;

    // Patch RB_STATE.fetchJSON
    if (typeof RB_STATE !== 'undefined' && RB_STATE.fetchJSON) {
      const origFetch = RB_STATE.fetchJSON.bind(RB_STATE);
      RB_STATE.fetchJSON = async (path) => {
        const start = Date.now();
        try {
          const result = await origFetch(path);
          const ms = Date.now() - start;
          this._record('fetch', path + ' ' + ms + 'ms ok');
          return result;
        } catch (error) {
          const ms = Date.now() - start;
          this._record('fetch', path + ' ' + ms + 'ms FAIL: ' + error.message);
          throw error;
        }
      };
    }

    // Patch RB_STATE.getCached
    if (typeof RB_STATE !== 'undefined' && RB_STATE.getCached) {
      const origGetCached = RB_STATE.getCached.bind(RB_STATE);
      RB_STATE.getCached = async (key, fetcher) => {
        const now = Date.now();
        if (RB_STATE.cache[key] && (now - RB_STATE.cache[key].timestamp < RB_STATE.cacheExpiry)) {
          this._record('cache', 'HIT ' + key);
        }
        return origGetCached(key, fetcher);
      };
    }

    // Patch RB_ROUTER.navigate
    if (typeof RB_ROUTER !== 'undefined' && RB_ROUTER.navigate) {
      const origNavigate = RB_ROUTER.navigate.bind(RB_ROUTER);
      RB_ROUTER.navigate = async () => {
        const hash = window.location.hash.slice(1) || '/';
        this._record('nav', hash);
        const start = Date.now();
        await origNavigate();
        const ms = Date.now() - start;
        this._record('nav', hash + ' rendered ' + ms + 'ms');
      };
    }

    // Patch RB_DISCUSSIONS.fetchDiscussion
    if (typeof RB_DISCUSSIONS !== 'undefined' && RB_DISCUSSIONS.fetchDiscussion) {
      const origFetchDisc = RB_DISCUSSIONS.fetchDiscussion.bind(RB_DISCUSSIONS);
      RB_DISCUSSIONS.fetchDiscussion = async (number) => {
        const start = Date.now();
        try {
          const result = await origFetchDisc(number);
          const ms = Date.now() - start;
          this._record('fetch', 'discussion/' + number + ' ' + ms + 'ms ok');
          return result;
        } catch (error) {
          const ms = Date.now() - start;
          this._record('fetch', 'discussion/' + number + ' ' + ms + 'ms FAIL: ' + error.message);
          throw error;
        }
      };
    }

    // Patch RB_DISCUSSIONS.fetchComments
    if (typeof RB_DISCUSSIONS !== 'undefined' && RB_DISCUSSIONS.fetchComments) {
      const origFetchComments = RB_DISCUSSIONS.fetchComments.bind(RB_DISCUSSIONS);
      RB_DISCUSSIONS.fetchComments = async (number) => {
        const start = Date.now();
        try {
          const result = await origFetchComments(number);
          const ms = Date.now() - start;
          this._record('fetch', 'comments/' + number + ' ' + ms + 'ms ok');
          return result;
        } catch (error) {
          const ms = Date.now() - start;
          this._record('fetch', 'comments/' + number + ' ' + ms + 'ms FAIL: ' + error.message);
          throw error;
        }
      };
    }

    this._record('sys', 'patches applied');
  },

  // Dump the event log as compact text
  dump(opts) {
    opts = opts || {};
    let events = this._events.slice();

    // Filter by type
    if (opts.type) {
      events = events.filter(e => e.kind === opts.type);
    }

    // Limit to last N
    if (opts.last && opts.last > 0) {
      events = events.slice(-opts.last);
    }

    const sessionSec = ((Date.now() - this._startTime) / 1000).toFixed(0);
    const route = (typeof RB_ROUTER !== 'undefined' && RB_ROUTER.currentRoute) ? RB_ROUTER.currentRoute : '?';

    const lines = [];
    lines.push('=RB_DEBUG v' + this._version + ' | session=' + sessionSec + 's | events=' + this._events.length + ' | showing=' + events.length + ' | route=#' + route);

    for (const ev of events) {
      const sec = (ev.t / 1000).toFixed(2);
      const pad = sec.length < 8 ? ' '.repeat(8 - sec.length) : '';
      const kindPad = ev.kind.length < 6 ? ev.kind + ' '.repeat(6 - ev.kind.length) : ev.kind;
      let line = pad + sec + ' ' + kindPad + ev.detail;
      if (ev.extra) {
        line += ' ' + JSON.stringify(ev.extra);
      }
      lines.push(line);
    }

    const output = lines.join('\n');
    console.log(output);
    return output;
  },

  // Dump + copy to clipboard
  copy(opts) {
    const text = this.dump(opts);
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).then(
        () => console.log('RB_DEBUG: copied to clipboard'),
        () => console.warn('RB_DEBUG: clipboard copy failed')
      );
    } else {
      console.warn('RB_DEBUG: clipboard API not available');
    }
    return text;
  }
};

// Boot immediately — no dependencies needed
RB_DEBUG._boot();
