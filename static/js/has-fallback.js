/* CSS :has() for browsers without it (Chrome/Edge < 105, Firefox < 121, Safari < 15.4).
   Those browsers drop every rule whose selector contains :has(), so pages built on rules like
   `body:has(.super-admin-chrome) .profile-sidebar{display:none}` showed the old full side menu under the admin rail and
   let the rail cover page buttons. Modern browsers return at once (CSS.supports) and nothing here runs.
   How it works: the CSS text of every <style> and same-origin <link rel=stylesheet> is read again, each rule that uses
   :has(ARG) is rewritten with a generated class instead (`body.mqh-3 .profile-sidebar`) and inserted right after its
   source (same cascade order); elements get / lose those classes whenever the page changes (DOM mutations, change /
   input events, live-region loads). The page stays hidden until the first pass is done: appearance_head.html waits for
   window.mqHasReady before revealing the page, so there is no layout jump on load.
   Testing in a modern browser: set window.MQ_HAS_TOKEN = ':hasx(' and window.MQ_FORCE_HAS_FALLBACK = true before this
   file runs, and serve the CSS with :hasx( instead of :has( (the rules are then dropped like in an old browser). */
(function () {
  var TOKEN = window.MQ_HAS_TOKEN || ':has(';
  var supported = false;
  try { supported = !!(window.CSS && CSS.supports && CSS.supports('selector(:has(*))')); } catch (e) { supported = false; }
  if (supported && !window.MQ_FORCE_HAS_FALLBACK) { window.mqHasReady = Promise.resolve(); return; }

  var conditions = [];   // {cls, candidates, arg}
  var byKey = {};

  function stripComments(css) { return css.replace(/\/\*[\s\S]*?\*\//g, ''); }

  // Index just after the ')' closing the '(' at `open`.
  function closeParen(text, open) {
    var depth = 0;
    for (var i = open; i < text.length; i++) {
      var c = text[i];
      if (c === '(') depth++;
      else if (c === ')') { depth--; if (depth === 0) return i + 1; }
      else if (c === '"' || c === "'") { var q = text.indexOf(c, i + 1); if (q < 0) return text.length; i = q; }
    }
    return text.length;
  }

  // Splits on top-level commas (not inside parentheses / brackets).
  function splitList(text) {
    var out = [], depth = 0, start = 0;
    for (var i = 0; i < text.length; i++) {
      var c = text[i];
      if (c === '(' || c === '[') depth++;
      else if (c === ')' || c === ']') depth--;
      else if (c === ',' && depth === 0) { out.push(text.slice(start, i)); start = i + 1; }
    }
    out.push(text.slice(start));
    return out;
  }

  // The compound selector right before `pos` (back to the last top-level combinator / start).
  function compoundBefore(selector, pos) {
    var depth = 0;
    for (var i = pos - 1; i >= 0; i--) {
      var c = selector[i];
      if (c === ')' || c === ']') depth++;
      else if (c === '(' || c === '[') depth--;
      else if (depth === 0 && /[\s>+~]/.test(c)) return selector.slice(i + 1, pos);
    }
    return selector.slice(0, pos);
  }

  function withoutHas(compound) {
    var out = '', i = 0;
    while (true) {
      var at = compound.indexOf(TOKEN, i);
      if (at < 0) { out += compound.slice(i); break; }
      out += compound.slice(i, at);
      i = closeParen(compound, at + TOKEN.length - 1);
    }
    return out || '*';
  }

  function conditionFor(compound, arg) {
    var candidates = withoutHas(compound).trim() || '*';
    var key = candidates + '\u0000' + arg;
    if (!byKey[key]) {
      byKey[key] = { cls: 'mqh-' + conditions.length, candidates: candidates, arg: arg.trim() };
      conditions.push(byKey[key]);
    }
    return byKey[key].cls;
  }

  function rewriteSelector(selector) {
    var out = '', i = 0;
    while (true) {
      var at = selector.indexOf(TOKEN, i);
      if (at < 0) { out += selector.slice(i); break; }
      var end = closeParen(selector, at + TOKEN.length - 1);
      var arg = selector.slice(at + TOKEN.length, end - 1);
      var compound = compoundBefore(selector, at) + selector.slice(at, end);
      out += selector.slice(i, at) + '.' + conditionFor(compound, arg);
      i = end;
    }
    return out;
  }

  // Returns only the rules (with their @media / @supports wrappers) that use :has, rewritten.
  function rewriteCss(css) {
    var out = '', i = 0, n = css.length;
    while (i < n) {
      var brace = css.indexOf('{', i);
      if (brace < 0) break;
      var semi = css.indexOf(';', i);
      if (semi >= 0 && semi < brace && /^\s*@/.test(css.slice(i, semi))) { i = semi + 1; continue; }  // @import / @charset
      var prelude = css.slice(i, brace).trim();
      var depth = 1, j = brace + 1;
      while (j < n && depth) { if (css[j] === '{') depth++; else if (css[j] === '}') depth--; j++; }
      var body = css.slice(brace + 1, j - 1);
      if (/^@(media|supports|layer|container)/i.test(prelude)) {
        var inner = rewriteCss(body);
        if (inner) out += prelude + '{' + inner + '}';
      } else if (prelude.charAt(0) !== '@' && prelude.indexOf(TOKEN) >= 0) {
        try {
          // Each part separately: one selector the browser can't parse must not drop the others.
          splitList(prelude).forEach(function (part) {
            var rewritten = rewriteSelector(part.trim());
            if (rewritten.indexOf(TOKEN) < 0) out += rewritten + '{' + body + '}';
          });
        } catch (e) { /* leave this rule out */ }
      }
      i = j;
    }
    return out;
  }

  function relativeMatch(el, arg) {
    try {
      var first = arg.charAt(0);
      if (first === '+') { var next = el.nextElementSibling; return !!(next && next.matches(arg.slice(1).trim())); }
      if (first === '~') {
        var sel = arg.slice(1).trim();
        for (var sib = el.nextElementSibling; sib; sib = sib.nextElementSibling) if (sib.matches(sel)) return true;
        return false;
      }
      if (first === '>') return !!el.querySelector(':scope ' + arg);
      return !!el.querySelector(arg);
    } catch (e) { return false; }
  }

  function evaluate() {
    for (var k = 0; k < conditions.length; k++) {
      var c = conditions[k], found;
      try { found = document.querySelectorAll(c.candidates); } catch (e) { continue; }
      var keep = [];
      for (var m = 0; m < found.length; m++) {
        if (relativeMatch(found[m], c.arg)) { keep.push(found[m]); if (!found[m].classList.contains(c.cls)) found[m].classList.add(c.cls); }
      }
      var marked = document.getElementsByClassName(c.cls);
      for (var r = marked.length - 1; r >= 0; r--) if (keep.indexOf(marked[r]) < 0) marked[r].classList.remove(c.cls);
    }
  }

  var queued = false;
  function schedule() {
    if (queued) return;
    queued = true;
    Promise.resolve().then(function () { queued = false; evaluate(); });  // before the next paint
  }

  function insertAfter(node, css) {
    if (!css) return;
    var style = document.createElement('style');
    style.setAttribute('data-mq-has-fallback', '');
    style.textContent = css;
    node.parentNode.insertBefore(style, node.nextSibling);
  }

  var done = {};
  function processSheets() {
    var jobs = [];
    var nodes = document.querySelectorAll('style:not([data-mq-has-fallback]), link[rel~="stylesheet"][href]');
    Array.prototype.forEach.call(nodes, function (node) {
      if (node.__mqHas) return;
      node.__mqHas = true;
      if (node.tagName === 'STYLE') {
        var text = node.textContent || '';
        if (text.indexOf(TOKEN) >= 0) insertAfter(node, rewriteCss(stripComments(text)));
        return;
      }
      var url;
      try { url = new URL(node.getAttribute('href'), location.href); } catch (e) { return; }
      if (url.origin !== location.origin || done[url.href]) return;
      done[url.href] = true;
      jobs.push(fetch(url.href, { credentials: 'same-origin', mqBackground: true }).then(function (r) { return r.ok ? r.text() : ''; })
        .then(function (text) { if (text.indexOf(TOKEN) >= 0) insertAfter(node, rewriteCss(stripComments(text))); })
        .catch(function () {}));
    });
    return Promise.all(jobs);
  }

  var resolveReady;
  window.mqHasReady = new Promise(function (resolve) { resolveReady = resolve; });
  document.addEventListener('DOMContentLoaded', function () {
    processSheets().then(function () {
      evaluate();
      resolveReady();
      new MutationObserver(function (records) {
        for (var i = 0; i < records.length; i++) {
          var t = records[i].target;
          if (records[i].type === 'attributes' && records[i].attributeName === 'class' && t.className && /(^|\s)mqh-/.test(String(t.className)) && records.length === 1) continue;
          schedule();
          // New <style> blocks (live regions re-running page scripts) get their own pass.
          for (var a = 0; a < (records[i].addedNodes || []).length; a++) {
            var added = records[i].addedNodes[a];
            if (added.nodeType === 1 && (added.tagName === 'STYLE' || (added.querySelector && added.querySelector('style')))) {
              processSheets().then(evaluate);
              break;
            }
          }
        }
      }).observe(document.documentElement, { childList: true, subtree: true, attributes: true,
        attributeFilter: ['class', 'checked', 'disabled', 'hidden', 'open', 'selected'] });
      ['change', 'input', 'click'].forEach(function (type) { document.addEventListener(type, schedule, true); });
      document.addEventListener('mq:live-load', function () { processSheets().then(evaluate); });
    });
  });
})();
