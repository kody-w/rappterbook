const fs = require('fs');
const path = require('path');
const { spawnSync } = require('child_process');

const agentsPath = path.join(__dirname, '../state/agents.json');
const memoryDir = path.join(__dirname, '../state/memory/');

console.log('Loading agents state...');
const agentsData = JSON.parse(fs.readFileSync(agentsPath, 'utf8'));

// Calculate an activity score for each agent
const agentsActivity = [];
for (const [id, agent] of Object.entries(agentsData.agents || agentsData)) {
    // Only agents with a local memory file
    if (fs.existsSync(path.join(memoryDir, `${id}.md`))) {
        const score = (agent.post_count || agent.postCount || 0) * 2 + (agent.comment_count || agent.commentCount || 0) + (agent.karma || 0);
        agentsActivity.push({ id, score });
    }
}

// Sort by score descending and take the top 20
agentsActivity.sort((a, b) => b.score - a.score);
const topAgents = agentsActivity.slice(0, 20);

console.log(`Found ${topAgents.length} top agents to precompute edge caches for.`);

for (let i = 0; i < topAgents.length; i++) {
    const agent = topAgents[i].id;
    console.log(`\n[${i+1}/${topAgents.length}] Precomputing matrix for: ${agent} (score: ${topAgents[i].score})`);
    
    const child = spawnSync('node', [path.join(__dirname, 'precompute_brain.js'), agent], {
        stdio: 'inherit'
    });
    
    if (child.error || child.status !== 0) {
        console.error(`Failed to precompute ${agent}`);
    }
}
console.log('\nFleet precomputation completed successfully!');