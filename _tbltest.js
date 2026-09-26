/* 看表单测：列头排序 + p 值上色（阈值可换）
   跑法：  & "F:\New Folder\node.exe" "F:\try\用户研究\workbench\_tbltest.js"
   给 app.js 套一层假 DOM，直接调内部的 tableHtml / sortTable / setAlpha / csvTableHtml。 */

const fs = require('fs');
const path = require('path');

/* ---------------- 假 DOM ---------------- */
const IDX = new WeakMap();
let allNodes = [];

function mkClassList(el) {
  const set = new Set();
  return {
    add(c) { set.add(c); },
    remove(c) { set.delete(c); },
    contains(c) { return set.has(c); },
    _set: set,
  };
}

function mkEl(tag, attrs) {
  const el = {
    tagName: String(tag || 'div').toUpperCase(),
    nodeType: 1,                     // 元素节点 —— 委托里要靠它判断「点的是不是元素」
    _attrs: Object.assign({}, attrs || {}),
    _children: [],
    _parent: null,
    _text: '',
    _html: '',
    dataset: {},
    style: {},
    value: '',
    onclick: null,
    classList: null,
    querySelectorAll() { return []; },
    querySelector() { return null; },
    appendChild(ch) {
      // 真 DOM 里同一个节点挪窝会先从老父亲那儿摘掉，这里也照做
      if (ch._parent && ch._parent._children) {
        const i = ch._parent._children.indexOf(ch);
        if (i >= 0) ch._parent._children.splice(i, 1);
      }
      this._children.push(ch);
      ch._parent = this;
      return ch;
    },
    closest() { return null; },
    focus() {}, select() {},
  };
  el.classList = mkClassList(el);
  el.getAttribute = (k) => (k in el._attrs ? el._attrs[k] : null);
  el.setAttribute = (k, v) => { el._attrs[k] = String(v); };
  el.removeAttribute = (k) => { delete el._attrs[k]; };
  Object.defineProperty(el, 'textContent', {
    get() {
      const own = (el._text === undefined || el._text === null) ? '' : el._text;
      if (own !== '') return own;
      return el._children.map(c => c.textContent).join('');
    },
    set(v) { el._text = String(v); el._children = []; },
  });
  Object.defineProperty(el, 'innerHTML', {
    get() { return el._html; },
    set(v) {
      // 真 DOM 里 set innerHTML 会把原来的文字和子节点全掀掉
      el._html = String(v);
      el._text = '';
      el._children = [];
      parseHtml(el._html, el);
      hydrate(el);
    },
  });
  Object.defineProperty(el, 'outerHTML', {
    get() { return el._html; },
    set(v) {
      // 用新节点把自己顶掉（app 里换阈值时就是这么换那排按钮的）
      const p = el._parent;
      if (!p) return;
      const at = p._children.indexOf(el);
      const holder = mkEl('div', {});
      parseHtml(String(v), holder);
      const fresh = holder._children[0];
      if (!fresh) return;
      hydrate(holder);
      if (at >= 0) p._children[at] = fresh; else p._children.push(fresh);
      fresh._parent = p;
    },
  });
  Object.defineProperty(el, 'className', {
    get() { return el._attrs['class'] || ''; },
    set(v) { el._attrs['class'] = String(v); },
  });
  for (const k of ['sortcol', 'col', 'tblalpha', 'a', 'v', 't', 'tbl']) {
    Object.defineProperty(el.dataset, k, {
      get() { return el._attrs['data-' + k]; },
      set(v) { el._attrs['data-' + k] = String(v); },
      configurable: true,
    });
  }
  IDX.set(el, allNodes.length);
  allNodes.push(el);
  return el;
}

/* 极简 HTML 解析：够解析我们自己的模板就行（属性值里没有裸 '>'） */
const VOID = { br: 1, hr: 1, img: 1, input: 1, meta: 1, link: 1 };

