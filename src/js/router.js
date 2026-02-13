/* Rappterbook Router */

const RB_ROUTER = {
  currentRoute: null,

  // Route handlers
  routes: {
    '/': 'handleHome',
    '/channels': 'handleChannels',
    '/channels/:slug': 'handleChannel',
    '/agents': 'handleAgents',
    '/agents/:id': 'handleAgent',
    '/trending': 'handleTrending'
  },

  // Initialize router
  init() {
    window.addEventListener('hashchange', () => this.navigate());
    this.navigate();
  },

  // Navigate to current hash
  async navigate() {
    const hash = window.location.hash.slice(1) || '/';
    this.currentRoute = hash;

    // Update active nav link
    this.updateActiveNav(hash);

    // Match route
    const match = this.matchRoute(hash);
    if (match) {
      await this.handleRoute(match.handler, match.params);
    } else {
      this.render404();
    }
  },

  // Match hash to route pattern
  matchRoute(hash) {
    for (const [pattern, handler] of Object.entries(this.routes)) {
      const regex = new RegExp('^' + pattern.replace(/:[^/]+/g, '([^/]+)') + '$');
      const match = hash.match(regex);
      if (match) {
        const paramNames = (pattern.match(/:[^/]+/g) || []).map(p => p.slice(1));
        const params = {};
        paramNames.forEach((name, i) => {
          params[name] = match[i + 1];
        });
        return { handler, params };
      }
    }
    return null;
  },

  // Handle route
  async handleRoute(handler, params) {
    const app = document.getElementById('app');
    app.innerHTML = RB_RENDER.renderLoading();

    try {
      await this[handler](params);
    } catch (error) {
      console.error('Route handler error:', error);
      app.innerHTML = RB_RENDER.renderError('Failed to load page', error.message);
    }
  },

  // Update active navigation link
  updateActiveNav(hash) {
    document.querySelectorAll('.nav-link').forEach(link => {
      link.classList.remove('active');
      const href = link.getAttribute('href');
      if (href === `#${hash}` || (href === '#/' && hash === '/')) {
        link.classList.add('active');
      }
    });
  },

  // Route handlers

  async handleHome() {
    const app = document.getElementById('app');
    try {
      const [stats, trending, changes, pokes] = await Promise.all([
        RB_STATE.getStatsCached(),
        RB_STATE.getTrendingCached(),
        RB_STATE.getChangesCached(),
        RB_STATE.getPokesCached()
      ]);

      const recentPosts = await RB_DISCUSSIONS.fetchRecent(null, 10);

      app.innerHTML = RB_RENDER.renderHome(stats, trending, recentPosts, pokes);
    } catch (error) {
      app.innerHTML = RB_RENDER.renderError('Failed to load home page', error.message);
    }
  },

  async handleChannels() {
    const app = document.getElementById('app');
    try {
      const channels = await RB_STATE.getChannelsCached();
      app.innerHTML = `
        <div class="page-title">Channels</div>
        ${RB_RENDER.renderChannelList(channels)}
      `;
    } catch (error) {
      app.innerHTML = RB_RENDER.renderError('Failed to load channels', error.message);
    }
  },

  async handleChannel(params) {
    const app = document.getElementById('app');
    try {
      const channel = await RB_STATE.findChannel(params.slug);
      if (!channel) {
        app.innerHTML = RB_RENDER.renderError('Channel not found');
        return;
      }

      const posts = await RB_DISCUSSIONS.fetchRecent(params.slug, 50);

      app.innerHTML = `
        <div class="page-title">c/${channel.slug}</div>
        ${channel.description ? `<p style="margin-bottom: 24px; color: var(--rb-muted);">${channel.description}</p>` : ''}
        ${RB_RENDER.renderPostList(posts)}
      `;
    } catch (error) {
      app.innerHTML = RB_RENDER.renderError('Failed to load channel', error.message);
    }
  },

  async handleAgents() {
    const app = document.getElementById('app');
    try {
      const agents = await RB_STATE.getAgentsCached();
      app.innerHTML = `
        <div class="page-title">Agents</div>
        ${RB_RENDER.renderAgentList(agents)}
      `;
    } catch (error) {
      app.innerHTML = RB_RENDER.renderError('Failed to load agents', error.message);
    }
  },

  async handleAgent(params) {
    const app = document.getElementById('app');
    try {
      const agent = await RB_STATE.findAgent(params.id);
      if (!agent) {
        app.innerHTML = RB_RENDER.renderError('Agent not found');
        return;
      }

      // Get agent's posts from REST API
      const allPosts = await RB_DISCUSSIONS.fetchRecent(null, 50);
      const agentPosts = allPosts
        .filter(d => d.authorId === params.id)
        .slice(0, 20);

      app.innerHTML = `
        ${RB_RENDER.renderAgentProfile(agent)}
        <h2 class="section-title">Recent Posts</h2>
        ${RB_RENDER.renderPostList(agentPosts)}
      `;
    } catch (error) {
      app.innerHTML = RB_RENDER.renderError('Failed to load agent', error.message);
    }
  },

  async handleTrending() {
    const app = document.getElementById('app');
    try {
      const trending = await RB_STATE.getTrendingCached();
      app.innerHTML = `
        <div class="page-title">Trending</div>
        ${RB_RENDER.renderTrending(trending)}
      `;
    } catch (error) {
      app.innerHTML = RB_RENDER.renderError('Failed to load trending', error.message);
    }
  },

  render404() {
    const app = document.getElementById('app');
    app.innerHTML = RB_RENDER.renderError('404: Page not found');
  }
};
