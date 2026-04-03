import fs from 'fs';
import process from 'process';

async function main() {
    const args = process.argv.slice(2);
    if (args.length > 0 && (args[0].includes('brain') || args[0] === '-')) {
        args.shift();
    }
    const promptText = args.join(' ') || "What is the true nature of this network?";

    console.log(`[SYS] Loading Local Agent Brain & synaptic weights from local fs...`);
    
    // Read directly from local docs/
    const code = fs.readFileSync('docs/microgpt.js', 'utf8');
    const weightsStr = fs.readFileSync('docs/pretrained_system.json', 'utf8');

    const weights = JSON.parse(weightsStr);
    let isDone = false;

    global.self = {
        customModel: { use_true_math: true },
        postMessage: (msg) => {
            if (msg.type === 'TOKEN') {
                process.stdout.write(msg.char || "");
            } else if (msg.type === 'INFERENCE_DONE') {
                console.log("\n");
                isDone = true;
            } else if (msg.type === 'LOG') {
                // hide debug logs for clean output
            }
        }
    };

    eval(code);

    self.onmessage({
        data: {
            type: 'INIT_PRETRAINED',
            params: weights,
            customModel: { use_true_math: true }
        }
    });

    console.log(`[SYS] Engine assembled. Starting local inference.\n`);
    process.stdout.write("Agent: ");

    self.onmessage({
        data: {
            type: 'INJECT',
            text: promptText,
            temperature: 0.8
        }
    });

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
