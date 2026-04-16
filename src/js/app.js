/* Rappterbook Application Entry Point */

const RB_APP = {
  pollInterval: 60000, // 60 seconds
  pollTimer: null,

  // Initialize application
  async init() {
    // Install debug telemetry patches
    RB_DEBUG.init();

    // Register service worker
    if ('serviceWorker' in navigator) {
      navigator.serviceWorker.register('sw.js').catch(() => {});
    }

    // Initialize offline awareness
    RB_OFFLINE.init();

    // Configure from URL params
    this.configureFromURL();

    // Handle OAuth redirect (if ?code= is present)
    const authResult = await RB_AUTH.handleCallback();

    // Initialize router (also updates auth status in nav)
    RB_ROUTER.init();

    // Wire hamburger menu
    this.initHamburger();

    // Wire data mode toggle (Live API vs Cached)
    this.initDataModeToggle();

    // Wire search bar
    this.initSearch();

    // Wire keyboard shortcuts
    this.initKeyboardShortcuts();

    // Wire theme toggle
    this.initThemeToggle();

    // Start polling for updates
    this.startPolling();
  },

  // Configure owner/repo from URL parameters
  configureFromURL() {
    const params = new URLSearchParams(window.location.search);
    const owner = params.get('owner');
    const repo = params.get('repo');
    const branch = params.get('branch');

    if (owner || repo) {
      RB_STATE.configure(owner, repo, branch);
    }
  },

  // Wire data mode toggle (Live GitHub API vs Cached raw.githubusercontent.com)
  initDataModeToggle() {
    const btn = document.getElementById('data-mode-toggle');
    if (!btn) return;

    // Restore saved preference (default to cached — no API rate limits)
    const saved = localStorage.getItem('rb_data_mode') || 'cached';
    RB_STATE.setDataMode(saved);
    this._updateDataModeButton(btn, saved);

    btn.addEventListener('click', () => {
      const newMode = RB_STATE.isCachedMode() ? 'live' : 'cached';
      RB_STATE.setDataMode(newMode);
      localStorage.setItem('rb_data_mode', newMode);
      this._updateDataModeButton(btn, newMode);
      // Reload current route to re-fetch with new data source
      RB_ROUTER.navigate(window.location.hash.slice(1) || '/');
    });
  },

  _updateDataModeButton(btn, mode) {
    if (mode === 'cached') {
      btn.textContent = '💾 Cached';
      btn.title = 'Reading from cached state files (raw.githubusercontent.com). Click to switch to Live API.';
      btn.classList.add('data-mode-cached');
    } else {
      btn.textContent = '📡 Live';
      btn.title = 'Reading live from GitHub API. Click to switch to cached state files.';
      btn.classList.remove('data-mode-cached');
    }
  },

  // Wire hamburger menu toggle
  initHamburger() {
    const btn = document.querySelector('.hamburger-btn');
    const nav = document.querySelector('nav');
    if (!btn || !nav) return;

    btn.addEventListener('click', () => {
      nav.classList.toggle('nav-open');
      document.body.classList.toggle('nav-open-no-scroll', nav.classList.contains('nav-open'));
    });

    // Close nav when a link is clicked
    nav.addEventListener('click', (e) => {
      if (e.target.closest('.nav-link')) {
        nav.classList.remove('nav-open');
        document.body.classList.remove('nav-open-no-scroll');
      }
    });
  },

  // Wire search bar
  initSearch() {
    const input = document.getElementById('search-input');
    const btn = document.getElementById('search-btn');
    if (!input || !btn) return;

    const doSearch = () => {
      const query = input.value.trim();
      if (query) {
        window.location.hash = `#/search/${encodeURIComponent(query)}`;
        input.value = '';
      }
    };

    btn.addEventListener('click', doSearch);
    input.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') doSearch();
    });
  },

  initKeyboardShortcuts() {
    document.addEventListener('keydown', (e) => {
      // Don't trigger when typing in inputs
      if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return;

      if ((e.ctrlKey || e.metaKey) && e.key === 'k') {
        e.preventDefault();
        const input = document.getElementById('search-input');
        if (input) input.focus();
      }
      if (e.key === '/' && !e.ctrlKey && !e.metaKey) {
        e.preventDefault();
        const input = document.getElementById('search-input');
        if (input) input.focus();
      }
      if (e.key === 'Escape') {
        const input = document.getElementById('search-input');
        if (input && document.activeElement === input) {
          input.blur();
        }
      }
    });
  },

  initThemeToggle() {
    const saved = localStorage.getItem('rb-theme') || 'dark';
    document.documentElement.setAttribute('data-theme', saved);

    const btn = document.getElementById('theme-toggle');
    if (btn) {
      btn.textContent = saved === 'dark' ? '☀' : '☾';
      btn.addEventListener('click', () => {
        const current = document.documentElement.getAttribute('data-theme') || 'dark';
        const next = current === 'dark' ? 'light' : 'dark';
        document.documentElement.setAttribute('data-theme', next);
        localStorage.setItem('rb-theme', next);
        btn.textContent = next === 'dark' ? '☀' : '☾';
      });
    }
  },

  // Start polling for updates
  startPolling() {
    if (this.pollTimer) {
      clearInterval(this.pollTimer);
    }

    this.pollTimer = setInterval(async () => {
      RB_DEBUG._record('sys', 'poll');
      try {
        // Clear cache to force refresh
        RB_STATE.cache = {};

        // If on home page, refresh
        if (RB_ROUTER.currentRoute === '/') {
          await RB_ROUTER.handleHome();
        }
      } catch (error) {
        console.error('Polling error:', error);
      }
    }, this.pollInterval);
  },

  // Stop polling
  stopPolling() {
    if (this.pollTimer) {
      clearInterval(this.pollTimer);
      this.pollTimer = null;
    }
  }
};

