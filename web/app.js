/* 用户研究工作台 · 前端逻辑
   原生 JS，无框架、无 CDN、无构建。改一行刷新即生效。 */

'use strict';

const S = {
  state: null,
  blockId: null,
  form: {},          // { blockId: {key: value} }
  jobId: null,
  job: null,
  logs: [],
  logCount: 0,
  tab: 'result',
  result: null,
  running: false,
  cols: {},          // { "项目根|数据文件rel": [列定义] } —— 变量下拉用
  steps: [],         // 过程可见：我每一步做了什么
  stepCount: 0,
  pending: null,     // 正在等研究员拍板的检查点
  answers: [],       // 研究员做过的决定
  // 每个组块各留一份自己的运行现场：换组块时把当前这份存起来，
  // 回来时原样还回去 —— 免得「流程 A 的结果栏里躺着流程 B 的输出」。
  perBlock: {},      // { blockId: { logs, result, steps, pending, ... } }
  // 待确认项侧栏：模型把不确定的地方写成「（待确认：…）」，
  // 一条条在这里过，不用回正文里大海捞针
  confirm: { open: false, items: [], log: [], ignored: [] },
  // 变量表：记「这张表已经从简报读过一次了」，免得每次重画都去请求一遍
  vtPulled: {},
  vtCache: {},       // { 项目|组块|字段: 上次从简报读回来的内容 } —— 用来分辨「表空着」是没读还是被他删空了
  formLoaded: {},    // { 组块id: true } —— 项目里那份表单内容拉过了，别反复拉
  layers: null,      // 产物分两层：{key: [标过的], other: [过程产物]}
  art: null,         // 正在看的那个产物：{rel, raw, editing, isTable, canEdit}
  showOther: false,  // 过程产物默认折叠
  lastVerRel: '',    // 打标签之后要重新打开哪份文件的版本面板
  // 看表用的：每个表各自记住「按哪列排的」和「显著性阈值定在多少」。
  // 变量一多，靠眼睛一行行找 p 太累 —— 点列头排序、p 上色，比改数字有用。
  tblSort: {},       // { 表id: {col, dir} }
  tblAlpha: {},      // { 表id: 0.05 }
};

/* 当前这份「运行现场」里，属于某个组块的全部字段 */
const BLOCK_FIELDS = ['logs', 'logCount', 'result', 'steps', 'stepCount',
  'pending', 'answers', 'jobId', 'job', 'tab'];

function resetBlockState(id) {
  S.blockId = id;
  S.logs = []; S.logCount = 0;
  S.steps = []; S.stepCount = 0;
  S.pending = null; S.answers = [];
  S.jobId = null; S.job = null;
  S.result = null; S.tab = 'result';
}

function saveBlockState() {
  if (!S.blockId) return;
  const snap = {};
  BLOCK_FIELDS.forEach(k => { snap[k] = S[k]; });
  S.perBlock[S.blockId] = snap;
}

function loadBlockState(id) {
  const snap = S.perBlock[id];
  if (!snap) { resetBlockState(id); return; }
  S.blockId = id;
  BLOCK_FIELDS.forEach(k => { S[k] = snap[k]; });
  // 不让「回来看一眼」变成「看着日志发呆」：有结果就落在结果页
  if (!S.result) S.tab = 'result';
}

/* 换项目：上一个项目的运行现场、表单、列名缓存全部作废 */
function clearProjectState() {
  S.perBlock = {};
  S.form = {};
  S.cols = {};
  S.tblSort = {};
  S.tblAlpha = {};
  S.vtPulled = {};
  S.vtCache = {};
  S.formLoaded = {};        // 换了项目 → 项目里那份表单内容要重新拉
  S.formRequested = {};     // ⚠ 这个也要清：它是"这次会话里为这个组块读过表单没"，
                            //   不清的话换到下一个项目就永远不认为自己是"第一次"了
  S.layers = null;          // 换项目 → 产物分层要重新拉
  S.showOther = false;
  S.confirm = { open: false, items: [], log: [], ignored: [] };
  const dr = $('#drawer');
  if (dr) dr.classList.remove('on');
  S.running = false;
  S.jobId = null; S.job = null;
  resetBlockState(null);
}

/* ---------------- 小工具 ---------------- */

const $ = (sel) => document.querySelector(sel);

