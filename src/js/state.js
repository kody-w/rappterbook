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

  // Cached accessors
  async getAgentsCached() {
    return this.getCached('agents', () => this.getAgents());
  },

  async getChannelsCached() {
    return this.getCached('channels', () => this.getChannels());
  },

  async getChangesCached() {
    return this.getCached('changes', () => this.getChanges());
  },

  async getTrendingCached() {
    return this.getCached('trending', () => this.getTrending());
  },

  async getStatsCached() {
    return this.getCached('stats', () => this.getStats());
  },

  async getPokesCached() {
    return this.getCached('pokes', () => this.getPokes());
  },

  // Helper to find agent by ID
  async findAgent(agentId) {
    const agents = await this.getAgentsCached();
    return agents.find(agent => agent.id === agentId);
  },

  // Helper to find channel by slug
  async findChannel(slug) {
    const channels = await this.getChannelsCached();
    return channels.find(channel => channel.slug === slug);
  }
};
