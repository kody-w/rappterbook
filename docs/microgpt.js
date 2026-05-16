/*
 * MicroGPT JavaScript Port
 * Based on Andrej Karpathy's pure Python microgpt
 * Zero-dependencies, scalar autograd, GPT-2 architecture
 * Designed to run in a Web Worker for local intelligence
 */

class Value {
    constructor(data, children = [], local_grads = []) {
        this.data = data;
        this.grad = 0;
        this._children = children;
        this._local_grads = local_grads;
    }
    add(other) {
        other = other instanceof Value ? other : new Value(other);
        return new Value(this.data + other.data, [this, other], [1, 1]);
    }
    mul(other) {
        other = other instanceof Value ? other : new Value(other);
        return new Value(this.data * other.data, [this, other], [other.data, this.data]);
    }
    pow(n) {
        return new Value(Math.pow(this.data, n), [this], [n * Math.pow(this.data, n - 1)]);
    }
    log() {
        return new Value(Math.log(this.data), [this], [1 / this.data]);
    }
    exp() {
        return new Value(Math.exp(this.data), [this], [Math.exp(this.data)]);
    }
    relu() {
        return new Value(Math.max(0, this.data), [this], [this.data > 0 ? 1 : 0]);
    }
    backward() {
        const topo = [];
        const visited = new Set();
        const build_topo = (v) => {
            if (!visited.has(v)) {
                visited.add(v);
                for (let i=0; i < v._children.length; i++) build_topo(v._children[i]);
                topo.push(v);
            }
        };
        build_topo(this);
        this.grad = 1;
        for (let i = topo.length - 1; i >= 0; i--) {
            const v = topo[i];
            for (let j = 0; j < v._children.length; j++) {
                v._children[j].grad += v._local_grads[j] * v.grad;
            }
        }
    }
}

class MicroGPT {
    constructor(vocab_size, n_embd = 8, n_head = 2, n_layer = 1, block_size = 8) {
        this.vocab_size = vocab_size;
        this.n_embd = n_embd;
        this.n_head = n_head;
        this.n_layer = n_layer;
        this.block_size = block_size;
        this.head_dim = Math.floor(n_embd / n_head);
        
        // Random normal distribution approx
        const randG = () => (Math.random() + Math.random() + Math.random() + Math.random() - 2) * 0.08; 
        this.matrix = (nout, nin) => Array.from({length: nout}, () => Array.from({length: nin}, () => new Value(randG())));
        
        this.wte = this.matrix(vocab_size, n_embd);
        this.wpe = this.matrix(block_size, n_embd);
        this.lm_head = this.matrix(vocab_size, n_embd);
        
        this.layers = [];
        for (let i = 0; i < n_layer; i++) {
            this.layers.push({
                attn_wq: this.matrix(n_embd, n_embd),
                attn_wk: this.matrix(n_embd, n_embd),
                attn_wv: this.matrix(n_embd, n_embd),
                attn_wo: this.matrix(n_embd, n_embd),
                mlp_fc1: this.matrix(4 * n_embd, n_embd),
                mlp_fc2: this.matrix(n_embd, 4 * n_embd)
            });
        }
        
        this.params = [];
        for (const row of this.wte) this.params.push(...row);
        for (const row of this.wpe) this.params.push(...row);
        for (const row of this.lm_head) this.params.push(...row);
        for (const L of this.layers) {
            for (const row of L.attn_wq) this.params.push(...row);
            for (const row of L.attn_wk) this.params.push(...row);
            for (const row of L.attn_wv) this.params.push(...row);
            for (const row of L.attn_wo) this.params.push(...row);
            for (const row of L.mlp_fc1) this.params.push(...row);
            for (const row of L.mlp_fc2) this.params.push(...row);
        }
    }

    linear(x, w) {
        return w.map(wo => {
            let sum = new Value(0);
            for (let i = 0; i < wo.length; i++) {
                sum = sum.add(wo[i].mul(x[i]));
            }
            return sum;
        });
    }

    softmax(logits) {
        const max_val = Math.max(...logits.map(v => v.data));
        const exps = logits.map(v => v.add(new Value(-max_val)).exp());
        let total = Object.assign(new Value(0), {data: 0});
        for (const e of exps) Object.assign(total, total.add(e));
        return exps.map(e => e.mul(total.pow(-1)));
    }

    rmsnorm(x) {
        let ms = new Value(0);
        for (const xi of x) ms = ms.add(xi.mul(xi));
        ms = ms.mul(new Value(1 / x.length));
        const scale = ms.add(new Value(1e-5)).pow(-0.5);
        return x.map(xi => xi.mul(scale));
    }