function esc(s) {  return String(s === undefined || s === null ? '' : s)
    .replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

function inline(s) {
  s = esc(s);
  s = s.replace(/`([^`]+)`/g, '<code>$1</code>');
  s = s.replace(/\*\*([^*]+)\*\*/g, '<b>$1</b>');
  s = s.replace(/「([^」]*)」/g, '「$1」');
  return s;
}

function fmtSize(n) {
  if (n < 1024) return n + ' B';
  if (n < 1024 * 1024) return (n / 1024).toFixed(1) + ' KB';
  return (n / 1024 / 1024).toFixed(1) + ' MB';
}

async function api(path, opts) {
  try {
    const r = await fetch(path, opts);
    return await r.json();
  } catch (e) {
    return { ok: false, error: '连不上本地服务：' + e.message };
  }
}

function post(path, data) {
  return api(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data || {}),
  });
}

function setStatus(text) { $('#statusText').textContent = text; }

/* ---------------- 极简 Markdown 渲染 ---------------- */

function splitRow(l) {
  return l.trim().replace(/^\|/, '').replace(/\|$/, '').split('|').map(s => s.trim());
}

function mdToHtml(md) {
  const lines = String(md || '').replace(/\r/g, '').split('\n');
  const out = [];
  let i = 0;
  while (i < lines.length) {
    const ln = lines[i];

    // 表格
    if (/^\s*\|/.test(ln) && i + 1 < lines.length && /^\s*\|[\s:\-|]+\|\s*$/.test(lines[i + 1])) {
      const head = splitRow(ln); i += 2;
      const rows = [];
      while (i < lines.length && /^\s*\|/.test(lines[i])) { rows.push(splitRow(lines[i])); i++; }
      out.push('<table><thead><tr>' + head.map(h => '<th>' + inline(h) + '</th>').join('') +
        '</tr></thead><tbody>' + rows.map(r =>
          '<tr>' + r.map(c => '<td>' + inline(c) + '</td>').join('') + '</tr>').join('') +
        '</tbody></table>');
      continue;
    }

    // 标题
    let m = ln.match(/^(#{1,6})\s+(.*)$/);
    if (m) { out.push('<h' + m[1].length + '>' + inline(m[2]) + '</h' + m[1].length + '>'); i++; continue; }

    // 水平线
    if (/^\s*(-{3,}|\*{3,})\s*$/.test(ln)) { out.push('<hr>'); i++; continue; }

    // 引用
    if (/^\s*>\s?/.test(ln)) {
      const buf = [];
      while (i < lines.length && /^\s*>\s?/.test(lines[i])) { buf.push(lines[i].replace(/^\s*>\s?/, '')); i++; }
      out.push('<blockquote>' + buf.map(b => inline(b)).join('<br>') + '</blockquote>');
      continue;
    }

    // 列表
    if (/^\s*([-*+]|\d+\.)\s+/.test(ln)) {
      const ordered = /^\s*\d+\./.test(ln);
      const items = [];
      while (i < lines.length && /^\s*([-*+]|\d+\.)\s+/.test(lines[i])) {
        items.push(lines[i].replace(/^\s*([-*+]|\d+\.)\s+/, '')); i++;
      }
      const tag = ordered ? 'ol' : 'ul';
      out.push('<' + tag + '>' + items.map(t => '<li>' + inline(t) + '</li>').join('') + '</' + tag + '>');
      continue;
    }

    // 空行
    if (!ln.trim()) { i++; continue; }

    // 段落
    // ⚠ 必须保证 i 一定会前进：上面每个分支都吃掉了特定的行，
    //   但仍有行可能三边不靠（比如只有一行、不成表的 `| xxx`）——
    //   这时如果 while 一次都不进，就会原地死循环把浏览器卡死。
    const buf = [ln];
    i++;
    while (i < lines.length && lines[i].trim() &&
           !/^\s*([-*+]|\d+\.|>|#{1,6}\s|\|)/.test(lines[i])) {
      buf.push(lines[i]); i++;
    }
    out.push('<p>' + buf.map(b => inline(b)).join('<br>') + '</p>');
  }
  return out.join('\n');
}

/* ---------------- 状态加载 ---------------- */

async function loadState(root, keepBlock) {
  const url = '/api/state' + (root ? '?project=' + encodeURIComponent(root) : '');
  const j = await api(url);
  if (!j.ok) { setStatus('加载失败：' + (j.error || '')); return; }
  S.state = j;
  // 「这条不用再问」的名单也跟着项目走（存项目里，不是浏览器）
  S.ignoredAlerts = (j.ignored_alerts || []).slice();
  const ids = (j.blocks || []).map(b => b.id);
  if (!keepBlock || ids.indexOf(S.blockId) < 0) {
    loadBlockState(ids[0] || null);
  }
  renderAll();
  // 服务端说的话必须显示出来 —— 尤其是「记着的项目不见了 / 不是项目」这种：
  // 不显示的话，界面看着只是"空栏"，人就不知道刚才那份研究为什么没了。
  const p = curProject();
  if (j.error) {
    setStatus('⚠ ' + String(j.error).split(' —— ')[0]);
    showStateNotice(j.error);
  } else {
    setStatus('就绪 · ' + (p && p.name ? p.name : '（还没选项目）'));
  }
}

// 顶栏下面的一条持久提示（服务端的 error 不能只闪一下就没了）
function showStateNotice(msg) {
  let el = document.getElementById('stateNotice');
  if (!el) {
    el = document.createElement('div');
    el.id = 'stateNotice';
    el.className = 'banner warnb';
    const head = document.querySelector('.topbar') || document.body;
    head.parentNode.insertBefore(el, head.nextSibling);
  }
  el.innerHTML = '⚠ ' + esc(String(msg).replace(/\*\*/g, ''));
}

/* 换组块：先把当前这份现场存好，再把目标组块的那份取出来 */
function switchBlock(id) {
  if (id === S.blockId) { S.tab = 'result'; renderAll(); return; }
  if (S.running) {
    setStatus('这个组块还在跑 —— 等它跑完，或者点「停止」再切');
    return;
  }
  saveBlockState();
  loadBlockState(id);
  cfRefresh();
  renderAll();
}

/* 换项目：整个换台，不留上一个项目的任何痕迹 */
async function switchProject(root) {
  if (S.running) {
    setStatus('还在跑 —— 先停下再换项目');
    renderProjects();
    return;
  }
  clearProjectState();
  await loadState(root);
}

/* 删项目。**不再要人打项目名** —— 研究员说的：
   「删除了为什么还要再输一次项目名，别这么搞，多加一个确认键就好了」。
   让人手打名字是用**输入成本**假装安全：要删的人照样会打，只有手滑的人被拦一下。
   真正的安全是**删了能找回来** —— 所以现在「删除」= **移进回收站**
   （`项目之家/.trash/<项目名>_<时间>`），删完还给一个「撤销」。 */
function deleteProject(root) {
  const p = (S.state.projects || []).filter(x => x.root === root)[0] || {};
  const name = p.name || String(root).split(/[\\/]/).pop();
  const cp = curProject();
  const isCur = cp && cp.root === root;
  showModal(`<h3>删除项目「${esc(name)}」</h3>
    <div class="banner warnb">它会**移进回收站**，不会真的抹掉——
      手滑了还能撤销，或者在「项目之家\\.trash\\」里自己搬回来。</div>
    ${isCur ? '<div class="hint">⚠ 它正是**当前打开**的项目；删完当前项目会变成空栏。</div>' : ''}
    <div class="actions">
      <button class="btn ghost2" onclick="closeModal()">算了</button>
      <button class="btn danger" id="delGo">移到回收站</button>
    </div>`);
  const go = $('#delGo');
  if (go) go.onclick = async () => {
    go.disabled = true; go.textContent = '正在移…';
    const r = await post('/api/project/delete', { root: root });
    if (!r.ok) { alert(r.error || '删不掉'); go.disabled = false; go.textContent = '移到回收站'; return; }
    closeModal();
    clearProjectState();
    await loadState();                     // 当前项目可能已被清空，重新拉状态
    // 删完给一次「撤销」——这才是让"一次确认"站得住的东西
    showModal(`<h3>已移进回收站</h3>
      <div class="banner ok">「${esc(r.deleted)}」已经在回收站里，没被抹掉。</div>
      <div class="hint" style="word-break:break-all">${esc(r.trash || '')}</div>
      <div class="actions">
        <button class="btn ghost2" onclick="closeModal()">知道了</button>
        <button class="btn primary" id="undelGo">↩ 撤销删除</button>
      </div>`);
    const u = $('#undelGo');
    if (u) u.onclick = async () => {
      u.disabled = true; u.textContent = '正在还原…';
      const rr = await post('/api/project/undelete', { token: r.undo_token });
      if (!rr.ok) { alert(rr.error || '还原不了'); u.disabled = false; u.textContent = '↩ 撤销删除'; return; }
      closeModal();
      await loadState();
      setStatus('已还原项目「' + r.deleted + '」');
    };
  };
}

function currentBlock() {
  if (!S.state) return null;
  return (S.state.blocks || []).find(b => b.id === S.blockId) || null;
}

/* ---------------- 表单的保存 ----------------

   存**两份**，各有各的用处：

   · `localStorage`（快 `urw.form.<项目路径>|组块`）—— 刷新不丢。但键里带**绝对路径**，
     项目导出成快照、导入回别的地方之后路径变了，键就对不上，表单会全空。
   · 项目里的 `表单填写.json` —— **这份能跟着项目走**。导出、换机器、导入回来，
     表单里还是当初填的那些。所以"导入回来接着做"才能真的接着做。

   两份都写，读的时候项目里那份优先（它才是"作者存过的"）。
   ⚠ 合并规则：**只用它来补"还没填的"，不覆盖你已经打过的字**。
     否则你刚改完一栏，切个组块回来就被旧值盖掉了。 */

let _formSaveTimer = null;
const _localSnapshot = {};      // 组块id → 从 localStorage 读上来的那份（用来分辨"旧缓存"和"刚打的字"）

function formKey(blockId) {
  const root = (S.state && S.state.project && S.state.project.root) || '';
  return 'urw.form.' + root + '|' + blockId;
}

function loadForm(b) {
  if (!b) return;
  let local = {};
  try {
    const raw = localStorage.getItem(formKey(b.id));
    if (raw) local = JSON.parse(raw) || {};
  } catch (e) { /* 无痕模式 / 没有 localStorage：跳过，不影响用 */ }
  S.form[b.id] = Object.assign({}, local, S.form[b.id] || {});
  // ⚠ **别在这里就 loadFormFromProject 然后拿它的结果去比**：那是异步的，
  //   等它回来时 `S.form` 里可能已经有"刚打的字"了，分不清谁是新的。
  //   所以先把这份 localStorage 快照留好，等异步读完项目里那份再决定谁说了算。
  _localSnapshot[b.id] = local;
}

/* 用项目里那份表单**替换**内存里的（项目文件是权威），并报出丢了什么。
 *
 * ⚠ 这是一个真 bug 的修法（研究员撞上的）：
 *   原来 `loadFormFromProject` **只补空值**（`if (cur[k] === undefined)`），
 *   而 `loadForm` 又把 localStorage 放在前面 —— 结果"内存里的旧内容"永远赢，
 *   项目文件里正确的内容一个字都进不来。研究员把项目文件还原之后，
 *   页面上还是那版错的，**强刷也不行**，看着就像"还原没生效"。
 *
 *   现在的规则（和上面那段注释的本意一致）：
 *     · **项目文件是权威**（它才是"作者存过的"、跟着项目走的那份）
 *     · 内存里有、项目文件里没有的键 → 留着（可能是这一会话刚填的）
 *     · 两边都有但不一样 → **项目文件赢**，并把被顶掉的值报出来（能救回来）
 */
function syncFormFromProject(blockId, mine, force) {
  const cur = S.form[blockId] || (S.form[blockId] = {});
  const localsnap = _localSnapshot[blockId] || {};
  // 判据只有一条：**localStorage 快照里有没有这个键、值还一不一样**。
  //   · 快照里压根没有这个键      → 这是刚打的字（还没进 localStorage），别盖
  //   · 快照里有、但和现在不一样   → 读过之后又被改了 = 刚打的字，别盖
  //   · 快照里有、而且一模一样     → **上个会话留下的旧内容**，该被项目文件盖掉
  // 没有 localStorage（无痕模式等）时快照是空的 → 一律按"刚打的字"处理（保守，不动它）。
  // ⚠ 别再加"是不是这次会话第一次拉"那种判据：模块级的标志会在整个会话里累积，
  //   第二次打开页面就不成立了；第一版就是那样，被 `_uitest` 的【20】和【32】两条一起抓出来。
  const effForce = !!force;
  const dropped = [];
  Object.keys(mine || {}).forEach(k => {
    const pv = mine[k];
    if (JSON.stringify(pv) === JSON.stringify(cur[k])) return;      // 一样，不用动
    if (!effForce && cur[k] !== undefined) {
      const hasLocal = Object.prototype.hasOwnProperty.call(localsnap, k);
      const sameAsLocal = hasLocal
        && JSON.stringify(cur[k]) === JSON.stringify(localsnap[k]);
      if (!sameAsLocal) return;      // 刚打的字，别盖
    }
    if (cur[k] !== undefined) dropped.push(k);
    cur[k] = pv;
  });
  if (dropped.length) {
    const names = dropped.map(k => {
      const f = ((currentBlock() || {}).form || []).filter(x => x.key === k)[0] || {};
      return f.label || k;
    });
    setStatus('已按项目里的 `表单填写.json` 刷新表单：' + names.join('、')
              + ' 用文件里的内容（文件是权威）。留了份 localStorage 快照，要找回来说一声。');
  }
  return dropped.length;
}


// 从项目目录里读回（异步；读到了就补上"还没填的"）
  // 从项目目录里读回（异步）。**项目文件是权威** —— 见 syncFormFromProject 的说明。
async function loadFormFromProject(b, force) {
  if (!b || !curProject()) return;
  // 「第一次」= 这次会话里还没为这个组块读过表单。
  // 这时候内存里就算有值，也不是"现在打的"（页面刚起来 / 缓存留下来的），
  // 所以项目文件说了算。之后的重画一律保守，不碰任何已有值。
  // ⚠ 标志挂在 `S` 上（跟着项目走），别用模块级变量 —— 那种会在整个会话里累积，
  //   换个项目就永远不认为自己是第一次了（第一版就是这么错的）。
  const first = !((S.formRequested || {})[b.id]);
  if (S.formLoaded[b.id] && !force) return;    // 每个组块只在第一次拉一次
  S.formLoaded[b.id] = true;
  (S.formRequested = S.formRequested || {})[b.id] = true;
  const j = await api('/api/forms?project=' + encodeURIComponent(S.state.project.root));
  if (!j.ok) { S.formLoaded[b.id] = false; return; }   // 失败就允许下次再试
  const mine = (j.forms || {})[b.id];
  if (!mine || typeof mine !== 'object') return;
  if (syncFormFromProject(b.id, mine, first || !!force)) renderStage();
}

function saveForm(b) {
  if (!b) return;
  const data = S.form[b.id] || {};
  // ⚠ ① `localStorage`：**仍然每次都写**。
  //   它只在本机浏览器里，是"刷新不丢字"的缓冲，不会碰项目文件、也不会悄悄
  //   把内容带进导出/快照。留着它是为了不让人丢正在打的字。
  try { localStorage.setItem(formKey(b.id), JSON.stringify(data)); }
  catch (e) { /* 存不下就算了 */ }
  // ⚠ ② 项目里那份：**不再自动写**。
  //   研究员说的：「为什么会自动保存呀，不要呀，我们只保留手动保存吧」——
  //   原来这里挂了个 500ms 防抖，每敲一下就往项目文件写一次，
  //   于是"改着改着发现项目被改了"、还原的东西又被覆盖回去了。
  //   项目文件是**权威、跟着项目走**的那份，只该由人明确点「保存表单」时才动。
  markFormDirty(b);
}

// 表单"有改动还没存进项目"的标记 —— 界面上要看得见，不然人会忘了保存
function markFormDirty(b) {
  if (!b) return;
  S.formDirty = S.formDirty || {};
  S.formDirty[b.id] = true;
  const el = document.getElementById('formDirtyTag');
  if (el) { el.style.display = ''; }
}

function clearFormDirty(b) {
  if (!b) return;
  (S.formDirty = S.formDirty || {})[b.id] = false;
  const el = document.getElementById('formDirtyTag');
  if (el) { el.style.display = 'none'; }
  const btn = document.getElementById('formSaveBtn');
  if (btn) { btn.classList.remove('primary'); btn.classList.add('ghost'); }
}

// 手动保存：把表单落进项目的 `表单填写.json`（那份会跟着项目走）
async function saveFormNow() {
  const b = currentBlock();
  if (!b || !curProject()) { setStatus('还没选项目'); return; }
  const btn = document.getElementById('formSaveBtn');
  if (btn) { btn.disabled = true; btn.textContent = '保存中…'; }
  try {
    const r = await post('/api/forms/save', {
      project: S.state.project.root,
      block: b.id,
      fields: formSnapshot(b, S.form[b.id] || {}),
    });
    if (!r || !r.ok) { setStatus('存不上：' + ((r && r.error) || '未知原因')); return; }
    clearFormDirty(b);
    setStatus('表单已保存进项目（' + (r.rel || '表单填写.json') + '）');
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = '💾 保存表单'; }
  }
}

/* 落盘前把表单"整份"补齐：**声明里有的字段都要有一个值**（没填的就是空串/默认值）。
   ⚠ 为什么：原来只存"界面碰过的字段"，于是出现过一个很难查的现象 ——
     导入回来之后，变量表有内容（它从简报读），别的文本框全空，
     而表单文件里确实只有三个字段（有默认值的那些 + 被碰过的）。
     存"整份"之后就不会再有这种"看着像丢了、其实是没存"。 */
function formSnapshot(b, data) {
  const out = {};
  (b.form || []).forEach(f => {
    if (f.key === undefined) return;
    const cur = data[f.key];
    if (cur !== undefined) { out[f.key] = cur; return; }
    if (f.default !== undefined) { out[f.key] = f.default; return; }
    out[f.key] = (f.type === 'checks' || f.type === 'vartable') ? [] : '';
  });
  return out;
}

/* ⚠ 这里原来有个 `saveFormToProject()` —— 防抖 500ms 自动往项目里写表单。
   已经删掉了（研究员说的：「为什么会自动保存呀，不要呀，我们只保留手动保存吧」）。
   要往项目里写，只能走 `saveFormNow()`（界面上那个「💾 保存表单」按钮）。
   别再把它请回来：自动写项目文件会让人"改着改着发现项目被改了"，
   而且会把从 `_history` 还原回来的内容又覆盖掉。

   本地那份 `localStorage` 仍然每次写（见 saveForm）—— 它只影响本机浏览器，
   作用是"刷新不丢正在打的字"，不碰项目文件、也不进导出。 */

/* ---------------- 渲染：顶栏 ---------------- */

// 顶栏那一排状态 chip。单独拎出来是为了能被前端回归直接断言（不用真跑 DOM）。
function envChipsHtml(e, cfg) {
  e = e || {};
  cfg = cfg || {};
  const llm = cfg.llm || {};
  const st = cfg.llm_status || {};
  const libs = e.libs || {};
  const chips = [];
  chips.push(`<span class="chip ${e.python_exists ? 'ok' : 'bad'}" title="${esc(e.python || '')}">引擎 ${e.python_exists ? '✅' : '❌'}</span>`);
  // ⚠ 判据是 **openpyxl**（读 .xlsx），不是"两个都装齐"。
  //   原来写的是 `openpyxl && pyreadstat` → 在没装 pyreadstat 的机器上**永远显示红**，
  //   而 pyreadstat 只影响"读 SPSS 的 .sav"这一个入口，是可选件。
  //   把它当必要条件，用户会以为"环境缺东西不能用"，其实日常 csv/xlsx 完全没问题。
  const xlsxOk = !!libs.openpyxl;
  const libTip = '读 .xlsx 用的 openpyxl' + (libs.pyreadstat
    ? '；读 SPSS .sav 的 pyreadstat 也在'
    : '。pyreadstat（读 .sav）没装 —— 只在你直接导入 SPSS 数据文件时才需要，csv/xlsx 不受影响');
  chips.push(`<span class="chip ${xlsxOk ? 'ok' : 'bad'}" title="${esc(libTip)}">导入 ${xlsxOk ? '✅' : '缺包'}</span>`);
  chips.push(`<span class="chip ${e.spss_exists ? 'ok' : ''}" id="spssChip"
    style="${e.spss_exists ? 'cursor:pointer' : ''}"
    title="${esc(e.spss || '')}${e.spss_exists ? ' —— 点一下做个自检：看工作台能不能真的把 SPSS 跑起来' : '（没装也能用；点「⚙ 设置」可以填它的路径）'}">SPSS ${e.spss_exists ? '✅' : '—'}</span>`);
  const cls = !llm.enabled ? '' : (st.ready ? 'ok' : 'bad');
  const tip = llm.enabled
    ? ('模型：' + (st.model || '') + ' · ' + (st.ready
        ? '就绪（' + (st.provider === 'api' ? '自带 API' : 'DSH') + '）' : (st.note || '没就绪')))
    : '模型通道关着（关着也能用，所有组块都能跑）。点「⚙ 设置」填 API，或点这个 chip 试着打开。';
  chips.push(`<span class="chip ${cls}" id="llmChip" style="cursor:pointer" title="${esc(tip)}">模型 ${llm.enabled ? (st.ready ? '开 ✅' : '开 ⚠') : '关'}</span>`);
  return chips.join('');
}

function renderEnv() {
  const e = S.state.env || {};
  const cfg = S.state.config || {};
  $('#env').innerHTML = envChipsHtml(e, cfg);
  const chip = $('#llmChip');
  if (chip) chip.onclick = toggleLlm;
  const sc = $('#spssChip');
  if (sc) sc.onclick = probeSpss;
}

/* SPSS 面板。⚠ 这里**不再自动探测** —— 探测会真的启动 SPSS，
   而 SPSS 遇到不认识的开关会弹一个模态框、进程一直活着；
   自动跑会变成「你关掉一个它又开一个」（真发生过：关不掉 SPSS）。
   所以改成：先给你看清楚状态，点了按钮才试。 */
async function probeSpss() {
  const e = (S.state && S.state.env) || {};
  const arts = (S.state.project.artifacts || []).map(a => a.rel);
  const sps = arts.find(r => String(r).replace(/\\/g, '/') === 'output/分析_语法.sps') || '';
  if (!e.spss_exists) {
    showModal(`<h3>本机没找到 SPSS</h3>
      <p>config.json 里的 <code>spss_exe</code> 指向：</p>
      <div class="banner">${esc(e.spss || '（空）')}</div>
      <div class="actions"><button class="btn" onclick="closeModal()">知道了</button></div>`);
    return;
  }
  const j = await post('/api/spss/state', {});
  const running = (j.running || 0);
  const batch = j.batch_args || null;
  showModal(`<h3>SPSS 串联</h3>
    <div class="kv" style="margin-bottom:12px">
      <dt>SPSS</dt><dd style="word-break:break-all">${esc(e.spss)}</dd>
      <dt>怎么调起来</dt><dd><code>-runsyntax</code> —— 打开 SPSS 并<b>自动运行</b>语法，不用按键</dd>
      <dt>语法编码</dt><dd>${esc(j.syntax_encoding || 'gbk')}（SPSS 按本机代码页读语法，
        UTF-8 的中文进去会乱码）</dd>
      <dt>现在开着吗</dt><dd>${running
        ? '<b>开着</b>（' + running + ' 个进程）—— 跑分析时不会再另开窗口'
        : '没开'}</dd>
    </div>
    <div class="hint" style="margin-bottom:12px">⑥ 统计分析里勾上「顺便用 SPSS 跑一遍」，
      跑完它会自动调出 SPSS、自动运行，输出再自动收回结果页。你什么都不用按。</div>
    <div class="actions">
      ${sps ? '<button class="btn primary" id="spssGo">▶ 打开 SPSS 并自动运行</button>' : ''}
      <button class="btn ghost2" id="spssTry"
        title="会真的打开一次 SPSS（算个 1+1），验证 -runsyntax 在这台机器上管不管用">试一下（会打开 SPSS）…</button>
      <button class="btn" onclick="closeModal()">关闭</button>
    </div>
    <div id="spssMsg" style="margin-top:10px"></div>`);

  const go = $('#spssGo');
  if (go) go.onclick = async () => {
    go.disabled = true;
    go.innerHTML = '<span class="spin">◌</span> 正在打开…';
    const r = await post('/api/spss/launch', { rel: sps });
    go.disabled = false;
    go.innerHTML = '▶ 打开 SPSS 并自动运行';
    if (r.ok) { closeModal(); setStatus('SPSS 已打开，会自动运行'); }
    else $('#spssMsg').innerHTML = `<div class="banner err">${esc(r.error)}</div>`;
  };
  const tb = $('#spssTry');
  if (tb) tb.onclick = async () => {
    tb.disabled = true;
    $('#spssMsg').innerHTML = '<div class="banner"><span class="spin">◌</span> '
      + '正在试（会打开一次 SPSS，算个 1+1，最多等一两分钟）…</div>';
    setStatus('正在验证 -runsyntax…');
    const r = await post('/api/spss/probe', {});
    const rows = (r.tries || []).map(t => `<tr>
        <td><code>${esc(t.args)}</code></td>
        <td>${t.seconds}s</td>
        <td>${t.html ? '✅ 跑出结果了' : '—'}</td>
        <td style="font-size:11.5px;color:#9aa3b2">${esc((t.note || '').slice(0, 100))}</td>
      </tr>`).join('');
    $('#spssMsg').innerHTML = (r.ok
      ? '<div class="banner ok">管用：SPSS 打开后自动跑完了，输出也导出来了。</div>'
      : `<div class="banner err" style="white-space:pre-wrap">${esc(r.error || '没试出来')}</div>`)
      + (rows ? `<div class="tblwrap" style="margin-top:8px"><table>
        <thead><tr><th>写法</th><th>耗时</th><th>结果</th><th>说明</th></tr></thead>
        <tbody>${rows}</tbody></table></div>` : '');
    tb.disabled = false;
    setStatus(r.ok ? 'SPSS 自动运行可用' : 'SPSS 自动运行没验证通过');
  };
}

async function toggleLlm() {
  const cur = (S.state.config && S.state.config.llm) || {};
  const st = (S.state.config && S.state.config.llm_status) || {};
  const on = !cur.enabled;
  if (on && !st.ready) {
    // 没就绪时**别再扔一段 alert 就完事** —— 直接把人带到能改的地方
    alert('模型通道还没就绪：\n' + (st.note || '') +
      '\n\n点「确定」我帮你打开设置页，在那里填接口地址 / 密钥 / 型号就行。');
    showSettings();
    return;
  }
  const j = await post('/api/config/save', { config: { llm: { enabled: on } } });
  if (!j.ok) { alert(j.error); return; }
  setStatus(on ? '模型通道已打开（调用会消耗你的额度）' : '模型通道已关闭');
  await refreshProject();
}

/* ---------------- ⚙ 设置（可选功能：SPSS 路径 / 模型 API） ----------------
   为什么要有这一页：这两件事原来只能改 config.json —— 而 config.json 是给人手改的
   JSON，注释还特别多，普通用户根本不敢动。这里把它们做成能填、能选、能测的界面。 */

let _settings = null;                 // 最近一次从服务端拿到的设置状态

/* 「连不上后端」和「后端说不行」是两回事，得分开讲。
   ⚠ 踩过（2026-09-27 实测）：服务停了之后点 ⚙，弹的是
     `读设置失败：TypeError: Failed to fetch` —— 这话对研究者毫无意义（看着像程序坏了）。
     根因：这里当初用了**裸 fetch**，绕过了 `api()` 里那句中文兜底
     （「连不上本地服务」）。真实原因通常只有一个：**那个黑色命令行窗口被关了**。
   ⇒ 统一走 `api()`，网络层失败时给出人话 + 一条能照做的出路 + 重试。 */
function _offlineAlert(what) {
  return confirm(
    '连不上工作台服务（后端没在跑）。\n\n' +
    '多半是那个**黑色命令行窗口**被关掉了 —— 关掉它就等于停了服务。\n' +
    '重新双击 `启动工作台.bat`，然后刷新这个页面就能继续；\n' +
    '你的数据不会丢（产物都在项目文件夹里）。\n\n' +
    '=== 技术细节（给排查用）===\n' + what + '\n\n' +
    '点「确定」重试一次；点「取消」先这样。');
}

async function getSettings(force) {
  if (_settings && !force) return _settings;
  for (let attempt = 0; attempt < 6; attempt++) {
    const j = await api('/api/settings?project=' + encodeURIComponent(
      (curProject() || {}).root || ''));
    if (j && j.ok) { _settings = j; return j; }
    // `api()` 在连不上时给的就是「连不上本地服务：…」—— 按这个判
    const offline = !j || /连不上本地服务/.test(String(j.error || ''));
    if (offline) {
      if (!_offlineAlert((j && j.error) || '没有响应')) return null;
      continue;                     // 用户点了重试
    }
    alert('读设置失败（服务端返回了错误）：\n' + ((j && j.error) || '没给原因'));
    return null;
  }
  return null;
}

async function saveSettings(patch, quiet) {
  setStatus('正在保存设置…');
  const j = await post('/api/settings/save', { settings: patch });
  if (!j.ok) { setStatus(''); alert('保存失败：\n' + (j.error || '')); return null; }
  _settings = j.settings || null;
  if (!quiet) setStatus('已保存：' + ((j.saved || []).join('、') || '没变化'));
  // 顶栏那些 chip 要跟着变（SPSS ✅ / 模型开 ⚠ 之类）
  await refreshProject();
  return j;
}

function settingsModalHtml(st) {
  const sp = st.spss || {};
  const ll = st.llm || {};
  const cands = (sp.candidates || []).filter(c => c.exists);
  return `
  <h3>⚙ 设置</h3>
  <p class="setlead">这两个都是**可选功能** —— 不配也能完整跑完整个流程。
    配置存在 <code>${esc(st.config_file || 'config.json')}</code>，
    <b>密钥只留在你这台机器上</b>（这个文件不进 git 仓库）。</p>

  <div class="setsec">
    <div class="sethead">
      <b>SPSS 复核</b>
      <span class="badge ${sp.exists ? 'done' : ''}">${sp.exists ? '已找到' : '没找到'}</span>
    </div>
    <div class="hint">装了 SPSS 才能「顺便用 SPSS 跑一遍、把它的输出带回来」。
      没装也不影响其它功能 —— 工作台照样生成 <code>.sps</code> 语法文件，你可以自己拿去跑。</div>
    <div class="row" style="margin-top:8px">
      <input type="text" class="grow" id="setSpss" value="${esc(sp.exe || '')}"
             placeholder="stats.exe 的完整路径，例如 D:\\SPSS\\stats.exe">
      <button class="btn ghost2 pickbtn" id="setSpssPick" title="打开 Windows 文件选择框">📁 浏览…</button>
      <button class="btn ghost2 pickbtn" id="setSpssAuto" title="在常见安装位置里找一遍（只看文件，不会启动 SPSS）">🔍 自动找</button>
    </div>
    <div class="row" style="margin-top:6px">
      <button class="btn primary" id="setSpssSave">保存路径</button>
      <span class="setmsg" id="setSpssMsg"></span>
    </div>
    ${cands.length ? `<details class="fnote" style="margin-top:8px"><summary>我找到 ${cands.length} 个装着 stats.exe 的位置（点开看）</summary>
      <div class="fnote-body">${cands.map(c =>
        `<div class="rulechk good"><code>${esc(c.exe || c.path)}</code> <span>${esc(c.kind)}</span>
           <button class="ghost2 tiny" data-spssuse="${esc(c.exe)}">用这个</button></div>`).join('')}</div></details>` : ''}
    ${sp.find_help ? `<details class="fnote" style="margin-top:8px"><summary>没找到？看看怎么办</summary>
      <div class="fnote-body"><pre class="setpre">${esc(sp.find_help)}</pre></div></details>` : ''}
  </div>

  <div class="setsec">
    <div class="sethead">
      <b>模型建议</b>
      <span class="badge ${ll.provider === 'api' ? 'done' : (ll.provider === 'dsh' ? 'run' : '')}">
        ${ll.provider === 'api' ? '自带 API 就绪' : (ll.provider === 'dsh' ? 'DSH 就绪' : '两条路都没就绪')}</span>
    </div>
    <div class="hint">模型只做「给初稿」（提纲初稿、把大白话拆成结构化意图），
      <b>不参与任何算术</b>。它也能完全不配：不配时界面上有「📋 复制任务书」，
      贴到任意聊天窗口、把结果贴回来一样能用。</div>

    <div class="setsub">A · 自带 API（推荐）</div>
    <div class="field"><label>接口地址</label>
      <input type="text" id="setLlmBase" value="${esc(ll.api_base || '')}" placeholder="${esc(ll.default_base || '')}">
      <div class="hint">写到 <code>/v1</code> 这一层。
        ${(ll.base_hints || []).map(h => `<a href="#" class="sethint" data-base="${esc(h.base)}">${esc(h.name)}</a>`).join(' · ')}</div>
    </div>
    <div class="field"><label>密钥</label>
      <input type="text" id="setLlmKey" value="" autocomplete="off" spellcheck="false"
             placeholder="${ll.api_key_set ? esc(ll.api_key_mask || '已设置') + ' —— 要换就填新的，不填就保持不动' : '粘贴你的 API Key'}">
      <div class="hint">${ll.api_key_set
        ? '已设置。这一栏<b>不回显</b>（避免密钥出现在页面里）；留空保存 = 保持原样。'
        : '只写进本机的 config.json，不进仓库、不打印、不回显。'}</div>
    </div>
    <div class="field"><label>型号</label>
      <input type="text" id="setLlmModel" value="${esc(ll.api_model || '')}" placeholder="${esc(ll.default_model || '')}"></div>
    <div class="row">
      <button class="btn primary" id="setLlmSave">保存</button>
      <button class="btn" id="setLlmTest">🔌 测试连接</button>
      <label class="check ${ll.enabled ? 'on' : ''}" id="setLlmOn"><input type="checkbox" ${ll.enabled ? 'checked' : ''}> 打开模型通道</label>
      <span class="setmsg" id="setLlmMsg"></span>
    </div>
    <div class="hint" id="setLlmTestOut"></div>
    ${ll.has_dsh ? '<div class="hint">另外：这台机器上 DSH 那条路也是通的，会自动优先用你填的 API、没有才走 DSH。</div>' : ''}
  </div>

  <div class="actions">
    <button class="btn" onclick="closeModal()">关闭</button>
  </div>`;
}

async function showSettings() {
  const st = await getSettings(true);
  if (!st) return;
  showModal(settingsModalHtml(st));
  bindSettings(st);
}

function bindSettings(st) {
  const msg = (id, text, bad) => {
    const el = $('#' + id);
    if (el) { el.textContent = text || ''; el.className = 'setmsg' + (bad ? ' bad' : ' ok'); }
  };

  // ---- SPSS ----
  const pickBtn = $('#setSpssPick');
  if (pickBtn) pickBtn.onclick = async () => {
    // ⚠ 用 pickAnyFile（绝对路径 + 不拷贝），不是 pickFileFor ——
    //   stats.exe 是程序不是数据，拷进项目里没意义。
    const p = await pickAnyFile('选 SPSS 的 stats.exe', ['exe']);
    if (p) $('#setSpss').value = p;
  };
  const autoBtn = $('#setSpssAuto');
  if (autoBtn) autoBtn.onclick = async () => {
    msg('setSpssMsg', '正在常见位置里找…');
    const j = await post('/api/spss/apply', {});
    if (j.exe) { $('#setSpss').value = j.exe; msg('setSpssMsg', '找到了：' + j.exe); }
    else { msg('setSpssMsg', '常见位置里没找到 —— 装的是绿色版？用「📁 浏览…」手动选。', true); }
    _settings = null;                        // 候选列表变了，下次重开要重新取
  };
  $('#stage'); // no-op，保持风格一致
  document.querySelectorAll('[data-spssuse]').forEach(el => {
    el.onclick = () => { const i = $('#setSpss'); if (i) i.value = el.dataset.spssuse; };
  });
  const sSave = $('#setSpssSave');
  if (sSave) sSave.onclick = async () => {
    const v = ($('#setSpss') || {}).value || '';
    msg('setSpssMsg', '正在保存…');
    const j = await saveSettings({ spss: { exe: v } }, true);
    if (j) msg('setSpssMsg', v ? '已保存' : '已清空（改回自动探测）');
  };

  // ---- 模型 ----
  document.querySelectorAll('.sethint').forEach(el => {
    el.onclick = (e) => { e.preventDefault(); const i = $('#setLlmBase'); if (i) i.value = el.dataset.base; };
  });
  const lSave = $('#setLlmSave');
  if (lSave) lSave.onclick = async () => {
    const key = (($('#setLlmKey') || {}).value || '').trim();
    const patch = {
      api_base: (($('#setLlmBase') || {}).value || '').trim(),
      api_model: (($('#setLlmModel') || {}).value || '').trim(),
    };
    if (key) patch.api_key = key;            // ⚠ 空着就别发 —— 发了等于把密钥抹掉
    msg('setLlmMsg', '正在保存…');
    const j = await saveSettings({ llm: patch }, true);
    if (j) { msg('setLlmMsg', '已保存'); $('#setLlmKey').value = ''; showSettings(); }
  };
  const lTest = $('#setLlmTest');
  if (lTest) lTest.onclick = async () => {
    msg('setLlmMsg', '正在测试（最多等 30 秒）…');
    const out = $('#setLlmTestOut');
    if (out) out.innerHTML = '';
    const j = await post('/api/llm/test', {});
    if (j.ok) {
      msg('setLlmMsg', '连上了 ✅');
      if (out) out.innerHTML = '模型回了：「' + esc(j.reply || '') + '」　（' + esc(j.model || '') + ' · ' + (j.seconds || '?') + ' 秒）';
    } else {
      msg('setLlmMsg', '没连上', true);
      if (out) out.innerHTML = '<pre class="setpre">' + esc(j.error || '') + '</pre>';
    }
  };
  const onBox = $('#setLlmOn');
  if (onBox) onBox.onclick = async (e) => {
    e.preventDefault();
    const want = !onBox.classList.contains('on');
    const j = await saveSettings({ llm: { enabled: want } }, true);
    if (j) { onBox.classList.toggle('on', want); msg('setLlmMsg', want ? '模型通道已打开（调用会消耗你的额度）' : '模型通道已关闭'); }
  };
}

function renderProjects() {
  const sel = $('#projSel');
  if (!sel) return;
  const p = curProject();
  const cur = p ? p.root : '';
  const opts = (S.state.projects || []).map(x =>
    `<option value="${esc(x.root)}" ${x.root === cur ? 'selected' : ''}>${esc(x.name)}</option>`).join('');
  // **没选项目就空着** —— 不拿历史目录（项目之家）凑数。
  // 踩过：拿它凑数之后，产物落进历史目录，界面上还看不出哪里不对。
  sel.innerHTML = `<option value="" ${cur ? '' : 'selected'}>（还没选项目）</option>` + opts;
}

// 当前项目对象；没选就是 null。所有读 S.state.project.xxx 的地方都该先过这里。
function curProject() {
  return (S.state && S.state.project) ? S.state.project : null;
}

/* ---------------- 渲染：左侧流程 ---------------- */

/* 左侧栏的图标：一律用线性 SVG。
   为什么换掉 emoji：原来 ⓪①② 是数字、③④⑥ 是 emoji、🔒 又是另一个体系，
   三种风格挤在一列 22px 的格子里 → 看着毛毛的。
   统一成同一套描边图标之后，左栏才像一条"流程"而不是一串标签。
   ⚠ 按 b.id 映射，不认得的组块**退回显示编号文字**（.ic-txt）——加新组块不会变成空白。 */
const RAIL_ICONS = {
  b0_brief: '<path d="M5 2.4h6.2l3.4 3.4v11.8H5z"/><path d="M11.2 2.4v3.4h3.4"/>'
          + '<path d="M7.4 11.6h5M7.4 14.2h3.2"/>',
  b1_guide: '<path d="M3.6 4.2A1.8 1.8 0 0 1 5.4 2.4h9A1.8 1.8 0 0 1 16.2 4.2v7.4a1.8 1.8 0 0 1-1.8 1.8H8.2L4.8 16.4v-3H5.4A1.8 1.8 0 0 1 3.6 11.6z"/>'
          + '<path d="M7.6 6.6h5M7.6 9.2h3.2"/>',
  b2_coding: '<path d="M3.4 10.4V4.2a1.2 1.2 0 0 1 1.2-1.2h6.2l5.8 5.8v7.4a1.2 1.2 0 0 1-1.2 1.2H7.6"/>'
          + '<circle cx="6" cy="13.6" r="2.6"/>',
  b2b_codesum: '<path d="M4 16V4.6M4 16h12"/><path d="M7.4 13.6V9.8M10.6 13.6V6.8M13.8 13.6v-2.4"/>',
  b3_survey_design: '<rect x="4.6" y="3.2" width="10.8" height="14" rx="1.4"/>'
          + '<path d="M7.6 7h4.8M7.6 10h4.8M7.6 13h3"/>',
  b3_survey: '<rect x="3.2" y="3.2" width="13.6" height="13.6" rx="2"/>'
          + '<path d="M6.8 8h6.4M6.8 11h6.4M6.8 14h3.6"/>',
  b4_prep: '<path d="M3.6 4.6h12.8l-5 5.6v5.2l-2.8 1.6v-6.8z"/>',
  b5_stats: '<path d="M4.4 16.4V9.8M10 16.4V4.6M15.6 16.4v-4.6"/><path d="M3.2 16.4h13.6"/>',
  b9_deident: '<rect x="4.2" y="8.6" width="11.6" height="8.2" rx="1.6"/>'
          + '<path d="M6.8 8.6V6.4a3.2 3.2 0 0 1 6.4 0v2.2"/><path d="M10 11.8v2.6"/>'
};
function railIcon(b){
  const paths = RAIL_ICONS[b.id];
  if (paths){
    return '<span class="ic" title="' + esc(b.name || '') + '">'
         + '<svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.5"'
         + ' stroke-linecap="round" stroke-linejoin="round">' + paths + '</svg></span>';
  }
  // 没配图标的组块：显示后端给的编号（⓪①🔒 都行），不显示成空白
  return '<span class="ic"><b class="ic-txt">' + esc(b.num || '•') + '</b></span>';
}

// 左侧栏那条列表的 HTML —— 单独拎出来，好让测试直接断言生成的结果
function railHtml(blocks, status, groups) {
  const st = status || {};
  const item = b => {
    const s = st[b.id] || {};
    const done = s.done;
    // ⚠ 过期标记：产物还在、但**它的上游比它新**（契约改过、提纲还是旧的这种）。
    //   这类静默过期比"缺文件"更危险 —— 缺了会被发现，过期不会，
    //   人会拿着一份按旧契约生成的东西继续往下做。
    const stale = done && s.stale;
    const cls = 'dot' + (b.broken ? ' broken' : (stale ? ' stale' : (done ? ' done' : '')));
    const tip = stale
      ? `产物比上游旧了（${s.stale_why || '上游有更新'}）—— 建议重跑一遍`
      : (done ? '已完成' : '还没跑');
    // 图标位统一走 railIcon（线性 SVG）；名字里**不再重复铺那个 emoji** ——
    // 图标已经把身份说清楚了，再来一个 emoji 就是同一句话说两遍。
    const nm = b.name || b.icon || b.num || '';
    return `<div class="rail-item ${b.id === S.blockId ? 'active' : ''}" data-id="${esc(b.id)}">
      ${railIcon(b)}
      <span class="nm" title="${esc(nm)}">${esc(nm)}</span>
      ${stale ? '<span class="staletag" title="' + esc(tip) + '">过期</span>' : ''}
      <span class="${cls}" title="${esc(tip)}"></span></div>`;
  };
  if (!groups || !groups.length) return blocks.map(item).join('');
  // 按「入口 / 质性 / 量化」分组摆 —— 工作台本来就不是一条直线，
  // 硬排成一列会让人以为必须 ①②③④⑤⑥ 顺着走。
  return groups.map(g => {
    const gs = blocks.filter(b => (b.group || 'quant') === g.key);
    if (!gs.length) return '';
    const doneN = gs.filter(b => st[b.id] && st[b.id].done).length;
    return `<div class="rail-grp"><span>${esc(g.label)}</span>`
      + `<span class="gc">${doneN}/${gs.length}</span></div>`
      + gs.map(item).join('');
  }).join('');
}

function renderRail() {
  const blocks = S.state.blocks || [];
  const p = curProject();
  const st = (p && p.status) || {};
  const groups = S.state.rail_groups || [];

  const html = railHtml(blocks, st, groups);

  $('#railList').innerHTML = html || '<div class="empty">还没有组块</div>';
  $('#railList').querySelectorAll('.rail-item').forEach(el => {
    el.onclick = () => switchBlock(el.dataset.id);
  });

  if (!p) {
    // 空栏：不拿项目之家凑数，也不假装有产物
    $('#railFoot').innerHTML = '<span style="color:#9aa3b2">还没选项目 —— 顶栏「新建」或「打开…」</span>';
    return;
  }
  const arts = p.artifacts || [];
  $('#railFoot').innerHTML = `产物 <b>${arts.length}</b> 个<br>
    <span style="font-size:11.5px;word-break:break-all">${esc(p.root)}</span>`;
}

/* ---------------- 渲染：主区 ---------------- */

// 扔掉"没保存的改动"，回到**项目文件里存的那份**。
// 为什么要有它：研究员选了「留草稿但给一条退路」——
//   打字仍然留在本机（刷新/手滑关掉不丢），但人必须能一声令下"当没写过"。
//   「不丢字」和「我的保存才算数」不冲突，冲突的是"没有退路"。
async function resetFormToSaved() {
  const b = currentBlock();
  if (!b || !curProject()) { setStatus('还没选项目'); return; }
  const btn = document.getElementById('formResetBtn');
  if (btn) { btn.disabled = true; btn.textContent = '还原中…'; }
  try {
    const j = await api('/api/forms?project=' + encodeURIComponent(S.state.project.root));
    if (!j.ok) { setStatus('读不到项目里的表单：' + (j.error || '')); return; }
    const mine = (j.forms || {})[b.id];
    if (!mine) {
      setStatus('项目里还没存过这个组块的表单 —— 那就按字段默认值来');
      S.form[b.id] = {};
    } else {
      // 直接把内存整份换掉（不是"补空值"）：这才是"还原"，不是"合并"
      S.form[b.id] = {};
      Object.keys(mine).forEach(k => { S.form[b.id][k] = mine[k]; });
    }
    // 本机那份草稿也一起清掉，否则刷新一下又把 121 变回来
    try { localStorage.removeItem(formKey(b.id)); } catch (e) { /* 没有就算了 */ }
    _localSnapshot[b.id] = {};
    clearFormDirty(b);
    renderStage();
    setStatus('已还原成项目里保存的那份（没保存的改动都丢掉了）');
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = '↺ 还原成已保存的'; }
  }
}

// 「保存表单」按钮 + 未保存标记。
// 为什么要有这个按钮：研究员说的「我们只保留手动保存吧」——
// 那自动写项目文件那条路去掉之后，人得有个明确的地方按一下。
// 标"未保存"是因为：不标的话人会以为已经存了，关掉页面才发现没有。
function formSaveBtnHtml() {
  const b = currentBlock();
  const dirty = b && (S.formDirty || {})[b.id];
  return `<button class="btn ${dirty ? 'primary' : 'ghost'} tiny" id="formSaveBtn"
      title="把这一栏填的内容存进项目里的 表单填写.json（那份会跟着项目走、导出也带着）"
      >💾 保存表单</button>
    ${dirty
      ? `<button class="btn ghost tiny" id="formResetBtn"
           title="扔掉没保存的改动，回到项目文件里存的那份（本机草稿也一起清掉）"
           >↺ 还原成已保存的</button>` : ''}
    <span class="hint" id="formDirtyTag" style="font-size:11.5px;color:#b45309;${dirty ? '' : 'display:none'}"
      >● 有改动还没保存</span>`;
}

function renderAll() { renderEnv(); renderProjects(); renderRail(); renderStage(); }

/* ---------------- 检查点 & 过程 ---------------- */

function renderPending() {
  const p = S.pending || {};
  const btns = (p.options || []).map(o => {
    const primary = o.value === p.default ? ' primary' : '';
    const hint = o.hint ? ` title="${esc(o.hint)}"` : '';
    return `<button class="btn${primary}" data-answer="${esc(o.value)}"${hint}>${esc(o.label)}</button>`;
  }).join('');
  const tbl = (p.rows && p.rows.length)
    ? tableHtml({ columns: p.columns || [], rows: p.rows }) : '';
  return `<div class="card askcard">
    <h3>⏸ 停下来等你决定</h3>
    <div class="asktitle">${esc(p.title || '')}</div>
    ${p.detail ? `<div class="askdetail">${esc(p.detail)}</div>` : ''}
    ${tbl}
    <div class="actions" style="margin-top:14px">${btns}</div>
  </div>`;
}

function renderProcess() {
  const cards = S.steps.map(s => {
    let inner = `<div class="steptitle">${esc(s.title || '')}</div>`;
    if (s.detail) inner += `<div class="stepdetail">${esc(s.detail)}</div>`;
    if (s.rows && s.rows.length) {
      inner += tableHtml({ columns: s.columns || [], rows: s.rows });
    }
    return `<div class="stepcard"><span class="stepdot"></span><div class="stepbody">${inner}</div></div>`;
  }).join('');

  const ans = (S.answers || []).map((a, i) =>
    `<div class="stepcard answer"><span class="stepdot ok"></span><div class="stepbody">
       <div class="steptitle">你的决定：${esc(a.label || a.choice)}${a.replayed ? ' <span class="badge">回放</span>' : ''}</div>
       <div class="stepdetail">${esc(a.title || '')}</div>
       <div style="margin-top:7px">
         <button class="btn ghost2" style="padding:3px 10px;font-size:12px" data-rewind="${i}"
           title="重跑一遍，前面 ${i} 个决定照原样，跑到这里停下来让你重选">↩ 回到这一步之前</button>
       </div>
     </div></div>`).join('');

  const running = S.running
    ? `<div class="stepcard running"><span class="stepdot live"></span>
         <div class="stepbody"><div class="steptitle"><span class="spin">◌</span> 正在跑…</div></div></div>`
    : '';

  return `<div class="card">
    <h3>过程 · 我每一步做了什么</h3>
    <div class="steps">${cards}${ans}${running || (cards || ans ? '' : '<div class="empty">还没有步骤</div>')}</div>
  </div>`;
}

// 没选项目时的空栏。**不拿项目之家凑数** ——
// 踩过：拿它凑数之后产物落进历史目录，界面上还看不出哪里不对。
// 文案单独拎出来是为了测试能直接断言。
function stageNoProjectHtml() {
  return `<div class="empty" style="padding:26px 18px; text-align:left">
      <div style="font-size:15px;font-weight:700;color:#374151;margin-bottom:8px">还没选项目</div>
      <div class="hint" style="line-height:1.9">
        产物要落在某个项目里，所以先挑一个地方：<br>
        · <b>新建</b>：起个名字，工作台给你建好 <code>contracts/ data/ output/ samples/</code><br>
        · <b>打开…</b>：直接选一个已有目录（比如你已经在用的资料夹）<br>
        · 或者从顶栏下拉里选一个以前的项目
      </div>
      <div class="actions" style="margin-top:14px">
        <button class="btn primary" id="npNew">＋ 新建项目</button>
        <button class="btn" id="npOpen">打开已有目录…</button>
      </div>
      <div class="hint" style="margin-top:12px;color:#9aa3b2">
        没有项目的时候，工作台不会拿「项目之家」那一层凑数 ——
        那样产物会落进历史目录，界面上还看不出哪里不对，所以现在空着。
      </div>
    </div>`;
}

function renderStage() {
  // 没选项目：**先于组块判断** —— 否则「没选项目」会被说成「左边选一个组块」，指错了方向
  if (!curProject()) {
    $('#stage').innerHTML = stageNoProjectHtml();
    bindStage();
    return;
  }
  const b = currentBlock();
  if (!b) { $('#stage').innerHTML = '<div class="empty">左边选一个组块</div>'; return; }

  const parts = [];
  parts.push(`<div class="stage-head">
      <h1>${esc(b.title || b.name)}</h1>
      <p>${esc(b.desc || '')}</p>
    </div>`);

  if (b.broken) {
    parts.push(`<div class="banner err">这个组块加载失败，看一下服务端窗口的报错。</div>`);
  }
  if (b.needs && b.needs.length) {
    const missing = b.needs.filter(n => !fileExists(n));
    if (missing.length) {
      parts.push(`<div class="banner">这一步依赖前面的产物：<code>${missing.map(esc).join('</code> <code>')}</code>
        —— 还没有。可以先跳过（引擎会提示），或先去做前面那一步。</div>`);
    }
  }

  const mx = $('#modalBox');
  if (mx) {
    const np = mx.querySelector('#npNew');
    if (np) np.onclick = () => { closeModal(); $('#btnNewProj').click(); };
    const op = mx.querySelector('#npOpen');
    if (op) op.onclick = () => { closeModal(); $('#btnOpenProj').click(); };
  }

  // 空栏文案（单独拎出来，好在测试里直接断言）
  if (!curProject()) {
    $('#stage').innerHTML = stageNoProjectHtml();
    bindStage();
    return;
  }

  // 表单
  if ((b.form || []).length) {
    const nConf = scanBlockUnconfirmed(b).length;
    // ⚠ 这个按钮**不能没有待确认项就消失**：
    //   侧栏里除了待确认项，还有「已处理 N 处」和每条旁边的「撤销」。
    //   原来写成 nConf ? 按钮 : ''，于是处理完最后一条 → 点「收起」→ 按钮已经没了 →
    //   再也打不开，也看不到自己刚才处理过什么（踩过，用户报的）。
    const confBtn = nConf
      ? `<button class="btn confbtn" id="btnConf">📌 ${nConf} 处待确认</button>`
      : `<button class="btn ghost2" id="btnConf" title="待确认项已处理完；这里可以回看处理记录、撤销">📌 待确认（0）</button>`;
    // 「⚤ 从简报填回表单」：简报里已经写着研究员填过的东西（背景/目的/RQ/人群…），
    // 但表单可能因为导入旧快照等原因是空的 —— 给一个按钮把已有内容读回来，别让人重打一遍。
    // 只对「有 purpose 字段」的组块显示（就是 ⓪）。
    const hasBriefFields = (b.form || []).some(f => f.key === 'purpose') && !!curProject();
    const pullBtn = hasBriefFields
      ? `<button class="btn ghost2" id="btnPullForm"
           title="把研究简报里各小节的原文读回这些文本框（只补空着的，不覆盖你已经改过的）">⇩ 从简报填回表单</button>`
      : '';
    parts.push(`<div class="card"><h3><span class="num">1</span> 填参数 ${confBtn} ${pullBtn} ${formSaveBtnHtml()}</h3>${renderFields(b)}</div>`);
  }

  // 动作
  const engineNote = b.has_engine ? '' : '（这个组块还没写引擎）';
  parts.push(`<div class="card"><h3><span class="num">2</span> 干活</h3>
    <div class="actions">
      <button class="btn primary" id="btnRun" ${S.running || !b.has_engine ? 'disabled' : ''}>
        ${S.running ? '<span class="spin">◌</span> 运行中…' : '▶ 用 Python 跑'}</button>
      <button class="btn ghost2" id="btnLlm" title="让模型给一份初稿，你再改">🤖 让模型建议</button>
      ${S.running ? '<button class="btn danger" id="btnStop">停止</button>' : ''}
      <span class="badge">${esc(b.has_engine ? '引擎就绪' : '缺引擎')} ${esc(engineNote)}</span>
    </div>
    ${b.hint ? `<div class="hint" style="margin-top:10px">${esc(b.hint)}</div>` : ''}
  </div>`);

  // 检查点：停下来等你拍板（要醒目，因为它需要你动手）
  if (S.pending) parts.push(renderPending());

  // 过程：我每一步做了什么（跑完也留着，可以回看）
  if (S.steps.length || S.running) parts.push(renderProcess());

  // 结果
  parts.push(`<div class="card">
    <h3><span class="num">3</span> 结果
      <span style="font-weight:400;font-size:12px;color:#9aa3b2">· ${esc(b.title || b.name)}${S.result ? '' : '（这个组块还没跑过）'}</span>
    </h3>
    ${renderTabs()}
    <div id="tabBody">${renderTabBody()}</div>
  </div>`);

  $('#stage').innerHTML = parts.join('');
  bindStage();
  bindAlertOptions();          // 提醒里的「选项 + 自定义填写」
  const fsb = $('#formSaveBtn');
  if (fsb) fsb.onclick = saveFormNow;
  const frs = $('#formResetBtn');
  if (frs) frs.onclick = resetFormToSaved;
  ensureColumns();
}

function kindCn(k) {
  return { continuous: '连续', categorical: '分类', text: '文本', empty: '空列' }[k] || k;
}

/* 列名缓存按「项目 + 文件」双键 —— 不同项目里同名文件（如 data/survey.csv）
   列结构完全不同，只按文件名缓存会串台。 */
function colsKey(rel) {
  const root = (S.state && S.state.project && S.state.project.root) || '';
  return root + '|' + rel;
}

/* 选了数据文件后，把列名读回来给变量下拉用 */
async function ensureColumns() {
  const b = currentBlock();
  if (!b || !S.state) return;
  const need = (b.form || []).some(f => f.type === 'varlist' || f.type === 'varlist_multi');
  if (!need) return;
  const fv = (S.form[b.id] || {})['file'];
  if (!fv) return;
  const key = colsKey(fv);
  if (S.cols[key] !== undefined) return;      // 已有（null = 正在读）
  S.cols[key] = null;
  const j = await api('/api/columns?rel=' + encodeURIComponent(fv));
  S.cols[key] = j.ok ? j.columns : { _err: j.error || '读不了' };
  const cur = currentBlock();
  if (cur && cur.id === b.id) renderStage();
}

function fileExists(rel) {
  const arts = (S.state.project.artifacts || []).map(a => a.rel.replace(/\\/g, '/'));
  return arts.indexOf(String(rel).replace(/\\/g, '/')) >= 0;
}

function renderFields(b) {
  loadForm(b);
  const vals = S.form[b.id] || (S.form[b.id] = {});
  return (b.form || []).map(f => {
    const v = vals[f.key] !== undefined ? vals[f.key] : (f.default !== undefined ? f.default : '');
    if (v !== undefined && vals[f.key] === undefined && f.default !== undefined) vals[f.key] = f.default;
    const label = `<label>${esc(f.label || f.key)}${f.required ? ' <span style="color:#dc2626">*</span>' : ''}</label>`;
    // 变量表的字段说明交给表格自己显示（表格在下面），这里别再重复一遍
    const hint = (f.hint && f.type !== 'vartable') ? `<div class="hint">${esc(f.hint)}</div>` : '';
    let ctrl = '';

    if (f.type === 'textarea') {
      ctrl = `<textarea data-k="${esc(f.key)}" placeholder="${esc(f.placeholder || '')}">${esc(v)}</textarea>`;
      // 「自定义替换」这一栏的逐行自检：认得出／认不出，当场标出来。
      // 研究员连点了几个选项、跑完看不出哪条起作用，最后只能得出"我选了没效果"——
      // 把判定摆在眼前，就不用猜了。
      if (f.key === 'extra_rules') {
        ctrl += `<div class="rulechk-wrap" data-rulecheck="1">${ruleCheckHtml(v)}</div>`;
      }
    } else if (f.type === 'checks') {
      const cur = Array.isArray(v) ? v : [];
      ctrl = `<div class="checks">` + (f.options || []).map(o => {
        const on = cur.indexOf(o.value) >= 0;
        return `<label class="check ${on ? 'on' : ''}" data-k="${esc(f.key)}" data-v="${esc(o.value)}">
          <input type="checkbox" ${on ? 'checked' : ''}> ${esc(o.label)}</label>`;
      }).join('') + `</div>`;
    } else if (f.type === 'select') {
      ctrl = `<select data-k="${esc(f.key)}">` + (f.options || []).map(o =>
        `<option value="${esc(o.value)}" ${String(o.value) === String(v) ? 'selected' : ''}>${esc(o.label)}</option>`).join('') + `</select>`;
    } else if (f.type === 'file') {
      const files = (S.state.project.artifacts || []).concat(S.state.project.artifacts || []);
      // 「从项目里挑」的可选项：默认包含文本类文件——转写稿 / 简报也是 file 字段的常客
      const exts = f.accept || ['csv', 'xlsx', 'xls', 'sav', 'txt', 'md', 'tsv', 'json'];
      const opts = (S.state.project.artifacts || []).filter(a =>
        new RegExp('\\.(' + exts.join('|') + ')$', 'i').test(a.rel));
      ctrl = `<div class="row">
        <input type="text" class="grow" data-k="${esc(f.key)}" value="${esc(v)}" placeholder="${esc(f.placeholder || '项目内相对路径，如 data/survey.xlsx')}">
        <button class="btn ghost2 pickbtn" data-browse="${esc(f.key)}"
          title="打开文件夹选一个文件（项目外面的会自动拷进来）">📁 浏览…</button>
        <select data-pick="${esc(f.key)}"><option value="">— 从项目里挑 —</option>` +
        opts.map(o => `<option value="${esc(o.rel)}">${esc(o.rel)}</option>`).join('') + `</select></div>`;
    } else if (f.type === 'varlist' || f.type === 'varlist_multi') {
      const fileRel = vals['file'] || '';
      const cs = S.cols[colsKey(fileRel)];
      if (!fileRel) {
        ctrl = `<input type="text" data-k="${esc(f.key)}" value="${esc(v)}" placeholder="先在上面选好数据文件">`;
      } else if (cs === null || cs === undefined) {
        ctrl = `<input type="text" data-k="${esc(f.key)}" value="${esc(v)}" placeholder="正在读列名…">`;
      } else if (cs._err) {
        ctrl = `<div class="hint" style="color:#dc2626">读不了这个文件：${esc(cs._err)}</div>`;
      } else if (f.type === 'varlist') {
        ctrl = `<select data-k="${esc(f.key)}"><option value="">— 选一个变量 —</option>` +
          cs.map(c => `<option value="${esc(c.name)}"${c.name === v ? ' selected' : ''}>${esc(c.name)}（${kindCn(c.kind)}，${c.n_unique} 种取值）</option>`).join('') +
          `</select>`;
      } else {
        const cur = Array.isArray(v) ? v : [];
        ctrl = `<div class="checks">` + cs.map(c =>
          `<label class="check ${cur.indexOf(c.name) >= 0 ? 'on' : ''}" data-k="${esc(f.key)}" data-v="${esc(c.name)}">
            <input type="checkbox"${cur.indexOf(c.name) >= 0 ? ' checked' : ''}> ${esc(c.name)}
            <span style="color:#9aa3b2;font-size:11.5px">${kindCn(c.kind)}</span></label>`).join('') +
          `</div>`;
      }
    } else if (f.type === 'vartable') {
      const rows = varRowsFilled(v);
      varTableMaybeAutoPull(b, f, rows);
      ctrl = varTableHtml(b, f, v);
    } else if (f.type === 'number') {
      ctrl = `<input type="number" data-k="${esc(f.key)}" value="${esc(v)}" step="${esc(f.step || 'any')}">`;
    } else {
      ctrl = `<input type="text" data-k="${esc(f.key)}" value="${esc(v)}" placeholder="${esc(f.placeholder || '')}">`;
    }
    return `<div class="field">${label}${ctrl}${hint}</div>`;
  }).join('');
}

/* ---------------- 变量表：逐行编辑 ----------------
   以前是一个 textarea，让人手打「变量名, 角色, 测量层次, 怎么测」。
   问题是：列数、逗号、空行全靠自己维持，格式一错引擎就静默解析不出东西
   （踩过：析出 0 个变量，界面什么都不说，③ 照着出了 18 道莫名其妙的题）。
   现在改成真表格：一行一个变量，每列有列名和提示，删行/加行是按钮，
   提交时再序列化成和以前一模一样的文本格式 —— 引擎和解析器一行都不用改。 */

const VT_DEFAULT_COLS = [
  { key: 'name', label: '变量名', width: '22%', placeholder: '满意度' },
  { key: 'role', label: '角色', width: '16%', placeholder: '因变量' },
  { key: 'level', label: '测量层次', width: '16%', placeholder: '定距' },
  { key: 'op', label: '怎么测（操作化定义）', width: '46%', placeholder: '5 点量表 Q8_1~Q8_5' },
];

function vtCols(f) {
  const cs = (f && f.columns) || [];
  return cs.length ? cs : VT_DEFAULT_COLS;
}

// 文本 → 四列。也认「一列都没填」的空行（表格里刚加的新行）
function varRowCells(r) {
  const a = Array.isArray(r) ? r : String(r === undefined || r === null ? '' : r).split(',');
  const out = [];
  for (let i = 0; i < 4; i++) out.push(String(a[i] === undefined || a[i] === null ? '' : a[i]).trim());
  return out;
}

function varRowsOf(v) {
  if (!Array.isArray(v)) return [];
  return v.map(varRowCells);
}

// 真正要交出去的：空行不算变量（空行只是「正在填的那一行」，留着好让他继续填）
function varRowsFilled(v) {
  return varRowsOf(v).filter(r => r.some(x => x !== ''));
}

function varTableHtml(b, f, v) {
  const cols = vtCols(f);
  const rows = varRowsOf(v);
  const body = rows.map((cells, i) => {
    const tds = cols.map((c, j) =>
      `<td><input class="vtin" data-vt="${i}" data-vtc="${j}" value="${esc(cells[j] || '')}"
        placeholder="${esc(c.placeholder || '')}"
        title="${esc(c.hint || c.label || '')}"></td>`).join('');
    return `<tr>${tds}<td class="vtact"><button class="btn ghost2 vtdel" data-vtdel="${i}"
      title="删掉这一行">✕</button></td></tr>`;
  }).join('');
  const head = cols.map(c =>
    `<th style="width:${esc(c.width || 'auto')}" title="${esc(c.hint || '')}">${esc(c.label || c.key)}</th>`
  ).join('') + `<th class="vtact"></th>`;
  const filled = varRowsFilled(rows);
  const emptyN = rows.length - filled.length;
  const bad = filled.map(varRowBad).filter(Boolean);
  return `<div class="vt" data-vtbl="${esc(f.key)}">
    <div class="vtwrap"><table class="vtbl"><thead><tr>${head}</tr></thead>
      <tbody>${body || `<tr><td colspan="${cols.length + 1}" class="vtempty">
        还没有变量。点下面的「加一行」，或者从研究简报里读回来。</td></tr>`}</tbody></table></div>
    <div class="vttools">
      <button class="btn ghost2 vtadd" data-vtadd="${esc(f.key)}">＋ 加一行</button>
      <button class="btn ghost2 vtpull" data-vtpull="${esc(f.key)}"
        title="读研究简报里的变量表（规则和引擎同一套）">⟳ 从研究简报读回</button>
      <span class="grow"></span>
      <span class="vtcount">${filled.length} 个变量${emptyN ? '（还有 ' + emptyN + ' 行没填）' : ''}</span>
    </div>
    ${bad.length ? `<div class="vterr">有 ${bad.length} 处带了半角逗号或换行 —— 那是列与列的分隔符，
      会被解析器切开。中文逗号「，」没问题：
      ${esc(bad.slice(0, 3).join('、'))}${bad.length > 3 ? ' …' : ''}</div>` : ''}
    <div class="vthint">一行一个变量。${esc(f.hint || '')}</div>
    ${f.note ? noteHtml(f.note) : ''}
  </div>`;
}

/* 字段自带的「这个东西是干什么的」。**默认收起**：
   平时不占地方，卡住的时候点开就有 —— 说明写在产品里，而不是写在文档里等人去翻。
   （起因：有人想不通「③ 这张变量表和 ⓪ 那张是什么关系」，而答案只存在于聊天里。） */
function noteHtml(note) {
  if (!note || !note.body) return '';
  const t = note.title || '这个字段是干什么的';
  return `<details class="fnote">
    <summary>❔ ${esc(t)}</summary>
    <div class="fnote-body">${String(note.body).split(/\n{2,}/).map(p =>
      `<p>${p.split('\n').map(inline).join('<br>')}</p>`).join('')}</div>
  </details>`;
}

// 会被**解析器**当成列分隔符的字符才拦：半角逗号、制表符、换行、竖线。
// ⚠ 全角逗号「，」是中文标点，不该拦 —— 踩过：操作化定义写成
//   「5 级 Likert（1 完全不愿意，5 非常愿意）」是正常写法，拦它等于天天误报，
//   提示看多了就没人看了，真出问题时反而被忽略。（`，` 只在 Markdown 表里当分隔符，
//   而提交用的是逗号分隔格式，所以这里放它过。）
function varCellBad(s) {
  return /[,\n\r\t|]/.test(String(s === undefined || s === null ? '' : s));
}

function varRowBad(cells) {
  for (let i = 0; i < cells.length; i++) {
    if (varCellBad(cells[i])) return '第 ' + (i + 1) + ' 列「' + cells[i].slice(0, 12) + '」';
  }
  return '';
}

// 表格 → 存储。**空行照存**，不在这里过滤：
// 界面上「第几行」和存储里「第几行」必须一一对应，否则删行会删错人
//（踩过：加一空行再删最后一行，删掉的是最后那个真变量，表里静默少了一个）。
function varTableSet(b, key, cells, i, j) {
  const cur = varRowsOf((S.form[b.id] || {})[key]);
  while (cur.length <= i) cur.push(['', '', '', '']);
  cur[i][j] = cells;
  S.form[b.id] = S.form[b.id] || {};
  S.form[b.id][key] = cur;
  saveForm(b);
}

function varTableAddRow(b, key) {
  const cur = varRowsOf((S.form[b.id] || {})[key]);
  cur.push(['', '', '', '']);
  S.form[b.id] = S.form[b.id] || {};
  S.form[b.id][key] = cur;
  saveForm(b);
  renderStage();
}

function varTableDelRow(b, key, i) {
  const cur = varRowsOf((S.form[b.id] || {})[key]);
  cur.splice(i, 1);
  S.form[b.id] = S.form[b.id] || {};
  S.form[b.id][key] = cur;
  saveForm(b);
  renderStage();
}
// 变量表的值可能是两种形态：逐行数组（正常），或一段文本（「填回表单」塞进来的、
// 还带着「（待确认：…）」那种）。擦除/替换要能把结果写回**表格**，
// 所以统一先折成文本 —— 两种形态都能折叠成同一份文本。
function varTableText(v) {
  if (typeof v === 'string') return v;
  return varRowsOf(v).map(r => r.join(', ')).join('\n');
}

// 变量表字段的文本转换已经交给 TEXT_ACCEPTORS（按字段声明分发），
// 这里只剩"擦完待确认之后把文本还原成表格"这一个用途。
async function tidyVarTableField(b, f, text) {
  const j = await post('/api/vartable/parse', { text: text });
  const rows = (j.ok ? (j.rows || []) : []).map(varRowCells);
  if (rows.length) S.form[b.id][f.key] = rows;
  return rows.length;
}

// 从研究简报把变量表读回来 —— 走后端，规则和引擎一致
async function varTablePull(b, key) {  const vals = S.form[b.id] || {};
  const rel = vals['brief'] || 'contracts/research_brief.md';
  setStatus('正在读 ' + rel + ' 里的变量表…');
  const j = await api('/api/brief/variables?rel=' + encodeURIComponent(rel) +
    '&project=' + encodeURIComponent(S.state.project.root));
  if (!j.ok) { setStatus('读不回来：' + j.error); return; }
  if (!j.exists) { setStatus('没找到 ' + rel + '（先把 ⓪ 跑出来）'); return; }
  const rows = (j.rows || []).map(varRowCells);
  if (!rows.length) { setStatus(rel + ' 里没解析出变量表 —— 看看 ⓪ 的第 6 节写了没有'); return; }
  S.form[b.id] = S.form[b.id] || {};
  S.form[b.id][key] = rows;
  S.vtPulled[(b.id || '') + '|' + key] = true;
  S.vtCache[(S.state.project.root || '') + '|' + (b.id || '') + '|' + key] = JSON.stringify(rows);
  saveForm(b);
  renderStage();
  setStatus('已经从简报读回 ' + rows.length + ' 个变量');
}

// 表空的时候自动去简报读一趟。
// ⚠ 不能只看「这次会话读过没有」——那样会覆盖研究员自己删干净的表。
//   所以比对上次读回来的内容：一模一样（或本来就是空的）才敢再读，
//   说明他动过，就不碰。
function varTableMaybeAutoPull(b, f, rows) {
  const k = (b.id || '') + '|' + f.key;
  const ck = (S.state.project.root || '') + '|' + k;
  if (S.vtPulled[k]) return;
  const cached = S.vtCache[ck];
  if (rows.length && JSON.stringify(rows) !== cached) return;   // 有内容又和简报那次不一样 → 是他的编辑
  S.vtPulled[k] = true;
  varTablePull(b, f.key);
}

function bindVarTable() {
  const stage = $('#stage');
  if (!stage) return;
  stage.querySelectorAll('input[data-vt]').forEach(el => {
    el.oninput = () => {
      const box = el.closest('.vt');
      const b = currentBlock();
      if (!box || !b) return;
      const i = Number(el.dataset.vt), j = Number(el.dataset.vtc);
      const cells = el.value;
      if (varCellBad(cells)) {                 // 先别存，让它自己看见问题
        box.classList.add('bad');
        el.classList.add('badcell');
        return;
      }
      el.classList.remove('badcell');
      box.classList.remove('bad');
      varTableSet(b, box.dataset.vtbl, cells, i, j);
    };
  });
  stage.querySelectorAll('[data-vtadd]').forEach(el => {
    el.onclick = () => varTableAddRow(currentBlock(), el.dataset.vtadd);
  });
  stage.querySelectorAll('[data-vtdel]').forEach(el => {
    el.onclick = () => varTableDelRow(currentBlock(), el.closest('.vt').dataset.vtbl,
      Number(el.dataset.vtdel));
  });
  stage.querySelectorAll('[data-vtpull]').forEach(el => {
    el.onclick = () => varTablePull(currentBlock(), el.dataset.vtpull);
  });
}

function renderTabs() {
  const t = S.tab;
  const arts = (S.state.project.artifacts || []).length;
  const logs = S.logs.length;
  const mk = (id, label) => `<button class="tab ${t === id ? 'on' : ''}" data-tab="${id}">${label}</button>`;
  return `<div class="tabs">${mk('result', '结果')}${mk('files', '产物 ' + arts)}${mk('log', '日志 ' + logs)}</div>`;
}

function renderTabBody() {
  if (S.tab === 'log') return renderLogs();
  if (S.tab === 'files') { loadLayersSoon(); return renderFiles(); }
  return renderResult();
}

// 产物页的分层清单要先拉一次；拉了就不再重复请求（免得每次重画都打接口）
function loadLayersSoon() {
  if (S.layers || S.layersBusy) return;
  S.layersBusy = true;
  loadLayers().then(() => { S.layersBusy = false; });
}

/* 知识库规则的出处类型 —— 研究员要能分清「通行做法」和「某家偏好」 */
function kindCn(k) {
  return ({ convention: '行业惯例', opinion: '某家观点', heuristic: '经验法则',
            internal: '工作台自身' })[k] || k;
}

// 哪些提醒属于「知识库/设计建议」——这些话一律只是提醒，绝不拦人。
// 单独拎出来是为了在界面上把这句话说明白：**研究怎么设计是研究者的选择**。
const ADVICE_KINDS = ['convention', 'opinion', 'heuristic'];

function hasAdvice(alerts) {
  return (alerts || []).some(a => ADVICE_KINDS.indexOf(a.kind) >= 0);
}

// 一条提醒的**稳定标识**：用来记住"这条我看过了，别再显示"。
// ⚠ 不能用消息原文以外的会变的东西（比如数组下标）—— 下次跑提醒顺序一变，
//   "忽略"就串到别的提醒上了。用「消息 + 位置」的短哈希，稳。
function alertSig(a) {
  const base = String((a && a.msg) || '') + '|' + String((a && a.level) || '')
    + '|' + String(((a && a.locate) || {}).line || '');
  let h = 0;
  for (let i = 0; i < base.length; i++) {
    h = ((h << 5) - h + base.charCodeAt(i)) | 0;
  }
  return 'a' + (h >>> 0).toString(36);
}

function renderResult() {
  const r = S.result;
  if (!r) {
    if (S.running) return '<div class="empty">跑着呢，先看「日志」页</div>';
    return '<div class="empty">还没跑。填好上面的参数，点「用 Python 跑」。</div>';
  }
  const out = [];
  if (r.error) out.push(`<div class="banner err">${esc(r.error)}</div>`);
  // 引擎报的「出事了」——放在摘要**上面**，因为摘要那行绿字会让人以为一切正常
  (r.alerts || []).forEach(a => {
    const sig = alertSig(a);
    if ((S.ignoredAlerts || []).indexOf(sig) >= 0) return;      // 他说过「这条不用再问」
    const bad = a.level === 'error';
    out.push(`<div class="banner ${bad ? 'err' : 'warnb'} alertbox" data-sig="${esc(sig)}">
      <div><b>${bad ? '⛔' : '⚠'} ${esc(a.msg)}</b></div>
      ${a.fix ? `<div class="afix">怎么办：${esc(a.fix)}</div>` : ''}
      ${a.source ? `<div class="asrc">依据${a.kind ? '（' + esc(kindCn(a.kind)) + '）' : ''}：${esc(a.source)}</div>` : ''}
      ${alertOptionsHtml(a)}
      ${alertMsgOf(sig)
        ? `<div class="banner ${alertMsgOf(sig).bad ? 'err' : 'ok'} rulemsgb inalert">`
          + `${alertMsgOf(sig).bad ? '⚠' : '✓'} ${esc(alertMsgOf(sig).text)}</div>`
        : ''}
      <div class="aact">
        ${a.locate && a.locate.file
          ? `<a href="#" data-goto-file="${esc(a.locate.file)}" data-goto-line="${esc(a.locate.line || 1)}"
               title="直接翻到原文那一行（不用自己去搜）"
               >📍 看原文第 ${esc(a.locate.line || 1)} 行</a>` : ''}
        ${a.rel ? `<a href="#" data-open-rel="${esc(a.rel)}">打开 ${esc(a.rel)}</a>` : ''}
        <a href="#" class="alertmute" data-mute="${esc(sig)}"
           title="这条我看过了，别再显示它（记在项目里，换机器也还在）">🙈 这条不用再问</a>
      </div>
    </div>`);
  });
  // 把「这只是提醒」写在脸上 —— 研究怎么设计是研究者的选择，不该由工具替他定
  if (hasAdvice(r.alerts)) {
    out.push(`<div class="hint advnote">上面这些只是提醒，不是拦你。研究怎么设计是你的选择——
      不满意就照你的想法往下走，工作台不会因此拒绝执行；觉得规则本身不对，就改
      <code>workbench/knowledge/</code> 里那份文件，下次跑就按你改的来。</div>`);
  }
  // 刚才并入的那条规则：**留在原地**，别让它跟着提示一起蒸发。
  // ⚠ 这份在**结果区**，只在跑完/切页时才画；点选项时重画的是表单区，
  //   所以真正管用的是 `renderStage` 里那一条（他去那边看）。这里保留是为了
  //   跑完之后还能看见"上一步动了什么"。
  if (S.ruleMsg && S.ruleMsg.text) {
    out.push(`<div class="banner ${S.ruleMsg.bad ? 'err' : 'ok'} rulemsgb">`
      + `${S.ruleMsg.bad ? '⚠' : '✓'} ${esc(S.ruleMsg.text)}</div>`);
  }
  if (r.summary) {
    // 有提醒的时候，别让那行绿色摘要抢戏 —— 它写的是「跑完了」，而提醒说的是「跑出来的东西是空的」
    const bad = (r.alerts || []).some(a => a.level === 'error');
    if (bad) {
      out.push(`<div class="hint" style="margin-top:2px">这次跑的摘要（但不代表结果能用）：
        ${esc(r.summary)}</div>`);
    } else {
      out.push(`<div class="banner ok">${esc(r.summary)}</div>`);
    }
  }

  // 下一步卡片：② 跑完要人去 Excel 填码这段「工作台外面的活」，
  // 以前界面上完全没有痕迹（走查时学生点 ②b 只撞到一句报错）。
  if (r.next && r.next.title) {
    const nx = r.next;
    out.push(`<div class="nextcard">
      <div class="nxt-title">⏭ ${esc(nx.title)}</div>
      <div class="nxt-body">${String(nx.body || '').split(/\n{2,}/).map(p =>
        `<p>${p.split('\n').map(inline).join('<br>')}</p>`).join('')}</div>
      <div class="nxt-acts">${(nx.btns || []).map(bt =>
        bt.action === 'open'
          ? `<button class="btn ghost2" data-open-art="${esc(bt.rel || '')}">${esc(bt.label)}</button>`
          : '').join('')}</div></div>`);
  }

  (r.tables || []).forEach((t, i) => {
    const tid = t.id || ((r.block || 'run') + '#' + i + '·' + (t.name || '表'));
    out.push(`<div style="margin-bottom:16px">
      <h3 style="font-size:13.5px;margin:0 0 7px;color:#4b5563">📋 ${esc(t.name || '表')}</h3>
      ${t.note ? `<div class="hint" style="margin-bottom:6px">${esc(t.note)}</div>` : ''}
      ${tableHtml(Object.assign({}, t, { id: tid }))}</div>`);
  });

  (r.figures || []).forEach(f => {
    out.push(`<div class="fig">
      <img src="/api/artifact?rel=${encodeURIComponent(f.rel)}&t=${Date.now()}" alt="${esc(f.name || '')}">
      <div class="cap"><b>${esc(f.name || '')}</b>${f.caption ? ' · ' + esc(f.caption) : ''}</div></div>`);
  });

  (r.markdown || []).forEach(m => {
    out.push(`<div style="margin-bottom:16px">
      <h3 style="font-size:13.5px;margin:0 0 7px;color:#4b5563">📄 ${esc(m.name || m.rel || '')}</h3>
      <div class="md">${mdToHtml(m.text || '')}</div></div>`);
  });

  (r.text || []).forEach(t => {
    const isSps = /\.sps$/i.test(t.rel || '');
    out.push(`<div style="margin-bottom:16px">
      <h3 style="font-size:13.5px;margin:0 0 7px;color:#4b5563">📝 ${esc(t.name || t.rel || '')}
        ${isSps ? `<span style="font-weight:400;margin-left:8px">
          <a href="#" data-spss-open="${esc(t.rel)}" style="font-size:12px"
             title="把这份语法丢给 SPSS 打开，你自己按运行">用 SPSS 打开</a></span>` : ''}</h3>
      <pre class="out ${t.mono ? 'sps' : ''}">${esc(t.text || '')}</pre></div>`);
  });

  // SPSS 自己导出的输出：整块嵌进来看，样式是 SPSS 的（三线表、脚注那些）
  if (r.spss && r.spss.warning) {
    out.push(`<div class="banner err" style="margin-bottom:12px;white-space:pre-wrap">`
      + esc(r.spss.warning) + `</div>`);
  }
  (r.html || []).forEach((h, i) => {
    out.push(`<div style="margin-bottom:16px">
      <h3 style="font-size:13.5px;margin:0 0 7px;color:#4b5563">📊 ${esc(h.name || 'SPSS 输出')}
        <span style="font-weight:400;display:inline-flex;gap:8px;margin-left:8px">
          <a href="#" data-open-rel="${esc(h.rel || '')}" style="font-size:12px">在产物里打开</a>
        </span></h3>
      <div class="hint" style="margin-bottom:6px">这一块是 SPSS 自己导出的原文，样式就是 SPSS 的——
        用来和上面 Python 算的数字对照。</div>
      <iframe class="spssframe" id="spssframe${i}" sandbox
        srcdoc="${esc(h.text || '')}"></iframe></div>`);
  });

  // SPSS 走了「打开界面」那条路：给它一个等待区，跑完自动把输出收回来
  if (r.spss && r.spss.mode === 'gui' && r.spss.ok) {
    const auto = r.spss.autorun && !r.spss.already_open;
    out.push(`<div class="card" id="spssWait" data-sps="${esc(r.spss.sps || '')}"
        data-html="${esc(r.spss.html || '')}"
        style="margin-bottom:16px;background:#fbfcfe">
      <h3 style="font-size:13.5px;margin:0 0 7px;color:#4b5563">🔗 等 SPSS 的输出</h3>
      <div class="hint" style="margin-bottom:8px">${auto
        ? 'SPSS 已经打开，而且<b>会自动运行</b>这份语法（用的是 <code>-runsyntax</code>，不用你按键）。'
        : (r.spss.already_open
            ? 'SPSS 本来就开着，没有另开窗口。如果那份语法没自动跑，在 SPSS 里按 <b>Ctrl+A</b> 再 <b>Ctrl+R</b>。'
            : 'SPSS 已经打开，请在窗口里按 <b>Ctrl+A</b> 全选、<b>Ctrl+R</b> 运行。')}
        跑完这边会自动把 SPSS 的输出收回来显示。</div>
      <div id="spssWaitMsg" class="banner"><span class="spin">◌</span> 正在等 SPSS 跑完…</div>
      <div class="actions" style="margin-top:9px">
        <button class="btn ghost2" id="spssRelaunch">再打开一次 SPSS</button>
        <button class="btn ghost2" id="spssStop">不等了</button>
      </div>
    </div>`);
  } else if (r.spss && r.spss.mode !== 'batch' && r.spss.error) {
    out.push(`<div class="banner err" style="margin-bottom:16px">
      SPSS 没调起来：${esc(r.spss.error)}　
      Python 那一遍的结果不受影响。</div>`);
  }

  if (r.notes) out.push(`<div class="hint" style="margin-top:8px">${esc(r.notes)}</div>`);
  return out.join('') || '<div class="empty">这次没有表格/图，看看日志页</div>';
}

/* ---------------- 看表：排序 + 显著性上色 ----------------
   研究员看表最累的一件事：变量一多，得一行行找 p。
   所以表头能点着排序，p 那一列按阈值上色 —— 一眼扫出哪些不显著。 */

const TBL_LEGEND_URI = 'data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHZpZXdCb3g9IjAgMCAxNiAxNiI+PHBhdGggZD0iTTggM2w0IDRIM3oiIGZpbGw9IiM0NzU1NjkiLz48L3N2Zz4=';

function parseNumText(s) {
  if (typeof s === 'number') return s;
  const t = String(s === undefined || s === null ? '' : s).trim();
  if (!t) return null;
  const m = /^[+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?$/.exec(t.replace(/,/g, ''));
  if (!m) return null;
  const v = Number(t.replace(/,/g, ''));
  return isFinite(v) ? v : null;
}

// 「这一列是 p 吗」。宁可漏判，别把「标准化 β」也认成 p 去上色。
function isPName(name) {
  const s = String(name || '').trim().toLowerCase();
  if (!s) return false;
  if (/^(p|sig|p值|p-?value|显著性(水平)?|p值\(.*\))$/.test(s)) return true;
  return /^(p|sig)[\s·:：]/.test(s);
}

const pColsOf = (cols) => cols.map((c, i) => (isPName(c) ? i : -1)).filter(i => i >= 0);
const pRowOf = (rows) => rows.findIndex(r => /^(p|sig|显著性)$/i.test(String(r && r[0] || '').trim()));

function pCellHtml(v, alpha) {
  const n = parseNumText(v);
  if (n === null) return { cls: '', tip: '' };
  if (n < alpha) return { cls: 'p-sig', tip: '显著（p < ' + alpha + '）' };
  if (n < 0.1) return { cls: 'p-weak', tip: '勉强（0.05 ≤ p < 0.1）' };
  return { cls: 'p-no', tip: '不显著（p ≥ 0.1）' };
}

function tstate(id) {
  S.tblSort = S.tblSort || {}; S.tblAlpha = S.tblAlpha || {};
  if (S.tblAlpha[id] === undefined) S.tblAlpha[id] = 0.05;
  return {
    id: id,
    alpha: S.tblAlpha[id],
    sort: S.tblSort[id] || null,
  };
}

function fmtNumCell(c) {
  if (typeof c !== 'number') return String(c === undefined || c === null ? '' : c);
  if (Math.abs(c) >= 1e6 || (c !== 0 && Math.abs(c) < 1e-4)) return String(c);
  const s = (+c.toFixed(4));
  return (Math.abs(s) >= 1000 ? s.toLocaleString('en-US') : String(s));
}

function tblHeadRow(cols, st) {
  return '<tr>' + cols.map((c, i) => {
    const on = st.sort && st.sort.col === i;
    const arrow = on ? (st.sort.dir > 0 ? '▲' : '▼') : '';
    return `<th class="sortable${on ? ' sorted' : ''}" data-sortcol="${i}" data-col="${esc(c)}"`
      + ` title="点一下按「${esc(c)}」排序">${esc(c)}<span class="ar">${arrow}</span></th>`;
  }).join('') + '</tr>';
}

function tblBody(rows, cols, st, pcols) {
  const pr = pRowOf(rows);
  return rows.map((r, ri) => {
    const pRow = ri === pr;
    return '<tr' + (pRow ? ' class="prow"' : '') + '>' + cols.map((c, ci) => {
      const isNum = typeof r[ci] === 'number';
      if (pcols.indexOf(ci) >= 0) {
        const p = pCellHtml(r[ci], st.alpha);
        return `<td class="num ${p.cls}" data-v="${esc(r[ci])}" data-t="n"`
          + `${p.tip ? ` title="${esc(p.tip)}"` : ''}>${esc(fmtNumCell(r[ci]))}</td>`;
      }
      return `<td class="${isNum ? 'num' : ''}" data-v="${esc(isNum ? r[ci] : String(r[ci] === undefined || r[ci] === null ? '' : r[ci]))}"`
        + ` data-t="${isNum ? 'n' : 's'}">${esc(fmtNumCell(r[ci]))}</td>`;
    }).join('') + '</tr>';
  }).join('');
}

function tableCaption(cols, rows, st) {
  return `<div class="tblcap">${captionInner(cols, rows, st)}</div>`;
}

function captionInner(cols, rows, st) {
  const hasP = pColsOf(cols).length > 0 || pRowOf(rows) >= 0;
  const opts = [0.01, 0.05, 0.1].map(a =>
    `<button class="al${Math.abs(st.alpha - a) < 1e-9 ? ' on' : ''}" data-tblalpha="${st.id}" data-a="${a}">p&lt;${a}</button>`).join('');
  return `<span class="hint">点列头可以排序</span>
    ${hasP ? `<span class="grow"></span>
      <span class="lg"><i class="d-sig"></i>显著</span>
      <span class="lg"><i class="d-weak"></i>勉强（0.05～0.1）</span>
      <span class="lg"><i class="d-no"></i>不显著</span>
      <span class="hint">阈值</span>
      <span class="alphapick">${opts}</span>` : ''}`;
}

function tableHtml(t) {
  const cols = (t && t.columns) || [];
  const rows = (t && t.rows) || [];
  if (!cols.length) return '<div class="empty">空表</div>';
  const id = String((t && t.id) || (t && t.name) || '表');
  const st = tstate(id);
  const pcols = pColsOf(cols);
  return `<div class="tblwrap" data-tbl="${esc(id)}" data-alpha="${st.alpha}">
    ${tableCaption(cols, rows, st)}
    <table><thead>${tblHeadRow(cols, st)}</thead>
    <tbody>${tblBody(rows, cols, st, pcols)}</tbody></table></div>`;
}

function cellText(td) {
  if (td.dataset && td.dataset.t === 'n') {
    const v = parseNumText(td.dataset.v);
    if (v !== null) return v;
  }
  const s = String(td.dataset && td.dataset.v !== undefined ? td.dataset.v
    : (td.textContent || '')).trim();
  const n = parseNumText(s);
  return n === null ? s : n;
}

// 表头文字：优先读 data-col（表头里那个排序箭头是画上去的，别把它当列名）
function headTexts(the) {
  const row = the.rows[the.rows.length - 1];
  return Array.prototype.map.call(row.cells, (th, i) => {
    if (th.dataset && th.dataset.col !== undefined && th.dataset.col !== '') return th.dataset.col;
    const ar = th.querySelector('.ar');
    const txt = th.textContent || '';
    return ar ? txt.replace(ar.textContent || '', '').trim() : txt.trim();
  });
}

// 只看这一个表重画，别把整个「结果」页重刷 —— 免得图、SPSS 那块跟着闪
function repaintTable(id) {
  const wrap = document.querySelector(`.tblwrap[data-tbl="${cssq(id)}"]`);
  if (!wrap) return;
  const tb = wrap.querySelector('tbody');
  const the = wrap.querySelector('thead');
  if (!tb || !the) return;
  const st = tstate(id);
  const rows = Array.prototype.slice.call(tb.rows).map(tr =>
    Array.prototype.map.call(tr.cells, td => cellText(td)));
  if (!rows.length) return;            // 读不出行就别重画，免得把表擦成空的
  // 排序后的顺序在 DOM 里，但 tblBody 是按传进去的顺序画的 —— 所以先排好再画
  const so = S.tblSort[id];
  if (so && so.col >= 0) {
    const dir = so.dir || 1;
    rows.sort((ra, rb) => {
      const a = ra[so.col], b = rb[so.col];
      const an = typeof a === 'number', bn = typeof b === 'number';
      if (an && bn) return (a - b) * dir;
      if (an !== bn) return (an ? -1 : 1) * dir;
      return String(a).localeCompare(String(b), 'zh') * dir;
    });
  }
  const cols = headTexts(the);
  const old = wrap.getAttribute('data-alpha');
  wrap.setAttribute('data-alpha', String(st.alpha));
  if (String(old) !== String(st.alpha)) {
    const cap = wrap.querySelector('.tblcap');
    // 只换里面的内容，别把 .tblcap 这个节点本身换掉 —— 换掉的话整张表包上那层就散了
    if (cap) cap.innerHTML = captionInner(cols, rows, st);
  }
  the.innerHTML = tblHeadRow(cols, st);
  tb.innerHTML = tblBody(rows, cols, st, pColsOf(cols));
}

function cssq(s) { return String(s).replace(/["\\]/g, '\\$&'); }

function sortTable(id, ci) {
  const wrap = document.querySelector(`.tblwrap[data-tbl="${cssq(id)}"]`);
  if (!wrap) return;
  const tb = wrap.querySelector('tbody');
  if (!tb) return;
  const cur = S.tblSort[id] || {};
  let dir = cur.col === ci ? -(cur.dir || 1) : 1;   // 再点一下翻方向
  const rows = Array.prototype.slice.call(tb.rows);
  const keyOf = tr => cellText(tr.cells[ci]);
  rows.sort((ra, rb) => {
    const a = keyOf(ra), b = keyOf(rb);
    const an = typeof a === 'number', bn = typeof b === 'number';
    if (an && bn) return (a - b) * dir;
    if (an !== bn) return (an ? -1 : 1) * dir;      // 数字在前，空/文字垫底
    return String(a).localeCompare(String(b), 'zh') * dir;
  });
  S.tblSort[id] = { col: ci, dir: dir };
  const the = wrap.querySelector('thead');
  if (the) {
    const cols = headTexts(the);
    the.innerHTML = tblHeadRow(cols, tstate(id));
  }
  rows.forEach(tr => tb.appendChild(tr));
}

function setAlpha(id, a) {
  S.tblAlpha[id] = a;
  repaintTable(id);
}

/* 点一次听一辈子的做法：把「听」挂在整张表上，里面怎么重画都不掉。
   之前是每画一次就给每个列头/按钮各挂一次 onclick —— 换完阈值按钮是新节点，
   没人再挂，所以只能改一次（作者就是这么踩到的）。 */
function bindTableTools(scopeSel) {
  const scope = document.querySelector(scopeSel);
  if (!scope) return;
  // 只认「结果表」：带 data-tbl 的才是。SPSS 探测那张小表也是 .tblwrap，
  // 但它不是结果表，给它挂上就是挂了个点了没反应的死处理器。
  scope.querySelectorAll('.tblwrap[data-tbl]').forEach(wrap => {
    wrap.onclick = (ev) => {
      const t = ev.target;
      if (!t || t.nodeType !== 1) return;
      const aid = t.getAttribute('data-tblalpha');
      if (aid) { setAlpha(aid, Number(t.getAttribute('data-a'))); return; }
      const th = t.closest('th[data-sortcol]');
      if (th) sortTable(wrap.dataset.tbl, Number(th.getAttribute('data-sortcol')));
    };
  });
}

/* ---------------- 看表结束 ---------------- */

function renderFiles() {
  const arts = S.state.project.artifacts || [];
  if (!arts.length) return '<div class="empty">项目里还没有产物</div>';

  // 两层：**核心产出**在前（按约定自动分 + 你标的 ⭐），过程产物折叠在后面。
  // 这就是「产物太多」的解法——中间件不删（可复现性靠它们），但默认不占你的眼睛。
  //
  // ⚠ 改成"自动分"的原因（2026-09-24 提的）：
  //   原来只有点过 ⭐ 的才算关键结果，于是一份**必须打开来编辑**的产物
  //   （最典型：`output/编码工作表.csv`，逐段填编码用的）默认沉在过程产物里，
  //   每次都要先展开再找。它不是"重不重要"的问题，是**天生就在流程主干上**。
  //   规则在 `core/report.py: key_reason()`，每条都带一句理由（显示在这里的 title 上）。
  const layers = S.layers;
  if (layers) {
    const row = (a) => {
      const inCore = !!(a.manual || a.auto_why);
      const auto = !a.manual && !!a.auto_why;
      // ⭐ 亮 = 现在就在核心产出里（手动标的 或 按约定自动归的）
      // ⚠ 点它切换的是**手动标记**，不是"从核心产出删掉" —— 自动归的项永远在核心产出里
      //   （想让它下去，得改规则 `core/report.py: key_reason`，不是点 ⭐）。
      //   这两种状态在 title 里说清楚，不然"点了 ⭐ 它还在上面"看着像坏了。
      const tip = a.manual
        ? ('你标的：' + esc(a.note || '关键结果') + '　（点一下取消手动标记'
           + (a.auto_why ? '；但它按约定本来就归核心产出，取消后仍在前面的列表里' : '') + '）')
        : (auto ? ('按约定自动归到核心产出 —— ' + esc(a.auto_why)
                   + '　（点 ⭐ 是"我也标一下"，不会把它从核心产出挪走）')
          : '标成关键结果：它会进报告汇总');
      return `<li data-rel="${esc(a.rel)}"><span>${iconFor(a.rel)}</span>
        <span class="nm">${esc(a.rel)}</span>
        <span class="sz">${fmtSize(a.size)}</span>
        ${auto ? '<span class="autotag" title="' + tip + '">自动</span>' : ''}
        <button class="btn ghost2 verbtn" data-ver="${esc(a.rel)}"
          title="看历史版本、每一轮改了什么">版本</button>
        <button class="btn ghost2 star${inCore ? ' on' : ''}" data-star="${esc(a.rel)}"
          title="${tip}">⭐</button></li>`;
    };
    const key = layers.key || [], other = layers.other || [];
    const nAuto = (layers.auto != null) ? layers.auto : key.filter(a => !a.manual).length;
    return `<div style="margin-bottom:16px">
        <h3 style="font-size:13px;color:#4b5563;margin:0 0 7px">📌 核心产出
          <span style="font-weight:400;color:#9aa3b2">${key.length} 个 ——
            按约定自动归的 ${nAuto} 个（要编辑 / 要过目 / 契约 / 报告正文），
            你自己标了 ${key.length - nAuto} 个；（鼠标停在「自动」上看理由）</span></h3>
        ${key.length ? `<ul class="filelist">${key.map(row).join('')}</ul>`
                     : '<div class="hint">还没有核心产出。点产物右边的 ⭐ 自己标 ——'
                       + '报告汇总只用这些，中间件不往里塞。</div>'}
        <div class="row" style="margin-top:9px">
          <button class="btn primary" id="btnBuildReport">📄 生成报告汇总</button>
          <button class="btn ghost2" id="btnRefreshArts">↻ 刷新产物</button>
        </div>
      </div>
      <div style="margin-bottom:14px">
        <h3 style="font-size:13px;color:#4b5563;margin:0 0 7px;cursor:pointer" id="otherToggle">
          ${S.showOther ? '▾' : '▸'} 过程产物
          <span style="font-weight:400;color:#9aa3b2">${other.length} 个（中间件；可复现性靠它们，默认折叠）</span></h3>
        ${S.showOther ? `<ul class="filelist">${other.map(row).join('')}</ul>` : ''}
      </div>`;
  }

  const byDir = {};
  arts.forEach(a => {
    const d = a.rel.split('/')[0] || '.';
    (byDir[d] = byDir[d] || []).push(a);
  });
  return Object.keys(byDir).map(d => `
    <div style="margin-bottom:14px">
      <h3 style="font-size:13px;color:#4b5563;margin:0 0 7px">📁 ${esc(d)}/</h3>
      <ul class="filelist">${byDir[d].map(a =>
        `<li data-rel="${esc(a.rel)}"><span>${iconFor(a.rel)}</span>
         <span class="nm">${esc(a.rel.split('/').slice(1).join('/'))}</span>
         <span class="sz">${fmtSize(a.size)}</span>
         <button class="btn ghost2 verbtn" data-ver="${esc(a.rel)}"
           title="看这份文件的历史版本，以及每一轮改了什么">版本</button></li>`).join('')}</ul>
    </div>`).join('');
}

function iconFor(rel) {
  const e = (rel.split('.').pop() || '').toLowerCase();
  if (['png', 'jpg', 'jpeg', 'webp', 'gif', 'svg'].indexOf(e) >= 0) return '🖼';
  if (e === 'md') return '📄';
  if (e === 'csv' || e === 'xlsx' || e === 'sav') return '📊';
  if (e === 'sps') return '⚙';
  if (e === 'py') return '🐍';
  return '📎';
}

function renderLogs() {
  if (!S.logs.length) return '<div class="empty">还没有日志</div>';
  return '<div id="logBox">' + S.logs.map(l =>
    `<div class="logline ${esc(l.level || 'info')}"><span class="t">${esc(l.t)}s</span>${esc(l.msg)}</div>`).join('') + '</div>';
}

/* ---------------- 交互 ---------------- */

/* 「一键带上」：把 block 声明里的 prefill_texts[text] 追加到 target 字段。
   ⚠ 只追加、不覆盖 —— 研究员自己写的东西一个字都不能动。
   已经带过就不重复带（免得连点两下变成两份）。 */
function applyPrefill(b, prefill) {
  const key = prefill && prefill.target;
  const text = prefill && prefill.text;
  if (!key || !text) return false;
  // 目标字段必须在声明里真的存在 —— 否则会凭空往表单数据里塞一个界面上没有的键，
  // 看着"带上成功了"，其实那句话掉进了一个看不见的地方。
  if (!(b.form || []).some(f => f.key === key)) return false;
  const dict = b.prefill_texts || {};
  const add = dict[text];
  if (!add) return false;
  const vals = S.form[b.id] || (S.form[b.id] = {});
  const cur = String(vals[key] === undefined ? '' : vals[key]);
  if (cur.indexOf(add) >= 0) return false;                 // 已经带过了
  vals[key] = cur.trim() ? (cur.replace(/\s+$/, '') + '\n\n' + add) : add;
  saveForm(b);
  renderStage();
  return true;
}

/* 「从简报填回表单」：简报里各小节的原文 → 补进表单里**空着的**字段。
   ⚠ 只补空的，不覆盖你已经改过的 —— 和读回表单内容是同一条规矩。
   起因：导入一个旧快照之后，变量表有内容（它从简报读）、别的文本框全空，
   而简报里明明写着背景、目的、4 条 RQ、人群 —— 却没有任何入口把它们读回来。 */
async function pullFormFromBrief(b) {
  if (!b || !curProject()) return;
  const rel = (S.form[b.id] || {}).brief || 'contracts/research_brief.md';
  setStatus('正在读 ' + rel + ' 的各小节…');
  const j = await api('/api/brief/sections?rel=' + encodeURIComponent(rel) +
    '&project=' + encodeURIComponent(S.state.project.root));
  if (!j.ok) { setStatus('读不回来：' + j.error); return; }
  if (!j.exists) { setStatus('没找到 ' + rel + '（先把 ⓪ 跑出来）'); return; }
  const secs = j.sections || {};
  const vals = S.form[b.id] || (S.form[b.id] = {});
  const filled = [], skipped = [];
  Object.keys(secs).forEach(k => {
    const v = secs[k];
    if (!v) return;                                   // 简报里这节本来就是空的
    const fld = (b.form || []).filter(f => f.key === k)[0];
    if (!fld) return;                                 // 表单里没这个字段，跳过
    if (fld.type === 'vartable') return;              // 变量表有自己的「读回」按钮
    const now = vals[k];
    if (now !== undefined && String(now).trim() !== '') { skipped.push(k); return; }
    vals[k] = v;
    filled.push(fld.label || k);
  });
  saveForm(b);
  renderStage();
  if (!filled.length && !skipped.length) {
    setStatus('简报里没有可读的小节内容（可能还没跑过 ⓪）');
  } else if (!filled.length) {
    setStatus('这些栏你已经填过了，没有覆盖：' + skipped.join('、'));
  } else {
    setStatus('已填回：' + filled.join('、') +
      (skipped.length ? '（' + skipped.join('、') + ' 你已经填过，没动）' : ''));
  }
}

/* 提醒里的「选项 + 自定义填写」。
   每条提醒可以带 options：每个选项就是**一行自定义替换规则**（`原文 = 替换为`）。
   点一下 → 并进 🔒 的「自定义替换」框 → 再点运行就生效。

   为什么这么做（研究员提的）：「在提示处增加选项与自定义填写（要求用户按规定格式输出，
   必须带有 =），然后把用户的填写或选择直接转到自定义替换」——
   把"你得会写规则"降到"点一下"。 */
function alertOptionsHtml(a) {
  const opts = (a && a.options) || [];
  // ⚠ 那套"写替换规则"的输入框**只有当这条提醒真的能填进某个字段时才摆** ——
  //   靠组块声明里的 `rules_field` 判断（runner 会把它写进每条 alert）。
  //   踩过：原来是无条件渲染的，于是 ③ 弹出一条「你勾了筛选题，但一道都没生成」的提醒，
  //   底下却跟着 `原文 = 换成什么（空 = 删掉）` + 「加进自定义替换」——
  //   那是 🔒 去标识化的填法，跟"筛选题怎么写"半点关系没有（实测报的，说"内容明显与之无关"）。
  const canFill = !!(a && a.rules_field);
  const picks = (opts || []).map(o => (o.line || o.src)
    ? `<button class="btn ghost2 tiny aopt" data-rule="${esc(o.line || '')}"
         data-src="${esc(o.src || '')}" data-dst="${esc(o.dst || '')}"
         title="${esc(o.hint || '')}">＋ ${esc(o.label)}</button>`
    : `<span class="hint" style="font-size:11.5px">${esc(o.label)}：${esc(o.hint || '')}</span>`
  ).join('');
  if (!canFill && !picks) return '';
  // 只剩"可点的选项"、没有可填的字段时，就别摆那两个输入框了
  const box = canFill
    ? `<input type="text" class="aopt-src" data-rulesrc="1" placeholder="原文（要换掉的那段，可手填）">
       <span class="aopt-eq">=</span>
       <input type="text" class="aopt-in" data-rulein="1" placeholder="换成什么（空 = 删掉）">
       <button class="btn ghost2 tiny" data-ruleadd="1">加进「自定义替换」</button>`
    : '';
  return `<div class="aopts">${box}${picks}
    <span class="aopt-msg hint" style="font-size:11.5px"></span>
  </div>`;
}

// 「自定义替换」并入一条规则之后，把这句话**留在原地**。
// ⚠ 研究员报的：「点击选项后的已选择提醒消失跑到上面去了，会不方便用户确认」——
//   原来那句话写在状态栏（页面最底下），而重画表单时提示就没了，
//   于是点完选项的人**根本来不及确认自己选了什么**。
// ⚠ 他后来又补了一句更要紧的：「**我还是希望你把哪个问题已选择的绿字加到对应问题的框里，
//   而不是全部塞下面**」——对，绿字要长在**那条提醒自己的框**里，不然他得自己找是哪一条。
//   所以按 `sig` 分开存：每条提醒记自己那条回执，重画之后还在它自己的框里。
function rememberRuleMsg(box, text, bad, sig) {
  if (sig) {
    S.ruleMsgs = S.ruleMsgs || {};
    S.ruleMsgs[sig] = { text: text, bad: !!bad };
  }
  S.ruleMsg = { text: text, bad: !!bad };
  const el = box ? box.querySelector('.aopt-msg') : null;
  if (el) {
    el.textContent = text;
    el.style.color = bad ? '#b91c1c' : '#15803d';
  }
  // 让这句话在 DOM 里就是"这一条的回执"，重画时由 renderResult 按 sig 复原
  if (box && box.classList && box.classList.contains('alertbox')) {
    box.dataset.msg = text;
    box.dataset.msgbad = bad ? '1' : '';
  }
}

// 某条提醒自己的回执（点击选项后写下的那句）
function alertMsgOf(sig) {
  const m = (S.ruleMsgs || {})[sig];
  return (m && m.text) ? m : null;
}

// 把一行规则并进「自定义替换」。
// `src`/`dst` 分开传（界面就是这么收集的）；也可以直接给一整行 `原文 = 替换为`。
// **右边留空 = 把这段原文删掉**（清前缀用，比如 `QQ 13177778888` 去掉 `QQ `）。
function addCustomRule(srcOrLine, dst, msgEl, sig) {
  const b = (S.state.blocks || []).filter(x => x.id === 'b9_deident')[0];
  // 回执要写进**那条提醒自己的框**里（研究员的要求），所以得知道是哪一条；
  // `msgEl` 就是那个框里的 `.aopt-msg`，从它往上找 alertbox。
  const boxOf = () => {
    let el = msgEl;
    while (el) {
      if (el.classList && el.classList.contains('alertbox')) return el;
      el = el.parentNode;
    }
    return null;
  };
  const say = (t, bad) => {
    rememberRuleMsg(boxOf(), t, bad, sig);
    if (msgEl) { msgEl.textContent = t; msgEl.style.color = bad ? '#b91c1c' : '#15803d'; }
    else setStatus(t);
  };
  if (!b) { say('找不到 🔒 那个组块', true); return false; }
  // ⚠ 要分清「两个框分开填的」和「一整行给的」：
  //   分开填时右边空 = 故意要把这段删掉（合法）；
  //   一整行给的时候**没有 `=`** 才是格式写错了（研究员写了一条、跑完没生效还找不到原因，
  //   那种最难查，所以必须当场拦）。
  const fromFields = (dst !== undefined && dst !== null);
  let src = String(srcOrLine || '').trim();
  let to = fromFields ? String(dst).trim() : '';
  if (!src && to) { say('左边「原文」是空的 —— 先点上面的选项，或者手填要换掉的那个词', true); return false; }
  if (!src) { say('先写一条，或者点上面的选项', true); return false; }
  // 兼容「整行给过来」的写法
  if (!fromFields) {
    // ⚠ `!` 开头的**指令行**没有 `=` 也是合法的：
    //   `!这是手机 131...`（某一格是手机）、`!第3段是手机`（整段是手机）、`!不用管 X`。
    //   上一版一律要求有 `=`，于是「第 3 段是手机」这类选项点下去会被当场拦下 ——
    //   而研究员要的恰恰就是它（「每一行原文都不一样我怎么填呢，也没有选项告诉我她是手机」）。
    if (src.charAt(0) === '!') {
      to = '';
    } else if (src.indexOf('=') < 0) {
      say('少了个 `=` —— 写成「原文 = 换成什么」（右边留空就是删掉这段）', true);
      return false;
    } else {
      const parts = src.split('=');
      src = parts[0].trim();
      to = parts.slice(1).join('=').trim();
    }
    if (!src) { say('= 左边不能空（那是我要换掉的东西）', true); return false; }
  }
  // ⚠ 「同一条原文」判定要把 `!` 指令也认进去：`!这是手机 131... = ` 和 `131... = `
  //   是两条不同的规则（一条是"按我的判断处理"、一条是"直接换掉"），不能互相覆盖。
  const sameKey = x => x.split('=')[0].trim() === src;
  // 指令行**原样存**（不加 `=`）；普通替换规则才拼 `原文 = 替换为`
  const line = isDirectiveRule(src) ? src : (src + ' = ' + to);
  const vals = S.form[b.id] || (S.form[b.id] = {});
  const cur = String(vals.extra_rules || '');
  // 同一条原文只留一条规则（换一条 = 覆盖旧的），否则后面那条永远不生效
  const kept = cur.split('\n').map(x => x.trim()).filter(Boolean).filter(x => !sameKey(x));
  kept.push(line);
  vals.extra_rules = kept.join('\n');
  saveForm(b);
  // 说人话：指令是"判断"，普通替换才是"改字"——别把两种混在一句话里
  const tail = isDirectiveRule(src)
    ? '（这是**判断**不是替换规则：按你说的处理，程序照办）　→ 点「用 Python 跑」生效'
    : (to ? '　→ 点「用 Python 跑」生效' : '（右边空 = 把这段删掉）　→ 点「用 Python 跑」生效');
  say('已加进「自定义替换」：' + line + tail
      + '（想改/想删，在下面 🔒 的「自定义替换」框里改）', false);
  // ⚠ **不要**在这里 `renderStage()`：那会把整块表单连**提醒框**一起重建，
  //   刚写进框里的那句绿字就跟着没了（研究员两次说"绿字消失"，就是这个机制）。
  //   只把「自定义替换」下面那块逐行自检就地刷新一下就够了 —— 它才是需要更新的东西。
  updateRuleCheck();
  return true;
}

// 就地刷新「自定义替换」框下面的自检提示（不重建表单、不动提醒框里的回执）。
function updateRuleCheck() {
  const t = document.querySelector('#stage textarea[data-k="extra_rules"]');
  if (!t || !t.parentNode) return;
  const wrap = t.parentNode.querySelector('[data-rulecheck]');
  if (!wrap) return;
  const raw = (S.form['b9_deident'] || {}).extra_rules;
  wrap.innerHTML = ruleCheckHtml(raw === undefined ? t.value : raw);
}

// 判定一条规则**是不是 `!` 指令**（`!这是手机 X` / `!第3段是手机` / `!不用管 X`）。
// ⚠ 这三类指令**没有 `=`**，是不合法的"替换规则"，但完全合法的"判断"。
//   踩过（研究员报的）：`addCustomRule` 一律拼 `src + ' = ' + to` ——
//   指令被存成 `!这是手机 X = `，多出来的那个 `=` 让工程师那边**匹配不上**，于是
//   "选了没效果"。所以指令必须**原样存**，一个字符都不加。
function isDirectiveRule(line) {
  return String(line || '').trim().charAt(0) === '!';
}

// 逐行检查「自定义替换」框里的东西 —— 哪条认得出、哪条不认得、哪条是普通替换。
// 研究员要的就是这个：他连点了几个选项、跑完却看不出哪条起了作用，
// 最后只能得出"我选了没效果"（他真踩了，而且查了很久）。
// 这里把判定摆出来，**看见**就不用猜了。
function ruleCheckHtml(text) {
  const lines = String(text || '').split('\n').map(x => x.trim()).filter(Boolean);
  if (!lines.length) return '';
  const out = [];
  for (const ln of lines) {
    let ok = true, why = '';
    if (isDirectiveRule(ln)) {
      const body = ln.replace(/^!\s*/, '').replace(/\s*=\s*$/, '').trim();
      if (/^第\s*\d+\s*段\s*(?:是|为)\s*\S+$/.test(body)) {
        why = '段位判断（整列照办）';
      } else if (/^第\s*\d+\s*段\s*(?:不用管|不是标识符|别管)$/.test(body)) {
        why = '段位判断（这一列不动）';
      } else if (/^这是(手机号?|QQ|qq|微信号?|微信|邮箱|学号)\s+\S+$/.test(body)) {
        why = '单个值判断';
      } else if (/^(不用管|不管|保留)\s+\S+$/.test(body)) {
        why = '单个值——原样留着';
      } else {
        ok = false;
        why = '这条指令看不懂，跑的时候会被跳过';
      }
    } else if (ln.indexOf('=') >= 0) {
      const a = ln.split('=')[0].trim();
      ok = !!a;
      why = ok ? '普通替换' : '等号左边是空的';
    } else {
      ok = false;
      why = '既不是指令、也没有等号';
    }
    out.push(`<div class="rulechk ${ok ? 'good' : 'bad'}">${ok ? '✓' : '✗'} `
      + `<code>${esc(ln)}</code> <span>${esc(why)}</span></div>`);
  }
  const bad = out.filter(x => x.indexOf('class="rulechk bad"') >= 0).length;
  return `<div class="rulechks">${out.join('')}`
    + (bad ? `<div class="rulechk bad">有 ${bad} 条**不会生效** —— 照上面的提示改一下，或者删掉它</div>`
           : '') + `</div>`;
}

function bindAlertOptions() {
  const stage = document.getElementById('stage');
  if (!stage) return;
  stage.querySelectorAll('[data-rule]').forEach(el => {
    el.onclick = () => {
      const box = el.parentNode;
      const msg = box ? box.querySelector('.aopt-msg') : null;
      // ⚠ 选项**直接落进「自定义替换」框**，不再"先塞进两个输入框、再让你点加进"。
      //   研究员的话：「选项和我想的不一样……有点割裂」「我自定义填写之后输出没效果」——
      //   点一下就能跑出结果，才是选项该有的样子；两个输入框留给"我要换的词不在选项里"。
      //   落进去之后它在 🔒 的框里看得见、改得动、删得掉（不是背着他偷偷写规则）。
      const line = el.dataset.rule || ((el.dataset.src || '') + ' = ' + (el.dataset.dst || ''));
      // 这条提醒的标识 —— 回执要按它归位到**这一条**的框里
      const abox = el.closest ? el.closest('.alertbox') : null;
      addCustomRule(line, undefined, msg, (abox && abox.dataset.sig) || '');
    };
  });
  stage.querySelectorAll('[data-ruleadd]').forEach(el => {
    el.onclick = () => {
      const box = el.parentNode;
      const srcIn = box ? box.querySelector('.aopt-src') : null;
      const dstIn = box ? box.querySelector('.aopt-in') : null;
      const msg = box ? box.querySelector('.aopt-msg') : null;
      if (addCustomRule(srcIn ? srcIn.value : '', dstIn ? dstIn.value : '', msg)) {
        if (srcIn) srcIn.value = '';
        if (dstIn) dstIn.value = '';
      }
    };
  });
}

function bindStage() {
  // 空栏上的两个按钮（没选项目时主区只有这两条路）
  const npNew = $('#npNew'), npOpen = $('#npOpen');
  if (npNew) npNew.onclick = () => $('#btnNewProj').click();
  if (npOpen) npOpen.onclick = () => $('#btnOpenProj').click();
  // 输入
  $('#stage').querySelectorAll('[data-k]').forEach(el => {
    const k = el.dataset.k;
    const b = currentBlock();
    const set = (v) => { (S.form[b.id] = S.form[b.id] || {})[k] = v; saveForm(b); };
    if (el.classList.contains('check')) {
      el.onclick = (ev) => {
        ev.preventDefault();
        const v = el.dataset.v;
        const arr = (S.form[b.id] && S.form[b.id][k]) || [];
        const idx = arr.indexOf(v);
        if (idx >= 0) arr.splice(idx, 1); else arr.push(v);
        set(arr.slice());
        el.classList.toggle('on');
        el.querySelector('input').checked = arr.indexOf(v) >= 0;
        // 勾选框可以声明「勾上要带什么文本」（比如伦理条款一键带上）。
        // 声明式：字段自己写 prefill={target,text}，这里只管照做。
        const f = (b.form || []).filter(x => x.key === k)[0] || {};
        if (f.prefill) {
          if (idx < 0) applyPrefill(b, f.prefill);
          else setStatus('已勾上「' + (f.label || k) + '」—— 相关条款带进了「' +
            ((b.form || []).filter(x => x.key === f.prefill.target)[0] || {}).label +
            '」，可以改也可以删');
        }
      };
    } else if (el.tagName === 'SELECT') {
      el.onchange = () => set(el.value);
    } else if (k === 'file') {
      el.onchange = () => { set(el.value); renderStage(); };   // 换了文件要重新列变量
    } else {
      el.oninput = () => {
        set(el.value);
        // 「自定义替换」边打字边自检：哪条认得出、哪条不认得，当场标出来
        if (k === 'extra_rules') {
          const wrap = el.parentNode
            ? el.parentNode.querySelector('[data-rulecheck]') : null;
          if (wrap) wrap.innerHTML = ruleCheckHtml(el.value);
        }
      };
    }
  });
  // 变量表：加行/删行/读回/单元格编辑
  bindVarTable();

  // 📁 打开文件夹选文件（选到项目外面的会先拷进来）
  $('#stage').querySelectorAll('[data-browse]').forEach(el => {
    el.onclick = async () => {
      const k = el.dataset.browse;
      const b = currentBlock();
      const fld = (b.form || []).find(x => x.key === k) || {};
      const rel = await pickFileFor(k, fld.label, fld.accept);
      if (rel === null) return;
      (S.form[b.id] = S.form[b.id] || {})[k] = rel;
      saveForm(b);
      renderStage();
    };
  });

  // 从项目里挑文件
  $('#stage').querySelectorAll('[data-pick]').forEach(el => {
    el.onchange = () => {
      if (!el.value) return;
      const k = el.dataset.pick;
      const b = currentBlock();
      (S.form[b.id] = S.form[b.id] || {})[k] = el.value;
      saveForm(b);
      const input = $('#stage').querySelector(`input[data-k="${k}"]`);
      if (input) input.value = el.value;
      renderStage();
    };
  });
  // tabs
  $('#stage').querySelectorAll('[data-tab]').forEach(el => {
    el.onclick = () => { S.tab = el.dataset.tab; renderStage(); };
  });
  // 产物点击
  $('#stage').querySelectorAll('.filelist li').forEach(el => {
    el.onclick = (ev) => {
      if (ev.target && ev.target.dataset && ev.target.dataset.ver) return;   // 点的是「版本」按钮
      openArtifact(el.dataset.rel);
    };
  });
  // 「版本」按钮：看历史 + 对比
  $('#stage').querySelectorAll('[data-ver]').forEach(el => {
    el.onclick = (ev) => { ev.stopPropagation(); openVersions(el.dataset.ver); };
  });
  // ⭐ 标成关键结果（研究员自己标，程序不猜）
  $('#stage').querySelectorAll('[data-star]').forEach(el => {
    el.onclick = async (ev) => {
      ev.stopPropagation();
      const rel = el.dataset.star;
      const on = !el.classList.contains('on');
      let note = '';
      if (on) note = prompt('为什么它是关键结果？（可留空，会写进报告）', '') || '';
      const r = await post('/api/report/flag', { rel: rel, on: on, note: note });
      if (!r.ok) { alert(r.error || '标不上'); return; }
      setStatus(on ? ('已标关键结果（共 ' + r.count + ' 个）') : '已取消标记');
      loadLayers();
    };
  });
  const oth = $('#otherToggle');
  if (oth) oth.onclick = () => { S.showOther = !S.showOther; renderStage(); };
  // 卡片上的「打开 xxx」按钮
  $('#stage').querySelectorAll('[data-open-art]').forEach(el => {
    el.onclick = () => openArtifact(el.dataset.openArt);
  });
  const br = $('#btnBuildReport');
  if (br) br.onclick = async () => {
    br.disabled = true; br.textContent = '正在串…';
    const r = await post('/api/report/build', { title: (S.state.project.meta || {}).name || '' });
    br.disabled = false; br.textContent = '📄 生成报告汇总';
    if (!r.ok) { alert(r.error || '生成失败'); return; }
    setStatus('汇总已生成 → ' + r.rel);
    await loadState();
    loadLayers();
    openArtifact(r.rel);
  };
  const rf = $('#btnRefreshArts');
  if (rf) rf.onclick = () => { loadLayers(); };

  // 待确认项：打开右侧栏
  const bc = $('#btnConf');
  if (bc) bc.onclick = openConfirm;
  // 从简报填回表单（只补空着的）
  const bp = $('#btnPullForm');
  if (bp) bp.onclick = () => pullFormFromBrief(currentBlock());

  // 看表：点列头排序、改显著性阈值
  bindTableTools('#stage');

  // 检查点的选项按钮
  $('#stage').querySelectorAll('[data-answer]').forEach(el => {
    el.onclick = () => answerCheckpoint(el.dataset.answer);
  });

  // 结果里嵌的 SPSS 输出，点标题旁的链接去产物里打开
  $('#stage').querySelectorAll('[data-open-rel]').forEach(el => {
    el.onclick = (ev) => { ev.preventDefault(); openArtifact(el.dataset.openRel); };
  });
  // 「📍 看原文第 N 行」：直接翻到原文档对应位置。
  // 研究员提的：「自己翻原文档一行行找太要命了」—— 所以不在浏览器里搜，而是打开带行号的视图。
  $('#stage').querySelectorAll('[data-goto-file]').forEach(el => {
    el.onclick = (ev) => {
      ev.preventDefault();
      openArtifact(el.dataset.gotoFile, Number(el.dataset.gotoLine || 1));
    };
  });
  // 「🙈 这条不用再问」：记进项目里，下次跑完不再显示这条提醒。
  // 研究员提的：「为了防止…这种复杂情况，最好加一个选项来跳过或者无视这一提醒」——
  // 有些提醒（比如「没被认出来的词」把一批杂七杂八的东西混在一起）根本没有逐条回答的办法，
  // 那就得允许他说"这条我看过了，别再显示"。
  $('#stage').querySelectorAll('[data-mute]').forEach(el => {
    el.onclick = async (ev) => {
      ev.preventDefault();
      const sig = el.dataset.mute;
      const p = curProject();
      const r = await post('/api/alerts/ignore',
                           { sig: sig, project: (p && p.root) || undefined });
      if (!r.ok) { setStatus(r.error || '记不下来'); return; }
      S.ignoredAlerts = r.ignored || [];
      const box = el.closest ? el.closest('.alertbox') : null;
      if (box && box.parentNode) box.parentNode.removeChild(box);
      setStatus('这条提醒不再显示（想让它回来：删掉项目里 忽略的提醒.json 里那一行）');
    };
  });

  // 「用 SPSS 打开这份语法」——把 .sps 交给 SPSS 的界面
  $('#stage').querySelectorAll('[data-spss-open]').forEach(el => {
    el.onclick = async (ev) => {
      ev.preventDefault();
      setStatus('正在把语法交给 SPSS…');
      const j = await post('/api/spss/open', { rel: el.dataset.spssOpen });
      setStatus(j.ok ? 'SPSS 应该打开了（没反应就看一眼任务栏）' : ('打不开：' + j.error));
      if (!j.ok) alert('打不开 SPSS：\n\n' + j.error);
    };
  });

  // 🔗 等 SPSS 的输出：SPSS 在界面里跑完后，把导出的 HTML 收回来显示
  const wait = $('#spssWait');
  if (wait) startSpssWatch(wait);

  // 「回到这一步之前」：回退重跑
  $('#stage').querySelectorAll('[data-rewind]').forEach(el => {
    el.onclick = () => rewindTo(parseInt(el.dataset.rewind, 10));
  });

  const run = $('#btnRun');
  // ⚠ 别写成 run.onclick = runBlock —— 那样点击事件对象会当成 confirmed 传进去（真值），
  //   守卫会被当成「已确认」静默跳过。踩过：界面看着有关卡，其实每次都在放行。
  if (run) run.onclick = () => runBlock();
  const stop = $('#btnStop');
  if (stop) stop.onclick = async () => {
    await post('/api/job/cancel', { id: S.jobId });
    setStatus('已请求停止…');
  };
  const llm = $('#btnLlm');
  if (llm) llm.onclick = askModel;
}

function collectForm(b) {
  const vals = S.form[b.id] || {};
  const out = {};
  (b.form || []).forEach(f => {
    let v = vals[f.key];
    if (v === undefined) v = f.default !== undefined ? f.default : (f.type === 'checks' ? [] : '');
    if (f.type === 'vartable') {
      // 界面存的是逐行数组；引擎那边既给文本（老路径，解析器认），也给结构化（新路径）。
      // 序列化格式和以前那个 textarea 完全一样，所以 parse_var_table / parse_brief 一行都不用改。
      // 空行（还没填的那一行）不算变量。
      const rows = varRowsFilled(v);
      out[f.key] = rows.map(r => r.join(', ')).join('\n');
      out[f.key + '_rows'] = rows;
      return;
    }
    out[f.key] = v;
  });
  return out;
}

/* ---------------- 跑任务 ---------------- */

// 必填的结构化字段空着时：**把后果说清楚，然后让他自己选**，不是拦住他。
// 这一栏（变量表）重要到完全影响后续：③ 出题、④ 预处理、⑤ 选统计方法都靠它。
// 但工作台的规矩是「提醒不能变成拦路」，所以给三条路，选哪条都照跑。
function requiredEmptyCheck(b) {
  const bad = [];
  (b.form || []).forEach(f => {
    if (!f.required) return;
    if (f.type === 'vartable') {
      const rows = varRowsFilled((S.form[b.id] || {})[f.key] || []);
      if (!rows.length) bad.push({ f: f, kind: 'vartable' });
    }
  });
  return bad;
}

function askFillVariables(b, bad, runBlockFn) {
  const f = bad[0].f;
  const hasModel = S.state.config && S.state.config.llm_status &&
                   S.state.config.llm_status.ok;
  const conseq = b.id === 'b0_brief'
    ? '这一栏空着，后面处处受影响：**③ 会出一份「0 道题」的空壳问卷**，'
      + '④ 不知道该预处理哪些列，⑤ 没法判断该用哪个统计方法。'
    : '这一栏空着，③ 就只会出一份「0 道题」的空壳问卷 —— 题干、选项都无从谈起。';
  showModal(`<h3>「${esc(f.label || '变量表')}」还空着</h3>
    <div class="hint" style="line-height:1.85">${conseq}</div>
    <div class="hint" style="margin-top:8px">怎么填这一栏（每条变量一行，四列）：
      变量名 · 角色（自变量/因变量/中介/调节/控制） · 测量层次（定类/定序/定距/定比） · 怎么测</div>
    <div class="hint" style="margin-top:8px">**三条路随你选**——工作台不替你决定，也不会因为这一栏空着不让你跑：</div>
    <div class="actions" style="margin-top:12px; flex-wrap:wrap; gap:8px">
      <button class="btn" id="rfManual">✍ 我自己填（打开这张表）</button>
      ${hasModel ? `<button class="btn ghost2" id="rfModel"
        title="让模型按你的背景/RQ 起草一版，**回来必须逐行核**">🤖 让模型起草一版</button>` : ''}
      <button class="btn ghost2" id="rfAnyway">就是先不填，照跑（我知道后果）</button>
      <span class="grow"></span>
      <button class="btn ghost2" onclick="closeModal()">取消</button>
    </div>
    ${hasModel ? '' : `<div class="hint" style="margin-top:8px">模型没接上（或没开），所以只有自己填这一条路。</div>`}`);
  const m = $('#rfManual');
  if (m) m.onclick = () => {
    closeModal();
    const el = document.querySelector(`[data-vt="${b.id}|${f.key}"]`);
    if (el) { el.scrollIntoView({ block: 'center' }); el.classList.add('flash'); setTimeout(() => el.classList.remove('flash'), 1600); }
    setStatus('在下面这张表里逐行填；填完再点「用 Python 跑」');
  };
  const mm = $('#rfModel');
  if (mm) mm.onclick = async () => {
    closeModal();
    // 走「让模型建议」的老路（同一个接口、同一套「待确认」标记），
    // 只是把注意力指到变量表上：模型照样按小节输出，回来我们只取这一栏填进表。
    setStatus('让模型起草变量表…（半分钟到两分钟）');
    await askModel(f.key);
  };
  const aw = $('#rfAnyway');
  if (aw) aw.onclick = () => { closeModal(); runBlockFn(true); };
}

async function runBlock(confirmed) {
  const b = currentBlock();
  if (!b) return;
  // 只认严格的 true：传进来个事件对象、字符串、1 都不算「我确认过了」
  const ack = (confirmed === true);
  // 必填的结构化字段空着 → 先说清后果 + 给三条路；说「就是先不填」就照跑。
  if (!ack) {
    const bad = requiredEmptyCheck(b);
    if (bad.length) { askFillVariables(b, bad, runBlock); return; }
  }
  const params = collectForm(b);
  S.logs = []; S.logCount = 0; S.result = null; S.tab = 'log';
  S.steps = []; S.stepCount = 0; S.pending = null; S.answers = [];
  S.running = true; S.job = null; S.jobId = null;   // 上一次的任务号不能留着冒充这一次
  renderStage();
  setStatus('正在起引擎…');
  const j = await post('/api/run', {
    block_id: b.id,
    params: params,
    project: S.state.project.root,
    confirmed_sensitive: ack,
  });
  if (j.need_guard) {                 // 素材里有没脱敏的直接标识符：先摆出来
    S.running = false;
    renderStage();
    setStatus('⏸ 先看一眼素材：有 ' + ((j.guard || {}).total || 0) + ' 份还没过 🔒');
    showSensitiveGuard(b, j.guard, params);
    return;
  }
  if (!j.ok) {
    S.running = false;
    S.result = { error: j.error };
    S.tab = 'result';
    renderStage();
    setStatus('起不来：' + j.error);
    return;
  }
  S.jobId = j.job_id;
  pollJob();
}

/* 素材入口守卫：把「哪几份素材没脱敏、里面命中了什么」摆到台面上。
   不是硬拦 —— 研究员点「我知道，继续」就往下跑，那一句确认会落进项目目录。 */
function showSensitiveGuard(block, g, params) {
  const mats = g.materials || [];
  const rows = mats.map(m => {
    const hits = (m.hits || []).map(h =>
      `<span class="gk">${esc(h.label)}×${h.count}</span>`).join('');
    const sample = (m.hits || []).map(h => h.sample).filter(Boolean).join('　');
    return `<div class="gmat">
      <div class="gtop"><b>${esc(m.rel)}</b><span class="gsz">${fmtSize(m.size || 0)}</span></div>
      <div class="ghits">${hits}</div>
      ${sample ? `<div class="gsample">例如：${esc(sample)}</div>` : ''}
    </div>`;
  }).join('');
  showModal(`<h3>🔒 这些素材还没过脱敏</h3>
    <p>${esc(g.why || '')}</p>
    <div class="glist">${rows}</div>
    <div class="field"><input type="text" id="gNote"
      placeholder="确认理由（可选，会写进项目目录）：比如「这批是模拟数据」"></div>
    <div class="hint">点「我知道，继续」会在项目里留下一条确认记录
      （<code>${esc('output/去标识化_确认.json')}</code>）——研究过程里查得到你当时知道这件事。
      已经处理过的素材不会再问你。</div>
    <div class="actions">
      <button class="btn ghost2" onclick="closeModal()">先去处理</button>
      <span class="grow"></span>
      <button class="btn primary" id="gGo">我知道，继续跑「${esc(block.title || block.name)}」</button>
    </div>`);
  const go = $('#gGo');
  if (go) go.onclick = async () => {
    const note = ($('#gNote') || {}).value || '';
    const a = await post('/api/deident/ack', {
      block_id: block.id, rels: mats.map(m => m.rel), note: note,
    });
    closeModal();
    if (!a.ok) { alert('确认没记下来：' + (a.error || '未知原因')); return; }
    setStatus('已记下这次确认 → ' + (a.file || ''));
    runBlock(true);
  };
}

async function pollJob() {
  const j = await api('/api/job?id=' + encodeURIComponent(S.jobId) +
    '&since=' + S.logCount + '&steps_since=' + S.stepCount);
  if (!j.ok) { S.running = false; renderStage(); setStatus('任务查询失败：' + j.error); return; }
  const job = j.job;
  if (job.logs && job.logs.length) {
    S.logs = S.logs.concat(job.logs);
    S.logCount = job.log_count;
  }
  const gotStep = !!(job.steps && job.steps.length);
  if (gotStep) {
    S.steps = S.steps.concat(job.steps);
    S.stepCount = job.step_count;
  }
  S.job = job;
  S.answers = job.answers || [];

  // ---- 停在检查点：等研究员拍板 ----
  if (job.status === 'waiting') {
    S.pending = job.pending;
    renderStage();
    setStatus('⏸ 停下来等你决定');
    $('#statusJob').textContent = '⏸ ' + ((job.pending || {}).title || '');
    return;                     // 不再轮询，点了按钮才继续
  }

  if (gotStep) renderStage();
  setStatus('运行中… ' + job.elapsed + 's');
  $('#statusJob').textContent = job.block_id + ' · ' + job.elapsed + 's';
  if (S.tab === 'log') {
    const box = $('#logBox');
    if (box) { box.innerHTML = renderLogs().replace(/^<div id="logBox">|<\/div>$/g, ''); box.scrollTop = box.scrollHeight; }
    const tabEl = document.querySelector('[data-tab="log"]');
    if (tabEl) tabEl.textContent = '日志 ' + S.logs.length;
  }

  if (job.status === 'running') {
    setTimeout(pollJob, 600);
  } else {
    S.running = false;
    S.pending = null;
    S.result = job.result || {};
    if (job.status === 'error' && !S.result.error) S.result.error = job.error;
    if (job.status === 'done' && !S.result.summary) S.result.summary = '跑完了（' + job.elapsed + 's）';
    S.tab = 'result';
    renderStage();
    if (job.status === 'error') {
      setStatus('出错了 · 看日志');
    } else if ((S.result || {}).stopped) {
      setStatus('已停下 · 按你的决定，没有往下算');
    } else {
      const w = job.wait_seconds ? '（另有 ' + job.wait_seconds + 's 在等你决定）' : '';
      setStatus('完成 · ' + job.elapsed + 's' + w);
    }
    refreshProject();
  }
}

/* ---- 检查点：研究员拍板 ---- */
async function answerCheckpoint(choice) {
  const j = await post('/api/job/answer', { id: S.jobId, choice });
  if (!j.ok) { alert(j.error || '回答失败'); return; }
  S.pending = null;
  renderStage();
  setStatus('已回复，继续跑…');
  pollJob();
}

/* ---- ↩ 回退：重跑到某个检查点之前，重新拍板 ---- */
async function rewindTo(upto) {
  if (!S.jobId) return;
  const a = (S.answers || [])[upto];
  const label = a ? (a.title || a.label) : ('第 ' + (upto + 1) + ' 个检查点');
  if (!confirm('回到这一步之前？\n\n' +
      '· 当前这次运行会被中止\n' +
      '· 用同样的参数重跑一遍，前面 ' + upto + ' 个决定照原样自动回放\n' +
      '· 跑到「' + label + '」停下来，你可以重新选（也可以改成「就停在这儿」）\n\n' +
      '（引擎是无状态的，所以只能重跑，做不到真正的「时间倒流」）')) return;
  const j = await post('/api/job/rewind', { id: S.jobId, upto });
  if (!j.ok) { alert(j.error || '回退失败'); return; }
  S.jobId = j.job_id;
  S.logs = []; S.logCount = 0;
  S.steps = []; S.stepCount = 0;
  S.pending = null; S.answers = []; S.result = null;
  S.running = true;
  renderStage();
  setStatus('↩ 正在回退重跑…');
  pollJob();
}

async function refreshProject() {
  const j = await api('/api/state');
  if (j.ok) { S.state = j; renderEnv(); renderProjects(); renderRail(); }
}

/* ---------------- 模型建议 / 产物 / 项目 ---------------- */

async function askModel(focusKey) {
  const b = currentBlock();
  if (!b) return;
  if (!b.llm) {
    alert('「' + b.name + '」没有配模型提示词——这一步的活本来也不该交给模型。\n\n' +
      '（比如 ② 访谈编码是刻意不自动编码的：编码是研究者对材料的理解。）');
    return;
  }
  const btn = $('#btnLlm');
  if (btn) { btn.disabled = true; btn.innerHTML = '<span class="spin">◌</span> 模型在读材料…'; }
  setStatus('模型正在读材料…（半分钟到两分钟，看材料大小）');
  const j = await post('/api/llm', {
    block_id: b.id,
    params: collectForm(b),
    project: S.state.project.root,
    focus_key: focusKey || '',
  });
  if (btn) { btn.disabled = false; btn.innerHTML = '🤖 让模型建议'; }

  if (!j.ok) {
    setStatus('模型没跑起来');
    showModal(`<h3>模型没跑起来</h3>
      <div class="banner err" style="white-space:pre-wrap;max-height:40vh;overflow:auto">${esc(j.error || '')}</div>
      <div class="actions"><button class="btn" onclick="closeModal()">知道了</button></div>`);
    return;
  }
  setStatus('模型给了初稿（' + j.seconds + 's）');
  const fs = j.fields || {};
  const nFields = Object.keys(fs).length;
  const declared = (j.fields_meta || []).length;
  const missing = j.missing_fields || [];
  // 声明了小节却一个都没切出来 —— 说清楚，不要让按钮「默默消失」
  const broke = (!nFields && declared > 0)
    ? `<div class="banner err" style="margin-bottom:10px">
         这次<b>没能按小节切回来</b>（声明了 ${declared} 个小节，一个都没对上），所以
         <b>没有「填回表单」按钮</b>——模型这次没照着小节标题写，或者标题被改了。
         下面全文可以「复制全文」，手动粘到对应的栏里。
       </div>`
    : '';
  showModal(`<h3>${esc(j.title || '模型初稿')}</h3>
    <p>${esc(j.model)} · ${j.seconds}s —— 这是初稿，自己过一遍再决定要不要用。
       模型不做算术，数字仍然由 Python 产生。</p>
    ${broke}
    ${nFields ? `<div class="banner ok" style="margin-bottom:10px">
        模型按 <b>${nFields}</b> 个小节输出，可以<b>一键填回表单</b>${missing.length ? `；
        ${missing.length} 项没解析出来（${missing.map(esc).join('、')}），那几栏要自己补` : ''}。
      </div>` : ''}
    <textarea id="llmOut" spellcheck="false"
      style="width:76vw;height:52vh;font-family:Consolas,'Courier New',monospace;font-size:12.5px;line-height:1.6">${esc(j.text)}</textarea>
    <div class="actions">
      ${nFields ? `<button class="btn primary" id="llmFill">⤵ 填回表单（${nFields} 项）</button>` : ''}
      <button class="btn" id="llmCopy">复制全文</button>
      <button class="btn" onclick="closeModal()">关闭</button>
    </div>`);
  const cp = $('#llmCopy');
  if (cp) cp.onclick = () => {
    const ta = $('#llmOut');
    ta.focus(); ta.select();
    try { document.execCommand('copy'); setStatus('已复制到剪贴板'); }
    catch (e) { setStatus('复制失败，手动全选复制吧'); }
  };
  const fl = $('#llmFill');
  if (fl) fl.onclick = async () => {
    const b = currentBlock();
    S.form[b.id] = S.form[b.id] || {};
    let n = 0;
    const tables = [];                       // 这次填回来的值里，哪些落在「按文本接收」的字段上
    (j.fields_meta || []).forEach(m => {
      if (fs[m.key] === undefined) return;
      S.form[b.id][m.key] = fs[m.key];
      const f = (b.form || []).filter(x => x.key === m.key)[0];
      if (f && textAcceptor(f)) tables.push({ f: f, text: fs[m.key] });
      n++;
    });
    saveForm(b);
    closeModal();
    let note = '';
    if (tables.length) note = await adoptAcceptedText(b, tables);
    renderStage();
    cfRefresh();
    const tail = note ? ('；' + note) : '';
    if (S.confirm.items.length) {
      openConfirm();
      setStatus('已把 ' + n + ' 项填回表单 —— 还有 ' + S.confirm.items.length +
                ' 处「待确认」在右边，过一遍再跑' + tail);
    } else {
      setStatus('已把 ' + n + ' 项填回表单 —— 自己过一遍再点「用 Python 跑」' + tail);
    }
  };
}

/* ---------------- 待确认项（模型标出来的「我不确定」） ----------------

   模型不该编，所以信息不足的地方它写「（待确认：要确认的是什么）」。
   但填回表单之后这些标记散在十几个文本框里，人得一个个翻 —— 这里把它们收进右边一条侧栏：
   每条给出上下文原句、要确认的是什么，研究员写一句就直接替换回原处。 */

const CONF_WORDS = ['待确认', '待补充', '待定', 'TBD'];
const CONF_OPEN = { '（': '）', '(': ')', '【': '】', '[': ']' };
// 模型有时不写括号，直接来一条「待确认：…」
const CONF_LINE_RE = /(?:^|\n)[ \t]*(?:[-*+•·]|\d+[.、)）])?[ \t]*(待确认|待补充|待定|TBD)\s*[:：][ \t]*([^\n]+)/g;

function sentenceAround(s, idx) {
  const stop = '。！？!?；;\n';
  let a = idx, b = idx;
  while (a > 0 && stop.indexOf(s[a - 1]) < 0) a--;
  while (b < s.length && stop.indexOf(s[b]) < 0) b++;
  const t = s.slice(a, b).trim();
  return t.length > 160 ? t.slice(0, 157) + '…' : t;
}

/* 括号成对找结尾：`（待确认：要不要采集（用于关联）？）` 这种嵌套，
   用正则的非贪婪匹配会在第一个 `）` 就收尾 —— 于是「删掉标记」只删掉半截，
   正文里留下「？）」。这里数括号层级，找到真正配对的那一个。 */
function matchBracket(s, open) {
  const close = CONF_OPEN[open];
  let depth = 0;
  for (let i = 0; i < s.length; i++) {
    if (s[i] === open) depth++;
    else if (s[i] === close) { depth--; if (depth === 0) return i; }
  }
  return -1;
}

/* 从一段文字里找出所有待确认标记（纯函数，方便单独测）
   两种写法都认：`（待确认：…）` 和 不带括号的 `待确认：…` */
function findUnconfirmed(text) {
  const s = String(text === undefined || text === null ? '' : text);
  const out = [];
  for (let i = 0; i < s.length; i++) {
    const ch = s[i];
    if (!CONF_OPEN[ch]) continue;
    // 括号后面允许空格，然后是「待确认」这类词
    let j = i + 1;
    while (j < s.length && /\s/.test(s[j])) j++;
    const word = CONF_WORDS.find(w => s.startsWith(w, j));
    if (!word) continue;
    const end = matchBracket(s.slice(i), ch);
    if (end < 0) continue;
    const raw = s.slice(i, i + end + 1);
    let hint = raw.slice(1 + (j - i - 1) + word.length, -1).replace(/^\s*[:：]?\s*/, '').trim();
    out.push({ start: i, end: i + end + 1, raw: raw, kind: word,
               hint: hint, sentence: sentenceAround(s, i) });
    i = i + end;                                  // 跳过整个标记，免得在里面又找一遍
  }

  const spans = out.map(x => [x.start, x.end]);
  CONF_LINE_RE.lastIndex = 0;
  let m;
  while ((m = CONF_LINE_RE.exec(s)) !== null) {
    const start = m.index + m[0].indexOf(m[1]);
    const end = m.index + m[0].length;
    if (spans.some(sp => start < sp[1] && end > sp[0])) continue;   // 和上面重合了，跳过
    spans.push([start, end]);
    out.push({ start: start, end: end, raw: s.slice(start, end),
               kind: m[1], hint: (m[2] || '').trim(), sentence: sentenceAround(s, start) });
  }

  out.sort((a, b) => a.start - b.start);
  const seen = {};
  out.forEach(it => {
    const k = it.sentence;
    it.occ = seen[k] || 0;
    seen[k] = it.occ + 1;
  });
  return out;
}

/* 扫一个组块的表单，看还剩几处待确认 */
function scanBlockUnconfirmed(b) {
  if (!b) return [];
  const vals = S.form[b.id] || {};
  const items = [];
  (b.form || []).forEach(f => {
    if (f.type !== 'textarea' && f.type !== 'text' && f.type !== 'vartable') return;
    // 变量表折成一份文本一起扫（两种形态都能折）：表格里那几处「（待确认：…）」
    // 也该出现在右边那条侧栏里，不然填回之后它们就藏在格子里没人管。
    const v = (f.type === 'vartable') ? varTableText(vals[f.key]) : vals[f.key];
    if (!v) return;
    findUnconfirmed(v).forEach(it => {
      const sig = b.id + '|' + f.key + '|' + it.sentence + '|' + it.hint + '|' + it.occ;
      if (S.confirm.ignored.indexOf(sig) >= 0) return;
      items.push(Object.assign({}, it, { key: f.key, label: f.label || f.key, sig: sig }));
    });
  });
  return items;
}

/* 把某一处标记替换成替换文本（空字符串＝删掉标记） */
function cfReplace(text, it, repl) {
  const all = findUnconfirmed(text);
  const cand = all.filter(x => x.sentence === it.sentence);
  const target = cand[it.occ] || cand[0];
  if (!target) return text;
  return text.slice(0, target.start) + repl + text.slice(target.end);
}

function cfRefresh() {
  S.confirm.items = scanBlockUnconfirmed(currentBlock());
  if (S.confirm.open) renderConfirm();
}

function openConfirm() {
  S.confirm.open = true;
  S.confirm.items = scanBlockUnconfirmed(currentBlock());
  renderConfirm();
  $('#drawer').classList.add('on');
  syncDrawerTab();
}

function closeConfirm() {
  S.confirm.open = false;
  $('#drawer').classList.remove('on');
  syncDrawerTab();
}

/* 抽屉收起后，右边留一个把手 —— 「收起」了还得能再打开。
   （原来只有表单里那个「N 处待确认」按钮能开，处理完就没有了。） */
function syncDrawerTab() {
  let tab = document.getElementById('drawerTab');
  if (!tab) {
    tab = document.createElement('div');
    tab.id = 'drawerTab';
    tab.className = 'drawer-tab';
    tab.onclick = () => openConfirm();
    document.body.appendChild(tab);
  }
  const n = S.confirm.items.length;
  tab.innerHTML = '📌<br>' + (n ? n + ' 处' : '记录');
  tab.title = n ? (n + ' 处待确认 —— 点开逐条处理') : '待确认项已处理完 —— 点开回看处理记录 / 撤销';
  tab.style.display = S.confirm.open ? 'none' : 'flex';
}

/* 看这句话像不像「你对模型提问的回复」，而不是「要填进去的内容」。

   踩过的坑：模型在 RQ 那一节里用大白话问「要不要补第 4 条？」，研究员回「用四条」，
   那句答复就被当成第 4 条 RQ 填进去了（假设那栏也一样：「忽略本次假设」变成了第四条假设）。
   所以填之前先看一眼：**像答复的，就明说要把它当内容填，让研究员自己确认。** */
const REPLYISH = ['用', '同意', '可以', '好的', '好的，', '忽略', '不要', '按你说', '就用',
                  '赞成', '行', '听你的', '那', '你说得对', '没问题', '算了'];
const CONTENTISH = ['定类', '定序', '定距', '定比', '量表', '单选', '多选', 'Likert', '李克特',
                    '（待确认', '(待确认', 'http', '：', ':'];

function looksLikeReply(txt) {
  const s = String(txt || '').trim();
  if (!s) return false;
  if (CONTENTISH.some(w => s.indexOf(w) >= 0)) return false;   // 明显是内容
  if (replyishTail(s) && s.length > 30) return false;          // 长句多半是内容
  return REPLYISH.some(w => s === w || s.indexOf(w) === 0) && s.length <= 30;
}
function replyishTail(s) { return /[。；;]$/.test(s); }

function cfApply(i, mode) {
  const it = S.confirm.items[i];
  const b = currentBlock();
  if (!it || !b) return;
  const vals = S.form[b.id] || (S.form[b.id] = {});
  const fld = (b.form || []).filter(x => x.key === it.key)[0] || {};
  const isVT = fld.type === 'vartable';
  const rawBefore = vals[it.key];
  // 变量表要折成文本再改 —— 改完再解析回表格，别让一次「擦除」把整张表变成一段文本
  const before = isVT ? varTableText(rawBefore) : String(rawBefore === undefined ? '' : rawBefore);
  const box = $('#cf-in-' + i);
  const typed = box ? box.value.trim() : '';

  let after = before;
  let record = null;
  if (mode === 'fill') {
    if (!typed) { setStatus('先在上面写一句要填的内容，再点「填入」'); if (box) box.focus(); return; }
    // 像「回复」而不像「内容」时，先说清我准备干什么，让他自己拍板。
    // 不要替他判断 —— 有时候「忽略本次假设」确实就是他想要的正文。
    if (!it._replyOK && looksLikeReply(typed)) {
      const pre = cfReplace(before, it, typed);
      showModal(`<h3>这句要当成「${esc(it.label)}」的内容填进去吗？</h3>
        <div class="hint" style="line-height:1.85">
          你写的是：<b>${esc(typed)}</b><br>
          它看起来像**对上面那个问题的答复**，不像要填的内容。
          模型问在正文里的话不是问题，填进去就会变成正文的一部分
          （踩过：「用四条」被当成了第 4 条 RQ）。<br><br>
          填进去之后，<b>${esc(it.label)}</b> 会变成这样：
        </div>
        <div class="vline add" style="margin:8px 0">+ ${esc(typed)}</div>
        <div class="actions" style="flex-wrap:wrap;gap:8px">
          <button class="btn primary" id="rpYes">就这样填</button>
          <button class="btn ghost2" id="rpNo">等一下，我改一下措辞</button>
          <span class="grow"></span>
          <button class="btn ghost2" onclick="closeModal()">取消</button>
        </div>`);
      const yes = $('#rpYes');
      if (yes) yes.onclick = () => { closeModal(); it._replyOK = true; cfApply(i, 'fill'); };
      const no = $('#rpNo');
      if (no) no.onclick = () => {
        closeModal();
        setStatus('把措辞改成"要填的内容"，再点「填入」；或者点「删掉这个标记」直接跳过');
        if (box) box.focus();
      };
      return;
    }
    after = cfReplace(before, it, typed);
    record = { label: it.label, hint: it.hint, text: typed, mode: mode,
               key: it.key, before: before, sig: it.sig };
  } else if (mode === 'strip') {
    after = cfReplace(before, it, '');
    record = { label: it.label, hint: it.hint, text: '', mode: mode,
               key: it.key, before: before, sig: it.sig };
  } else {                                   // keep：先留着，别再提醒我
    S.confirm.ignored.push(it.sig);
    record = { label: it.label, hint: it.hint, text: '', mode: 'keep',
               key: it.key, before: before, sig: it.sig };
  }
  if (after !== before) vals[it.key] = after;
  saveForm(b);
  S.confirm.log.unshift(record);
  const done = () => {
    cfRefresh();
    renderStage();
    const left = S.confirm.items.length;
    setStatus(left ? ('还剩 ' + left + ' 处待确认') : '待确认项都过完了 👌');
  };
  if (isVT && after !== before) {
    tidyVarTableField(b, fld, after).then(done);   // 解析回表格再重画
  } else {
    done();
  }
}

function cfUndo(k) {
  const e = S.confirm.log[k];
  if (!e) return;
  const b = currentBlock();
  if (!b) return;
  const vals = S.form[b.id] || (S.form[b.id] = {});
  const fld = (b.form || []).filter(x => x.key === e.key)[0] || {};
  vals[e.key] = e.before;
  // 「先留着」的条目要一并解除屏蔽，否则撤销了也还是不提醒
  if (e.sig) S.confirm.ignored = S.confirm.ignored.filter(x => x !== e.sig);
  saveForm(b);
  // 同一条里更早的处理结果也一起撤掉（后面的 before 里含着前一步的结果）
  S.confirm.log = S.confirm.log.slice(k + 1).concat(
    S.confirm.log.slice(0, k).filter(x => x.key !== e.key));
  const done = () => {
    cfRefresh();
    renderStage();
    setStatus('撤回了：' + e.label);
  };
  // 撤销的是一张变量表：before 是文本，解析回表格再重画（不然表会变成一段文字）
  if (fld.type === 'vartable' && typeof e.before === 'string') {
    tidyVarTableField(b, fld, e.before).then(done);
  } else {
    done();
  }
}

function renderConfirm() {
  const b = currentBlock();
  const box = $('#drawerBox');
  if (!box) return;
  const items = S.confirm.items;
  const head = `<div class="dr-head">
      <div class="dr-title">📌 待确认项 <span class="badge ${items.length ? 'run' : 'done'}">${items.length}</span></div>
      <button class="ghost" id="drClose">收起</button>
    </div>`;

  const intro = items.length
    ? `<div class="dr-intro">这些是<b>模型不确定、没有硬编</b>的地方。逐条写清楚 → 点「填入」，
       它会直接替换回表单里对应的位置，不用回正文里找。</div>`
    : `<div class="dr-intro">没有待确认项了 👌 回去看一眼表单，就可以点「用 Python 跑」。</div>`;

  const cards = items.map((it, i) => `
    <div class="cfcard">
      <div class="cfmeta"><span class="badge">${esc(it.label)}</span>
        <span class="cfkind">${esc(it.kind)}</span></div>
      <div class="cfsent">${esc(it.sentence)}</div>
      ${it.hint ? `<div class="cfhint">要确认的是：<b>${esc(it.hint)}</b></div>`
                : `<div class="cfhint">模型没说要确认什么，你看一下上下文。</div>`}
      <div class="row" style="margin-top:8px">
        <input type="text" class="grow" id="cf-in-${i}" placeholder="写清楚，回车即填入">
        <button class="btn primary" data-cf="fill" data-i="${i}">✓ 填入</button>
      </div>
      <div class="actions" style="margin-top:7px">
        <button class="btn ghost2" data-cf="strip" data-i="${i}">删掉这个标记</button>
        <button class="btn ghost2" data-cf="keep" data-i="${i}">先留着，别再提醒我</button>
      </div>
    </div>`).join('');

  const done = S.confirm.log.length ? `
    <div class="cfdone">
      <div class="cfdone-t">已处理 ${S.confirm.log.length} 处</div>
      ${S.confirm.log.map((e, k) => `<div class="cfrow">
        <span class="cfok">${e.mode === 'keep' ? '留' : (e.mode === 'strip' ? '删' : '✓')}</span>
        <span class="cfrow-t">${esc(e.label)}${e.text ? ' ← ' + esc(e.text.slice(0, 40)) : ''}
          ${e.hint ? '<span class="muted">（' + esc(e.hint.slice(0, 30)) + '）</span>' : ''}</span>
        <button class="ghost2 tiny" data-undo="${k}">撤销</button>
      </div>`).join('')}
    </div>` : '';

  box.innerHTML = head + `<div class="dr-body">${intro}${cards}${done}</div>`;

  const c = $('#drClose');
  if (c) c.onclick = closeConfirm;
  syncDrawerTab();
  box.querySelectorAll('[data-cf]').forEach(el => {
    el.onclick = () => cfApply(Number(el.dataset.i), el.dataset.cf);
  });
  box.querySelectorAll('[data-undo]').forEach(el => {
    el.onclick = () => cfUndo(Number(el.dataset.undo));
  });
  items.forEach((it, i) => {
    const inp = $('#cf-in-' + i);
    if (inp) inp.onkeydown = (ev) => {
      if (ev.key === 'Enter') { ev.preventDefault(); cfApply(i, 'fill'); }
    };
  });
}

/* ---------------- 📁 选路径（不让人手打路径） ----------------

   浏览器拿不到本地路径，但工作台是**本机服务**：让服务端去弹一个 Windows 原生的
   选择框，选完把路径回填到输入框。选到项目外面的文件会自动**拷进项目**——
   一来引擎认得相对路径，二来项目还能整体打包带走。 */

function filterFor(f) {
  const exts = (f && f.accept) || ['csv', 'xlsx', 'xls', 'sav', 'txt', 'md', 'tsv', 'json'];
  const pat = exts.map(e => '*.' + e).join(';');
  return '可用的文件 (' + pat + ')|' + pat + '|所有文件 (*.*)|*.*';
}

async function pickPath(kind, opts) {
  opts = opts || {};
  setStatus('正在打开选择框…（如果没看见，看一下是不是被浏览器窗口挡住了）');
  const j = await post('/api/pick', {
    kind: kind, start: opts.start || '', title: opts.title || '',
    filter: opts.filter || '所有文件 (*.*)|*.*',
  });
  if (!j.ok) {
    setStatus('打不开选择框：' + j.error);
    alert('打不开选择框：\n\n' + j.error + '\n\n可以先手动把路径粘进输入框。');
    return null;
  }
  if (j.cancelled) { setStatus('没选（取消）'); return null; }
  return j;
}

/* 选一个「文件」并变成项目内的相对路径（项目外的会先拷进来） */
async function pickFileFor(fieldKey, label, accept) {
  const b = currentBlock();
  const cur = ((S.form[b.id] || {})[fieldKey] || '');
  const j = await pickPath('file', {
    start: cur, title: '选择' + (label || '文件'),
    filter: filterFor({ accept: accept }),
  });
  if (!j) return null;
  if (j.inside) { setStatus('选好了：' + j.rel); return j.rel; }

  setStatus('这个文件在项目外面，正在拷进项目…');
  const c = await post('/api/file/import', { src: j.path, sub: 'data' });
  if (!c.ok) {
    setStatus('拷不进来（' + c.error + '），先用绝对路径填着');
    return j.path;
  }
  setStatus('从项目外拷进来了：' + c.rel + '（放在 data/ 里，项目能整体带走）');
  return c.rel;
}

/* 选项目**外面**的一个文件，并且**保持绝对路径、不拷进项目**。

   为什么要单独一个：`pickFileFor` 的语义是"给分析用的数据文件" —— 项目外的会拷进
   `data/`（那样项目才能整体打包带走）。但设置页里选 SPSS 的 `stats.exe` 不是这个语义：
   它是个**程序**，拷进项目里毫无意义，而且填进去的相对路径 SPSS 根本认不了。
   ⇒ 这里走 `/api/pick` 的 `kind='anyfile'`：只回绝对路径，一个字节都不动。
*/
async function pickAnyFile(label, exts) {
  const j = await pickPath('anyfile', { title: label || '选一个文件', filter: filterFor({ accept: exts }) });
  if (!j || !j.path) return null;
  return j.path;
}

/* 🔗 等 SPSS 把输出导出来，然后直接显示在结果里。
   为什么是「等」：这台 SPSS 没有静默批处理开关，只能在界面里跑；
   但语法末尾已经写好 OUTPUT EXPORT，跑完它自己会把 HTML 落盘，我们盯着那个文件就行。 */
function startSpssWatch(box) {
  const spsRel = box.dataset.sps || '';
  const htmlRel = box.dataset.html || '';
  const msg = () => $('#spssWaitMsg');
  const started = Date.now() / 1000 - 5;      // 只看这之后新写出来的文件
  let stopped = false;
  let tries = 0;

  const stop = (text, cls) => {
    stopped = true;
    const m = msg();
    if (m && text) m.outerHTML = `<div class="banner ${cls || ''}">${esc(text)}</div>`;
  };

  const tick = async () => {
    if (stopped) return;
    tries++;
    const j = await post('/api/spss/collect', { rel: htmlRel, since: started });
    if (j.ok && j.ready) {
      const m = msg();
      if (m) {
        m.outerHTML = `<div class="hint" style="margin-bottom:8px">
          SPSS 跑完了，输出 ${fmtBytes(j.size || 0)} —— 下面就是它的原文，样式是 SPSS 的。</div>
          <iframe class="spssframe" sandbox srcdoc="${esc(j.text || '')}"></iframe>`;
      }
      setStatus('SPSS 的输出收回来了');
      refreshProject();
      return;
    }
    if (tries > 100) { stop('等了五分钟还没等到 SPSS 的输出。SPSS 里跑完了吗？' +
                            '也可以在 SPSS 的查看器里直接看，或点上面「在产物里打开」。', ''); return; }
    setTimeout(tick, 3000);
  };
  setTimeout(tick, 3000);

  const rl = $('#spssRelaunch');
  if (rl) rl.onclick = async () => {
    const j = await post('/api/spss/launch', { rel: spsRel, html: htmlRel });
    setStatus(j.ok ? 'SPSS 又打开了一次' : ('打不开：' + j.error));
  };
  const st = $('#spssStop');
  if (st) st.onclick = () => { stop('不再等了。SPSS 跑完的话，输出会出现在「产物」里。', ''); };
}

/* ---------------- 版本对比 ----------------
   契约文件每被覆盖一次，旧版都会留一份在 _history/ —— 但以前没人看得见。
   这里把它摆出来：这份文件有哪几轮、每一轮改了什么。
   默认比对「相邻两轮」（只看这次改了什么）；标签在看懂差异之后顺手打。 */

async function openVersions(rel) {
  S.lastVerRel = rel;
  const j = await api('/api/versions?rel=' + encodeURIComponent(rel) +
    '&project=' + encodeURIComponent(S.state.project.root));
  if (!j.ok) { alert(j.error || '读不到版本'); return; }
  const vs = j.versions || [];
  const rows = vs.length ? vs.map((v, i) => {
    const prev = vs[i + 1];        // 列表是新的在前，所以「上一轮」是下一条
    const name = v.kind === 'current' ? '当前版本' : (v.label || '（还没起名字）');
    const can = (v.kind === 'current' && prev) || (v.kind === 'history' && prev);
    return `<div class="vrow">
      <div class="vleft">
        <div class="vname">${esc(name)}</div>
        <div class="vmeta">${esc(v.at || '')} · ${v.lines} 行 · ${fmtSize(v.size || 0)}</div>
        ${v.note ? `<div class="vnote">${esc(v.note)}</div>` : ''}
      </div>
      <div class="vacts">
        ${can ? `<button class="btn ghost2" data-vdiff="${esc(rel)}|${esc(v.name)}|${esc(prev.name)}"
          title="和上一轮比：这一轮改了什么">对比上一轮</button>` : ''}
        ${v.kind === 'history' ? `<button class="btn ghost2" data-vlabel="${esc(v.name)}"
          title="起个人话名字，说清这一轮为什么改">起名 / 备注</button>` : ''}
      </div></div>`;
  }).join('') : '<div class="empty">这份文件还没有历史版本（第一次生成之后，改过才会有）</div>';

  showModal(`<h3>🕘 版本 · ${esc(rel)}</h3>
    <div class="hint" style="margin-bottom:8px">共 ${vs.length} 个版本，新的在上面。
      每次覆盖前工作台都会留一份旧版，所以这里的每一行都是真做过的版本，不是快照。</div>
    <div class="vlist">${rows}</div>
    <div id="vdiffBox"></div>
    <div class="actions">
      <span class="grow"></span>
      <button class="btn" onclick="closeModal()">关闭</button>
    </div>`);
  bindVersionModal();
}

function bindVersionModal() {
  const box = $('#modalBox');
  if (!box) return;
  box.querySelectorAll('[data-vdiff]').forEach(el => {
    el.onclick = async () => {
      const parts = String(el.dataset.vdiff).split('|');
      const rel = parts[0], a = parts[1], b = parts[2];
      const out = $('#vdiffBox');
      if (out) out.innerHTML = '<div class="hint"><span class="spin">◌</span> 正在比对…</div>';
      const d = await api('/api/version/diff?rel=' + encodeURIComponent(rel) +
        '&a=' + encodeURIComponent(a) + '&b=' + encodeURIComponent(b) +
        '&project=' + encodeURIComponent(S.state.project.root));
      if (!d.ok) { if (out) out.innerHTML = `<div class="banner err">${esc(d.error || '比不了')}</div>`; return; }
      if (out) {
        out.innerHTML = `<div class="vbox">
          <h3>这一轮改了什么</h3>
          ${diffHtml(d)}
          <div class="actions" style="margin-top:8px">
            <button class="btn ghost2" id="vexport">⤓ 导出成 markdown（可以写「为什么改」）</button>
          </div></div>`;
        const ex = $('#vexport');
        if (ex) ex.onclick = async () => {
          const r = await post('/api/version/export', { rel: rel, a: a, b: b });
          setStatus(r.ok ? ('已导出 → ' + r.rel) : ('导出失败：' + r.error));
          if (r.ok) alert('已导出：' + r.rel + '\n\n在「产物」里打开它，写下这一轮为什么改。');
        };
      }
      box.querySelectorAll('[data-vdiff]').forEach(x => { x.classList.remove('on'); });
      el.classList.add('on');
    };
  });
  box.querySelectorAll('[data-vlabel]').forEach(el => {
    el.onclick = async () => {
      const name = el.dataset.vlabel;
      const label = prompt('给这一轮起个名字（比如「第 2 轮：加了价格敏感度」）', '');
      if (label === null) return;
      const note = prompt('这一轮为什么改？（可留空）', '') || '';
      const r = await post('/api/version/label', { name: name, label: label, note: note });
      if (!r.ok) { alert(r.error || '打不上'); return; }
      closeModal();
      openVersions(S.lastVerRel || '');
    };
  });
}

function diffHtml(d) {
  const s = d.summary || {};
  const head = d.kind === 'md'
    ? `新增 <b>${s.added}</b> 个小节 · 改动 <b>${s.changed}</b> 个 · 删掉 <b>${s.removed}</b> 个`
    : (d.kind === 'table'
      ? `新增 <b>${s.added}</b> 条 · 删掉 <b>${s.removed}</b> 条（${s.rows_old} → ${s.rows_new}）`
      : `新增 <b>${s.added}</b> 行 · 删掉 <b>${s.removed}</b> 行`);
  const out = [`<div class="vhint">${head}
    <span class="vwho">旧的：${esc((d.a || {}).name || '')} → 新的：${esc((d.b || {}).name || '')}</span></div>`];

  if (d.kind === 'md') {
    (d.sections || []).forEach(sec => {
      out.push(`<div class="vsec">
        <div class="vtitle"><span class="vtag v-${sec.status === '新增' ? 'add' : (sec.status === '删除' ? 'del' : 'chg')}">${esc(sec.status)}</span>
          ${esc(sec.title)}</div>
        ${(sec.removed || []).map(x => `<div class="vline del">− ${esc(x)}</div>`).join('')}
        ${(sec.added || []).map(x => `<div class="vline add">+ ${esc(x)}</div>`).join('')}
      </div>`);
    });
    if (!(d.sections || []).length) out.push('<div class="hint">这两轮内容一样。</div>');
  } else if (d.kind === 'table') {
    if ((d.added || []).length) {
      out.push('<div class="vsec"><div class="vtitle"><span class="vtag v-add">新增</span></div>'
        + d.added.map(x => `<div class="vline add">+ ${esc(x)}</div>`).join('') + '</div>');
    }
    if ((d.removed || []).length) {
      out.push('<div class="vsec"><div class="vtitle"><span class="vtag v-del">删掉</span></div>'
        + d.removed.map(x => `<div class="vline del">− ${esc(x)}</div>`).join('') + '</div>');
    }
    if (!(d.added || []).length && !(d.removed || []).length) out.push('<div class="hint">条目没变。</div>');
  } else {
    (d.removed || []).forEach(x => out.push(`<div class="vline del">− ${esc(x)}</div>`));
    (d.added || []).forEach(x => out.push(`<div class="vline add">+ ${esc(x)}</div>`));
    if (!(d.removed || []).length && !(d.added || []).length) out.push('<div class="hint">内容一样。</div>');
  }
  return out.join('');
}

async function loadLayers() {
  const j = await api('/api/report/artifacts?project=' + encodeURIComponent(S.state.project.root));
  S.layers = j.ok ? j.layers : null;
  renderStage();
}

/* ---------------- 填回表单：结构化字段怎么吃「一段文本」 ----------------

   「⤵ 填回表单」是把模型输出**按字段**写进表单的，而模型给的是文本。
   界面上的 vartable 字段存的是数组 —— 直接把字符串塞进去，表格会一行都显示不出来
   （踩过：变量表在界面上凭空消失，而引擎靠文本兜底照样跑得通，只有眼睛被骗）。

   **别再给每种字段各写一个 if**（那就是补丁）。改成：
   声明里写 `accept_text: "变量表"`，这里按这个键查表，由对应的 writer 负责
   「文本 → 这个字段的结构」。加新字段类型时只加一个 writer，不动别的地方。 */

const TEXT_ACCEPTORS = {
  // 变量表：模型常给 Markdown 表格，交给后端用**和引擎同一套**解析规则变成行
  '变量表': async (b, f, text) => {
    const j = await post('/api/vartable/parse', { text: text });
    const rows = (j.ok ? (j.rows || []) : []).map(varRowCells);
    return { value: rows, ok: rows.length > 0,
             msg: rows.length ? ('解析成 ' + rows.length + ' 行填进表格') : '' };
  },
};

// 这个字段要按哪种文本吃掉填进来的值？（没有声明就返回空 = 按普通文本字段处理）
function textAcceptor(f) {
  const key = f && f.accept_text;
  return key ? (TEXT_ACCEPTORS[key] || null) : null;
}

// 「填回表单」填到结构化字段上的整段文本：按声明分发。
// 带「（待确认：…）」的先不转 —— 让研究员在待确认侧栏里一条条过完再转。
async function adoptAcceptedText(b, fields) {
  const notes = [];
  for (const t of fields) {
    const txt = String(t.text || '');
    if (!txt.trim()) { S.form[b.id][t.f.key] = []; continue; }
    if (txt.indexOf('（待确认') >= 0 || txt.indexOf('(待确认') >= 0) {
      notes.push('「' + (t.f.label || t.f.key) + '」里还有待确认项，先过完再点表上的「从研究简报读回」');
      continue;
    }
    const acc = textAcceptor(t.f);
    if (!acc) { notes.push('「' + (t.f.label || t.f.key) + '」没有声明怎么接收文本，原样存着'); continue; }
    const r = await acc(b, t.f, txt);
    if (r && r.ok) {
      S.form[b.id][t.f.key] = r.value;
      if (r.msg) notes.push(r.msg);
    } else {
      notes.push('模型给的「' + (t.f.label || t.f.key) + '」没解析出东西，'
        + '点表上的「从研究简报读回」再试一次');
    }
  }
  saveForm(b);
  return notes.join('；');
}

async function openArtifact(rel, at) {
  const ext = (rel.split('.').pop() || '').toLowerCase();
  if (!at && ['png', 'jpg', 'jpeg', 'webp', 'gif', 'svg'].indexOf(ext) >= 0) {
    window.open('/api/artifact?rel=' + encodeURIComponent(rel), '_blank');
    return;
  }
  const j = await api('/api/artifact?rel=' + encodeURIComponent(rel));
  if (!j.ok) { alert(j.error); return; }
  const raw = j.text || '';
  // 结果是表就看表：能排序、p 能上色。当纯文本看等于白瞎了这些列。
  // ⚠ 带 `at`（要翻到第几行）时改走**带行号的纯文本视图** ——
  //   研究员提的：「加一个跳转到原文档对应位置直接查看的功能，
  //   自己翻原文档一行行找太要命了」。表格/渲染后的 md 都没法"翻到第 N 行"。
  const isTable = !at && (ext === 'csv' || ext === 'tsv') && !j.skipped;
  const canEdit = ['.png', '.jpg', '.jpeg', '.webp', '.gif', '.xlsx', '.xls', '.sav']
    .indexOf('.' + ext) < 0;
  S.art = { rel: rel, raw: raw, editing: false, isTable: isTable,
            canEdit: canEdit, at: at || 0, rawEdit: false, _panel: false, _sheet: null };
  showArtifactModal();
}

// 带行号的原文视图：要高亮的那一行加 class，其余照排。
// 为什么不用现成的 md 渲染：md 渲染完就没有"行"了，没法定位；而这里要的正是定位。
function locateHtml(raw, at) {
  const lines = String(raw || '').split('\n');
  return `<div class="locate">` + lines.map((ln, i) => {
    const n = i + 1;
    const hit = (n === Number(at));
    return `<div class="lnrow${hit ? ' hit' : ''}"${hit ? ' id="locHit"' : ''}>`
      + `<span class="lnno">${n}</span><span class="lntx">${esc(ln) || '&nbsp;'}</span></div>`;
  }).join('') + `</div>`;
}

// 产物弹窗单独抽出来：查看 / 编辑 两种状态都在这里画。
// HTML 部分独立成 artifactModalHtml()，好让测试直接断言（不用去点 DOM）。
/** 这个产物能不能用「逐段编码」面板：
 *  csv/tsv + 里面有原文列和三列编码列。 */
function canCodingPanel(a) {
  if (!a || !a.canEdit || !isDelimited(a.rel)) return false;
  return !!codingSheet(a);
}

function artifactModalHtml(a) {
  a = a || {};
  // 四种状态：
  //   查看            —— 表格 / md / 带行号的原文（老样子）
  //   **逐段编码**     —— 编码工作表的默认编辑方式（上下文 + 点码就贴）
  //   编辑·表格        —— 其他 CSV 的编辑方式（一格一个输入框）
  //   编辑·原始文本    —— 想批量粘贴 / 查引号时才用
  const gridMode = !!(a.editing && a.isTable && a.canEdit && !a.rawEdit);
  const panelMode = !!(a.editing && a._panel && !a.rawEdit);
  let body;
  if (!a.editing) {
    body = a.at ? locateHtml(a.raw, a.at)
      : (a.isTable
        ? `<div id="artTbl">${csvTableHtml(a.raw || '', '产物:' + a.rel)}</div>`
        : `<div class="md" style="max-height:60vh;overflow:auto">${mdToHtml(a.raw || '')}</div>`);
  } else if (panelMode) {
    body = codingPanelHtml(a);
  } else if (gridMode) {
    body = gridEditorHtml(a);
  } else {
    body = `<div class="hint" style="margin-bottom:6px">直接改原文，改完点「保存」。
        旧版会自动留进 <code>_history/</code>，改坏了能找回上一版。</div>
       <textarea id="artEdit" spellcheck="false" style="width:100%;height:52vh;
         font:12.5px/1.6 Consolas,'Courier New',monospace; white-space:pre; overflow:auto"
         >${esc(a.raw || '')}</textarea>`;
  }
  const modes = [];
  if (a.editing && a.canEdit) {
    if (canCodingPanel(a)) {
      modes.push(`<button class="btn ghost2${panelMode ? ' on' : ''}" id="artModePanel"
        title="一段一屏：看得见前后文，点已建的码就贴上去">🗂 逐段编码</button>`);
    }
    modes.push(`<button class="btn ghost2${(gridMode && !panelMode) ? ' on' : ''}" id="artMode"
      title="像表格一样一格一格改">▦ 表格</button>`);
    modes.push(`<button class="btn ghost2${(a.editing && a.rawEdit) ? ' on' : ''}" id="artModeRaw"
      title="改 CSV 原文（批量粘贴、查引号时用）">⌨ 原始文本</button>`);
  }
  return `<h3>${esc(a.rel || '')}</h3>
    <p>${fmtSize((a.raw || '').length)}${a.editing
      ? `　（编辑中${panelMode ? '·逐段编码' : (gridMode ? '·表格' : '·原始文本')}）`
        + '<span id="gridDirty"></span>' : ''}${
      a.at ? `　<span class="hitnote">📍 跳到了第 ${esc(a.at)} 行</span>` : ''}</p>
    <div id="artBody">${body}</div>
    <div class="actions">
      ${modes.join('')}
      ${a.editing
        ? `<span class="grow"></span>
           <button class="btn primary" id="artSave">💾 保存</button>
           <button class="btn ghost2" id="artCancel">取消</button>`
        : `${a.canEdit ? `<button class="btn" id="artEditBtn" title="直接改这个产物">✏ 编辑</button>` : ''}
           <span class="grow"></span>`}
      <button class="btn ghost2" onclick="closeModal()">关闭</button>
    </div>`;
}

function showArtifactModal() {
  const a = S.art || {};
  showModal(artifactModalHtml(a));
  // 编辑表格 / 逐段编码时把弹窗放宽：9 列挤在 78vw 里会变一条缝
  const box = $('#modalBox');
  if (box && box.classList) {
    const wide = !!(a.editing && a.isTable && a.canEdit && !a.rawEdit);
    if (wide) box.classList.add('wide'); else box.classList.remove('wide');
  }
  if (!a.editing && a.isTable) bindTableTools('#modal');
  if (a.editing && a._panel && !a.rawEdit) bindCodingPanel();
  else if (a.editing && a.isTable && a.canEdit && !a.rawEdit) bindGridEditor();
  // 跳转定位：滚到高亮那一行，并且**让它居中** —— 屏幕上就一行高亮最省眼睛。
  if (a.at) {
    const hit = document.getElementById('locHit');
    if (hit && hit.scrollIntoView) {
      try { hit.scrollIntoView({ block: 'center' }); } catch (e) { hit.scrollIntoView(); }
    }
  }
  const eb = $('#artEditBtn');
  if (eb) eb.onclick = () => {
    S.art.editing = true; S.art.at = 0; S.art.rawEdit = false;
    // 编码工作表默认进「逐段编码」；别的 CSV 进表格编辑
    S.art._panel = canCodingPanel(S.art);
    if (S.art._panel) {
      S.art._sheet = codingSheet(S.art);
      S.art._ri = 0;
    }
    showArtifactModal();
  };
  const cb = $('#artCancel');
  if (cb) cb.onclick = () => { S.art.editing = false; showArtifactModal(); };
  // 先把当前模式那版收下来（别让刚打的字蒸发），再切模式
  const stash = () => {
    if (!S.art.editing || S.art.rawEdit) {
      const box = $('#artEdit');
      if (box) S.art.raw = box.value;
      return;
    }
    if (S.art._panel && S.art._sheet) {
      collectPanelInto(S.art._sheet, S.art._cur, S.art._ri);
      S.art.raw = sheetToCsv(S.art._sheet);
    } else if (S.art.isTable) {
      S.art.raw = gridToCsv();
    }
  };
  const goMode = (which) => {
    stash();
    if (which === 'raw') { S.art.rawEdit = true; }
    else {
      S.art.rawEdit = false;
      S.art._panel = (which === 'panel') && canCodingPanel(S.art);
      if (S.art._panel) { S.art._sheet = codingSheet(S.art); S.art._ri = 0; }
    }
    showArtifactModal();
  };
  // ⚠ 这四个 id 必须和 artifactModalHtml 里**真的画出来的按钮**一一对应。
  //   踩过：我给「表格」按了个 `#artModeGrid`，可那个按钮的 id 其实叫 `#artMode` ——
  //   处理器于是挂在一个不存在的元素上（**点了没反应的死代码**），
  //   而"按钮都画出来了"看着一切正常。测试里那条「三个模式按钮的 id 都在」就是盯这个。
  const mb = $('#artMode');
  if (mb) mb.onclick = () => goMode('grid');
  const mp = $('#artModePanel');
  if (mp) mp.onclick = () => goMode('panel');
  const mr = $('#artModeRaw');
  if (mr) mr.onclick = () => goMode('raw');
  const sv = $('#artSave');
  if (sv) sv.onclick = async () => {
    const box = $('#artEdit');
    // 逐段编码 / 表格模式下，内容散在界面上，得先收成 CSV
    let text;
    if (S.art.editing && !S.art.rawEdit && S.art._panel && S.art._sheet) {
      collectPanelInto(S.art._sheet, S.art._cur, S.art._ri);
      text = sheetToCsv(S.art._sheet);
    } else if (S.art.editing && !S.art.rawEdit && S.art.isTable) {
      text = gridToCsv();
    } else {
      text = box ? box.value : '';
    }
    if (text === S.art.raw) { setStatus('没有改动'); S.art.editing = false; showArtifactModal(); return; }
    sv.disabled = true; sv.textContent = '保存中…';
    const r = await post('/api/artifact/save', { rel: S.art.rel, text: text });
    if (!r.ok) { sv.disabled = false; sv.textContent = '💾 保存'; alert(r.error || '存不上'); return; }
    S.art.raw = text;
    S.art.editing = false;
    S.art.at = 0;
    showArtifactModal();
    setStatus('已保存 ' + r.rel + (r.backup ? '（旧版留在 _history/' + r.backup + '）' : ''));
    loadState();                       // 大小变了，产物列表跟着刷新
  };
}