function parseHtml(html, parent) {
  const DBG = globalThis.__DBG;
  if (DBG === 1 || (DBG === 2 && globalThis.__DBGLOG)) {
    console.log('  [parse] len=' + html.length + ' head=' + JSON.stringify(html.slice(0, 60)));
  }
  if (DBG === 2 && globalThis.__DBGLOG) globalThis.__DBGLOG('PARSE len=' + html.length + ' :: ' + html.slice(0, 200));
  const stack = [parent];
  const re = /<\/?([a-zA-Z][\w-]*)((?:\s+[\w:.-]+(?:="[^"]*")?)*)\s*(\/?)>/g;
  let last = 0, m;
  const pushText = (txt) => {
    if (!txt) return;
    const top = stack[stack.length - 1];
    top._text = (top._text || '') + decodeEnt(txt);
  };
  while ((m = re.exec(html)) !== null) {
    if (DBG === 1) console.log('    tag=' + JSON.stringify(m[0]) + ' attrsRaw=' + JSON.stringify(m[2]));
    if (DBG === 2 && globalThis.__DBGLOG) globalThis.__DBGLOG('  tag=' + JSON.stringify(m[0]).slice(0, 120));
    pushText(html.slice(last, m.index));
    last = re.lastIndex;
    const closing = m[0][1] === '/';
    const tag = m[1].toLowerCase();
    if (closing) {
      for (let i = stack.length - 1; i > 0; i--) {
        if (stack[i].tagName === tag.toUpperCase()) { stack.length = i; break; }
      }
      continue;
    }
    const el = mkEl(tag, {});
    const are = /([\w:.-]+)(?:="([^"]*)")?/g;
    let a;
    while ((a = are.exec(m[2] || '')) !== null) {
      el._attrs[a[1]] = a[2] === undefined ? '' : decodeEnt(a[2]);
    }
    const top = stack[stack.length - 1];
    top._children.push(el);
    el._parent = top;
    if (!VOID[tag] && !m[3]) stack.push(el);
  }
  pushText(html.slice(last));
  return parent;
}

function decodeEnt(s) {
  return String(s).replace(/&lt;/g, '<').replace(/&gt;/g, '>')
    .replace(/&quot;/g, '"').replace(/&#39;/g, "'").replace(/&amp;/g, '&');
}

/* 填充派生属性：rows / cells / closest / querySelector(All) */
function hydrate(root) {
  const tags = [];
  (function walk(n) {
    n._derived = null;
    if (n.tagName === 'TR') {
      const cs = n._children.filter(c => c.tagName === 'TD' || c.tagName === 'TH');
      n.cells = cs; cs.forEach((c, i) => { c.cellIndex = i; });
    }
    if (n.tagName === 'TABLE') {
      const all = [];
      (function w(m) { m._children.forEach(c => { all.push(c); w(c); }); })(n);
      n.rows = all.filter(x => x.tagName === 'TR');
    }
    if (n.tagName === 'TBODY' || n.tagName === 'THEAD') {
      // 只算自己的行，别把嵌套表（caption 里那张小箭头表）的行也算进来
      n.rows = n._children.filter(x => x.tagName === 'TR');
    }
    n.closest = (sel) => {
      let cur = n;
      while (cur) {
        if (matchSel(cur, sel)) return cur;
        cur = cur._parent;
      }
      return null;
    };
    n.querySelector = (sel) => {
      const found = n.querySelectorAll(sel);
      return found.length ? found[0] : null;
    };
    n.querySelectorAll = (sel) => {
      const out = [];
      if (matchSel(n, sel)) out.push(n);          // 自己也可能是命中的那个
      (function w(m) {
        m._children.forEach(c => { if (matchSel(c, sel)) out.push(c); w(c); });
      })(n);
      return out;
    };
    n._children.forEach(walk);
  })(root);
  return root;
}

function matchSel(el, sel) {
  const m = /^([a-zA-Z]*)((?:\[[^\]]*\])*)$/.exec(sel.trim());
  if (!m) return false;
  if (m[1] && el.tagName !== m[1].toUpperCase()) return false;
  const attrs = m[2].match(/\[[^\]]*\]/g) || [];
  return attrs.every(a => {
    const inner = a.slice(1, -1);
    const eq = inner.indexOf('=');
    if (eq < 0) return el._attrs[inner] !== undefined;
    const k = inner.slice(0, eq);
    const v = inner.slice(eq + 1).replace(/^["']|["']$/g, '');
    return el._attrs[k] === v;
  });
}

/* 只认我们真用到的那几种选择器：.cls / tag / tag[attr="v"] / .cls[attr="v"]
   （按位置扫，别用 /g 正则 —— 它会把 "thead" 里的 "th" 也当成标签名） */
function parseSel(sel) {
  const out = { cls: null, tag: null, attrs: [] };
  const s = String(sel).trim();
  let i = 0;
  const tm = /^[a-zA-Z]+/.exec(s);
  if (tm) { out.tag = tm[0].toUpperCase(); i = tm[0].length; }
  while (i < s.length) {
    if (s[i] === '.') {
      const m = /^\.([\w-]+)/.exec(s.slice(i));
      if (!m) break;
      out.cls = m[1]; i += m[0].length;
    } else if (s[i] === '[') {
      const end = s.indexOf(']', i);
      if (end < 0) break;
      const inner = s.slice(i + 1, end);
      const eq = inner.indexOf('=');
      if (eq < 0) out.attrs.push({ k: inner, v: undefined });
      else out.attrs.push({
        k: inner.slice(0, eq),
        v: inner.slice(eq + 1).replace(/^["']|["']$/g, ''),
      });
      i = end + 1;
    } else i++;
  }
  return out;
}

function matchSel(el, sel) {
  const s = parseSel(sel);
  if (s.tag && el.tagName !== s.tag) return false;
  if (s.cls && (el._attrs['class'] || '').split(/\s+/).indexOf(s.cls) < 0) return false;
  return s.attrs.every(a => a.v === undefined
    ? el._attrs[a.k] !== undefined
    : el._attrs[a.k] === a.v);
}

/* 用真的解析器造文档，再挂到假的 document 上 */
const stage = hydrate(parseHtml('<div id="stage"></div><div id="modalBox"></div>', mkEl('body')));
const modal = hydrate(parseHtml('<div id="modal"></div>', mkEl('body')));

globalThis.document = {
  querySelector(sel) {
    if (sel === '#stage') return stage;
    if (sel === '#modal') return modal;
    if (sel === '#modalBox') return modal;
    const hit = stage.querySelectorAll(sel);
    if (hit.length) return hit[0];
    const hit2 = modal.querySelectorAll(sel);
    if (hit2.length) return hit2[0];
    return null;
  },
  getElementById(id) { return this.querySelector('#' + id); },
  querySelectorAll() { return []; },
  addEventListener() {},
  createElement(t) { return mkEl(t); },
  execCommand() { return true; },
};
globalThis.window = globalThis;
globalThis.alert = (m) => { throw new Error('不该弹窗：' + m); };
globalThis.confirm = () => true;
globalThis.setInterval = () => 0;
globalThis.setTimeout = () => 0;
globalThis.fetch = async () => ({ json: async () => ({ ok: false }) });
globalThis.location = { href: 'http://127.0.0.1:8765/' };

/* ---------------- 加载 app.js ---------------- */
const src = fs.readFileSync(path.join(__dirname, 'web', 'app.js'), 'utf8');
const wrapped = src + `
;globalThis.__T = { S, tableHtml, sortTable, setAlpha, csvTableHtml, parseNumText, isPName,
  repaintTable, bindTableTools, splitCsvLine };`;
(0, eval)(wrapped);
const T = globalThis.__T;

/* ---------------- 断言 ---------------- */
let pass = 0, fail = 0;
function ok(cond, label, extra) {
  if (cond) { pass++; console.log('  ✅ ' + label); }
  else { fail++; console.log('  ❌ ' + label + (extra === undefined ? '' : '  —— ' + extra)); }
}
function eq(a, b, label) {
  const same = JSON.stringify(a) === JSON.stringify(b);
  ok(same, label, same ? '' : '实际是 ' + JSON.stringify(a));
}

/* 把一段表格 HTML 挂进 #stage，好让 sortTable / repaintTable 找得到。
   注意按 data-tbl 找 —— 工作台里还有别的 .tblwrap（SPSS 探测那张小表），它不是结果表。 */
function mount(html, id) {
  stage._children = [];
  parseHtml(html, stage);
  hydrate(stage);
  return stage.querySelector(`.tblwrap[data-tbl="${id}"]`);
}

// 假 DOM 不认 ">" 和后代组合器，所以用 tag 找一遍再自己筛父亲
const pText = (wrap) => wrap.querySelectorAll('td.p-sig')
  .filter(td => td._parent && td._parent._parent && td._parent._parent.tagName === 'TBODY').length;
const rowKeys = (wrap, ci) => wrap.querySelectorAll('tr').filter(tr => tr._parent.tagName === 'TBODY')
  .map(tr => tr.cells[ci].textContent);
// 假 DOM 不认 ">" 这种子代组合器，只按最贴近的那个选择器找（真界面上用的是标准 DOM，没这问题）
const thOf = (wrap, ci) => wrap.querySelectorAll('th[data-sortcol="' + ci + '"]')[0];
// 真界面上表头重画后会由 afterRender 再挂一次点击，这里跟着补上
const rebind = (wrap) => T.bindTableTools('#stage');

/* 模拟一次真点击：事件从被点的元素往上冒泡，谁身上挂了 onclick 就触发谁。
   —— 这是这次要防的 bug：按钮被重画成新节点后，新节点身上是没有 onclick 的。 */
function click(el) {
  const ev = { target: el, nodeType: 1 };
  let cur = el;
  while (cur) {
    if (typeof cur.onclick === 'function') { cur.onclick(ev); return true; }
    cur = cur._parent;
  }
  return false;
}

const REG = {
  id: '回归系数',
  columns: ['项', 'B', '标准误', 't', 'p', '标准化 β'],
  rows: [
    ['（常数项）', 2.31, 0.42, 5.5, 1e-7, ''],
    ['价格敏感度', -0.31, 0.08, -3.9, 0.0001, -0.31],
    ['安全顾虑', -0.22, 0.07, -3.1, 0.002, -0.22],
    ['包装颜值', 0.05, 0.09, 0.6, 0.55, 0.05],
    ['代言人好感', 0.08, 0.09, 0.9, 0.02, 0.08],   // 0.01 和 0.05 之间：换阈值时会变脸的那一行
    ['到店频次', 0.58, 0.21, 2.8, 0.006, 0.19],
  ],
};

(async () => {
  console.log('\n【1】p 列认得出来，也只认该认的');
  eq(T.isPName('p'), true, '「p」算 p 列');
  eq(T.isPName('P值'), true, '「P值」算 p 列');
  eq(T.isPName('sig'), true, '「sig」算 p 列');
  eq(T.isPName('标准化 β'), false, '「标准化 β」不算 p 列');
  eq(T.isPName('判断'), false, '「判断」不算 p 列');
  eq(T.isPName('B'), false, '「B」不算 p 列');
  eq(T.isPName(''), false, '空列名不算 p 列');
  eq(T.parseNumText('1.1e-45'), 1.1e-45, '科学计数法认得出');
  eq(T.parseNumText('-0.307'), -0.307, '负号认得出');
  eq(T.parseNumText('显著'), null, '「显著」不是数字');
  eq(T.parseNumText(''), null, '空串不是数字');

  console.log('\n【2】p 值上色：阈值默认 0.05');
  const h1 = T.tableHtml(REG);
  ok(h1.indexOf('class="tblwrap') >= 0, '表渲染出来了');
  ok(h1.indexOf('data-tbl="回归系数"') >= 0, '表带得了身份证（排序状态要挂在它上面）');
  ok(h1.indexOf('data-sortcol="4"') >= 0, 'p 列头可点');
  ok(h1.indexOf('class="sortable"') >= 0, '表头带 sortable');
  const sig1 = (h1.match(/p-sig/g) || []).length;
  const no1 = (h1.match(/class="num p-no"/g) || []).length;
  eq(sig1, 5, '5 个显著（常数项/价格/安全/到店频次/代言人好感 p=0.02）被标绿');
  eq(no1, 1, '只有包装颜值（p=0.55）被压灰');
  ok(h1.indexOf('p-weak') < 0, '没有 0.05–0.1 那一档的（这张表里没有）');
  ok(h1.indexOf('p&lt;0.05') >= 0, '阈值按钮渲染出来了');

  console.log('\n【3】「不显著」不只一种灰：0.05 ≤ p < 0.1 单独一档');
  const h2 = T.tableHtml({
    id: '勉强', columns: ['项', 'B', 'p'],
    rows: [['包装颜值', 0.05, 0.08], ['代言人好感', 0.08, 0.38]],
  });
  ok(h2.indexOf('p-weak') >= 0, 'p=0.08 归到「勉强」');
  ok(h2.indexOf('d-weak') >= 0, '图例里写了「勉强」这一档是什么意思');
  const h2b = T.tableHtml({
    id: '行首p', columns: ['指标', '值'],
    rows: [['B', -0.22], ['p', 0.002]],
  });
  ok(h2b.indexOf('class="prow"') >= 0, 'p 在行首（指标/值 这种表）时整行提亮');

  console.log('\n【4】数字列排序：点一下升、再点一下降');
  // 结果表旁边故意放一张「不是结果表」的 .tblwrap（SPSS 探测那张就长这样）：
  // 它不该被当成可排序的表，否则会先抢走点击，真表就点不动了。
  let wrap = mount(`<div class="tblwrap"><table><tr><th>写法</th></tr><tr><td>a</td></tr></table></div>`
    + T.tableHtml(REG), REG.id);
  T.bindTableTools('#stage');
  const aliveWraps = stage.querySelectorAll('.tblwrap').filter(w => typeof w.onclick === 'function');
  eq(aliveWraps.length, 1, '只有带 data-tbl 的结果表被挂上点击（那张杂表不挂）');
  ok(aliveWraps[0] === wrap, '挂上的就是结果表自己');
  ok(click(thOf(wrap, 4)), '点列头能触发排序（事件从表里冒到表上）');
  eq(T.S.tblSort[REG.id], { col: 4, dir: 1 }, '记下了「按 p 升序」');
  eq(rowKeys(wrap, 0), ['（常数项）', '价格敏感度', '安全顾虑', '到店频次', '代言人好感', '包装颜值'],
    'p 从小到大：1e-7 → 0.0001 → 0.002 → 0.006 → 0.02 → 0.55');
  ok((thOf(wrap, 4).querySelectorAll('.ar')[0] || {}).textContent === '▲', '升序箭头画出来了',
    '箭头=' + JSON.stringify((thOf(wrap, 4).querySelectorAll('.ar')[0] || {}).textContent));
  ok(click(thOf(wrap, 4)), '关键：表头被重画过一遍，再点照样管用（不用谁重新挂）');
  eq(T.S.tblSort[REG.id], { col: 4, dir: -1 }, '再点一下翻成降序');
  eq(rowKeys(wrap, 0), ['包装颜值', '代言人好感', '到店频次', '安全顾虑', '价格敏感度', '（常数项）'], '降序反过来了');
  ok(click(thOf(wrap, 1)), '换一列也行');
  eq(T.S.tblSort[REG.id], { col: 1, dir: 1 }, '换一列：按 B 升序');
  eq(rowKeys(wrap, 0), ['价格敏感度', '安全顾虑', '包装颜值', '代言人好感', '到店频次', '（常数项）'], '按 B 数值排（不是按字符串）');

  console.log('\n【5】阈值一换，颜色跟着换，但顺序和数字不动');
  const before = rowKeys(wrap, 0).slice();
  const btnOf = (w, a) => w.querySelectorAll('button[data-tblalpha]')
    .filter(b => b._attrs['data-a'] === String(a))[0];
  eq(wrap.querySelectorAll('button[data-tblalpha]').length, 3, '三个阈值按钮');
  ok(pText(wrap) === 5, '默认阈值 0.05：5 个显著（含常数项；代言人好感 p=0.02 也算）',
    'p-sig=' + pText(wrap));
  ok(click(btnOf(wrap, 0.01)), '点 p<0.01');
  eq(T.S.tblAlpha[REG.id], 0.01, '阈值记成 0.01');
  ok(pText(wrap) === 4, '按 p<0.01 有 4 个显著（1e-7 / 0.0001 / 0.002 / 0.006；p=0.02 那行掉出去）',
    'p-sig=' + pText(wrap));
  eq(rowKeys(wrap, 0), before, '顺序没被动过');
  eq(wrap.querySelectorAll('button[data-tblalpha]').length, 3, '换阈值后按钮还在');
  // ↓↓↓ 前辈踩到的那个 bug：改过一次阈值，第二次就点不动了
  ok(click(btnOf(wrap, 0.1)), '关键：改过一次阈值，第二次还能改');
  eq(T.S.tblAlpha[REG.id], 0.1, '第二次也生效（阈值记成 0.1）');
  ok(click(btnOf(wrap, 0.05)), '第三次照样能改');
  eq(T.S.tblAlpha[REG.id], 0.05, '第三次也生效（回到 0.05）');
  ok(pText(wrap) === 5, '改回来以后颜色也跟着回来了', 'p-sig=' + pText(wrap));
  ok(wrap.getAttribute('data-alpha') === '0.05', '表上留着当前阈值（重画时用得上）');
  eq(rowKeys(wrap, 0)[0], '价格敏感度', '重画后排序还在');

  console.log('\n【6】文字列也能排，空值垫底');
  const w2 = mount(T.tableHtml({
    id: '偏不显著', columns: ['变量', 'p', '判断'],
    rows: [['乙', 0.4, ''], ['甲', 0.02, '显著'], ['丙', 0.06, '看情况']],
  }), '偏不显著');
  T.bindTableTools('#stage');
  click(w2.querySelectorAll('th[data-sortcol="0"]')[0]);
  eq(rowKeys(w2, 0), ['丙', '甲', '乙'], '中文按 zh 排（丙 < 甲 < 乙）');

  console.log('\n【7】产物里的 CSV 也能直接看表');
  const csv = '\uFEFF项,B,p,判断\r\n"价格,敏感度",-0.31,0.0001,显著\r\n包装颜值,0.05,0.55,不显著\r\n';
  const t = T.csvTableHtml(csv, '产物:分析_结果汇总.csv');
  ok(t.indexOf('data-tbl="产物:分析_结果汇总.csv"') >= 0, 'CSV 转成了表，id 用文件路径');
  ok(t.indexOf('价格,敏感度') >= 0 && t.indexOf('class="num p-sig"') >= 0, '引号里的逗号没被切开，p 也上了色');
  eq((t.match(/class="num p-no"/g) || []).length, 1, '不显著的那个压灰');

  console.log('\n【8】不该出岔子的地方');
  eq(T.tableHtml({ id: 'x', columns: [], rows: [] }), '<div class="empty">空表</div>', '空表给个提示，不炸');
  const plain = T.tableHtml({ id: 'p2', columns: ['指标', '值'], rows: [['n', 216], ['R²', 0.399]] });
  ok(plain.indexOf('p-sig') < 0 && plain.indexOf('p-no') < 0, '没有 p 列的表不瞎上色');
  ok(plain.indexOf('alphapick') < 0, '没有 p 列就不显示阈值按钮');

  console.log('\n【9】拿真跑出来的一张回归表试：p 是字符串也得认');
  // 这份是 ⑥ 真跑「零食零售研究」回归时吐出来的原样，不是我编的数：
  // 列全是字符串，p 有 0、有 9.5e-07，还有分类变量拆出来的一堆哑变量行
  const fx = {
    columns: ['项', 'B', '标准误', 't', 'p', '标准化 β'],
    rows: [
      ['（常数项）', '4.710', '0.290', '16.258', '0', '—'],
      ['价格敏感度', '-0.250', '0.050', '-5.054', '9.5e-07', '-0.333'],
      ['安全与品质顾虑', '-0.097', '0.053', '-1.845', '0.0665', '-0.117'],
      ['到店频次_每周 1 次及以上', '0.400', '0.168', '2.378', '0.0183', '0.227'],
      ['到店频次_每月 1 次', '0.078', '0.172', '0.451', '0.6525', '0.042'],
      ['到店频次_每月 2～3 次', '0.493', '0.162', '3.037', '0.0027', '0.296'],
      ['家庭月收入_20000～35000 元', '0.141', '0.160', '0.880', '0.3801', '0.062'],
      ['家庭月收入_35000 元以上', '-0.061', '0.190', '-0.322', '0.7476', '-0.022'],
      ['家庭月收入_5000 元以下', '0.143', '0.165', '0.868', '0.3865', '0.062'],
      ['家庭月收入_5000～10000 元', '0.002', '0.126', '0.015', '0.9880', '0.001'],
    ],
  };
  const w9 = mount(T.tableHtml({ id: '真表', columns: fx.columns, rows: fx.rows }), '真表');
  T.bindTableTools('#stage');
  ok(fx.columns.indexOf('p') >= 0 && typeof fx.rows[0][4] === 'string', '样本里 p 是字符串（引擎就是这么给的）');
  ok(fx.rows.some(r => r[0].indexOf('_') > 0), '有哑变量行（分类变量拆出来的，变量一多就看不过来）');
  eq(pText(w9), 4, 'α=0.05 → 4 个显著（常数项 / 价格敏感度 / 到店频次每周1次以上 / 每月2～3次）');
  ok(click(thOf(w9, 4)), '点 p 列头');
  rebind(w9);
  eq(rowKeys(w9, 4), ['0', '9.5e-07', '0.0027', '0.0183', '0.0665', '0.3801', '0.3865', '0.6525', '0.7476', '0.9880'],
    '点 p 列：按数字大小排，不是按字符串排（字符串会把 0.9880 排到最前）');
  eq(rowKeys(w9, 0)[0], '（常数项）', 'p 最小的排在最上面');
  ok(click(w9.querySelectorAll('button[data-tblalpha]').filter(b => b._attrs['data-a'] === '0.01')[0]),
    '换 α=0.01');
  eq(pText(w9), 3, '换成 α=0.01 → 3 个显著（0.0183 那行掉出去）');
  eq(rowKeys(w9, 0)[0], '（常数项）', '换阈值以后排序没丢');
  ok(click(w9.querySelectorAll('button[data-tblalpha]').filter(b => b._attrs['data-a'] === '0.05')[0]),
    '真表上连改两次阈值也不卡');
  eq(T.S.tblAlpha['真表'], 0.05, '第二次也生效');

  console.log('\n' + (fail === 0 ? '全部通过' : '有失败项') + '：' + pass + ' 通过 / ' + fail + ' 失败\n');
  process.exit(fail === 0 ? 0 : 1);
})();