    forward(token_id, pos_id, keys, values) {
        const tok_emb = this.wte[token_id];
        const pos_emb = this.wpe[pos_id];
        let x = tok_emb.map((t, i) => t.add(pos_emb[i]));
        x = this.rmsnorm(x);

        for (let li = 0; li < this.n_layer; li++) {
            let x_residual = x;
            x = this.rmsnorm(x);
            
            const L = this.layers[li];
            const q = this.linear(x, L.attn_wq);
            const k = this.linear(x, L.attn_wk);
            const v = this.linear(x, L.attn_wv);
            keys[li].push(k);
            values[li].push(v);
            
            let x_attn = [];
            for (let h = 0; h < this.n_head; h++) {
                const hs = h * this.head_dim;
                const q_h = q.slice(hs, hs + this.head_dim);
                const k_h = keys[li].map(ki => ki.slice(hs, hs + this.head_dim));
                const v_h = values[li].map(vi => vi.slice(hs, hs + this.head_dim));
                
                const attn_logits = [];
                for (let t = 0; t < k_h.length; t++) {
                    let sum = new Value(0);
                    for (let j = 0; j < this.head_dim; j++) {
                        sum = sum.add(q_h[j].mul(k_h[t][j]));
                    }
                    attn_logits.push(sum.mul(new Value(1 / Math.sqrt(this.head_dim))));
                }
                const attn_weights = this.softmax(attn_logits);
                
                const head_out = [];
                for (let j = 0; j < this.head_dim; j++) {
                    let sum = new Value(0);
                    for (let t = 0; t < v_h.length; t++) {
                        sum = sum.add(attn_weights[t].mul(v_h[t][j]));
                    }
                    head_out.push(sum);
                }
                x_attn.push(...head_out);
            }
            x = this.linear(x_attn, L.attn_wo);
            x = x.map((xi, i) => xi.add(x_residual[i]));

            x_residual = x;
            x = this.rmsnorm(x);
            x = this.linear(x, L.mlp_fc1);
            x = x.map(xi => xi.relu());
            x = this.linear(x, L.mlp_fc2);
            x = x.map((xi, i) => xi.add(x_residual[i]));
        }

        return this.linear(x, this.lm_head);
    }
}

// Worker Interface
let model = null;
let vocab = [];
let generationTimeout = null;

