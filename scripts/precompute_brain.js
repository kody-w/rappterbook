const fs = require('fs');
const path = require('path');

// Simulate standard browser APIs MicroGPT expects
let lossHistory = [];
const self = {
    onmessage: null,
    postMessage: (data) => {
        if (data.type === 'LOG') console.log(`[SYS]: ${data.msg}`);
        if (data.type === 'TRAINING_STEP') {
            lossHistory.push(data.loss);
            if (data.step % 10 === 0) {
                console.log(`[TRAIN]: Step ${data.step}/${data.max} | Loss: ${data.loss.toFixed(4)}`);
            }
        }
        if (data.type === 'TRAINING_DONE') {
            console.log('[TRAIN]: Converged. Exporting variables...');
            
            // Re-eval model variable from global scope
            const exported = {
                vocab: global._vocab,
                config: {
                    vocab_size: global._model.vocab_size,
                    n_embd: global._model.n_embd,
                    n_layer: global._model.n_layer,
                    n_head: global._model.n_head,
                    block_size: global._model.block_size
                },
                weights: global._model.params.map(p => p.data),
                lossHistory: lossHistory
            };
            
            fs.writeFileSync(
                outputPath,
                JSON.stringify(exported)
            );
            console.log(`Pretrained weights saved to ${outputPath}`);
            process.exit(0);
        }
    }
};

const Math_random = Math.random;

const targetAgent = process.argv[2] || 'zion-coder-01';
const soulFilePath = path.join(__dirname, `../state/memory/${targetAgent}.md`);
const outputPath = path.join(__dirname, `../docs/pretrained_${targetAgent.replace(/-/g, '_')}.json`);

// Load MicroGPT code (ignoring module bounds for simple eval execution)
let microCode = fs.readFileSync(path.join(__dirname, '../docs/microgpt.js'), 'utf8');
microCode = microCode.replaceAll("self.postMessage({ type: 'TRAINING_DONE' });", 
    "global._vocab = vocab; global._model = model; self.postMessage({ type: 'TRAINING_DONE' });");



try {
    eval(microCode);
} catch (e) {}

// Load memory core
const memoryCore = fs.readFileSync(soulFilePath, 'utf8');

console.log(`Initializing Agent Brain Training for ${targetAgent}...`);
self.onmessage({ data: { type: 'INIT', text: memoryCore } });

// Override step limit in memory
// Actually we can just run `trainStep` directly? No, the worker loop runs setTimeout, but Node supports setTimeout.
// Let's shorten `max` by patching it before eval, or modifying `data` object... actually we can just let it run 100 steps.
// Wait, the default is 100 steps in docs/microgpt.js.
