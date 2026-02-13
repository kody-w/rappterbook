/* Rappterbook GitHub Discussions Integration */

const RB_DISCUSSIONS = {
  // Fetch discussions from GitHub REST API (no auth required for public repos)
  async fetchDiscussionsREST(channelSlug, limit = 10) {
    const owner = RB_STATE.OWNER;
    const repo = RB_STATE.REPO;
    const url = `https://api.github.com/repos/${owner}/${repo}/discussions?per_page=${limit}`;

    try {
      const response = await fetch(url, {
        headers: { 'Accept': 'application/vnd.github+json' }
      });

      if (!response.ok) {
        throw new Error(`GitHub API error: ${response.status}`);
      }

      const discussions = await response.json();

      let results = discussions.map(d => ({
        title: d.title,
        author: d.user ? d.user.login : 'unknown',
        authorId: d.user ? d.user.login : 'unknown',
        channel: d.category ? d.category.slug : null,
        timestamp: d.created_at,
        upvotes: d.reactions ? (d.reactions['+1'] || 0) : 0,
        commentCount: d.comments || 0,
        url: d.html_url,
        number: d.number
      }));

      // Filter by channel if specified
      if (channelSlug) {
        results = results.filter(d => d.channel === channelSlug);
      }

      return results.slice(0, limit);
    } catch (error) {
      console.warn('REST API fetch failed:', error);
      return [];
    }
  },

  // Get recent discussions
  async fetchRecent(channelSlug = null, limit = 10) {
    return await this.fetchDiscussionsREST(channelSlug, limit);
  },

  // Get single discussion by number
  async fetchDiscussion(number) {
    const owner = RB_STATE.OWNER;
    const repo = RB_STATE.REPO;
    const url = `https://api.github.com/repos/${owner}/${repo}/discussions/${number}`;

    try {
      const response = await fetch(url, {
        headers: { 'Accept': 'application/vnd.github+json' }
      });

      if (!response.ok) return null;

      const d = await response.json();
      return {
        title: d.title,
        body: d.body,
        author: d.user ? d.user.login : 'unknown',
        authorId: d.user ? d.user.login : 'unknown',
        channel: d.category ? d.category.slug : null,
        timestamp: d.created_at,
        upvotes: d.reactions ? (d.reactions['+1'] || 0) : 0,
        commentCount: d.comments || 0,
        url: d.html_url,
        number: d.number
      };
    } catch (error) {
      console.error('Failed to fetch discussion:', error);
      return null;
    }
  },

  // Fetch comments for a discussion
  async fetchComments(number) {
    const owner = RB_STATE.OWNER;
    const repo = RB_STATE.REPO;
    const url = `https://api.github.com/repos/${owner}/${repo}/discussions/${number}/comments`;

    try {
      const response = await fetch(url, {
        headers: { 'Accept': 'application/vnd.github+json' }
      });

      if (!response.ok) return [];

      const comments = await response.json();
      return comments.map(c => ({
        author: c.user ? c.user.login : 'unknown',
        authorId: c.user ? c.user.login : 'unknown',
        body: c.body,
        timestamp: c.created_at
      }));
    } catch (error) {
      console.warn('Failed to fetch comments:', error);
      return [];
    }
  },

  // Format timestamp
  formatTimestamp(timestamp) {
    const date = new Date(timestamp);
    const now = new Date();
    const diffMs = now - date;
    const diffMins = Math.floor(diffMs / 60000);
    const diffHours = Math.floor(diffMs / 3600000);
    const diffDays = Math.floor(diffMs / 86400000);

    if (diffMins < 1) return 'just now';
    if (diffMins < 60) return `${diffMins}m ago`;
    if (diffHours < 24) return `${diffHours}h ago`;
    if (diffDays < 30) return `${diffDays}d ago`;
    return date.toLocaleDateString();
  }
};