/* 产物里的 CSV：切成表格，交给上面那套排序/上色 */
function csvTableHtml(csvText, id) {
  const txt = String(csvText || '').replace(/^\uFEFF/, '').replace(/\r\n?/g, '\n');
  const lines = txt.split('\n').filter(l => l.trim() !== '');
  if (!lines.length) return '<div class="empty">空文件</div>';
  const sep = (lines[0].indexOf('\t') >= 0 && lines[0].indexOf(',') < 0) ? '\t'
    : ((lines[0].indexOf(';') >= 0 && lines[0].indexOf(',') < 0) ? ';' : ',');
  const cols = splitCsvLine(lines[0], sep);
  const rows = lines.slice(1).map(l => {
    const c = splitCsvLine(l, sep);
    while (c.length < cols.length) c.push('');
    return c.slice(0, cols.length);
  });
  return tableHtml({ id: id, columns: cols, rows: rows });
}

function splitCsvLine(line, sep) {
  const out = [];
  let cur = '', q = false;
  for (let i = 0; i < line.length; i++) {
    const ch = line[i];
    if (q) {
      if (ch === '"') { if (line[i + 1] === '"') { cur += '"'; i++; } else q = false; }
      else cur += ch;
    } else if (ch === '"') q = true;
    else if (ch === sep) { out.push(cur); cur = ''; }
    else cur += ch;
  }
  out.push(cur);
  return out;
}

