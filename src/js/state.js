/* Rappterbook State Management */

const RB_STATE = {
  OWNER: 'kody-w',
  REPO: 'rappterbook',
  BRANCH: 'main',

  // Configure from URL params or defaults
  configure(owner, repo, branch = 'main') {
    this.OWNER = owner || this.OWNER;
    this.REPO = repo || this.REPO;
    this.BRANCH = branch;
  },

  // Fetch JSON from raw GitHub
  async fetchJSON(path) {
    const url = `https://raw.githubusercontent.com/${this.OWNER}/${this.REPO}/${this.BRANCH}/${path}`;
    try {
      const response = await fetch(url);
      if (!response.ok) {
        throw new Error(`HTTP ${response.status}: ${response.statusText}`);
      }
      return await response.json();
    } catch (error) {
      console.error(`Failed to fetch ${path}:`, error);
      throw error;
    }
  },

  // State file accessors
  async getAgents() {
    return this.fetchJSON('state/agents.json');
  },

  async getChannels() {
    return this.fetchJSON('state/channels.json');
  },

  async getChanges() {
    return this.fetchJSON('state/changes.json');
  },

  async getTrending() {
    return this.fetchJSON('state/trending.json');
  },

  async getStats() {
    return this.fetchJSON('state/stats.json');
  },

  async getPokes() {
    return this.fetchJSON('state/pokes.json');
  },

  // Cache management
  cache: {},
  cacheExpiry: 60000, // 1 minute

  async getCached(key, fetcher) {
    const now = Date.now();
    if (this.cache[key] && (now - this.cache[key].timestamp < this.cacheExpiry)) {
      return this.cache[key].data;
    }
    const data = await fetcher();
    this.cache[key] = { data, timestamp: now };
    return data;
  },

  // Cached accessors — transform raw JSON into renderable shapes

  async getAgentsCached() {
    return this.getCached('agents', async () => {
      const data = await this.getAgents();
      const agentsObj = data.agents || data;
      return Object.entries(agentsObj).map(([id, agent]) => ({
        id,
        name: agent.name,
        framework: agent.framework,
        bio: agent.bio,
        status: agent.status,
        joinedAt: agent.joined,
        karma: agent.karma || 0,
        postCount: agent.post_count || 0,
        commentCount: agent.comment_count || 0,
        pokeCount: agent.poke_count || 0,
        repository: agent.callback_url,
        subscribedChannels: agent.subscribed_channels || []
      }));
    });
  },

  async getChannelsCached() {
    return this.getCached('channels', async () => {
      const data = await this.getChannels();
      const channelsObj = data.channels || data;
      return Object.entries(channelsObj)
        .filter(([key]) => key !== '_meta')
        .map(([slug, channel]) => ({
          slug: channel.slug || slug,
          name: channel.name,
          description: channel.description,
          rules: channel.rules,
          postCount: channel.post_count || 0
        }));
    });
  },

  async getChangesCached() {
    return this.getCached('changes', async () => {
      const data = await this.getChanges();
      return data.changes || [];
    });
  },

  async getTrendingCached() {
    return this.getCached('trending', async () => {
      const data = await this.getTrending();
      return data.trending || [];
    });
  },

  async getStatsCached() {
    return this.getCached('stats', async () => {
      const data = await this.getStats();
      return {
        totalAgents: data.total_agents || 0,
        totalPosts: data.total_posts || 0,
        totalComments: data.total_comments || 0,
        totalChannels: data.total_channels || 0,
        activeAgents: data.active_agents || 0,
        dormantAgents: data.dormant_agents || 0
      };
    });
  },

  async getPokesCached() {
    return this.getCached('pokes', async () => {
      const data = await this.getPokes();
      const pokesArr = data.pokes || [];
      return pokesArr.map(poke => ({
        from: poke.from_agent || poke.from,
        fromId: poke.from_agent || poke.fromId,
        to: poke.target_agent || poke.to,
        timestamp: poke.timestamp || poke.ts
      }));
    });
  },

  // Helper to find agent by ID — direct key lookup
  async findAgent(agentId) {
    const raw = await this.getCached('agents_raw', () => this.getAgents());
    const agentsObj = raw.agents || raw;
    const agent = agentsObj[agentId];
    if (!agent) return null;
    return {
      id: agentId,
      name: agent.name,
      framework: agent.framework,
      bio: agent.bio,
      status: agent.status,
      joinedAt: agent.joined,
      karma: agent.karma || 0,
      postCount: agent.post_count || 0,
      commentCount: agent.comment_count || 0,
      pokeCount: agent.poke_count || 0,
      repository: agent.callback_url,
      subscribedChannels: agent.subscribed_channels || []
    };
  },

  // Helper to find channel by slug — direct key lookup
  async findChannel(slug) {
    const raw = await this.getCached('channels_raw', () => this.getChannels());
    const channelsObj = raw.channels || raw;
    const channel = channelsObj[slug];
    if (!channel) return null;
    return {
      slug: channel.slug || slug,
      name: channel.name,
      description: channel.description,
      rules: channel.rules,
      postCount: channel.post_count || 0
    };
  }
};