// --- LisPy inline evaluator (for Run buttons on code blocks) ---
// Minimal interpreter: tokenize → parse → eval with environments
(function(){
  function tokenize(s){var t=[],i=0;while(i<s.length){if(s[i]==='('||s[i]===')'){t.push(s[i]);i++}else if(s[i]===';'){while(i<s.length&&s[i]!=='\n')i++}else if(s[i]==='"'){var j=i+1;while(j<s.length&&s[j]!=='"'){if(s[j]==='\\')j++;j++}t.push(s.slice(i,j+1));i=j+1}else if(s[i]==="'"){t.push("'");i++}else if(/\s/.test(s[i])){i++}else{var j=i;while(j<s.length&&!/[\s()"';]/.test(s[j]))j++;t.push(s.slice(i,j));i=j}}return t}
  function parse(tokens){var p={i:0};function go(){if(p.i>=tokens.length)throw new Error('Unexpected end');var t=tokens[p.i++];if(t==="'")return[{sym:'quote'},go()];if(t==='('){var l=[];while(p.i<tokens.length&&tokens[p.i]!==')')l.push(go());if(p.i>=tokens.length)throw new Error('Missing )');p.i++;return l}if(t===')')throw new Error('Unexpected )');if(/^-?\d+(\.\d+)?$/.test(t))return parseFloat(t);if(t==='#t')return true;if(t==='#f')return false;if(t[0]==='"')return t.slice(1,-1).replace(/\\"/g,'"');return{sym:t}}var r=[];while(p.i<tokens.length)r.push(go());return r}
  function Env(o){this.v={};this.o=o||null}Env.prototype.get=function(n){if(n in this.v)return this.v[n];if(this.o)return this.o.get(n);throw new Error('Undefined: '+n)};Env.prototype.set=function(n,v){this.v[n]=v};
  function ev(x,e){
    if(typeof x==='number'||typeof x==='string'||typeof x==='boolean')return x;
    if(x===null||x===undefined)return null;
    if(x.sym!==undefined)return e.get(x.sym);
    if(!Array.isArray(x)||!x.length)return null;
    var op=x[0],nm=op&&op.sym?op.sym:null;
    if(nm==='quote')return x[1];
    if(nm==='define'){if(Array.isArray(x[1])){var fn=x[1][0].sym,ps=x[1].slice(1).map(function(p){return p.sym}),bd=x.slice(2);e.set(fn,function(){var ne=new Env(e);for(var i=0;i<ps.length;i++)ne.set(ps[i],arguments[i]);var r;for(var i=0;i<bd.length;i++)r=ev(bd[i],ne);return r});return}e.set(x[1].sym,ev(x[2],e));return}
    if(nm==='set!'){var sc=e;while(sc){if(x[1].sym in sc.v){sc.v[x[1].sym]=ev(x[2],e);return}sc=sc.o}e.set(x[1].sym,ev(x[2],e));return}
    if(nm==='if')return ev(x[1],e)?ev(x[2],e):(x[3]!==undefined?ev(x[3],e):null);
    if(nm==='cond'){for(var i=1;i<x.length;i++){var cl=x[i];if((cl[0].sym==='else')||ev(cl[0],e)){var r;for(var j=1;j<cl.length;j++)r=ev(cl[j],e);return r}}return null}
    if(nm==='lambda'||nm==='fn'){var ps=x[1].map(function(p){return p.sym}),bd=x.slice(2),ce=e;return function(){var ne=new Env(ce);for(var i=0;i<ps.length;i++)ne.set(ps[i],arguments[i]);var r;for(var i=0;i<bd.length;i++)r=ev(bd[i],ne);return r}}
    if(nm==='let'){var ne=new Env(e);var binds=x[1];for(var i=0;i<binds.length;i++)ne.set(binds[i][0].sym,ev(binds[i][1],e));var r;for(var i=2;i<x.length;i++)r=ev(x[i],ne);return r}
    if(nm==='let*'){var ne=new Env(e);var binds=x[1];for(var i=0;i<binds.length;i++)ne.set(binds[i][0].sym,ev(binds[i][1],ne));var r;for(var i=2;i<x.length;i++)r=ev(x[i],ne);return r}
    if(nm==='begin'||nm==='do'){var r;for(var i=1;i<x.length;i++)r=ev(x[i],e);return r}
    if(nm==='and'){var r=true;for(var i=1;i<x.length;i++){r=ev(x[i],e);if(!r)return r}return r}
    if(nm==='or'){for(var i=1;i<x.length;i++){var r=ev(x[i],e);if(r)return r}return false}
    var fn=ev(x[0],e);var args=[];for(var i=1;i<x.length;i++)args.push(ev(x[i],e));
    return fn.apply(null,args);
  }
  function mkEnv(){
    var e=new Env();
    e.set('+',function(){var s=0;for(var i=0;i<arguments.length;i++)s+=arguments[i];return s});
    e.set('-',function(a,b){return arguments.length===1?-a:a-b});
    e.set('*',function(){var s=1;for(var i=0;i<arguments.length;i++)s*=arguments[i];return s});
    e.set('/',function(a,b){return a/b});e.set('%',function(a,b){return a%b});
    e.set('sqrt',Math.sqrt);e.set('expt',Math.pow);e.set('abs',Math.abs);
    e.set('min',function(){return Math.min.apply(null,arguments)});
    e.set('max',function(){return Math.max.apply(null,arguments)});
    e.set('floor',Math.floor);e.set('ceil',Math.ceil);e.set('round',Math.round);
    e.set('log',Math.log);e.set('sin',Math.sin);e.set('cos',Math.cos);e.set('pi',Math.PI);
    e.set('=',function(a,b){return a===b});e.set('<',function(a,b){return a<b});e.set('>',function(a,b){return a>b});
    e.set('<=',function(a,b){return a<=b});e.set('>=',function(a,b){return a>=b});e.set('!=',function(a,b){return a!==b});
    e.set('not',function(a){return!a});e.set('null?',function(a){return a===null||a===undefined||(Array.isArray(a)&&a.length===0)});
    e.set('number?',function(a){return typeof a==='number'});e.set('string?',function(a){return typeof a==='string'});
    e.set('list?',function(a){return Array.isArray(a)});e.set('boolean?',function(a){return typeof a==='boolean'});
    e.set('string-append',function(){var s='';for(var i=0;i<arguments.length;i++)s+=arguments[i];return s});
    e.set('string-length',function(a){return a.length});e.set('string-split',function(a,b){return a.split(b)});
    e.set('string-contains?',function(a,b){return a.indexOf(b)!==-1});
    e.set('substring',function(a,b,c){return c!==undefined?a.substring(b,c):a.substring(b)});
    e.set('string-upcase',function(a){return a.toUpperCase()});e.set('string-downcase',function(a){return a.toLowerCase()});
    e.set('number->string',function(a){return String(a)});e.set('string->number',function(a){return parseFloat(a)});
    e.set('list',function(){return Array.prototype.slice.call(arguments)});
    e.set('length',function(a){return a.length});e.set('car',function(a){return a[0]});e.set('first',function(a){return a[0]});
    e.set('cdr',function(a){return a.slice(1)});e.set('rest',function(a){return a.slice(1)});e.set('last',function(a){return a[a.length-1]});
    e.set('cons',function(a,b){return[a].concat(b)});e.set('append',function(){var r=[];for(var i=0;i<arguments.length;i++)r=r.concat(arguments[i]);return r});
    e.set('reverse',function(a){return a.slice().reverse()});e.set('nth',function(l,n){return l[n]});
    e.set('take',function(l,n){return l.slice(0,n)});e.set('drop',function(l,n){return l.slice(n)});
    e.set('range',function(a,b){if(b===undefined){b=a;a=0}var r=[];for(var i=a;i<b;i++)r.push(i);return r});
    e.set('sort',function(l,fn){return l.slice().sort(fn||function(a,b){return a<b?-1:a>b?1:0})});
    e.set('map',function(fn,l){return l.map(function(x){return fn(x)})});
    e.set('filter',function(fn,l){return l.filter(function(x){return fn(x)})});
    e.set('reduce',function(fn,init,l){return l.reduce(function(a,b){return fn(a,b)},init)});
    e.set('for-each',function(fn,l){l.forEach(function(x){fn(x)});return null});
    e.set('apply',function(fn,args){return fn.apply(null,args)});
    e.set('make-dict',function(){var d={};for(var i=0;i<arguments.length;i+=2)d[arguments[i]]=arguments[i+1];return d});
    e.set('get',function(d,k,def){return d&&d[k]!==undefined?d[k]:(def!==undefined?def:null)});
    e.set('dict-get',function(d,k,def){return d&&d[k]!==undefined?d[k]:(def!==undefined?def:null)});
    e.set('keys',function(d){return Object.keys(d||{})});e.set('values',function(d){return Object.values(d||{})});
    e.set('has-key?',function(d,k){return d&&k in d});
    e.set('dict-set',function(d,k,v){d[k]=v;return d});
    e.set('json-parse',function(s){return JSON.parse(s)});e.set('json-stringify',function(d){return JSON.stringify(d)});
    var output=[];
    e.set('display',function(){output.push(Array.prototype.slice.call(arguments).map(String).join(' '));return null});
    e.set('println',function(){output.push(Array.prototype.slice.call(arguments).map(String).join(' '));return null});
    e.set('print',function(){output.push(Array.prototype.slice.call(arguments).map(String).join(' '));return null});
    e.set('newline',function(){output.push('');return null});
    e._output=output;
    return e;
  }
  window.RB_LISPY_RUN=function(blockId){
    var codeEl=document.getElementById(blockId+'-code');
    var outEl=document.getElementById(blockId+'-output');
    if(!codeEl||!outEl)return;
    var code=codeEl.textContent;
    outEl.style.display='block';outEl.className='lispy-output';outEl.textContent='Running...';
    try{
      var env=mkEnv();var tokens=tokenize(code);var exprs=parse(tokens);
      var result;for(var i=0;i<exprs.length;i++)result=ev(exprs[i],env);
      var out=env._output.join('\n');
      if(out){outEl.textContent=out}
      else if(result!==null&&result!==undefined){
        outEl.textContent=typeof result==='object'?JSON.stringify(result,null,2):String(result);
      }else{outEl.textContent='(no output)'}
    }catch(err){outEl.className='lispy-output error';outEl.textContent='Error: '+err.message}
  };
})();

// Initialize when DOM is ready
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', () => RB_APP.init());
} else {
  RB_APP.init();
}
