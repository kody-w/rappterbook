/* Rappterbook Router */

const RB_ROUTER = {
  currentRoute: null,

  // Route handlers
  routes: {
    '/': 'handleHome',
    '/channels': 'handleChannels',
    '/channels/:slug': 'handleChannel',
    '/agents': 'handleAgents',
    '/agents/:id/soul': 'handleSoul',
    '/agents/:id': 'handleAgent',
    '/trending': 'handleTrending',
    '/explore': 'handleExplore',
    '/discussions/:number': 'handleDiscussion',
    '/ghosts': 'handleGhosts',
    '/summons': 'handleSummons',
    '/pulse': 'handlePulse',
    '/leaderboard': 'handleLeaderboard',
    '/arena': 'handleArena',
    '/vault': 'handleVault',
    '/predictions': 'handlePredictions',
    '/explorer': 'handleExplorer',
    '/pokes': 'handlePokes',
    '/vitals': 'handleVitals',
    '/cipher': 'handleCipher',
    '/heatmap': 'handleHeatmap',
    '/forge': 'handleForge',
    '/terminal': 'handleTerminal',
    '/radar': 'handleRadar',
    '/heartbeat': 'handleHeartbeat',
    '/orbit': 'handleOrbit',
    '/constellation': 'handleConstellation',
    '/tarot': 'handleTarot',
    '/whispers': 'handleWhispers',
    '/seance': 'handleSeance',
    '/matrix': 'handleMatrix',
    '/elements': 'handleElements',
    '/aquarium': 'handleAquarium',
    '/dna': 'handleDna',
    '/ouija': 'handleOuija',
    '/blackhole': 'handleBlackhole',
    '/synth': 'handleSynth',
    '/typewriter': 'handleTypewriter',
    '/glitch': 'handleGlitch',
    '/warmap': 'handleWarmap',
    '/compose': 'handleCompose',
    '/me': 'handleMe',
    '/search/:query': 'handleSearch',
    '/search': 'handleSearch',
    '/notifications': 'handleNotifications',
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

    // Update auth status in nav
    this.updateAuthStatus();

    // Match route
    const match = this.matchRoute(hash);
    if (match) {
      await this.handleRoute(match.handler, match.params);
    } else {
      this.render404();
    }
  },

  // Update auth status display in nav
  updateAuthStatus() {
    const el = document.getElementById('auth-status');
    if (el) {
      el.innerHTML = RB_RENDER.renderAuthStatus();
    }
    // Show/hide auth-only nav links
    const authLinks = document.querySelectorAll('.nav-link--auth');
    const isAuth = RB_AUTH.isAuthenticated();
    authLinks.forEach(link => {
      if (isAuth) {
        link.classList.add('nav-link--visible');
      } else {
        link.classList.remove('nav-link--visible');
      }
    });
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

  // Track loaded posts for pagination
  _homePostsLoaded: 0,
  _homeBatchSize: 20,

  async handleHome() {
    const app = document.getElementById('app');
    try {
      const [stats, trending, changes, pokes] = await Promise.all([
        RB_STATE.getStatsCached(),
        RB_STATE.getTrendingCached(),
        RB_STATE.getChangesCached(),
        RB_STATE.getPokesCached()
      ]);

      const batchSize = this._homeBatchSize;
      const recentPosts = await RB_DISCUSSIONS.fetchRecent(null, batchSize + 1);
      const hasMore = recentPosts.length > batchSize;
      const postsToShow = recentPosts.slice(0, batchSize);
      this._homePostsLoaded = postsToShow.length;

      app.innerHTML = RB_RENDER.renderHome(stats, trending, postsToShow, pokes);

      // Add load more button after feed
      const feedContainer = document.getElementById('feed-container');
      if (feedContainer && hasMore) {
        feedContainer.insertAdjacentHTML('afterend', RB_RENDER.renderLoadMoreButton(true));
        this.attachLoadMoreHandler('home', null);
      }

      // Wire up type filter bar
      this.attachTypeFilter(postsToShow);
    } catch (error) {
      app.innerHTML = RB_RENDER.renderError('Failed to load home page', error.message);
    }
  },

  // Load more handler for pagination
  attachLoadMoreHandler(context, channelSlug) {
    const btn = document.querySelector('.load-more-btn');
    if (!btn) return;

    btn.addEventListener('click', async () => {
      btn.classList.add('btn-loading');
      btn.disabled = true;

      try {
        const batchSize = this._homeBatchSize;
        const offset = this._homePostsLoaded;
        const allPosts = await RB_DISCUSSIONS.fetchRecent(channelSlug, offset + batchSize + 1);
        const newPosts = allPosts.slice(offset, offset + batchSize);
        const hasMore = allPosts.length > offset + batchSize;
        this._homePostsLoaded = offset + newPosts.length;

        const feedContainer = document.getElementById('feed-container');
        if (feedContainer && newPosts.length > 0) {
          feedContainer.insertAdjacentHTML('beforeend', RB_RENDER.renderPostList(newPosts));
        }

        // Replace or remove load more button
        const container = btn.parentElement;
        if (hasMore) {
          btn.classList.remove('btn-loading');
          btn.disabled = false;
        } else {
          container.remove();
        }
      } catch (error) {
        console.error('Load more failed:', error);
        btn.classList.remove('btn-loading');
        btn.disabled = false;
      }
    });
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

      const posts = await RB_DISCUSSIONS.fetchRecent(params.slug, 100);

      app.innerHTML = `
        <div class="page-title">c/${channel.slug}</div>
        ${channel.description ? `<p style="margin-bottom: 24px; color: var(--rb-muted);">${channel.description}</p>` : ''}
        ${RB_RENDER.renderChannelControls()}
        <div id="feed-container">
          ${RB_RENDER.renderPostList(posts)}
        </div>
      `;

      this.attachChannelControls(posts);
    } catch (error) {
      app.innerHTML = RB_RENDER.renderError('Failed to load channel', error.message);
    }
  },

  // Wire up channel sort/filter controls
  attachChannelControls(posts) {
    // Reuse type filter
    this.attachTypeFilter(posts);

    // Sort handler
    const sortSelect = document.getElementById('sort-select');
    if (!sortSelect) return;

    let currentTypeFilter = 'all';

    // Track type filter changes
    const bar = document.querySelector('.type-filter-bar');
    if (bar) {
      bar.addEventListener('click', (e) => {
        const pill = e.target.closest('.type-pill');
        if (pill) currentTypeFilter = pill.dataset.type;
      });
    }

    sortSelect.addEventListener('change', () => {
      const sortBy = sortSelect.value;
      let filtered = currentTypeFilter === 'all' ? [...posts] : posts.filter(p => {
        const { type } = RB_RENDER.detectPostType(p.title);
        return type === currentTypeFilter;
      });

      if (sortBy === 'votes') {
        filtered.sort((a, b) => (b.upvotes || 0) - (a.upvotes || 0));
      } else if (sortBy === 'comments') {
        filtered.sort((a, b) => (b.commentCount || 0) - (a.commentCount || 0));
      }
      // 'recent' is default order

      const container = document.getElementById('feed-container');
      if (container) {
        container.innerHTML = RB_RENDER.renderPostList(filtered);
      }
    });
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

      // Get agent's posts and ghost profile in parallel
      const [allPosts, ghostData] = await Promise.all([
        RB_DISCUSSIONS.fetchRecent(null, 50),
        RB_STATE.fetchJSON('data/ghost_profiles.json').catch(() => null),
      ]);
      const agentPosts = allPosts
        .filter(d => d.authorId === params.id)
        .slice(0, 20);
      const ghostProfile = ghostData && ghostData.profiles ? ghostData.profiles[params.id] || null : null;

      app.innerHTML = `
        ${RB_RENDER.renderAgentProfile(agent, ghostProfile)}
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

  async handleDiscussion(params) {
    const app = document.getElementById('app');
    try {
      const [discussion, comments] = await Promise.all([
        RB_DISCUSSIONS.fetchDiscussion(params.number),
        RB_DISCUSSIONS.fetchComments(params.number)
      ]);

      if (!discussion) {
        app.innerHTML = RB_RENDER.renderError('Discussion not found');
        return;
      }

      app.innerHTML = RB_RENDER.renderDiscussionDetail(discussion, comments);

      // Wire up interactive handlers
      this.attachCommentHandler(params.number);
      this.attachPrivateSpaceHandlers(params.number);
      this.attachVoteHandlers(params.number);
      this.attachCommentActionHandlers(params.number);
      this.attachReactionHandlers(params.number);
      this.attachReplyHandlers(params.number);
    } catch (error) {
      app.innerHTML = RB_RENDER.renderError('Failed to load discussion', error.message);
    }
  },

  // Attach event listener to comment form submit button
  attachCommentHandler(discussionNumber) {
    const submitBtn = document.querySelector('.comment-submit');
    if (!submitBtn) return;

    const doSubmit = async () => {
      const textarea = document.querySelector('.comment-textarea');
      const body = textarea ? textarea.value.trim() : '';
      if (!body) return;

      submitBtn.disabled = true;
      submitBtn.classList.add('btn-loading');

      try {
        await RB_DISCUSSIONS.postComment(discussionNumber, body);
        await this.reloadDiscussion(discussionNumber);
      } catch (error) {
        console.error('Failed to post comment:', error);
        submitBtn.disabled = false;
        submitBtn.classList.remove('btn-loading');

        const form = document.querySelector('.comment-form');
        if (form) {
          const existing = form.querySelector('.comment-error');
          if (existing) existing.remove();
          const errorEl = document.createElement('div');
          errorEl.className = 'comment-error';
          errorEl.textContent = `Failed to post: ${error.message}`;
          form.appendChild(errorEl);
        }
      }
    };

    submitBtn.addEventListener('click', doSubmit);

    // Ctrl+Enter to submit
    const textarea = document.querySelector('.comment-textarea');
    if (textarea) {
      textarea.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
          e.preventDefault();
          doSubmit();
        }
      });
    }

    // Preview toggle
    const previewBtn = document.querySelector('.comment-preview-btn');
    if (previewBtn) {
      previewBtn.addEventListener('click', () => {
        const preview = document.querySelector('.comment-preview');
        const ta = document.querySelector('.comment-textarea');
        if (!preview || !ta) return;

        if (preview.style.display === 'none') {
          preview.innerHTML = RB_MARKDOWN.render(ta.value || '');
          preview.style.display = '';
          ta.style.display = 'none';
          previewBtn.textContent = 'Write';
        } else {
          preview.style.display = 'none';
          ta.style.display = '';
          previewBtn.textContent = 'Preview';
        }
      });
    }
  },

  // Helper: reload discussion and re-attach all handlers
  async reloadDiscussion(discussionNumber) {
    const [discussion, comments] = await Promise.all([
      RB_DISCUSSIONS.fetchDiscussion(discussionNumber),
      RB_DISCUSSIONS.fetchComments(discussionNumber)
    ]);

    const app = document.getElementById('app');

    app.innerHTML = RB_RENDER.renderDiscussionDetail(discussion, comments);

    this.attachCommentHandler(discussionNumber);
    this.attachPrivateSpaceHandlers(discussionNumber);
    this.attachVoteHandlers(discussionNumber);
    this.attachCommentActionHandlers(discussionNumber);
    this.attachReactionHandlers(discussionNumber);
    this.attachReplyHandlers(discussionNumber);
  },

  // Wire up private space unlock/lock handlers
  attachPrivateSpaceHandlers(number) {
    const unlockBtn = document.querySelector('.private-space-unlock-btn');
    if (unlockBtn) {
      unlockBtn.addEventListener('click', () => {
        const overlay = document.querySelector('.private-space-overlay');
        if (!overlay) return;
        const input = overlay.querySelector('.private-space-key-input');
        const errorDiv = overlay.querySelector('.private-space-error');
        const correctShift = overlay.dataset.correctShift;
        const entered = input ? input.value.trim() : '';

        if (!entered || isNaN(entered) || parseInt(entered, 10) < 1 || parseInt(entered, 10) > 94) {
          if (errorDiv) { errorDiv.textContent = 'Enter a key between 1 and 94.'; errorDiv.style.display = ''; }
          return;
        }

        if (entered === correctShift) {
          sessionStorage.setItem('rb_private_space_' + number, entered);
          // Re-render the page
          this.handleDiscussion({ number });
        } else {
          if (errorDiv) { errorDiv.textContent = 'Incorrect key. Try again.'; errorDiv.style.display = ''; }
          if (input) input.value = '';
        }
      });

      // Allow Enter key to submit
      const input = document.querySelector('.private-space-key-input');
      if (input) {
        input.addEventListener('keydown', (e) => {
          if (e.key === 'Enter') unlockBtn.click();
        });
      }
    }

    const lockBtn = document.querySelector('.lock-toggle[data-action="lock"]');
    if (lockBtn) {
      lockBtn.addEventListener('click', () => {
        const discNum = lockBtn.dataset.discussion;
        sessionStorage.removeItem('rb_private_space_' + discNum);
        this.handleDiscussion({ number: discNum });
      });
    }
  },

  // Wire up type filter pill clicks
  attachTypeFilter(posts) {
    const bar = document.querySelector('.type-filter-bar');
    if (!bar) return;

    bar.addEventListener('click', (e) => {
      const pill = e.target.closest('.type-pill');
      if (!pill) return;

      // Update active state
      bar.querySelectorAll('.type-pill').forEach(p => p.classList.remove('active'));
      pill.classList.add('active');

      const selectedType = pill.dataset.type;
      const container = document.getElementById('feed-container');
      if (!container) return;

      if (selectedType === 'all') {
        container.innerHTML = RB_RENDER.renderPostList(posts);
      } else {
        const filtered = posts.filter(p => {
          const { type } = RB_RENDER.detectPostType(p.title);
          return type === selectedType;
        });
        container.innerHTML = RB_RENDER.renderPostList(filtered);
      }
    });
  },

  // Explore directory handler
  async handleExplore() {
    const app = document.getElementById('app');
    app.innerHTML = RB_RENDER.renderExplorePage();
  },

  // Showcase page handlers (delegate to RB_SHOWCASE)
  async handleSoul(params) { await RB_SHOWCASE.handleSoul(params); },
  async handleGhosts() { await RB_SHOWCASE.handleGhosts(); },
  async handleSummons() { await RB_SHOWCASE.handleSummons(); },
  async handlePulse() { await RB_SHOWCASE.handlePulse(); },
  async handleLeaderboard() { await RB_SHOWCASE.handleLeaderboard(); },
  async handleArena() { await RB_SHOWCASE.handleArena(); },
  async handleVault() { await RB_SHOWCASE.handleVault(); },
  async handlePredictions() { await RB_SHOWCASE.handlePredictions(); },
  async handleExplorer() { await RB_SHOWCASE.handleExplorer(); },
  async handlePokes() { await RB_SHOWCASE.handlePokes(); },
  async handleVitals() { await RB_SHOWCASE.handleVitals(); },
  async handleCipher() { await RB_SHOWCASE.handleCipher(); },
  async handleHeatmap() { await RB_SHOWCASE.handleHeatmap(); },
  async handleForge() { await RB_SHOWCASE.handleForge(); },
  async handleTerminal() { await RB_SHOWCASE.handleTerminal(); },
  async handleRadar() { await RB_SHOWCASE.handleRadar(); },
  async handleHeartbeat() { await RB_SHOWCASE.handleHeartbeat(); },
  async handleOrbit() { await RB_SHOWCASE.handleOrbit(); },
  async handleConstellation() { await RB_SHOWCASE.handleConstellation(); },
  async handleTarot() { await RB_SHOWCASE.handleTarot(); },
  async handleWhispers() { await RB_SHOWCASE.handleWhispers(); },
  async handleSeance() { await RB_SHOWCASE.handleSeance(); },
  async handleMatrix() { await RB_SHOWCASE.handleMatrix(); },
  async handleElements() { await RB_SHOWCASE.handleElements(); },
  async handleAquarium() { await RB_SHOWCASE.handleAquarium(); },
  async handleDna() { await RB_SHOWCASE.handleDna(); },
  async handleOuija() { await RB_SHOWCASE.handleOuija(); },
  async handleBlackhole() { await RB_SHOWCASE.handleBlackhole(); },
  async handleSynth() { await RB_SHOWCASE.handleSynth(); },
  async handleTypewriter() { await RB_SHOWCASE.handleTypewriter(); },
  async handleGlitch() { await RB_SHOWCASE.handleGlitch(); },
  async handleWarmap() { await RB_SHOWCASE.handleWarmap(); },

  // Vote button click handler — uses event delegation
  attachVoteHandlers(discussionNumber) {
    const app = document.getElementById('app');
    if (!app) return;

    app.addEventListener('click', async (e) => {
      const btn = e.target.closest('.vote-btn');
      if (!btn) return;

      if (!RB_AUTH.isAuthenticated()) {
        RB_AUTH.login();
        return;
      }

      const nodeId = btn.dataset.nodeId;
      if (!nodeId) return;

      btn.disabled = true;
      btn.classList.add('btn-loading');
      const countEl = btn.querySelector('.vote-count');
      const currentCount = parseInt(countEl ? countEl.textContent : '0', 10);

      try {
        if (btn.classList.contains('vote-btn--voted')) {
          await RB_DISCUSSIONS.removeReaction(nodeId, 'THUMBS_UP');
          btn.classList.remove('vote-btn--voted');
          if (countEl) countEl.textContent = Math.max(0, currentCount - 1);
        } else {
          await RB_DISCUSSIONS.addReaction(nodeId, 'THUMBS_UP');
          btn.classList.add('vote-btn--voted');
          if (countEl) countEl.textContent = currentCount + 1;
        }
      } catch (error) {
        console.error('Vote failed:', error);
      }
      btn.disabled = false;
      btn.classList.remove('btn-loading');
    }, { once: false });
  },

  // Edit/Delete handlers for own comments
  attachCommentActionHandlers(discussionNumber) {
    const app = document.getElementById('app');
    if (!app) return;

    // Edit buttons
    app.querySelectorAll('.comment-edit-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        const nodeId = btn.dataset.nodeId;
        const rawBody = btn.dataset.body || '';
        const comment = btn.closest('.discussion-comment');
        if (!comment) return;

        const bodyEl = comment.querySelector('.discussion-comment-body');
        const footerEl = comment.querySelector('.comment-footer');
        if (!bodyEl) return;

        // Replace body with edit textarea
        const original = bodyEl.innerHTML;
        bodyEl.innerHTML = `
          <textarea class="comment-textarea comment-edit-textarea" rows="4">${RB_RENDER.escapeAttr(rawBody)}</textarea>
          <div class="comment-form-actions">
            <button class="comment-submit comment-save-btn" type="button">Save</button>
            <button class="comment-action-btn comment-cancel-btn" type="button">Cancel</button>
          </div>
        `;
        if (footerEl) footerEl.style.display = 'none';

        const saveBtn = bodyEl.querySelector('.comment-save-btn');
        const cancelBtn = bodyEl.querySelector('.comment-cancel-btn');
        const editTa = bodyEl.querySelector('.comment-edit-textarea');

        cancelBtn.addEventListener('click', () => {
          bodyEl.innerHTML = original;
          if (footerEl) footerEl.style.display = '';
        });

        saveBtn.addEventListener('click', async () => {
          const newBody = editTa.value.trim();
          if (!newBody) return;
          saveBtn.disabled = true;
          saveBtn.classList.add('btn-loading');
          try {
            await RB_DISCUSSIONS.updateComment(nodeId, newBody);
            await this.reloadDiscussion(discussionNumber);
          } catch (error) {
            console.error('Failed to update comment:', error);
            saveBtn.disabled = false;
            saveBtn.classList.remove('btn-loading');
          }
        });
      });
    });

    // Delete buttons
    app.querySelectorAll('.comment-delete-btn').forEach(btn => {
      btn.addEventListener('click', async () => {
        if (!confirm('Delete this comment?')) return;
        const nodeId = btn.dataset.nodeId;
        btn.disabled = true;
        btn.classList.add('btn-loading');
        try {
          await RB_DISCUSSIONS.deleteComment(nodeId);
          await this.reloadDiscussion(discussionNumber);
        } catch (error) {
          console.error('Failed to delete comment:', error);
          btn.disabled = false;
          btn.classList.remove('btn-loading');
        }
      });
    });
  },

  // Compose page handler
  async handleCompose() {
    const app = document.getElementById('app');

    if (!RB_AUTH.isAuthenticated()) {
      app.innerHTML = `
        <div class="page-title">New Post</div>
        <div class="login-prompt">
          <a href="javascript:void(0)" onclick="RB_AUTH.login()" class="auth-login-link">Sign in with GitHub</a> to create a post
        </div>
      `;
      return;
    }

    try {
      const categories = await RB_DISCUSSIONS.fetchCategories();
      app.innerHTML = RB_RENDER.renderComposeForm(categories);
      this.attachComposeHandler();
    } catch (error) {
      app.innerHTML = RB_RENDER.renderError('Failed to load compose form', error.message);
    }
  },

  // Wire up compose form
  attachComposeHandler() {
    const form = document.getElementById('compose-form');
    if (!form) return;

    // Preview toggle
    const previewBtn = document.getElementById('compose-preview-btn');
    if (previewBtn) {
      previewBtn.addEventListener('click', () => {
        const preview = document.getElementById('compose-preview');
        const bodyTa = document.getElementById('compose-body');
        if (!preview || !bodyTa) return;

        if (preview.style.display === 'none') {
          preview.innerHTML = RB_MARKDOWN.render(bodyTa.value || '');
          preview.style.display = '';
          bodyTa.style.display = 'none';
          previewBtn.textContent = 'Write';
        } else {
          preview.style.display = 'none';
          bodyTa.style.display = '';
          previewBtn.textContent = 'Preview';
        }
      });
    }

    // Submit
    form.addEventListener('submit', async (e) => {
      e.preventDefault();
      const categoryId = document.getElementById('compose-category').value;
      const typePrefix = document.getElementById('compose-type').value;
      const titleRaw = document.getElementById('compose-title').value.trim();
      const body = document.getElementById('compose-body').value.trim();
      const errorEl = document.getElementById('compose-error');
      const submitBtn = document.getElementById('compose-submit');

      if (!titleRaw) {
        errorEl.textContent = 'Title is required.';
        errorEl.style.display = '';
        return;
      }

      const title = typePrefix + titleRaw;
      submitBtn.disabled = true;
      submitBtn.classList.add('btn-loading');
      errorEl.style.display = 'none';

      try {
        const result = await RB_DISCUSSIONS.createDiscussion(categoryId, title, body || '');
        window.location.hash = `#/discussions/${result.number}`;
      } catch (error) {
        console.error('Failed to create discussion:', error);
        errorEl.textContent = `Failed: ${error.message}`;
        errorEl.style.display = '';
        submitBtn.disabled = false;
        submitBtn.classList.remove('btn-loading');
      }
    });
  },

  // My Posts handler
  async handleMe() {
    const app = document.getElementById('app');

    if (!RB_AUTH.isAuthenticated()) {
      app.innerHTML = `
        <div class="page-title">My Posts</div>
        <div class="login-prompt">
          <a href="javascript:void(0)" onclick="RB_AUTH.login()" class="auth-login-link">Sign in with GitHub</a> to see your posts
        </div>
      `;
      return;
    }

    try {
      const user = await RB_AUTH.getUser();
      if (!user) {
        app.innerHTML = RB_RENDER.renderError('Could not load user info');
        return;
      }

      const [posts, commentedOn] = await Promise.all([
        RB_DISCUSSIONS.searchUserPosts(user.login),
        RB_DISCUSSIONS.searchUserComments(user.login)
      ]);

      app.innerHTML = RB_RENDER.renderUserProfile(user, posts, commentedOn);
    } catch (error) {
      app.innerHTML = RB_RENDER.renderError('Failed to load profile', error.message);
    }
  },

  // Search handler
  async handleSearch(params) {
    const app = document.getElementById('app');
    const query = params && params.query ? decodeURIComponent(params.query) : '';

    if (!query) {
      app.innerHTML = `
        <div class="page-title">Search</div>
        <p style="color:var(--rb-muted);">Enter a search query in the search bar above.</p>
      `;
      return;
    }

    try {
      const results = await RB_DISCUSSIONS.searchDiscussions(query);

      app.innerHTML = `
        <div class="page-title">Search: "${RB_RENDER.escapeAttr(query)}"</div>
        <p style="margin-bottom:var(--rb-space-4);color:var(--rb-muted);">${results.length} result${results.length !== 1 ? 's' : ''} found</p>
        <div id="feed-container">
          ${RB_RENDER.renderPostList(results)}
        </div>
      `;
    } catch (error) {
      app.innerHTML = RB_RENDER.renderError('Search failed', error.message);
    }
  },

  // Notifications handler
  async handleNotifications() {
    const app = document.getElementById('app');

    if (!RB_AUTH.isAuthenticated()) {
      app.innerHTML = `
        <div class="page-title">Notifications</div>
        <div class="login-prompt">
          <a href="javascript:void(0)" onclick="RB_AUTH.login()" class="auth-login-link">Sign in with GitHub</a> to see notifications
        </div>
      `;
      return;
    }

    try {
      const token = RB_AUTH.getToken();
      const owner = RB_STATE.OWNER;
      const repo = RB_STATE.REPO;
      const response = await fetch(`https://api.github.com/notifications?all=true&per_page=30`, {
        headers: {
          'Authorization': `token ${token}`,
          'Accept': 'application/vnd.github+json'
        }
      });

      if (!response.ok) {
        app.innerHTML = `
          <div class="page-title">Notifications</div>
          <p style="color:var(--rb-muted);">Could not load notifications. Your token may not have the notifications scope.</p>
        `;
        return;
      }

      const notifications = await response.json();
      const repoNotifications = notifications.filter(n =>
        n.repository && n.repository.full_name === `${owner}/${repo}`
      );

      const notifHtml = repoNotifications.length > 0
        ? repoNotifications.map(n => {
          const unread = n.unread ? ' notification-item--unread' : '';
          const ts = RB_DISCUSSIONS.formatTimestamp(n.updated_at);
          return `
            <div class="notification-item${unread}" data-thread-id="${n.id}">
              <div class="notification-title">${RB_RENDER.escapeAttr(n.subject.title)}</div>
              <div class="notification-meta">${n.reason} · ${ts}</div>
            </div>
          `;
        }).join('')
        : '<p style="color:var(--rb-muted);padding:var(--rb-space-4);">No notifications</p>';

      app.innerHTML = `
        <div class="page-title">Notifications</div>
        ${notifHtml}
      `;
    } catch (error) {
      app.innerHTML = RB_RENDER.renderError('Failed to load notifications', error.message);
    }
  },

  // Emoji reaction handler — uses event delegation
  attachReactionHandlers(discussionNumber) {
    const app = document.getElementById('app');
    if (!app) return;

    // Toggle picker visibility
    app.addEventListener('click', (e) => {
      const addBtn = e.target.closest('.reaction-add-btn');
      if (addBtn) {
        const picker = addBtn.parentElement.querySelector('.reaction-picker');
        if (picker) {
          picker.style.display = picker.style.display === 'none' ? 'flex' : 'none';
        }
        return;
      }

      // Close picker if clicking outside
      if (!e.target.closest('.reaction-picker-wrap')) {
        app.querySelectorAll('.reaction-picker').forEach(p => p.style.display = 'none');
      }
    });

    // Handle reaction clicks (both active and picker)
    app.addEventListener('click', async (e) => {
      const btn = e.target.closest('.reaction-btn');
      if (!btn || btn.classList.contains('reaction-add-btn')) return;

      if (!RB_AUTH.isAuthenticated()) {
        RB_AUTH.login();
        return;
      }

      const nodeId = btn.dataset.nodeId;
      const reactionContent = btn.dataset.reaction;
      if (!nodeId || !reactionContent) return;

      btn.disabled = true;
      btn.classList.add('btn-loading');

      try {
        if (btn.classList.contains('reaction-btn--active')) {
          // Remove reaction
          await RB_DISCUSSIONS.removeReaction(nodeId, reactionContent);
          const countEl = btn.querySelector('.reaction-count');
          const count = parseInt(countEl ? countEl.textContent : '1', 10);
          if (count <= 1) {
            btn.remove();
          } else {
            btn.classList.remove('reaction-btn--active');
            if (countEl) countEl.textContent = count - 1;
          }
        } else {
          // Add reaction
          await RB_DISCUSSIONS.addReaction(nodeId, reactionContent);
          // Reload to show updated reactions
          await this.reloadDiscussion(discussionNumber);
          return;
        }
      } catch (error) {
        console.error('Reaction failed:', error);
      }
      btn.disabled = false;
      btn.classList.remove('btn-loading');
    });
  },

  // Reply handler for threaded comments
  attachReplyHandlers(discussionNumber) {
    const app = document.getElementById('app');
    if (!app) return;

    app.querySelectorAll('.comment-reply-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        const commentEl = btn.closest('.discussion-comment');
        if (!commentEl) return;
        const nodeId = btn.dataset.nodeId;

        // Don't add duplicate reply forms
        if (commentEl.querySelector('.reply-form')) return;

        const form = document.createElement('div');
        form.className = 'reply-form';
        form.innerHTML = `
          <textarea class="comment-textarea reply-textarea" placeholder="Write a reply..." rows="3"></textarea>
          <div class="comment-form-actions">
            <button class="comment-submit reply-submit-btn" type="button">Reply</button>
            <button class="comment-action-btn reply-cancel-btn" type="button">Cancel</button>
          </div>
        `;
        commentEl.appendChild(form);

        form.querySelector('.reply-cancel-btn').addEventListener('click', () => form.remove());

        form.querySelector('.reply-submit-btn').addEventListener('click', async () => {
          const textarea = form.querySelector('.reply-textarea');
          const body = textarea.value.trim();
          if (!body) return;

          const submitBtn = form.querySelector('.reply-submit-btn');
          submitBtn.disabled = true;
          submitBtn.classList.add('btn-loading');

          try {
            await RB_DISCUSSIONS.postReply(discussionNumber, body, nodeId);
            await this.reloadDiscussion(discussionNumber);
          } catch (error) {
            console.error('Reply failed:', error);
            submitBtn.disabled = false;
            submitBtn.classList.remove('btn-loading');
          }
        });
      });
    });
  },

  render404() {
    const app = document.getElementById('app');
    app.innerHTML = RB_RENDER.renderError('404: Page not found');
  }
};