/* ---------------- CSV/TSV 网格编辑器 ----------------
 *
 * 为什么加这个（2026-09-24 实测反馈）：
 *   **「查看」那版是好好的表格，一点「编辑」就变成一个原始 CSV 文本框** ——
 *   几十段中文挤在一行行逗号里，引号成对不成对全靠肉眼，读不成读、写不成写。
 *   而这恰恰是**唯一需要人大量手写**的产物（② 的编码工作表，要一段段填开放编码/范畴/主题）。
 *
 * 设计：**存储仍是 CSV 原文**（后端接口、_history 备份、可复现性都不动），
 *   只是把"编辑"的呈现方式换成一个表格：一格一个输入框、文字自己换行、能 Tab 走。
 *   另外留一个「原始文本」模式给想批量处理的人（粘贴一大段、查引号），默认不用它。
 */

function isDelimited(rel) {
  const e = String(rel || '').toLowerCase().split('.').pop();
  return e === 'csv' || e === 'tsv';
}

function detectSep(text) {
  const l = String(text || '').replace(/^\uFEFF/, '').replace(/\r\n?/g, '\n').split('\n')
    .filter(x => x.trim() !== '')[0] || '';
  if (l.indexOf('\t') >= 0 && l.indexOf(',') < 0) return '\t';
  if (l.indexOf(';') >= 0 && l.indexOf(',') < 0) return ';';
  return ',';
}