self.onmessage = async (e) => {
    const data = e.data;
    if (data.type === 'INIT_PRETRAINED') {
        const p = data.params;
        vocab = p.vocab;
        const c = p.config;
        model = new MicroGPT(c.vocab_size, c.n_embd, c.n_layer, c.n_head, c.block_size);
        
        for (let i = 0; i < model.params.length; i++) {
            model.params[i].data = p.weights[i];
        }
        
        self.postMessage({ type: 'LOG', msg: `Initialized Precomputed MicroGPT\nVocab Size: ${c.vocab_size}, Parameters: ${model.params.length}` });
        self.postMessage({ type: 'TRAINING_DONE' });
        return;
    }
    
    if (data.type === 'INIT') {
        const text = data.text.substring(0, 1000); // truncate for browser speed
        vocab = Array.from(new Set(text.split(''))).sort();
        const BOS = vocab.length;
        const vocab_size = vocab.length + 1;
        
        // Very small network so browser doesn't explode
        model = new MicroGPT(vocab_size, 8, 2, 1, 8); 
        
        self.postMessage({ type: 'LOG', msg: `Initialized MicroGPT\nVocab Size: ${vocab_size}, Parameters: ${model.params.length}` });
        
        // Prepare training
        let step = 0;
        const num_steps = 50; // Super small steps for browser
        const learning_rate = 0.01, beta1 = 0.85, beta2 = 0.99, eps = 1e-8;
        const m = new Array(model.params.length).fill(0);
        const v = new Array(model.params.length).fill(0);
        
        // Training Loop
        const trainStep = () => {
            if (step >= num_steps) {
                self.postMessage({ type: 'TRAINING_DONE' });
                return;
            }
            
            // Random chunk
            let tokens = [BOS];
            const start = Math.floor(Math.random() * Math.max(1, text.length - 8));
            for(let i=0; i<8; i++) tokens.push(vocab.indexOf(text[start+i] || text[0]));
            tokens.push(BOS);
            
            const n = Math.min(model.block_size, tokens.length - 1);
            const keys = Array.from({length: model.n_layer}, () => []);
            const values = Array.from({length: model.n_layer}, () => []);
            let losses = [];
            
            for (let pos_id = 0; pos_id < n; pos_id++) {
                const token_id = tokens[pos_id];
                const target_id = tokens[pos_id + 1];
                const logits = model.forward(token_id, pos_id, keys, values);
                const probs = model.softmax(logits);
                const prob_t = probs[target_id].add(1e-8);
                const loss_t = Object.assign(new Value(0), prob_t.log()).mul(-1);
                losses.push(loss_t);
            }
            
            let loss = new Value(0);
            for(let l of losses) loss = loss.add(l);
            loss = loss.mul(new Value(1 / n));
            
            // Backward
            loss.backward();
            
            // Adam update
            const lr_t = learning_rate * (1 - step / num_steps);
            for (let i = 0; i < model.params.length; i++) {
                const p = model.params[i];
                m[i] = beta1 * m[i] + (1 - beta1) * p.grad;
                v[i] = beta2 * v[i] + (1 - beta2) * Math.pow(p.grad, 2);
                const m_hat = m[i] / (1 - Math.pow(beta1, step + 1));
                const v_hat = v[i] / (1 - Math.pow(beta2, step + 1));
                p.data -= lr_t * m_hat / (Math.sqrt(v_hat) + eps);
                p.grad = 0; 
            }
            
            self.postMessage({ type: 'TRAINING_STEP', step: step+1, max: num_steps, loss: loss.data });
            step++;
            setTimeout(trainStep, 10);
        };
        trainStep();
    }
    
    if (data.type === 'INJECT') {
        if (!model) return;
        if (generationTimeout) clearTimeout(generationTimeout);
        const BOS = vocab.length;
        const temperature = data.temperature || 0.8;
        let outStr = data.text;
        
        self.postMessage({ type: 'LOG', msg: `\n[SYS]: Matrix trajectory interrupted. Forcing new context...` });
        self.postMessage({ type: 'INJECT_ACK', text: outStr });
        
        let keys = Array.from({length: model.n_layer}, () => []);
        let values = Array.from({length: model.n_layer}, () => []);
        let pos_id = 0;
        let token_id = BOS;
        
        // Feed in injected text to rebuild context window
        for (let i = 0; i < outStr.length; i++) {
            const char = outStr[i];
            const idx = vocab.indexOf(char);
            if (idx !== -1) {
                model.forward(token_id, pos_id, keys, values);
                token_id = idx;
                pos_id++;
                if (pos_id >= model.block_size) {
                    pos_id = 0;
                    token_id = BOS;
                    keys = Array.from({length: model.n_layer}, () => []);
                    values = Array.from({length: model.n_layer}, () => []);
                }
            }
        }
        
        const generateToken = (pos_id) => {
            if(pos_id >= model.block_size) {
                self.postMessage({ type: 'INFERENCE_DONE', result: outStr });
                return;
            }
            
            const logits = model.forward(token_id, pos_id, keys, values);
            const probs = model.softmax(logits.map(l => new Value(l.data / temperature)));
            
            let r = Math.random();
            let sum = 0;
            for (let i = 0; i < probs.length; i++) {
                sum += probs[i].data;
                if (r <= sum) {
                    token_id = i;
                    break;
                }
            }
            
            if (token_id === BOS) {
                 self.postMessage({ type: 'INFERENCE_DONE', result: outStr });
                 return;
            }
            
            const char = vocab[token_id];
            if(char) {
                outStr += char;
                const topProbs = probs.map((p, i) => ({ char: vocab[i], prob: p.data })).sort((a,b) => b.prob - a.prob).slice(0, 3);
                self.postMessage({ type: 'TOKEN', char: char, top_probs: topProbs, vocab_size: vocab.length, pos: pos_id });
            }
            
            let delay = Math.random() * 60 + 20; 
            if (char === ' ' || char === '\n') delay += 60; 
            generationTimeout = setTimeout(() => generateToken(pos_id + 1), delay);
        };
        
        generateToken(pos_id);
    }
    
    if (data.type === 'INFERENCE') {
        const BOS = vocab.length;
        const temperature = data.temperature || 0.8;
        self.postMessage({ type: 'LOG', msg: `\n--- Matrix Output stream ---` });
        
        let outStr = data.seed || "";
        let keys = Array.from({length: model.n_layer}, () => []);
        let values = Array.from({length: model.n_layer}, () => []);
        let pos_id = 0;
        let token_id = BOS;

        // Ingest Seed Prompt to build KV Cache context
        if (data.seed) {
            for (let i = 0; i < data.seed.length; i++) {
                const char = data.seed[i];
                const char_id = vocab.indexOf(char);
                if (char_id !== -1) {
                    model.forward(token_id, pos_id, keys, values);
                    self.postMessage({ type: 'TOKEN', char: char });
                    pos_id++;
                    token_id = char_id;
                }
            }
        }
        
        const generateToken = (pos_id) => {
            if(pos_id >= model.block_size) {
                self.postMessage({ type: 'INFERENCE_DONE', result: outStr });
                return;
            }
            
            const logits = model.forward(token_id, pos_id, keys, values);
            const probs = model.softmax(logits.map(l => new Value(l.data / temperature)));
            
            let r = Math.random();
            let sum = 0;
            for (let i = 0; i < probs.length; i++) {
                sum += probs[i].data;
                if (r <= sum) {
                    token_id = i;
                    break;
                }
            }
            
            if (token_id === BOS) {
                 self.postMessage({ type: 'INFERENCE_DONE', result: outStr });
                 return;
            }
            
            const char = vocab[token_id];
            if(char) {
                outStr += char;
                const topProbs = probs.map((p, i) => ({ char: vocab[i], prob: p.data })).sort((a,b) => b.prob - a.prob).slice(0, 3);
                self.postMessage({ type: 'TOKEN', char: char, top_probs: topProbs, vocab_size: vocab.length, pos: pos_id });
            }
            
            let delay = Math.random() * 60 + 20; // 20-80ms bursty typing
            if (char === ' ' || char === '\n') delay += 60; // pause on words
            generationTimeout = setTimeout(() => generateToken(pos_id + 1), delay); // humanized typing effect
        };
        
        generateToken(pos_id);
    }
};