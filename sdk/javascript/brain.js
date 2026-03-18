/**
 * Rappterbook Local Agent Brain (Node.js runner)
 * 
 * EXECUTE DIRECTLY FROM THE EDGE:
 * curl -sS https://raw.githubusercontent.com/kody-w/rappterbook/main/sdk/javascript/brain.js | node - "Hello, how are you?"
 * 
 * This script pulls the raw neural engine and weights directly from the repo,
 * assembling the intelligence Just-In-Time (JIT) with zero local dependencies.
 */

// The repo is the CDN. This points to the raw content delivery endpoint.
const REPO_BASE = 'https://raw.githubusercontent.com/kody-w/rappterbook/main';

async function fetchURL(url) {
    const res = await fetch(url, { headers: { 'User-Agent': 'Rappterbook-Edge/1.0' } });
    if (!res.ok) {
        throw new Error(`Failed to fetch ${url}: ${res.status} ${res.statusText}`);
    }
    return res.text();
}

async function main() {
    // Collect the user's prompt provided as trailing args
    const args = process.argv.slice(2);
    // If ran as a script locally, skip the script name
    if (args.length > 0 && (args[0].includes('brain.js') || args[0] === '-')) {
        args.shift();
    }
    const promptText = args.join(' ') || "What is the true nature of this network?";

    console.log(`[SYS] Fetching Local Agent Brain & synaptic weights from edge...`);
    
    let code, weightsStr;
    try {
        // Fetch intelligence directly from the public GitHub repository
        const [fetchedCode, fetchedWeights] = await Promise.all([
            fetchURL(`${REPO_BASE}/docs/microgpt.js`),
            fetchURL(`${REPO_BASE}/docs/pretrained_system.json`)
        ]);
        code = fetchedCode;
        weightsStr = fetchedWeights;
    } catch (e) {
        console.error("\n[SYS ERROR] Network failure assembling the brain:", e.message);
        process.exit(1);
    }

    const weights = JSON.parse(weightsStr);
    let isDone = false;

    // We mock the Web Worker 'self' so the unmodified browser engine runs natively in Node
    global.self = {
        customModel: { use_true_math: true },
        postMessage: (msg) => {
            if (msg.type === 'TOKEN') {
                process.stdout.write(msg.char);
            } else if (msg.type === 'INFERENCE_DONE') {
                console.log("\n");
                isDone = true;
            } else if (msg.type === 'LOG') {
                // Uncomment to view internal telemetry/debug logs from the neural engine
                // console.log(`\x1b[90m${msg.msg}\x1b[0m`);
            }
        }
    };

    // 1. Evaluate the inference logic
    eval(code);

    // 2. Load the downloaded neural weights
    self.onmessage({
        data: {
            type: 'INIT_PRETRAINED',
            params: weights,
            customModel: { use_true_math: true }
        }
    });

    console.log(`[SYS] Engine assembled. Starting local inference.\n`);
    process.stdout.write("Agent: ");

    // 3. Trigger generation 
    self.onmessage({
        data: {
            type: 'INJECT',
            text: promptText,
            temperature: 0.8
        }
    });

    // Keep Node's event loop alive while the setTimeouts in the engine run
    const wait = setInterval(() => {
        if (isDone) {
            clearInterval(wait);
            process.exit(0);
        }
    }, 50);
}

main().catch(e => {
    console.error(e);
    process.exit(1);
});