/** CSV 文本 → {cols, rows, sep}。**所有行都保留**（空行也要，免得存回去时行号错位）。
 *
 * ⚠ 必须**逐字符**解析，不能先按 `\n` 切行再拆逗号 —— 这个坑是回归测试当场抓到的：
 *   编码表里「原文」那一格是**整段访谈**，导入导出时很容易带换行；
 *   带引号的单元格里那个换行**是内容、不是换行记录**。先按 \n 切会把它切成两行，
 *   于是列数对不上、后面的行全部错位（`字数` 变成 `原文` 那种）——
 *   而表面上"表格画出来了"，很难看出错位。
 *   标准的 CSV 状态机：在引号里时，逗号和换行都是**普通字符**。
 */
function parseDelimited(text) {
  const txt = String(text || '').replace(/^\uFEFF/, '').replace(/\r\n?/g, '\n');
  const sep = detectSep(txt);
  const lines = [];
  let cell = '', row = [], q = false;
  for (let i = 0; i < txt.length; i++) {
    const ch = txt[i];
    if (q) {
      if (ch === '"') {
        if (txt[i + 1] === '"') { cell += '"'; i++; }   // 转义的引号
        else q = false;                                  // 引号段结束
      } else cell += ch;                                 // 引号里的换行/逗号都是内容
    } else if (ch === '"') {
      q = true;
    } else if (ch === sep) {
      row.push(cell); cell = '';
    } else if (ch === '\n') {
      row.push(cell); cell = '';
      lines.push(row); row = [];
    } else {
      cell += ch;
    }
  }
  if (cell !== '' || row.length) { row.push(cell); lines.push(row); }
  // 去掉尾部纯空行（文件末尾那个换行造成的），**中间的空行留着**
  while (lines.length && lines[lines.length - 1].every(x => String(x).trim() === '')) lines.pop();
  if (!lines.length) return { cols: [], rows: [], sep: sep };
  const cols = lines[0].map(String);
  const rows = lines.slice(1).map(r => {
    const c = r.map(x => String(x));
    while (c.length < cols.length) c.push('');
    return c.slice(0, cols.length);
  });
  return { cols: cols, rows: rows, sep: sep };
}

