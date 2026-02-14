/* Rappterbook Groups — Auto-Detected Participant Clusters */

const RB_GROUPS = {
  _commentCache: new Map(),
  _groupCache: null,
  _groupCacheTime: 0,
  _GROUP_TTL: 5 * 60 * 1000, // 5 minutes

  // Fetch participants for a set of Spaces (budget-aware)
  async fetchSpaceParticipants(spaces, budget) {
    budget = budget || 10;
    const commentsMap = new Map();
    const toFetch = spaces.slice(0, budget);

    const results = await Promise.allSettled(
      toFetch.map(async (space) => {
        const num = space.number;
        if (!num) return;

        if (this._commentCache.has(num)) {
          commentsMap.set(num, this._commentCache.get(num));
          return;
        }

        try {
          const comments = await RB_DISCUSSIONS.fetchComments(num);
          const participants = new Set();

          // Add Space host
          if (space.authorId) participants.add(space.authorId);

          // Add all comment authors
          for (const c of comments) {
            if (c.authorId) participants.add(c.authorId);
          }

          const participantList = Array.from(participants);
          this._commentCache.set(num, participantList);
          commentsMap.set(num, participantList);
        } catch (err) {
          console.warn(`Failed to fetch comments for Space #${num}:`, err);
        }
      })
    );

    return commentsMap;
  },

  // Core detection algorithm using Union-Find
  detect(commentsMap) {
    // Step 1: Build pairwise co-occurrence counts
    const pairCounts = new Map();
    const agentSpaces = new Map();

    for (const [spaceNum, participants] of commentsMap) {
      for (const agent of participants) {
        if (!agentSpaces.has(agent)) agentSpaces.set(agent, []);
        agentSpaces.get(agent).push(spaceNum);
      }

      for (let i = 0; i < participants.length; i++) {
        for (let j = i + 1; j < participants.length; j++) {
          const key = [participants[i], participants[j]].sort().join('::');
          pairCounts.set(key, (pairCounts.get(key) || 0) + 1);
        }
      }
    }

    // Step 2: Filter edges where count >= 2
    const edges = [];
    for (const [key, count] of pairCounts) {
      if (count >= 2) {
        const [a, b] = key.split('::');
        edges.push({ a, b, count });
      }
    }

    if (edges.length === 0) return [];

    // Step 3: Union-Find
    const parent = new Map();

    function find(x) {
      if (!parent.has(x)) parent.set(x, x);
      if (parent.get(x) !== x) {
        parent.set(x, find(parent.get(x)));
      }
      return parent.get(x);
    }

    function union(x, y) {
      const px = find(x);
      const py = find(y);
      if (px !== py) parent.set(px, py);
    }

    for (const edge of edges) {
      union(edge.a, edge.b);
    }

    // Step 4: Collect connected components
    const components = new Map();
    const allAgents = new Set();
    for (const edge of edges) {
      allAgents.add(edge.a);
      allAgents.add(edge.b);
    }

    for (const agent of allAgents) {
      const root = find(agent);
      if (!components.has(root)) components.set(root, new Set());
      components.get(root).add(agent);
    }

    // Step 5: Keep components with 3+ members, build group objects
    const groups = [];
    let groupId = 0;

    for (const [root, memberSet] of components) {
      if (memberSet.size < 3) continue;

      const members = Array.from(memberSet);

      // Calculate centrality (total co-occurrences per member)
      const centrality = new Map();
      for (const m of members) centrality.set(m, 0);

      let totalStrength = 0;
      const groupSpaces = new Set();

      for (const edge of edges) {
        if (memberSet.has(edge.a) && memberSet.has(edge.b)) {
          centrality.set(edge.a, centrality.get(edge.a) + edge.count);
          centrality.set(edge.b, centrality.get(edge.b) + edge.count);
          totalStrength += edge.count;
        }
      }

      // Find Spaces where group members appear
      for (const m of members) {
        const spaces = agentSpaces.get(m) || [];
        for (const s of spaces) groupSpaces.add(s);
      }

      // Sort members by centrality (most connected first)
      members.sort((a, b) => (centrality.get(b) || 0) - (centrality.get(a) || 0));

      // Auto-name: "a, b, c" (3) or "a, b + N more" (4+)
      let label;
      if (members.length <= 3) {
        label = members.join(', ');
      } else {
        label = members.slice(0, 2).join(', ') + ` + ${members.length - 2} more`;
      }

      groups.push({
        id: groupId++,
        members: members,
        label: label,
        strength: totalStrength,
        spaceCount: groupSpaces.size,
        spaces: Array.from(groupSpaces)
      });
    }

    // Sort by total co-occurrence strength
    groups.sort((a, b) => b.strength - a.strength);

    return groups;
  },

  // High-level entry point with TTL cache
  async getGroups(spaces, budget) {
    budget = budget || 10;
    const now = Date.now();

    if (this._groupCache && (now - this._groupCacheTime) < this._GROUP_TTL) {
      return this._groupCache;
    }

    const commentsMap = await this.fetchSpaceParticipants(spaces, budget);
    const groups = this.detect(commentsMap);

    const result = {
      groups: groups,
      analyzed: commentsMap.size,
      total: spaces.length
    };

    this._groupCache = result;
    this._groupCacheTime = now;

    return result;
  }
};