function csvCell(v, sep) {
  const s = String(v === null || v === undefined ? '' : v);
  if (s.indexOf('"') >= 0 || s.indexOf(sep) >= 0 || s.indexOf('\n') >= 0 || s.indexOf('\r') >= 0)
    return '"' + s.replace(/"/g, '""') + '"';
  return s;
}

/** 网格 → CSV 文本（和 parseDelimited 成对，往返不丢内容）。 */
function serializeDelimited(cols, rows, sep) {
  const out = [cols.map(c => csvCell(c, sep)).join(sep)];
  rows.forEach(r => out.push(cols.map((_, i) => csvCell(r[i], sep)).join(sep)));
  return out.join('\n') + '\n';
}

/** 哪个字段适合大输入框：长文本列（原文）和**要写的列**都给大一点的框。 */
function cellIsWide(colName) {
  return /原文|内容|备注|摘录|引语|题目|题干|说明|描述|话/.test(String(colName || ''));
}

/** 每列该占多少（相对权重，最后会归一化成百分比）。 */
function gridColWeight(c) {
  const s = String(c || '');
  if (/原文|内容|题目|题干|说明|描述|摘录/.test(s)) return 26;   // 整段访谈
  if (/开放编码|范畴|主题|编码|引语|备注/.test(s)) return 12;    // 要手写的那几列
  if (/关键词|线索/.test(s)) return 13;
  if (/^#|序号|编号|字数|说话人/.test(s)) return 6;
  return 8;
}

function gridEditorHtml(a) {
  const p = parseDelimited(a.raw || '');
  const cols = p.cols, rows = p.rows;
  if (!cols.length) return '<div class="empty">空文件</div>';
  a._cols = cols;
  a._rows = rows;
  a._sep = p.sep;
  // ⚠ 列宽**必须合计正好 100%**。踩过：我按「这类列给 34%」硬填，
  //   9 列加起来 114% —— 浏览器只好自己压缩，`table-layout:fixed` 下
  //   「原文」那一列被压成一条缝（每个字换一行），而表头还看着挺正常。
  //   改成"按权重归一化"，权重怎么调都不会超。
  const w0 = cols.map(gridColWeight);
  const tot = w0.reduce((x, y) => x + y, 0) || 1;
  const pct = w0.map(x => (x / tot) * 100);
  const cg = `<colgroup>` + cols.map((c, i) =>
    `<col style="width:${pct[i].toFixed(2)}%">`).join('') + '</colgroup>';
  const head = cols.map((c, i) =>
    `<th class="${cellIsWide(c) ? 'wide' : ''}" title="${esc(c)}">${esc(c)}</th>`).join('');
  // ⚠ **不再自己摆一列行号**：编码工作表的第一列本来就是 `#`（段号），
  //   我再加一列就变成表头里两个 `#`，对着看不知道哪个是哪个（实测报的截图里就是这个）。
  //   导航靠 `data-r` / `data-c`，不靠眼睛数格子。
  const body = rows.map((r, ri) =>
    `<tr data-r="${ri}">` + cols.map((c, ci) =>
      `<td class="${cellIsWide(c) ? 'wide' : ''}">`
      + `<textarea class="gcell" rows="${cellIsWide(c) ? 2 : 1}" spellcheck="false"`
      + ` data-r="${ri}" data-c="${ci}"`
      + ` title="第 ${ri + 1} 行 · ${esc(c)}">${esc(r[ci] || '')}</textarea>`
      + `</td>`).join('') + '</tr>').join('');
  return `<div class="hint" style="margin-bottom:6px">
      直接改格子，改完点「💾 保存」。<b>Tab</b> 下一格 · <b>Enter</b> 同一列下一行 ·
      <b>Ctrl+Enter</b> 保存 · 旧版自动留进 <code>_history/</code>。
      <span id="gridWhere" style="color:#9aa3b2"></span>
    </div>
    <div class="gridwrap" data-ncol="${cols.length}"><table class="gridtbl">
      ${cg}
      <thead><tr>${head}</tr></thead>
      <tbody>${body}</tbody></table></div>
    <div class="row" style="margin-top:8px">
      <button class="btn ghost2" id="gridAddRow">＋ 加一行</button>
      <span class="grow"></span>
      <span class="hint" style="margin:0">共 ${rows.length} 行 · ${cols.length} 列</span>
    </div>`;
}

/** 把网格里的输入框收成二维数组。 */
function collectGrid() {
  const boxes = document.querySelectorAll('.gridwrap textarea.gcell');
  const map = {};
  let maxR = -1;
  Array.prototype.forEach.call(boxes, t => {
    const r = Number(t.getAttribute('data-r')), c = Number(t.getAttribute('data-c'));
    if (!map[r]) map[r] = [];
    map[r][c] = t.value;
    if (r > maxR) maxR = r;
  });
  const out = [];
  for (let r = 0; r <= maxR; r++) out.push(map[r] || []);
  return out;
}

/** 当前二维内容 → CSV 文本（保存时用）。 */
function gridToCsv() {
  const a = S.art || {};
  return serializeDelimited(a._cols || [], collectGrid(), a._sep || ',');
}

/** 自动长高：不这么做，长段落只能看到一行，跟原来那个毛病一样。 */
function autoGrow(t, wide) {
  if (!t || !t.style) return;
  const min = wide ? 46 : 30;
  try {
    t.style.height = 'auto';
    t.style.height = Math.max(min, t.scrollHeight + 2) + 'px';
  } catch (e) { /* 测环境里没有布局，忽略 */ }
}

function bindGridEditor() {
  const wrap = document.querySelector('.gridwrap');
  if (!wrap) return;
  const boxes = Array.prototype.slice.call(wrap.querySelectorAll('textarea.gcell'));
  const cols = (S.art && S.art._cols) || [];
  const nCol = cols.length || 1;
  const wide = cols.map(cellIsWide);
  boxes.forEach(t => {
    const w = wide[Number(t.getAttribute('data-c'))];
    autoGrow(t, w);
    t.addEventListener('input', () => {
      autoGrow(t, w);
      markGridDirty();
    });
    t.addEventListener('focus', () => showGridWhere(t));
    t.addEventListener('keydown', (ev) => {
      const r = Number(t.getAttribute('data-r')), c = Number(t.getAttribute('data-c'));
      if (ev.key === 'Tab') {
        // 在**要写的列**之间走最顺：跳过那些只是给人看的列（字数、关键词）
        ev.preventDefault();
        moveCell(r, c, ev.shiftKey ? -1 : 1);
      } else if (ev.key === 'Enter' && !ev.ctrlKey && !ev.metaKey && !ev.shiftKey) {
        // Enter = 同一列往下一行（一路往下填编码最常用）
        ev.preventDefault();
        const next = document.querySelector(
          `.gridwrap textarea.gcell[data-r="${r + 1}"][data-c="${c}"]`);
        if (next) { next.focus(); }
        else {
          // 到底了：如果同一行还有别的列，往右走一格
          const right = document.querySelector(
            `.gridwrap textarea.gcell[data-r="${r}"][data-c="${c + 1}"]`);
          if (right) right.focus();
        }
      } else if (ev.key === 'Enter' && (ev.ctrlKey || ev.metaKey)) {
        ev.preventDefault();
        const sv = document.getElementById('artSave');
        if (sv) sv.click();
      }
    });
  });
  const add = document.getElementById('gridAddRow');
  if (add) add.onclick = () => {
    const a = S.art;
    const rows = collectGrid();
    rows.push(new Array(nCol).fill(''));
    a.raw = serializeDelimited(a._cols, rows, a._sep);
    showArtifactModal();
  };
  // 「跳到第 N 行」的小工具：编码表几十行，靠滚动找太累
  showGridWhere(boxes[0]);
  // 让 Tab 真的按 DOM 顺序走（默认行为会跳过 textarea 之外的）
  wrap.addEventListener('keydown', (ev) => {
    if (ev.key === 'Tab' && ev.target && ev.target.classList
        && !ev.target.classList.contains('gcell')) ev.preventDefault();
  });
}

function markGridDirty() {
  const el = document.getElementById('gridDirty');
  if (el) el.textContent = '● 有改动还没保存';
}

function showGridWhere(t) {
  const el = document.getElementById('gridWhere');
  if (!el || !t) return;
  const r = Number(t.getAttribute('data-r')) + 1;
  const c = Number(t.getAttribute('data-c'));
  const cols = (S.art && S.art._cols) || [];
  el.textContent = '　正在第 ' + r + ' 行 · ' + (cols[c] || '');
}

function moveCell(r, c, dir) {
  const nCol = ((S.art && S.art._cols) || []).length;
  const total = document.querySelectorAll('.gridwrap textarea.gcell').length;
  const flat = r * nCol + c + dir;
  if (flat < 0 || flat >= total) return;
  const nr = Math.floor(flat / nCol), nc = flat % nCol;
  const el = document.querySelector(
    `.gridwrap textarea.gcell[data-r="${nr}"][data-c="${nc}"]`);
  if (el) { el.focus(); el.select && el.select(); }
}

/* ---------------- 逐段编码面板（就地编码）----------------
 *
 * 为什么加这个（2026-09-24，问完 NVivo / MAXQDA 之后定的方向）：
 *   表格编辑解决了"能写"，但**编的时候看不见上下文** —— 判断"这句到底是什么情绪"，
 *   前后说了什么很关键；而且 70 段里哪几段还没编过，得自己在格子里找。
 *
 * 参照真工具的做法（NVivo 的 coding stripes / MAXQDA 的代码窗），但**不照抄**：
 *   我们不做"在原文上划选上色"（那要动存储格式），而是**一段一屏**：
 *   左边是**完整原文**（可滚动、当前段高亮、有角色深浅），右边是要编的这一段。
 *
 * ⚠ 存储一点没变：还是 `编码工作表.csv` 的那三列（开放编码 / 范畴 / 主题），
 *   一格多个码用 `；` 连 —— 和 ②b 的 `SEPS = "、；;/｜|\n"` 一致。
 *   所以这个面板**只是换了个填法**，产物格式、_history 备份、可复现性都不动。
 *
 * ⚠ 关于「访谈者的提问要不要编」（作者问的方法学问题）：
 *   结论是**编回答、但提问必须看得见** —— 提问决定"答案是自发说的还是被问出来的"，
 *   是方法学证据，不能藏。所以这里不"隐藏提问"，而是：
 *     · **背景深浅分角色**（提问浅、回答白）—— 一眼分得清，但都读得到
 *     · **角色筛选**只影响"哪些段要编 / 算进度"，不影响原文里看不看得到
 *     · 进度条按**回答段**算（提问占了整整一半，混进去会让主题覆盖数翻倍）
 */

// 编码表里那三列 + 原文列，按列名找（找不到就退回位置）
const CODE_FIELDS = [
  { key: 'open', label: '开放编码', re: /开放编码|开放式编码|初始编码/ },
  { key: 'cat', label: '范畴', re: /^范畴|类属|分类/ },
  { key: 'theme', label: '主题', re: /^主题|核心主题/ },
];
const RAW_COL_RE = /原文|原话|内容|文本|发言/;
const WHO_COL_RE = /说话人|发言人|受访者|对象/;

// 一眼分角色：访谈者的提问**浅色**，受访者的话**白色**（主文）。
// 为什么不用颜色区分（一红一蓝）：颜色在这套界面里已经被"码"占用了（chip 是蓝的），
// 再用颜色说角色会打架。深浅最省事也最不抢眼。
//
// ⚠ 判据三档，因为**真实稿子里写的就是光秃秃的人名**（「林晓：」「苏雨桐：」），
//   没有任何"访谈者"字样 —— 只看名字的话所有人都判成 other、深浅全白搭（实测踩到）。
//     ① 名字/占位名本身认得出来（`访谈者`、`[受访者1]`）
//     ② 认不出来时，用**"默认要编谁"反推**：那个集合是受访者，补集就是访谈者
//     ③ 还是定不了 → other（**保守，不瞎猜**）
function speakerTone(who, a) {
  const s = String(who || '');
  // ① 名字里就写着角色
  if (/受访|被访|访谈对象/.test(s)) return 'answer';
  if (/访谈者|采访者|研究者|主持人|提问者|记录/.test(s)) return 'ask';
  // ② 用"要编谁"反推（a._roles 是研究者确认过的）
  const roles = (a && a._roles) || null;
  if (roles && roles.length) {
    if (roles.indexOf(s) >= 0) return 'answer';
    const sheet = a._sheet;
    if (sheet && speakersOf(sheet).indexOf(s) >= 0) return 'ask';
  }
  return 'other';
}

// 谁在说话（按出场顺序，用于筛选下拉）
function speakersOf(sheet) {
  if (sheet.idx.who < 0) return [];
  const seen = [];
  (sheet.rows || []).forEach(r => {
    const w = String(r[sheet.idx.who] == null ? '' : r[sheet.idx.who]).trim();
    if (w && seen.indexOf(w) < 0) seen.push(w);
  });
  return seen;
}


// 默认"要编的那些人"：**排除**访谈者。
//
// ⚠ 判断"谁是访谈者"光靠名字不够：真实稿子里写着「林晓：」「苏雨桐：」这种**光秃秃的人名**，
//   没有任何"访谈者"字样（实测就是这种情况）。
//   所以按三档来，从可靠到兜底：
//     ① 名字/占位名本身认得出来（`访谈者`、`[姓名2]` 这种）→ 直接用
//     ② **只有两个人**时：访谈稿的惯例是访谈者**先开口**（问候、自我介绍），
//        所以**第一个出现的说话人**是访谈者 —— 这一条在真实转写稿里很稳
//     ③ 认不出来就**都算要编的**（宁可让人多编，也不擅自把受访者的段藏掉）
function defaultCodeRoles(sheet) {
  const all = speakersOf(sheet);
  if (!all.length) return [];
  const byName = [];
  all.forEach(w => {
    // ⚠ 这里**不传角色上下文**（还没定呢，正是这一步在定）—— 只看名字认不认得出。
    const t = speakerTone(w, null);
    if (t !== 'ask') byName.push(w);
  });
  if (byName.length < all.length) return byName;        // ① 认出来了
  if (all.length === 2) {
    // ② 两个人 → 先开口的那个是访谈者
    return [all[1]];
  }
  return all;                                           // ③ 兜底：都编
}

/** 这一段要不要编（角色筛选只管"编不编"，不管"看不看得到"）。 */
function segInScope(a, ri) {
  const roles = a._roles;
  if (!roles || !roles.length) return true;
  const sheet = a._sheet;
  if (!sheet || sheet.idx.who < 0) return true;
  const w = String(sheet.rows[ri][sheet.idx.who] || '').trim();
  return roles.indexOf(w) >= 0;
}

/** 「要编谁」被自动定过吗（用来给一条说明，让人知道深浅是他改之前的默认假设）。 */
function autoRolesNotice(a, sheet) {
  if (!a || !a._autoRoles) return '';
  const asks = speakersOf(sheet).filter(w => speakerTone(w, a) === 'ask');
  if (!asks.length) return '';
  return `<div class="cauto">深浅是按「**${asks.join('、')} 是访谈者**」这个假设画的
    （访谈稿里访谈者先开口）。**要改就直接改左边那些勾** —— 改完深浅跟着变。</div>`;
}

/** 完整原文（左侧）。可滚动、当前段高亮、角色深浅、点击跳段。 */
function panelTranscriptHtml(a) {
  const sheet = a._sheet;
  const ri = a._ri;
  const rows = sheet.rows;
  // ⚠ 太长的稿子一次性铺 DOM 会卡（几百段 × 几千字）。当前这一幕**窗口化**：
  //   当前段前后各留一大截，其余折叠 —— 想看全文用下面的「展开全文」。
  const near = 60;
  const useWindow = rows.length > 220 && !a._fullDoc;
  let from = 0, to = rows.length;
  if (useWindow) {
    from = Math.max(0, ri - near);
    to = Math.min(rows.length, ri + near);
  }
  const tone = (r) => {
    if (sheet.idx.who < 0) return 'other';
    return speakerTone(r[sheet.idx.who], a);
  };
  const seg = (i) => {
    const r = rows[i];
    const who = sheet.idx.who >= 0 ? String(r[sheet.idx.who] || '') : '';
    const raw = sheet.idx.raw >= 0 ? String(r[sheet.idx.raw] || '') : '';
    const done = segDone(sheet, i);
    const inScope = segInScope(a, i);
    return `<div class="dseg t-${tone(r)}${i === ri ? ' cur' : ''}${done ? ' done' : ''}${inScope ? '' : ' out'}"
      data-i="${i}" title="跳到第 ${esc(sheet.idx.id >= 0 ? r[sheet.idx.id] : i + 1)} 段">
      <span class="dno">${esc(sheet.idx.id >= 0 ? r[sheet.idx.id] : i + 1)}</span>
      <span class="dwho">${esc(shortWho(who, a))}</span>
      <span class="dtx">${esc(raw)}</span>
      ${done ? '<span class="dtick">✓</span>' : ''}</div>`;
  };
  const parts = [];
  if (useWindow && from > 0) {
    parts.push(`<div class="dmore" data-more="1">↑ 上面还有 ${from} 段
      （点这里展开全文）</div>`);
  }
  for (let i = from; i < to; i++) parts.push(seg(i));
  if (useWindow && to < rows.length) {
    parts.push(`<div class="dmore" data-more="1">↓ 下面还有 ${rows.length - to} 段
      （点这里展开全文）</div>`);
  }
  return `<div class="docwrap" id="docWrap">
    <div class="dochead">完整原文
      <span class="dochint">当前段高亮 · 点任意一段跳过去 · 背景浅的是访谈者的提问</span>
    </div>
    <div class="docbody">${parts.join('')}</div></div>`;
}

// 长名字（比如 `[受访者1]`）在窄列里挤，缩短显示但 title 里留全名
function shortWho(who, a) {
  const s = String(who || '');
  return s.length <= 5 ? s : s.slice(0, 5) + '…';
}

function chipHtml(fieldKey, code) {
  return `<span class="cchip" data-f="${fieldKey}" data-v="${esc(code)}">${esc(code)}`
    + `<b class="cchipx" title="去掉这个码">×</b></span>`;
}

function panelFieldHtml(a, sheet, ri, f) {
  const codes = a._cur[f.key] || [];
  return `<div class="cfield" data-f="${f.key}">
    <div class="cflabel">${esc(f.label)}
      <span class="cfhint">${codes.length ? codes.length + ' 个' : '还没填'}</span></div>
    <div class="cfbody">
      ${codes.map(c => chipHtml(f.key, c)).join('')}
      <input class="cadd" data-f="${f.key}" placeholder="＋ 打一个码，回车加上" />
    </div></div>`;
}

function panelPaletteHtml(a, sheet, reg) {
  // 已经用过的码：点一下贴到**当前聚焦的那个字段**上
  const blocks = CODE_FIELDS.map(f => {
    const items = Object.keys(reg[f.key])
      .sort((x, y) => reg[f.key][y] - reg[f.key][x] || x.localeCompare(y, 'zh'));
    if (!items.length) return '';
    return `<div class="cpalgrp"><span class="cpalt">${esc(f.label)}</span>${
      items.map(c => `<button class="cpal" data-f="${f.key}" data-v="${esc(c)}">${esc(c)}`
        + `<i>${reg[f.key][c]}</i></button>`).join('')}</div>`;
  }).filter(Boolean).join('');
  return blocks
    ? `<div class="cpal"><div class="cpalh">已经建过的码（点一下贴到当前聚焦的字段）
        <span class="cpalwarn">这些是你自己写的码，程序不替你定名</span></div>${blocks}</div>`
    : `<div class="cpal"><div class="cpalh">还没有任何码 —— 在下面三个框里写第一个。
        <span class="cpalwarn">码是你对材料的理解，程序不替你编</span></div></div>`;
}

/** 角色筛选条：勾谁就编谁（**不影响原文里看不看得到那个人**）。 */
function panelRolesHtml(a, sheet) {
  const all = speakersOf(sheet);
  if (all.length < 2) return '';
  const roles = a._roles || [];
  const cnt = (w) => sheet.rows.filter(r => String(r[sheet.idx.who] || '').trim() === w).length;
  return `<div class="croles">要编谁：
    ${all.map(w => `<label class="crole${roles.indexOf(w) >= 0 ? ' on' : ''}">
      <input type="checkbox" class="crolectl" value="${esc(w)}"${roles.indexOf(w) >= 0 ? ' checked' : ''}>
      <span class="tone t-${speakerTone(w, a)}"></span>${esc(w)}
      <i>${cnt(w)}</i></label>`).join('')}
    <span class="crolehint">不勾的人不进进度、也不算"要编的"，但左边原文里照样看得到</span>
  </div>`;
}

function _findCol(cols, re, fallbackIdx) {
  for (let i = 0; i < cols.length; i++) if (re.test(String(cols[i]))) return i;
  return fallbackIdx >= 0 && fallbackIdx < cols.length ? fallbackIdx : -1;
}

/** 编码表 → {cols, rows, idx:{id,raw,who,open,cat,theme}}。
 *  稳定 id 优先用 `#` 那列（② 生成的表天然有，且实测唯一）；没有就用行号。 */
function codingSheet(a) {
  const p = parseDelimited(a.raw || '');
  const cols = p.cols, rows = p.rows;
  const idx = {
    id: _findCol(cols, /^#|^序号$|^编号$|^段号$/, 0),
    raw: _findCol(cols, RAW_COL_RE, 3),
    who: _findCol(cols, WHO_COL_RE, 1),
    open: _findCol(cols, CODE_FIELDS[0].re, 5),
    cat: _findCol(cols, CODE_FIELDS[1].re, 6),
    theme: _findCol(cols, CODE_FIELDS[2].re, 7),
  };
  // 三列编码列都得找到，否则这不是编码表（别把别的 csv 硬当编码表）
  if (idx.open < 0 || idx.cat < 0 || idx.theme < 0 || idx.raw < 0) return null;
  return { cols: cols, rows: rows, idx: idx, sep: p.sep };
}

/** 一格里的多个码：按 ②b 同一套分隔符拆（中文逗号不拆）。 */
function splitCodes(v) {
  return String(v == null ? '' : v)
    .split(/[、；;/｜|\n]+/).map(s => s.trim()).filter(Boolean);
}

function joinCodes(arr) {
  const seen = [];
  (arr || []).forEach(x => {
    const s = String(x == null ? '' : x).trim();
    if (s && seen.indexOf(s) < 0) seen.push(s);
  });
  return seen.join('；');
}

/** 某一段的三个字段（值都是数组）。 */
function segCodes(sheet, ri) {
  const r = sheet.rows[ri] || [];
  const out = {};
  CODE_FIELDS.forEach(f => { out[f.key] = splitCodes(r[sheet.idx[f.key]]); });
  return out;
}

/** 全表用过的码 → {open:{码:次数}, cat:{...}, theme:{...}}（给"点一下就贴"用）。 */
function codeRegistry(sheet) {
  const reg = { open: {}, cat: {}, theme: {} };
  (sheet.rows || []).forEach(r => {
    CODE_FIELDS.forEach(f => {
      splitCodes(r[sheet.idx[f.key]]).forEach(c => {
        reg[f.key][c] = (reg[f.key][c] || 0) + 1;
      });
    });
  });
  return reg;
}

/** 这一段编完了吗。
 *
 *  ⚠ 判据是**「开放编码填了就算编完」**，不要求三列齐全。
 *    为什么改（2026-09-24 定的）：范畴和主题常常是**最后回头统一归**的，
 *    不是每段当场定 —— 要求三列齐全的话进度条永远显示"编了一半"，
 *    等于这个进度条没有用（他原话："如果按这样算进度的话，就永远不可能百分百编完了"）。
 *    想严格看"三列齐全"的话，面板上单列一个「三列齐全 N 段」的数。
 */
function segDone(sheet, ri) {
  return (segCodes(sheet, ri).open || []).length > 0;
}

/** 三列都填了（真正的"定稿"）—— 只做统计展示，不当进度判据。 */
function segFull(sheet, ri) {
  const c = segCodes(sheet, ri);
  return CODE_FIELDS.every(f => c[f.key].length > 0);
}

/** 填了、但还没填全（进度上算"编完"，但对内是"还要回头补范畴/主题"）。 */
function segPartially(sheet, ri) {
  if (!segDone(sheet, ri)) return false;
  return !segFull(sheet, ri);
}

/** 进度：**只算"要编的那些段"**（角色筛选之外的不计入）。
 *  ⚠ 分母这点很重要：一份访谈里访谈者的提问能占一半（实测 35/70），
 *    全算进去进度永远到不了头，而且 ②b 的"N 段证据"也会虚掉一倍。 */
function panelProgress(sheet, a) {
  const n = sheet.rows.length;
  let done = 0, part = 0, scope = 0, full = 0;
  for (let i = 0; i < n; i++) {
    if (a && !segInScope(a, i)) continue;
    scope++;
    if (segDone(sheet, i)) {
      done++;
      if (segFull(sheet, i)) full++;
      else part++;
    }
  }
  return { total: scope, all: n, done: done, part: part, full: full,
           left: scope - done };
}

/** 找下一段：mode = 'left'（还没编的）/ 'any'（就是下一段）。
 *  只在**角色筛选之内**的段里找 —— 否则"跳到下一段没编的"会把人带到访谈者的提问上。 */
function nextSeg(sheet, from, mode, dir, a) {
  const n = sheet.rows.length;
  const d = dir || 1;
  let i = from + d;
  while (i >= 0 && i < n) {
    if (!a || segInScope(a, i)) {
      if (mode !== 'left' || !segDone(sheet, i)) return i;
    }
    i += d;
  }
  return -1;
}



function codingPanelHtml(a) {
  const sheet = a._sheet;
  if (!sheet || !sheet.rows.length) return '<div class="empty">这个 CSV 里没有数据行</div>';
  if (a._roles === undefined || a._roles === null) {
    a._roles = defaultCodeRoles(sheet);
    // 记一下"这是程序猜的" —— 深浅是基于这个假设画的，得跟人说明白（可改）
    a._autoRoles = true;
  }
  if (a._ri == null || a._ri < 0) a._ri = 0;
  let ri = Math.max(0, Math.min(sheet.rows.length - 1, a._ri));
  // 落在"不编的人"身上时（比如切了筛选），挪到范围内最近的一段
  if (!segInScope(a, ri)) {
    const fwd = nextSeg(sheet, ri, 'any', 1, a);
    const back = nextSeg(sheet, ri, 'any', -1, a);
    if (fwd >= 0) ri = fwd;
    else if (back >= 0) ri = back;
  }
  a._ri = ri;
  a._cur = segCodes(sheet, ri);
  const row = sheet.rows[ri];
  const id = sheet.idx.id >= 0 ? row[sheet.idx.id] : String(ri + 1);
  const who = sheet.idx.who >= 0 ? row[sheet.idx.who] : '';
  const raw = sheet.idx.raw >= 0 ? row[sheet.idx.raw] : '';
  const pr = panelProgress(sheet, a);
  const pct = Math.round(pr.done / Math.max(1, pr.total) * 100);
  const state = segFull(sheet, ri) ? '<span class="cst done">三列齐全</span>'
    : (segDone(sheet, ri) ? '<span class="cst part">编过了（范畴/主题可后补）</span>'
      : '<span class="cst none">还没编</span>');
  const tone = speakerTone(who, a);
  return `<div class="hint" style="margin-bottom:6px">
      逐段编：左边是**完整原文**（点任意一段跳过去）· 点已建的码贴上去 ·
      <b>↑/↓</b> 换段 · <b>Ctrl+Enter</b> 保存 · 改动只写回那三列。
    </div>
    <div class="cbar">
      <div class="cbarfill" style="width:${pct}%"></div>
      <span class="cbartx">要编的 <b>${pr.total}</b> 段里：已编 <b>${pr.done}</b>
        ｜还没碰 ${pr.left}
        <span class="cbarhint">（其中三列齐全 ${pr.full} 段；全表 ${pr.all} 段，
        访谈者的提问不编、也没算进来）</span></span>
    </div>
    <div class="cnote"><b>编完的判据：这一段的「开放编码」有东西</b> ——
      范畴和主题可以最后回头统一归，不要求每段当场填全（所以进度能走到 100%）。
      想看"三列齐全"的进度看上面那个数。</div>
    ${panelRolesHtml(a, sheet)}
    ${autoRolesNotice(a, sheet)}
    <div class="cgrid">
      ${panelTranscriptHtml(a)}
      <div class="cpanel">
        <div class="cmain t-${tone}">
          <div class="cmhead">
            <span class="cmno">第 ${esc(id)} 段</span>
            <span class="ccwho">${esc(who)}</span>
            <span class="ctag t-${tone}">${tone === 'ask' ? '提问' : (tone === 'answer' ? '回答' : '')}</span>
            ${state}
            <span class="grow"></span>
            <span class="cmpos">${ri + 1} / ${sheet.rows.length}</span>
          </div>
          <div class="cmraw">${esc(raw)}</div>
          <div class="cfields">${CODE_FIELDS.map(f => panelFieldHtml(a, sheet, ri, f)).join('')}</div>
        </div>
        ${panelPaletteHtml(a, sheet, codeRegistry(sheet))}
        <div class="row" style="margin-top:8px">
          <button class="btn ghost2" id="cPrev">↑ 上一段</button>
          <button class="btn ghost2" id="cNext">↓ 下一段</button>
          <button class="btn" id="cLeft">→ 跳到下一段没编的</button>
          <span class="grow"></span>
          <span class="hint" style="margin:0" id="cWhere"></span>
        </div>
      </div>
    </div>`;
}

function bindCodingPanel() {
  const a = S.art;
  if (!a || !a._sheet) return;
  const sheet = a._sheet;
  const paint = (keepScroll) => {
    a.raw = sheetToCsv(sheet);
    showArtifactModal();
    if (keepScroll) {
      // 换段之后把左侧原文滚到当前段（不这么做，每换一段都跳回顶部，很晕）
      const wrap = document.getElementById('docWrap');
      const seg = wrap && wrap.querySelector('.dseg.cur');
      if (seg && seg.scrollIntoView) {
        try { seg.scrollIntoView({ block: 'center' }); } catch (e) { /* 忽略 */ }
      }
    }
  };
  // 换段：先把当前这版收进 sheet，再换
  const go = (ri) => {
    if (ri == null || ri < 0 || ri >= sheet.rows.length) return;
    collectPanelInto(sheet, a._cur, a._ri);
    a._ri = ri;
    paint(true);
  };
  const q = (sel) => document.querySelector(sel);
  const on = (sel, fn) => { const e = q(sel); if (e) e.onclick = fn; };
  on('#cPrev', () => go(nextSeg(sheet, a._ri, 'any', -1, a)));
  on('#cNext', () => go(nextSeg(sheet, a._ri, 'any', 1, a)));
  on('#cLeft', () => {
    const i = nextSeg(sheet, a._ri, 'left', 1, a);
    if (i < 0) { setStatus('要编的段都编完了（或者往回找找）'); return; }
    go(i);
  });
  // 左侧全文：点任意一段跳过去（**包括不编的提问段** —— 想看一眼就跳过去看）
  document.querySelectorAll('.dseg').forEach(el => {
    el.onclick = () => {
      const i = Number(el.getAttribute('data-i'));
      if (isNaN(i)) return;
      collectPanelInto(sheet, a._cur, a._ri);
      a._ri = i;
      paint(true);
    };
  });
  // 「展开全文」（长稿默认窗口化，避免一次铺太多 DOM）
  document.querySelectorAll('.dmore').forEach(el => {
    el.onclick = () => { a._fullDoc = true; paint(false); };
  });
  // 角色筛选：只管"编不编"，不管"看不看得到"
  document.querySelectorAll('.crolectl').forEach(cb => {
    cb.onchange = () => {
      collectPanelInto(sheet, a._cur, a._ri);
      a._roles = Array.prototype.slice.call(document.querySelectorAll('.crolectl'))
        .filter(x => x.checked).map(x => x.value);
      paint(false);
    };
  });
  // 去掉某个码
  document.querySelectorAll('.cchipx').forEach(x => {
    x.onclick = (ev) => {
      ev.stopPropagation();
      const chip = x.parentNode;
      const f = chip.getAttribute('data-f'), v = chip.getAttribute('data-v');
      a._cur[f] = (a._cur[f] || []).filter(c => c !== v);
      paint(false);
    };
  });
  // 加码：回车
  document.querySelectorAll('input.cadd').forEach(inp => {
    inp.onkeydown = (ev) => {
      if (ev.key !== 'Enter') return;
      ev.preventDefault();
      const f = inp.getAttribute('data-f');
      const v = String(inp.value || '').trim();
      if (!v) return;
      a._cur[f] = joinCodes((a._cur[f] || []).concat(splitCodes(v))).split('；').filter(Boolean);
      paint(false);
      const again = document.querySelector(`input.cadd[data-f="${f}"]`);
      if (again) again.focus();
    };
  });
  // 点已建过的码 → 贴到**当前聚焦的字段**；没聚焦过就按字段顺序
  a._focusField = a._focusField || 'open';
  document.querySelectorAll('input.cadd').forEach(inp => {
    inp.onfocus = () => { a._focusField = inp.getAttribute('data-f'); setPanelWhere(); };
  });
  document.querySelectorAll('.cpal').forEach(b => {
    b.onclick = () => {
      const f = b.getAttribute('data-f'), v = b.getAttribute('data-v');
      const cur = a._cur[f] || [];
      if (cur.indexOf(v) >= 0) { setStatus('「' + v + '」已经在这段里了'); return; }
      a._cur[f] = cur.concat([v]);
      paint(false);
    };
  });
  // 键盘：↑/↓ 换段（在输入框里时不要抢，免得打字打不了）
  const panel = document.querySelector('.cpanel');
  if (panel) {
    panel.addEventListener('keydown', (ev) => {
      const tag = (ev.target && ev.target.tagName) || '';
      if (tag === 'INPUT') return;
      if (ev.key === 'ArrowDown') { ev.preventDefault(); go(nextSeg(sheet, a._ri, 'any', 1, a)); }
      else if (ev.key === 'ArrowUp') { ev.preventDefault(); go(nextSeg(sheet, a._ri, 'any', -1, a)); }
    });
  }
  // 打开时把当前段滚进视野
  const wrap = document.getElementById('docWrap');
  const seg = wrap && wrap.querySelector('.dseg.cur');
  if (seg && seg.scrollIntoView) {
    try { seg.scrollIntoView({ block: 'center' }); } catch (e) { /* 忽略 */ }
  }
  setPanelWhere();
}

function setPanelWhere() {
  const el = document.getElementById('cWhere');
  if (!el || !S.art || !S.art._sheet) return;
  const sheet = S.art._sheet;
  const pr = panelProgress(sheet, S.art);
  el.textContent = '要编的 ' + pr.total + ' 段里，还没编完 ' + (pr.total - pr.done) + ' 段';
}

/** 把面板里当前这一段的值收进 sheet（改动还没落盘，落盘靠「保存」）。
 *
 *  ⚠ 参数显式传进来（不直接摸全局 `S`）：踩过 —— 原来写的是 `const a = S.art`，
 *    于是这个函数在测试里根本调不动（`S is not defined`），
 *    而它是"面板改的东西到底有没有落进那一行"的唯一出口，**必须能单独测**。
 *  `cur` 缺省时从表里现读（哪个字段是权威：表里那份）。 */
function collectPanelInto(sheet, cur, ri) {
  if (!sheet) return sheet;
  const i = (ri == null) ? 0 : ri;
  const vals = cur || segCodes(sheet, i);
  const row = sheet.rows[i];
  if (!row) return sheet;
  CODE_FIELDS.forEach(f => { row[sheet.idx[f.key]] = joinCodes(vals[f.key] || []); });
  return sheet;
}

/** sheet → CSV（只序列化，不改列顺序）。
 *  ⚠ 分隔符**必须沿用原文件那个**，不能拿列名去猜 ——
 *    「说话人,原文」这种 TSV 的列名里没有逗号，猜出来会是错的。 */
function sheetToCsv(sheet) {
  return serializeDelimited(sheet.cols, sheet.rows, sheet.sep || ',');
}

function showModal(html) { $('#modalBox').innerHTML = html; $('#modal').classList.add('on'); }
function closeModal() { $('#modal').classList.remove('on'); }
window.closeModal = closeModal;

$('#modal').onclick = (e) => { if (e.target.id === 'modal') closeModal(); };

document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape') {
    if ($('#modal').classList.contains('on')) closeModal();
    else if (S.confirm.open) closeConfirm();
  }
});
window.closeConfirm = closeConfirm;
window.openConfirm = openConfirm;

$('#projSel').onchange = (e) => {
  // 「（还没选项目）」那一项：不让切过去（切了也没地方放产物），点一次就弹回去
  if (!e.target.value) { renderProjects(); setStatus('先新建一个项目，或从下拉里选一个'); return; }
  switchProject(e.target.value);
};

// 删除：删的是**当前选中的那个**
$('#btnDelProj').onclick = () => {
  const p = curProject();
  if (!p) { setStatus('先在下拉里选中要删的项目'); return; }
  deleteProject(p.root);
};

$('#btnNewProj').onclick = () => {
  showModal(`<h3>新建研究项目</h3><p>会在 <code>projects/</code> 下建一个新目录</p>
    <div class="field"><input type="text" id="npName" placeholder="比如：校园二手平台_访谈研究"></div>
    <div class="actions"><button class="btn" onclick="closeModal()">取消</button>
    <button class="btn primary" id="npGo">创建</button></div>`);
  $('#npGo').onclick = async () => {
    const name = $('#npName').value.trim();
    const j = await post('/api/project/create', { name });
    if (!j.ok) { alert(j.error); return; }
    closeModal();
    clearProjectState();
    await loadState(j.project.root);
  };
};

$('#btnOpenProj').onclick = () => {
  showModal(`<h3>打开已有目录</h3><p>把任何一个研究项目目录交给工作台</p>
    <div class="field"><input type="text" id="opPath" placeholder="C:\\...\\某个项目目录"></div>
    <div class="actions">
      <button class="btn ghost2" id="opBrowse">📁 选文件夹…</button>
      <span class="grow"></span>
      <button class="btn" onclick="closeModal()">取消</button>
      <button class="btn primary" id="opGo">打开</button></div>`);
  const ob = $('#opBrowse');
  if (ob) ob.onclick = async () => {
    const j = await pickPath('dir', { start: $('#opPath').value, title: '选择研究项目目录' });
    if (j) { $('#opPath').value = j.path; setStatus('选好了：' + j.path); }
  };
  $('#opGo').onclick = async () => {
    const root = $('#opPath').value.trim();
    const j = await post('/api/project/open', { root });
    if (!j.ok) { alert(j.error); return; }
    closeModal();
    clearProjectState();
    await loadState(root);
  };
};

/* ---------------- 项目快照：存成一个文件 / 从文件还原现场 ----------------

   为什么要有这个：模型给的初稿、手工填的参数、跑出来的结果，都在浏览器的内存里，
   刷新一下就没。落成文件才算真的留着，也才拿得走、发得出。 */

function fmtBytes(n) {
  n = Number(n) || 0;
  if (n < 1024) return n + ' B';
  if (n < 1024 * 1024) return (n / 1024).toFixed(1) + ' KB';
  if (n < 1024 * 1024 * 1024) return (n / 1024 / 1024).toFixed(1) + ' MB';
  return (n / 1024 / 1024 / 1024).toFixed(2) + ' GB';
}

function openSaveProject() {
  const root = (S.state && S.state.project && S.state.project.root) || '';
  const name = (S.state && S.state.project && S.state.project.name) || '';
  const nArt = ((S.state && S.state.project && S.state.project.artifacts) || []).length;
  const lastDir = (S.state && S.state.config && S.state.config.export_dir) || '';
  showModal(`<h3>把项目存成一个文件</h3>
    <p>把「<b>${esc(name)}</b>」整个目录（契约 + 数据 + 产物 + 处理日志${''}，共 ${nArt} 个产物）
       打成一个 <code>.urwproj</code> 文件，放到你指定的文件夹。</p>
    <div class="field">
      <label>存到哪个文件夹</label>
      <div class="row">
        <input type="text" class="grow" id="saveDir" value="${esc(lastDir)}"
               placeholder="比如：D:\\我的研究\\快照  或  C:\\Users\\你\\Desktop">
        <button class="btn ghost2 pickbtn" id="saveBrowse" title="打开文件夹选一个位置">📁 选文件夹…</button>
      </div>
      <div class="hint">文件夹不存在会自动建。以后导入这个文件，就能把这套现场原样还原。</div>
    </div>
    <div class="checks" style="margin-top:6px">
      <label class="check on" id="chkHist" data-v="1">
        <input type="checkbox" checked> 连 <code>_history/</code> 一起存（覆盖前的备份，能回溯）
      </label>
    </div>
    <div id="saveMsg"></div>
    <div class="actions">
      <button class="btn" onclick="closeModal()">取消</button>
      <button class="btn primary" id="saveGo">💾 存到这个文件夹</button>
    </div>`);

  const chk = $('#chkHist');
  if (chk) chk.onclick = (ev) => {
    ev.preventDefault();
    const on = !chk.classList.contains('on');
    chk.classList.toggle('on', on);
    chk.querySelector('input').checked = on;
  };
  const dirBox = $('#saveDir');
  if (dirBox) { dirBox.focus(); dirBox.select(); }
  const sb = $('#saveBrowse');
  if (sb) sb.onclick = async () => {
    const j = await pickPath('dir', { start: ($('#saveDir').value || '').trim(),
                                      title: '选择快照存到哪个文件夹' });
    if (j) { $('#saveDir').value = j.path; setStatus('存到：' + j.path); }
  };

  $('#saveGo').onclick = async () => {
    const dir = ($('#saveDir').value || '').trim();
    if (!dir) { $('#saveMsg').innerHTML = '<div class="banner err">先填一个文件夹路径</div>'; return; }
    const btn = $('#saveGo');
    btn.disabled = true;
    btn.innerHTML = '<span class="spin">◌</span> 正在打包…';
    setStatus('正在把项目打成文件…');
    const withHist = $('#chkHist').classList.contains('on');
    const j = await post('/api/project/export', {
      dir: dir, with_history: withHist, project: root,
    });
    if (!j.ok) {
      $('#saveMsg').innerHTML = '<div class="banner err">存不了：' + esc(j.error) + '</div>';
      btn.disabled = false;
      btn.innerHTML = '💾 存到这个文件夹';
      setStatus('保存失败');
      return;
    }
    const s = j.snapshot;
    $('#saveMsg').innerHTML = `<div class="banner ok">
        存好了：<b>${esc(s.file)}</b><br>
        ${s.files} 个文件，打包后 ${fmtBytes(s.size)}（原来 ${fmtBytes(s.raw_bytes)}）<br>
        <span style="font-size:12.5px">以后点「导入…」选这个文件，就能把这套现场还原出来。</span>
      </div>
      <div class="actions" style="margin-top:10px">
        <button class="btn" id="saveReveal">打开所在文件夹</button>
      </div>`;
    const rv = $('#saveReveal');
    if (rv) rv.onclick = () => post('/api/reveal', { path: s.file });
    btn.disabled = false;
    btn.innerHTML = '💾 再存一份';
    setStatus('已保存快照：' + s.file);
    refreshProject();
  };
}

async function importProject(file) {
  if (!file) return;
  setStatus('正在还原「' + file.name + '」…');
  showModal(`<h3>正在还原现场</h3><p>${esc(file.name)} · ${fmtBytes(file.size)}
    —— 正在解开、放到 projects/ 下。</p>`);
  try {
    const r = await fetch('/api/project/import', { method: 'POST', body: file });
    const j = await r.json();
    if (!j.ok) throw new Error(j.error || '导入失败');
    closeModal();
    clearProjectState();
    await loadState(j.project.root);
    setStatus('已还原：' + j.project.name + '（原来的现场在 ' +
              ((j.snapshot || {})['原始路径'] || '?') + '）');
  } catch (e) {
    showModal(`<h3>还原失败</h3>
      <div class="banner err">${esc(e.message || String(e))}</div>
      <div class="actions"><button class="btn" onclick="closeModal()">知道了</button></div>`);
    setStatus('导入失败');
  }
}

$('#btnSaveProj').onclick = openSaveProject;
$('#btnImportProj').onclick = () => $('#fileImport').click();
$('#fileImport').onchange = (e) => {
  const f = e.target.files && e.target.files[0];
  e.target.value = '';
  if (f) importProject(f);
};

/* ---------------- 主题：浅色 / 深色 ----------------
   初值由 index.html 里那段内联脚本落好（它在样式表之前跑，免得白闪）。
   这里只管「点一下切过去 + 记住选择」。没点过 = 跟随系统。

   ⚠ 两套都要有：内联那段是**唯一**能在样式表之前跑的地方（防白闪），
     而它没法测；这里这份是能被 `_uitest.js` 直接调的正式实现。 */
// 读「人自己选过吗」（null = 没选过 → 跟随系统）。localStorage 在无痕模式会抛，一律当"没选过"
function readSavedTheme(dep){
  const ls = (dep && dep.storage) || (typeof localStorage !== 'undefined' ? localStorage : null);
  try { return ls ? ls.getItem('urw.theme') : null; } catch (e) { return null; }
}
// 系统现在是不是深色
function systemPrefersDark(dep){
  try {
    if (dep && typeof dep.systemDark === 'boolean') return dep.systemDark;
    return !!(typeof matchMedia === 'function' && matchMedia('(prefers-color-scheme: dark)').matches);
  } catch (e) { return false; }
}
// 初值：人选的 > 系统。返回定下来的那个（纯函数，测试直接调它）
function initializeTheme(dep){
  const saved = readSavedTheme(dep);
  const t = (saved === 'dark' || saved === 'light') ? saved : (systemPrefersDark(dep) ? 'dark' : 'light');
  applyTheme(t);
  return t;
}
function applyTheme(t){
  const root = document.documentElement;
  // ⚠ `_uitest.js` 里搭的是**假 DOM**，没有 documentElement —— 少这一道判断，
  //   整个前端回归会在加载 app.js 的那一步就死掉（而且报错看着跟主题毫无关系）。
  if (!root || typeof root.setAttribute !== 'function') return;
  root.setAttribute('data-theme', t === 'dark' ? 'dark' : 'light');
  const b = $('#btnTheme');
  if (b) b.title = '切换浅色 / 深色（现在是' + (t === 'dark' ? '深色' : '浅色') + '）';
}
function toggleTheme(){
  const root = document.documentElement;
  const now = (root && root.getAttribute && root.getAttribute('data-theme') === 'dark') ? 'dark' : 'light';
  const next = now === 'dark' ? 'light' : 'dark';
  applyTheme(next);
  // 点了就算"人自己选的"：从此不再跟随系统（不然人刚切完，系统一变又被掰回去）
  try { localStorage.setItem('urw.theme', next); } catch (e) { /* 无痕模式：这次有效，下次忘了 */ }
}
{
  const tb = $('#btnTheme');
  if (tb) tb.onclick = toggleTheme;
  // ⚙ 设置（SPSS 路径 / 模型 API）
  const sb = $('#btnSettings');
  if (sb) sb.onclick = showSettings;
  initializeTheme();
}

/* ---------------- 起步 ---------------- */

loadState();
setInterval(() => { if (!S.running) refreshProject(); }, 20000);
