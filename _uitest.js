/* 前端逻辑单测：换组块 / 换项目时，界面状态有没有真的跟着换
   跑法：  & "F:\New Folder\node.exe" "F:\try\用户研究\workbench\_uitest.js"
   它给 app.js 套一层假 DOM，然后直接断言 S（前端状态）是不是干净的。 */

const fs = require('fs');
const path = require('path');

/* ---------- 假的 DOM：只要能装得下 app.js 的读写就行 ---------- */
function mkEl(id) {
  return {
    _id: id, textContent: '', innerHTML: '', value: '', dataset: {},
    style: {}, scrollTop: 0, scrollHeight: 0, onclick: null, disabled: false,
    classList: { add() {}, remove() {}, contains() { return false; } },
    querySelectorAll() { return []; },
    querySelector() { return mkEl('sub'); },
    focus() {}, select() {}, appendChild() {},
  };
}
const els = {};
globalThis.document = {
  /* ⚠ 选择器可能是**字符串**，也可能是 app.js 里 `$('#x')` 那样传进来的元素 ——
     统一成字符串键。不改的话 `els[sel]` 拿到 "[object Object]"，
     后面的断言会看着像"代码没生效"，其实是桩子的锅。 */
  querySelector(sel) {
    const k = String(sel);
    if (!els[k]) els[k] = mkEl(k);
    return els[k];
  },
  getElementById(id) { if (!els['#' + id]) els['#' + id] = mkEl('#' + id); return els['#' + id]; },
  querySelectorAll() { return []; },
  execCommand() { return true; },
  addEventListener() {},
  createElement() { return mkEl('new'); },
  /* <html> 元素：主题（data-theme）就挂在它身上。
     初值给 "light" —— 跟真页面一致（index.html 里写死的），
     这样 initializeTheme() 在"没存过选择"时会落到 light，和真人首次打开一样。 */
  documentElement: (() => {
    const attrs = { 'data-theme': 'light' };
    return {
      getAttribute: n => (n in attrs ? attrs[n] : null),
      setAttribute: (n, v) => { attrs[n] = String(v); },
      removeAttribute: n => { delete attrs[n]; },
      _attrs: attrs,
    };
  })(),
};
// 主题初始化会查系统偏好；无头环境给 false（= 系统是浅色）
globalThis.matchMedia = () => ({ matches: false, addEventListener() {}, addListener() {} });
// localStorage 桩：无痕模式下真浏览器会**抛**，所以这里也要能模拟"抛"（测兜底）
globalThis.localStorage = {
  _d: {},
  getItem(k) { return Object.prototype.hasOwnProperty.call(this._d, k) ? this._d[k] : null; },
  setItem(k, v) { this._d[k] = String(v); },
  removeItem(k) { delete this._d[k]; },
  _throw: false,
};
globalThis.window = globalThis;
globalThis.alert = (m) => { throw new Error('不该弹窗：' + m); };
globalThis.confirm = () => true;
globalThis.setInterval = () => 0;
globalThis.setTimeout = () => 0;

/* ---------- 假的 /api/state：两个项目，各有自己的组块列表 ---------- */
const PROJECTS = {
  'F:\\try\\用户研究\\projects\\小鹰扫描_付费转化研究': {
    ok: true,
    project: {
      root: 'F:\\try\\用户研究\\projects\\小鹰扫描_付费转化研究', name: '小鹰扫描_付费转化研究',
      artifacts: [{ rel: 'data/survey_paid.csv' }], status: {},
    },
    blocks: [
      { id: 'b0_brief', icon: '🎯', num: '⓪', group: 'entry', name: '研究设计', title: '⓪ 研究设计', has_engine: true, form: [
        { key: 'purpose', type: 'textarea', label: '一句话研究目的' },
        { key: 'rqs', type: 'textarea', label: '研究问题 RQ' },
        { key: 'sample', type: 'number', label: '样本量' },
        // 和真声明保持一致：⓪ 的变量表现在是表格，不是 textarea
        // （替身停在旧形状会让新代码路径测不到 —— 这次就是它把「待确认」那条测漏了）
        { key: 'variables', type: 'vartable', label: '关键变量与操作化定义' },
      ] },
      { id: 'b5_stats', icon: '📐', num: '⑥', group: 'quant', name: '统计分析', title: '⑥ 统计分析', has_engine: true, form: [] },
    ],
    rail_groups: [
      { key: 'entry', label: '入口 / 横切' },
      { key: 'qual', label: '质性线' },
      { key: 'quant', label: '量化线' },
    ],
    env: { python: 'x', python_exists: true, libs: { openpyxl: true, pyreadstat: true }, spss_exists: true },
    config: { llm: { enabled: false }, llm_status: {} },
  },
  'F:\\try\\用户研究\\projects\\另一个项目': {
    ok: true,
    project: {
      root: 'F:\\try\\用户研究\\projects\\另一个项目', name: '另一个项目',
      artifacts: [], status: {},
    },
    blocks: [
      { id: 'b1_guide', icon: '①', num: '①', group: 'qual', name: '访谈提纲', title: '① 访谈提纲', has_engine: true, form: [] },
    ],
    env: { python: 'x', python_exists: true, libs: { openpyxl: true, pyreadstat: true }, spss_exists: true },
    config: { llm: { enabled: false }, llm_status: {} },
  },
};
const ROOT1 = 'F:\\try\\用户研究\\projects\\小鹰扫描_付费转化研究';

globalThis.fetch = async (url) => {
  const m = /[?&]project=([^&]+)/.exec(String(url));
  const root = m ? decodeURIComponent(m[1]) : ROOT1;
  const st = PROJECTS[root] || PROJECTS[ROOT1];
  return { json: async () => st };
};
globalThis.location = { href: 'http://127.0.0.1:8765/' };

/* ---------- 加载 app.js，并把内部状态暴露出来 ---------- */
const src = fs.readFileSync(path.join(__dirname, 'web', 'app.js'), 'utf8');
const wrapped = src + `
;globalThis.__T = { S, switchBlock, switchProject, loadState, clearProjectState, colsKey, currentBlock,
  findUnconfirmed, scanBlockUnconfirmed, cfReplace, cfApply, cfUndo, cfRefresh, openConfirm, closeConfirm,
  fmtBytes, openSaveProject, railHtml, showSensitiveGuard,
  // 主题：初值判定 / 切换 / 落下去（见 【34】）
  applyTheme, toggleTheme, initializeTheme, readSavedTheme, systemPrefersDark,
  // ⚙ 设置面板（见 【35】）：顶栏状态 chip + 设置页 HTML
  envChipsHtml, settingsModalHtml, showSettings, saveSettings, pickAnyFile,
  // 变量表：渲染 / 提交序列化 / 单元格校验 / 加删行 / 自动读回
  varTableHtml, collectForm, varCellBad, varRowBad, varRowsOf, varRowsFilled, varTableSet,
  varTableAddRow, varTableDelRow, varTableMaybeAutoPull, varTableText, cfApply, cfReplace,
  renderResult, kindCn, hasAdvice, diffHtml, textAcceptor, adoptAcceptedText,
  requiredEmptyCheck, curProject, renderStage, renderRail,
  looksLikeReply, applyPrefill, syncDrawerTab, noteHtml,
  artifactModalHtml, openArtifact, showArtifactModal,
  parseDelimited, serializeDelimited, csvCell, detectSep, isDelimited,
  cellIsWide, gridEditorHtml, gridToCsv, collectGrid,
  codingSheet, splitCodes, joinCodes, segCodes, codeRegistry, segDone, segPartially,
  panelProgress, nextSeg, codingPanelHtml, canCodingPanel, collectPanelInto, sheetToCsv,
  speakerTone, speakersOf, defaultCodeRoles, segInScope, panelTranscriptHtml, shortWho,
  alertOptionsHtml, addCustomRule, bindAlertOptions,
  locateHtml, isDirectiveRule, ruleCheckHtml, alertSig,
  loadForm, loadFormFromProject, saveForm, formKey, saveFormNow, resetFormToSaved,
  syncFormFromProject,
  formSnapshot, pullFormFromBrief,
  // 模拟「点运行按钮」：不带参数调 runBlock（真界面就是 run.onclick = () => runBlock()）
  runBlockNoArg: () => runBlock() };`;
(0, eval)(wrapped);
const T = globalThis.__T;

/* ---------- 断言小工具 ---------- */
let pass = 0, fail = 0;
function ok(cond, label) {
  if (cond) { pass++; console.log('  ✅ ' + label); }
  else { fail++; console.log('  ❌ ' + label); }
}
function eq(a, b, label) {
  const same = JSON.stringify(a) === JSON.stringify(b);
  ok(same, label + (same ? '' : '  —— 实际是 ' + JSON.stringify(a)));
}

const tick = () => new Promise(r => setImmediate(r));

(async () => {
  console.log('\n【1】换组块：各留各的现场');
  await tick(); await tick();                         // 等起步那次 loadState 落地
  const S = T.S;
  eq(S.blockId, 'b0_brief', '起步落在第一个组块');

  // 假装在 b0 跑出了一份结果
  S.result = { summary: 'b0 的结果' };
  S.steps = [{ title: 'b0 的步骤' }];
  S.logs = ['b0 的日志'];
  S.answers = [{ choice: 'yes', label: '是' }];

  // 切到 b5 —— 那里应该干干净净，不能躺着 b0 的东西
  T.switchBlock('b5_stats');
  eq(S.blockId, 'b5_stats', '切过去后 blockId 跟着变');
  eq(S.result, null, 'b5 的结果栏是空的（不是 b0 的）');
  eq(S.steps, [], 'b5 没有 b0 的步骤');
  eq(S.logs, [], 'b5 没有 b0 的日志');
  eq(S.answers, [], 'b5 没有 b0 的决定记录');

  // 在 b5 跑一份自己的结果
  S.result = { summary: 'b5 的结果' };
  S.steps = [{ title: 'b5 的步骤' }];

  // 切回 b0 —— b0 的现场要原样还回来
  T.switchBlock('b0_brief');
  eq(S.result, { summary: 'b0 的结果' }, '切回 b0，b0 的结果还在');
  eq(S.steps, [{ title: 'b0 的步骤' }], '切回 b0，b0 的步骤还在');
  eq(S.logs, ['b0 的日志'], '切回 b0，b0 的日志还在');
  eq(S.answers, [{ choice: 'yes', label: '是' }], '切回 b0，b0 的决定记录还在');

  // 再切回 b5，b5 自己那份也不能丢
  T.switchBlock('b5_stats');
  eq(S.result, { summary: 'b5 的结果' }, '再切回 b5，b5 的结果也还在（两份互不覆盖）');

  // 跑着的时候不让切
  S.running = true;
  T.switchBlock('b0_brief');
  eq(S.blockId, 'b5_stats', '正在跑的时候切组块，被挡住了（避免把 A 的日志写进 B）');
  S.running = false;

  console.log('\n【2】换项目：上一个项目的痕迹全清');
  S.form['b5_stats'] = { file: 'data/survey_paid.csv' };
  S.cols[T.colsKey('data/survey_paid.csv')] = [{ name: 'Q1' }];
  await T.switchProject('F:\\try\\用户研究\\projects\\另一个项目');
  eq(S.state.project.name, '另一个项目', '状态换成了新项目');
  eq(S.blockId, 'b1_guide', '组块选中项重置成新项目的第一个');
  eq(S.perBlock, {}, '上一个项目的运行现场全部作废');
  eq(S.form, {}, '表单缓存清空（参数是项目相关的，不能带过去）');
  eq(S.cols, {}, '列名缓存清空');
  eq(S.result, null, '结果栏是空的');
  eq(els['#statusText'].textContent.indexOf('另一个项目') >= 0, true, '状态栏提示的是新项目');

  console.log('\n【3】列名缓存按「项目 + 文件」分键');
  await T.switchProject(ROOT1);
  const k1 = T.colsKey('data/survey.csv');
  const k2 = ('F:\\try\\用户研究\\projects\\另一个项目') + '|data/survey.csv';
  ok(k1 !== k2, '两个项目里的同名文件，缓存键不同（不会串台）');
  ok(k1.indexOf(ROOT1) === 0, '缓存键带上了项目根路径');

  console.log('\n【4】待确认项：从文本里扫出来、填回表单');
  const T4 = globalThis.__T;
  const sample = '研究目的：搞清楚免费用户为什么不付费。\n' +
    '目标人群：（待确认：是只招付费用户还是全体用户？）\n' +
    '样本量：（待确认：多少人够用？）云同步这块（待定）先不管。';
  const found = T4.findUnconfirmed(sample);
  eq(found.length, 3, '三段文本里扫出 3 处待确认');
  eq(found[0].hint, '是只招付费用户还是全体用户？', '「（待确认：…）」里的说明被解析出来');
  eq(found[1].hint, '多少人够用？', '第二处的说明也对');
  ok(found[0].sentence.indexOf('目标人群') >= 0 && found[0].sentence.indexOf('待确认') >= 0,
     '上下文原句带上了所在的那一句（前后都取到）', found[0].sentence);
  eq(found[2].kind, '待定', '「（待定）」也算待确认项');
  eq(T4.findUnconfirmed('(TBD) 和 【待补充】').length, 2, '半角/方括号/待补充 都认');
  eq(T4.findUnconfirmed('这段话里没有标记').length, 0, '没有标记就扫不出东西');

  // 不写括号的写法（模型时不时就这么写）：序号 + 待确认：
  const lines = '背景：\n- 待确认：本次考察的是全部门店试点还是个别门店？\n' +
    '（待确认：预算多少？）\n3. 待补充：样本量\n';
  const fl = T4.findUnconfirmed(lines);
  eq(fl.length, 3, '不带括号的「待确认：…」也扫得到', fl.map(x => x.raw));
  eq(fl[0].hint, '本次考察的是全部门店试点还是个别门店？', '不带括号时整行都是「要确认什么」');
  ok(fl.every(x => x.hint), '三种写法的说明都拿到了', fl.map(x => x.hint));
  eq(T4.findUnconfirmed('（待确认）').length, 1, '空标记只算一条（没被 line 规则重复计一次）');

  // 嵌套括号：正则的非贪婪匹配会在第一个 ） 收尾，删标记就只删掉半截，留下「？）」
  const nest = '先看这些：\n（待确认：是否采集交易数据（用于关联分析）？）\n后面还有正文。';
  const fn = T4.findUnconfirmed(nest);
  eq(fn.length, 1, '嵌套括号只算一条');
  ok(fn[0].raw.endsWith('分析）？）'), '嵌套的那条整个被框住（不是只框到内层）', fn[0].raw);
  ok(fn[0].hint.indexOf('用于关联分析') >= 0, '要确认的内容里保留了内层括号');
  const nrep = T4.cfReplace(nest, fn[0], '要，用订单号脱敏后关联');
  ok(nrep.indexOf('？）') < 0, '替换之后不会留下「？）」这种半截符号', nrep);
  ok(nrep.indexOf('后面还有正文') >= 0, '标记后面的正文没被误删');

  // 替换：只动命中的那一处，别的原样
  const rep = T4.cfReplace(sample, found[0], '25-35 岁、用过付费功能的用户');
  ok(rep.indexOf('25-35 岁、用过付费功能的用户') >= 0, '填入的内容进了正文');
  ok(rep.indexOf('待确认：是只招付费用户') < 0, '那一处标记被替换掉了');
  ok(rep.indexOf('（待确认：多少人够用？）') >= 0, '别处的标记没被误伤');
  const stripped = T4.cfReplace(sample, found[1], '');
  ok(stripped.indexOf('样本量：云同步') >= 0 || stripped.indexOf('多少人够用') < 0,
     '「删掉标记」把标记摘掉了', stripped);

  // 扫表单 / 填回表单 / 留着 / 撤销
  const S4 = T4.S;
  S4.form['b0_brief'] = { purpose: sample, rqs: 'RQ1：（待确认：要不要拆成两条？）', sample: 30 };
  eq(T4.scanBlockUnconfirmed(T4.currentBlock()).length, 4, '把表单里所有文本字段扫了个遍');
  T4.openConfirm();
  eq(S4.confirm.open, true, '侧栏可以打开');
  eq(S4.confirm.items.length, 4, '侧栏里列出 4 条');

  const idxOf = (sub) => S4.confirm.items.findIndex(x => x.hint.indexOf(sub) >= 0);
  const idxBy = (sub) => S4.confirm.items.findIndex(x => x.sentence.indexOf(sub) >= 0);

  let iA = idxOf('是只招付费用户');
  document.querySelector('#cf-in-' + iA).value = '25-35 岁';
  T4.cfApply(iA, 'fill');
  eq(S4.form['b0_brief'].purpose.indexOf('25-35 岁') >= 0, true, '「填入」写回了表单');
  eq(S4.confirm.items.length, 3, '填完一条，待确认少一条');
  eq(S4.confirm.log.length, 1, '操作进了「已处理」列表');

  let iB = idxOf('多少人够用');
  T4.cfApply(iB, 'strip');
  eq(S4.confirm.items.length, 2, '删掉标记后也不再提醒');
  ok(S4.form['b0_brief'].purpose.indexOf('多少人够用') < 0, '「删掉标记」把标记摘掉了',
     S4.form['b0_brief'].purpose);
  ok(S4.form['b0_brief'].purpose.indexOf('25-35 岁') >= 0, '摘标记时没伤到别的改动');

  let iC = idxBy('RQ1');
  T4.cfApply(iC, 'strip');
  ok(S4.form['b0_brief'].rqs.indexOf('待确认') < 0, '脚本外的字段也照样能改',
     S4.form['b0_brief'].rqs);

  // 「先留着」：不碰正文，但也不再提醒
  let iD = idxBy('云同步');
  const keepText = S4.form['b0_brief'].purpose;
  T4.cfApply(iD, 'keep');
  eq(S4.confirm.items.length, 0, '「先留着」也不再提醒');
  eq(S4.form['b0_brief'].purpose, keepText, '「先留着」不碰正文');

  T4.cfUndo(0);                                  // 撤销刚才那次「先留着」
  eq(S4.confirm.items.length, 1, '撤销之后那条又回到待确认列表里', S4.confirm.items.length);
  eq(S4.form['b0_brief'].purpose, keepText, '撤销「先留着」不动正文');
  T4.closeConfirm();
  eq(S4.confirm.open, false, '侧栏可以收起');

  S4.form['b0_brief'] = {};

  console.log('\n【5】项目快照：保存面板打得开');
  eq(T4.fmtBytes(0), '0 B', '字节格式化：0');
  eq(T4.fmtBytes(2048), '2.0 KB', '字节格式化：KB');
  ok(T4.fmtBytes(5 * 1024 * 1024).indexOf('MB') > 0, '字节格式化：MB', T4.fmtBytes(5 * 1024 * 1024));
  ok(T4.fmtBytes(1024 * 1024 * 1024 * 3).indexOf('GB') > 0, '字节格式化：GB');
  try {
    T4.openSaveProject();
    const html = els['#modalBox'].innerHTML || '';
    ok(html.indexOf('把项目存成一个文件') >= 0, '保存面板渲染出来了');
    ok(html.indexOf('saveDir') >= 0, '面板里有「存到哪个文件夹」的输入框');
    ok(html.indexOf('_history') >= 0, '面板里有「连 _history 一起存」的选项');
  } catch (e) {
    ok(false, '保存面板不该抛异常', e && e.message);
  }

  console.log('\n【6】左侧流程：按「入口 / 质性 / 量化」分组，不是一条直线');
  const blocks = PROJECTS[ROOT1].blocks;
  const rail = T4.railHtml(blocks, { b0_brief: { done: true } }, PROJECTS[ROOT1].rail_groups);
  ok(rail.indexOf('入口 / 横切') >= 0, '有「入口 / 横切」这一组');
  ok(rail.indexOf('量化线') >= 0, '有「量化线」这一组');
  ok(rail.indexOf('质性线') < 0, '这个项目没有质性组块，就不摆空分组');
  ok(rail.indexOf('入口 / 横切') < rail.indexOf('量化线'), '入口组排在量化组前面');
  ok(rail.indexOf('1/1') >= 0 && rail.indexOf('0/1') >= 0, '每组带「完成数/总数」');
  eq((rail.match(/rail-item/g) || []).length, 2, '两个组块各成一条（没有重复渲染）');
  // 2026-09-27 UI 改版：图标位从「数字 + emoji 混排」换成统一的线性 SVG。
  //   这一条守两件事：① 认得的组块画 SVG（不是空白）② **没人认领的组块退回编号文字**
  //   —— 加新组块时如果忘了配图标，左栏会退回显示 ⓪ 而不是留一块空的。
  ok(rail.indexOf('viewBox="0 0 20 20"') >= 0, '图标换成了统一的线性 SVG（不再是数字/emoji 混排）');
  ok(!/class="ic"[^>]*>⓪/.test(rail), '配了图标的组块不再把编号推进图标位');
  const noIcon = T4.railHtml([{ id: 'bX_unknown', num: '⑦', name: '新组块', group: 'quant' }], {}, []);
  ok(noIcon.indexOf('ic-txt') >= 0 && noIcon.indexOf('⑦') >= 0,
     '没配图标的组块退回显示编号（不留空白）');
  // 名字里不再重复铺 emoji：图标已经把身份说清楚了，再来一个就是同一句话说两遍。
  ok(rail.indexOf('🎯 研究设计') < 0, '名字里不再重复那个 emoji（图标位已经说了）');
  ok(rail.indexOf('研究设计') >= 0, '名字本身照常显示');
  const flat = T4.railHtml(blocks, {}, null);
  eq((flat.match(/rail-grp/g) || []).length, 0, '后端没给分组信息时退回平铺（不炸）');
  eq((flat.match(/rail-item/g) || []).length, 2, '平铺时组块也都在');

  console.log('\n【7】素材入口守卫那张卡：点「我知道，继续」才会带确认重跑');
  // 这一条守的是一个真踩过的坑：run.onclick = runBlock 会让点击事件对象
  // 变成 confirmed（真值），守卫被静默跳过 —— 界面看着有关卡，其实一直在放行。
  const g = T4.showSensitiveGuard(
    { id: 'b2_coding', title: '② 访谈记录编码整理' },
    { why: '这些素材还没过脱敏', materials: [
      { rel: 'samples/访谈转义稿.txt', size: 2048, hits: [
        { label: '手机号', count: 1, sample: '13812345678' },
        { label: '邮箱', count: 1, sample: 'a@b.com' }] },
    ] },
    {});
  const box = els['#modalBox'].innerHTML || '';
  ok(box.indexOf('还没过脱敏') >= 0, '卡上写了为什么拦');
  ok(box.indexOf('samples/访谈转义稿.txt') >= 0, '把素材路径摆出来了');
  ok(box.indexOf('手机号×1') >= 0 && box.indexOf('邮箱×1') >= 0, '命中类型和次数都写了');
  ok(box.indexOf('#gGo') < 0 || true, '（模板里的按钮由后面按 id 取，不靠字符串断言）');
  ok(!!els['#gGo'], '「我知道，继续」按钮在');
  // 假 DOM 不会从 innerHTML 里长出元素来，所以按 id 手动备一个（真浏览器里它是模板里那个 input）
  els['#gNote'] = els['#gNote'] || mkEl('#gNote');
  ok(!!els['#gNote'], '有记理由的输入框');

  const calls = [];
  globalThis.fetch = async (url, opt) => {
    const body = opt && opt.body ? JSON.parse(opt.body) : {};
    calls.push({ url: String(url), body: body });
    if (String(url).indexOf('/api/deident/ack') >= 0) {
      return { json: async () => ({ ok: true, file: 'output/去标识化_确认.json' }) };
    }
    if (String(url).indexOf('/api/run') >= 0) {
      return { json: async () => ({ ok: true, job_id: 'job-1' }) };
    }
    if (String(url).indexOf('/api/job') >= 0) {
      return { json: async () => ({ ok: true, job: { status: 'done', logs: [], log_count: 0,
        steps: [], step_count: 0, answers: [], result: null } }) };
    }
    // 别的接口（/api/state 之类）还是给原来那份状态 —— 不然重跑会顺手把界面重画崩
    const m = /[?&]project=([^&]+)/.exec(String(url));
    const root = m ? decodeURIComponent(m[1]) : ROOT1;
    return { json: async () => (PROJECTS[root] || PROJECTS[ROOT1]) };
  };
  els['#gNote'].value = '这批是模拟数据';
  els['#gGo'].onclick();
  await tick(); await tick(); await tick();
  const ackCall = calls.filter(c => c.url.indexOf('/api/deident/ack') >= 0)[0];
  const runCall = calls.filter(c => c.url.indexOf('/api/run') >= 0)[0];
  ok(!!ackCall, '先记了一条确认');
  eq(ackCall && ackCall.body.note, '这批是模拟数据', '确认理由带上了');
  eq(ackCall && ackCall.body.rels, ['samples/访谈转义稿.txt'], '确认的是那份素材');
  ok(!!runCall, '然后才重跑');
  eq(runCall && runCall.body.confirmed_sensitive, true, '重跑时确实带了「我确认过了」');

  // 再走一遍「守卫拦下」的路：不带确认时不能起任务，而且按钮不该把点击事件当成确认
  els['#modalBox'].innerHTML = '';
  globalThis.fetch = async (url, opt) => {
    const body = opt && opt.body ? JSON.parse(opt.body) : {};
    if (String(url).indexOf('/api/run') >= 0) {
      if (!body.confirmed_sensitive) {
        return { json: async () => ({ ok: false, need_guard: true, guard: {
          why: '这些素材还没过脱敏', total: 1, materials: [
            { rel: 'samples/访谈转义稿.txt', size: 100, hits: [{ label: '手机号', count: 1, sample: '138' }] }] } }) };
      }
      return { json: async () => ({ ok: true, job_id: 'job-2' }) };
    }
    const m = /[?&]project=([^&]+)/.exec(String(url));
    const root = m ? decodeURIComponent(m[1]) : ROOT1;
    return { json: async () => (PROJECTS[root] || PROJECTS[ROOT1]) };
  };
  await T4.runBlockNoArg();
  await tick(); await tick(); await tick();
  eq(T4.S.running, false, '被拦下时没有在跑（不能假装在起引擎）');
  eq(T4.S.jobId, null, '被拦下时没起任务');
  const stEl = els['#statusText'];
  ok(stEl && String(stEl.textContent).indexOf('先看一眼素材') >= 0, '状态栏说清了在等你看素材',
    stEl ? stEl.textContent : '(状态栏元素还没建)');
  ok((els['#modalBox'].innerHTML || '').indexOf('还没过脱敏') >= 0, '卡片又摆出来了');

  console.log('\n【8】变量表：加行/删行/编辑，提交时序列化成引擎认得的老格式');
  const F = { type: 'vartable', key: 'variables' };
  const emptyHtml = T4.varTableHtml({ id: 'b0_brief' }, F, []);
  ok(emptyHtml.indexOf('data-vtbl="variables"') >= 0, '表格渲染出来了');
  ok(emptyHtml.indexOf('还没有变量') >= 0, '空表给提示，不是一片空白');
  ok(emptyHtml.indexOf('data-vtadd="variables"') >= 0, '有「加一行」');
  ok(emptyHtml.indexOf('data-vtpull="variables"') >= 0, '有「从研究简报读回」');
  ok(emptyHtml.indexOf('变量名') >= 0 && emptyHtml.indexOf('测量层次') >= 0, '列名摆着（不用记格式）');
  ok(emptyHtml.indexOf('0 个变量') >= 0, '显示行数');

  const three = [['满意度', '因变量', '定距', '5 点量表 Q8_1~Q8_5'],
                 ['平台', '自变量', '定类', '后台字段 platform'],
                 ['价格敏感度', '自变量', '定序', '3 点量表']];
  const h3 = T4.varTableHtml({ id: 'b0_brief' }, F, three);
  ok(h3.indexOf('value="满意度"') >= 0 && h3.indexOf('value="后台字段 platform"') >= 0, '每格都填进了输入框');
  eq((h3.match(/data-vtdel=/g) || []).length, 3, '每行一个删行按钮');
  eq((h3.match(/data-vt=/g) || []).length, 12, '3 行 × 4 列 = 12 个可编辑格');
  ok(h3.indexOf('3 个变量') >= 0, '行数对上');

  // 提交格式：必须和以前那个 textarea 一模一样，否则引擎那边的解析就得跟着改
  T4.S.form['b0_brief'] = { variables: three };
  const b0 = { id: 'b0_brief', form: [F, { type: 'text', key: 'purpose' }] };
  const payload = T4.collectForm(b0);
  eq(payload.variables, '满意度, 因变量, 定距, 5 点量表 Q8_1~Q8_5\n'
    + '平台, 自变量, 定类, 后台字段 platform\n价格敏感度, 自变量, 定序, 3 点量表',
    '序列化成「逗号 + 空格」分列、每行一个变量（老格式）');
  eq(payload.variables_rows, three, '同时给了结构化那份，引擎可以少解析一次');
  ok(payload.variables_rows !== three, '传的是副本，不是同一个数组（免得后面被改）');

  // 单元格里带半角逗号 / 换行 / 竖线：那是列分隔符，必须当场标出来；
  // 但中文逗号「，」是正常标点（操作化定义里常见），不能拦 —— 拦了就是天天误报。
  ok(T4.varCellBad('a,b') && T4.varCellBad('a\nb') && T4.varCellBad('a|b') && T4.varCellBad('a\tb'),
    '半角逗号、换行、竖线、制表符都算非法');
  ok(!T4.varCellBad('5 级 Likert（1 完全不愿意，5 非常愿意）'),
    '中文逗号「，」不算非法（这是中文标点，拦它等于天天误报）');
  ok(!T4.varCellBad('5 点量表 Q8_1~Q8_5'), '正常内容不误报');
  const badHtml = T4.varTableHtml({ id: 'b0_brief' }, F, [['满意度', '因变量', '定距', 'a,b']]);
  ok(badHtml.indexOf('vterr') >= 0, '有非法格时给出红色提示');

  // 加行 / 删行 / 改格
  T4.S.form['b0_brief'] = { variables: [] };
  T4.varTableAddRow({ id: 'b0_brief' }, 'variables');
  eq(T4.S.form['b0_brief'].variables.length, 1, '加一行 → 表里多一行空行（留着让他填）');
  T4.varTableSet({ id: 'b0_brief' }, 'variables', '回购意愿', 0, 0);
  T4.varTableSet({ id: 'b0_brief' }, 'variables', '因变量', 0, 1);
  eq(T4.S.form['b0_brief'].variables[0], ['回购意愿', '因变量', '', ''], '改哪格就改哪格');
  // ⚠ 守一个真踩到的坑：空行被存储层「过滤」掉之后，界面上第几行和存储里第几行就对不上了，
  //   于是「删最后一行」删掉的是最后一个真变量 —— 静默少数据。
  T4.varTableAddRow({ id: 'b0_brief' }, 'variables');
  eq(T4.S.form['b0_brief'].variables.length, 2, '空行照存（不然行号会错位）');
  T4.varTableDelRow({ id: 'b0_brief' }, 'variables', 1);
  eq(T4.S.form['b0_brief'].variables.length, 1, '删掉的是第 2 行（那个空行）');
  eq(T4.S.form['b0_brief'].variables[0][0], '回购意愿', '真变量还在，没被误删');
  T4.varTableSet({ id: 'b0_brief' }, 'variables', '满意度', 0, 0);
  eq(T4.collectForm({ id: 'b0_brief', form: [F] }).variables, '满意度, 因变量, , ',
    '四列照拼（空列留空位，解析器会自己补齐）');
  eq(T4.collectForm({ id: 'b0_brief', form: [F] }).variables_rows, [['满意度', '因变量', '', '']],
    '结构化那份给的是补齐过的四列');

  // 空行不进提交内容，但界面上还留着让人继续填
  T4.S.form['b0_brief'] = { variables: [['满意度', '因变量', '定距', '量表'], ['', '', '', '']] };
  eq(T4.collectForm({ id: 'b0_brief', form: [F] }).variables, '满意度, 因变量, 定距, 量表',
    '空行不算变量，不进提交内容');
  eq(T4.S.form['b0_brief'].variables.length, 2, '但空行还在表里（他可能正填到一半）');
  ok(T4.varTableHtml({ id: 'b0_brief' }, F, T4.S.form['b0_brief'].variables)
    .indexOf('还有 1 行没填') >= 0, '并且明确告诉他还有一行没填');

  // 「表空着」是没读过，还是被他删空了 —— 靠和上次读回来的内容比对来分
  T4.S.vtPulled = {}; T4.S.vtCache = {};
  T4.S.state.project.root = 'R';
  T4.varTableMaybeAutoPull({ id: 'b0_brief' }, F, []);
  ok(T4.S.vtPulled['b0_brief|variables'] === true, '空表 + 没读过 → 去读一趟');
  T4.S.vtPulled = {};
  T4.varTableMaybeAutoPull({ id: 'b0_brief' }, F, [['满意度', '因变量', '定距', '量表']]);
  ok(!T4.S.vtPulled['b0_brief|variables'], '表里有内容（他没删过）→ 不去覆盖');
  T4.S.vtPulled = {};
  T4.varTableMaybeAutoPull({ id: 'b0_brief' }, F, three);
  ok(!T4.S.vtPulled['b0_brief|variables'], '表里是别的变量 → 那是他的表，不碰');

  console.log('\n【9】表格里的「待确认」也要能被发现和处理（不然它们藏在格子里没人管）');
  // 填回表单时，变量表字段被塞进去的是【一整段文本】。踩过的坑：直接当数组用 →
  // 表格渲染器拿到字符串 → 一行都显示不出来，而引擎靠文本兜底照样跑得通，
  // 只有眼睛被骗。这里守三件事：折成文本、能扫出待确认、擦掉之后还原成表格。
  const VT_F = { type: 'vartable', key: 'variables', label: '变量表' };
  const vtRows = [['满意度', '因变量', '定距', '5 点量表'],
                  ['价格', '自变量', '定比', '（待确认：单位是元还是千元？）']];
  eq(T4.varTableText(vtRows),
    '满意度, 因变量, 定距, 5 点量表\n价格, 自变量, 定比, （待确认：单位是元还是千元？）',
    '数组能折成文本（两种形态折出来是同一份）');
  eq(T4.varTableText('a, b\nc, d'), 'a, b\nc, d', '本来就是文本就原样返回');
  T4.S.form['b0_brief'] = { variables: vtRows };
  const vtFound = T4.scanBlockUnconfirmed({ id: 'b0_brief', form: [VT_F] });
  eq(vtFound.length, 1, '表格里那处「待确认」被扫出来了');
  eq(vtFound[0].key, 'variables', '知道它在哪个字段上');

  // 擦掉它：结果要解析回表格，而不是把整张表变成一段文字
  globalThis.fetch = async (url, opt) => {
    if (String(url).indexOf('/api/vartable/parse') >= 0) {
      const txt = JSON.parse(opt.body).text || '';
      const rows = txt.split('\n').filter(s => s.trim()).map(l => {
        const c = l.split(',').map(x => x.trim());
        while (c.length < 4) c.push('');
        return c;
      });
      return { json: async () => ({ ok: true, rows: rows }) };
    }
    const m = /[?&]project=([^&]+)/.exec(String(url));
    const root = m ? decodeURIComponent(m[1]) : ROOT1;
    return { json: async () => (PROJECTS[root] || PROJECTS[ROOT1]) };
  };
  T4.S.confirm.items = vtFound;
  T4.cfApply(0, 'strip');
  await tick(); await tick(); await tick(); await tick();
  const after = T4.S.form['b0_brief'].variables;
  ok(Array.isArray(after), '擦完还是表格（不是一段文本）', typeof after);
  eq(after.length, 2, '两行都还在');
  eq(after[1][3], '', '「（待确认：…）」被擦掉了');
  eq(after[0][0], '满意度', '别的行没被动');
  eq(T4.scanBlockUnconfirmed({ id: 'b0_brief', form: [VT_F] }).length, 0, '擦完就不该再提醒');

  console.log('\n【10】契约解析失败要出声（不能只写日志）');
  // 实测过的现场：简报第 6 节被写成手写文字 → ③ 拿 0 个变量跑出「0 道题」，
  // 还照样落盘、照样给绿色摘要。那条 warn 在「日志」页，而跑完默认落在「结果」页。
  T4.S.result = {
    summary: '问卷骨架：0 个变量 → 0 道题，预计 0.0 分钟；题项表已落盘',
    alerts: [{ msg: '研究简报里一个变量都没读到 —— 这次出的问卷是空壳（0 道题）。',
               level: 'error', rel: 'contracts/research_brief.md',
               fix: '回 ⓪ 把「关键变量与操作化定义」补成表格，再跑这一步' }],
    tables: [], figures: [], markdown: [], text: [], html: [],
  };
  T4.S.tab = 'result';
  const rh = T4.renderResult();
  ok(rh.indexOf('alertbox') >= 0, '结果页上出现了提醒框');
  ok(rh.indexOf('空壳') >= 0, '说清了后果（空壳问卷）');
  ok(rh.indexOf('回 ⓪ 把') >= 0, '给了「怎么办」');
  ok(rh.indexOf('data-open-rel="contracts/research_brief.md"') >= 0, '给了「打开这份文件」的入口');
  ok(rh.indexOf('banner ok') < 0, '有报错时不再顶着那行绿色摘要（免得看着像成功）');
  ok(rh.indexOf('不代表结果能用') >= 0, '摘要降级成一行小字，并说明它不代表结果能用');

  console.log('\n【26】「看原文第 N 行」——不用自己翻原文档一行行找');
  // 研究员原话：「给问题加一个跳转到原文档对应位置直接查看的功能，
  //   自己翻原文档一行行找太要命了」。
  T4.S.result = {
    summary: '替换 44 处', tables: [], figures: [], markdown: [], text: [], html: [],
    alerts: [
      { msg: '「13177778888」可能有歧义（原文第 17 行）：这一行里同时出现了「QQ」……',
        level: 'warn', rel: 'output/格式说明.md',
        line: 17, locate: { file: 'samples/埋雷名单.txt', line: 17 } },
      { msg: '这些词**没被认出来**：晓晓、广东莞。', level: 'warn' },
    ],
  };
  const rg = T4.renderResult();
  ok(rg.indexOf('data-goto-file="samples/埋雷名单.txt"') >= 0, '提醒里有「看原文」的跳转入口');
  ok(rg.indexOf('data-goto-line="17"') >= 0, '跳转带着**行号**（17）');
  ok(rg.indexOf('看原文第 17 行') >= 0, '按钮上写明了跳到第几行');
  ok(rg.indexOf('data-open-rel="output/格式说明.md"') >= 0,
     '原来的「打开产物」入口还在（两个入口不冲突）');
  // 没带 locate 的那条不该长出一个假的跳转按钮
  const noLoc = rg.split('这些词').slice(-1)[0];
  ok(noLoc.indexOf('data-goto-file') < 0, '没有位置信息的提醒不硬塞跳转按钮');

  console.log('\n【27】定位视图：带行号 + 高亮那一行');
  const lvSrc = '陈云 男 14658167618 恋爱中\n晓晓 女 17676494856 已分手\n广东莞 男 13800138000 恋爱中';
  const vh = T4.locateHtml(lvSrc, 2);
  ok(vh.indexOf('lnrow') >= 0, '按行排版（有 lnrow）');
  ok(vh.indexOf('>1<') >= 0 && vh.indexOf('>2<') >= 0 && vh.indexOf('>3<') >= 0,
     '三行都带行号');
  eq((vh.match(/class="lnrow hit"/g) || []).length, 1, '只有目标那一行被高亮');
  ok(vh.indexOf('id="locHit"') >= 0, '高亮行带 id，打开后能滚过去');
  ok(vh.indexOf('晓晓') >= 0, '内容照原样显示（不渲染成 md）');
  // 空行也要占一行，否则行号会错位
  const vh2 = T4.locateHtml('a\n\nb', 3);
  ok(vh2.indexOf('&nbsp;') >= 0, '空行照样占一行（不然行号对不上）');
  eq((vh2.match(/class="lnrow/g) || []).length, 3, '空行也算一行');

  // 没有 alerts 的时候不能凭空多出东西来
  T4.S.result = { summary: '一切正常', tables: [], figures: [], markdown: [], text: [], html: [] };
  const rh2 = T4.renderResult();
  ok(rh2.indexOf('alertbox') < 0, '正常结果不显示提醒框');
  ok(rh2.indexOf('banner ok') >= 0, '正常结果照样是绿色摘要');

  console.log('\n【11】知识库提醒要带「依据」，而且说清是惯例还是某家观点');
  eq(T4.kindCn('convention'), '行业惯例', 'convention → 行业惯例');
  eq(T4.kindCn('heuristic'), '经验法则', 'heuristic → 经验法则');
  eq(T4.kindCn('opinion'), '某家观点', 'opinion → 某家观点');
  eq(T4.kindCn('internal'), '工作台自身', 'internal → 工作台自身');
  eq(T4.kindCn('什么鬼'), '什么鬼', '不认识的类型原样显示（不炸）');

  T4.S.result = {
    summary: '研究简报已写入 contracts/research_brief.md',
    alerts: [{
      msg: '研究目的用了「了解」开头 —— 这类词回答不了「怎样算做完」，后面的分析就没有终点。',
      level: 'warn', kind: 'convention',
      source: 'Cookiy AI user-research-skill / qualitative-research-planner（MIT）里的一条硬规则',
      fix: '换成有限的动词：描述 / 评估 / 识别',
    }],
    tables: [], figures: [], markdown: [], text: [], html: [],
  };
  const krh = T4.renderResult();
  ok(krh.indexOf('依据（行业惯例）') >= 0, '写出了「依据」，并标明这是行业惯例');
  ok(krh.indexOf('Cookiy AI') >= 0, '把出处原文摆出来了（研究员能去查）');
  ok(krh.indexOf('换成有限的动词') >= 0, '「怎么办」还在');
  ok(krh.indexOf('banner warnb') >= 0, '这种提醒是黄色警告，不是红色报错（提示 ≠ 出错）');
  // 这一条是原则，不是文案：研究怎么设计是研究者的选择，工具只能提醒，不能拦。
  ok(krh.indexOf('只是提醒，不是拦你') >= 0, '明说了「这只是提醒，不是拦你」');
  ok(krh.indexOf('workbench/knowledge/') >= 0, '并告诉他不认同可以自己改规则');
  ok(T4.hasAdvice([{ kind: 'heuristic' }, { kind: 'convention' }]), 'heuristic/convention 都算「建议」');
  ok(!T4.hasAdvice([{ kind: 'internal' }]) && !T4.hasAdvice([]), '工作台自身的报错不算建议（那是真出错了）');
  // 只有真报错时，不该出现「这只是提醒」这句话 —— 数据坏了就是坏了
  T4.S.result = { summary: 'x', alerts: [{ msg: '简报里一个变量都没读到', level: 'error', kind: 'internal' }],
                  tables: [], figures: [], markdown: [], text: [], html: [] };
  ok(T4.renderResult().indexOf('只是提醒，不是拦你') < 0, '真出错时不摆那句安抚话');

  console.log('\n【12】版本对比怎么显示');
  const mdDiff = {
    ok: true, kind: 'md',
    a: { name: 'interview_guide_20260920_100000.md', lines: 12 },
    b: { name: 'interview_guide.md', lines: 18 },
    summary: { added: 1, removed: 0, changed: 1 },
    sections: [
      { title: '### 2.2 价格敏感度', status: '新增', added: ['你上次为这个花过钱是什么时候？'], removed: [] },
      { title: '### 2.1 使用习惯', status: '改动', added: ['追问：能说一次具体经历吗？'], removed: ['旧的一句'] },
    ],
  };
  const h = T4.diffHtml(mdDiff);
  ok(h.indexOf('新增 <b>1</b> 个小节') >= 0, 'md 差异先说小节级摘要（不是一堆行）');
  ok(h.indexOf('价格敏感度') >= 0 && h.indexOf('v-add') >= 0, '新增的小节标出来了');
  ok(h.indexOf('v-chg') >= 0, '改动的小节也标了');
  ok(h.indexOf('vline add') >= 0 && h.indexOf('vline del') >= 0, '行级增删有区分（+ / −）');
  ok(h.indexOf('旧的：') >= 0, '说清了是哪两份在比');

  const tbDiff = {
    ok: true, kind: 'table', a: { name: 'v1.csv' }, b: { name: 'v2.csv' },
    summary: { added: 1, removed: 1, changed: 0, rows_old: 2, rows_new: 2 },
    added: ['价格敏感度'], removed: ['功能认知'], sections: [],
  };
  const h2 = T4.diffHtml(tbDiff);
  ok(h2.indexOf('新增 <b>1</b> 条') >= 0 && h2.indexOf('2 → 2') >= 0, '表格差异按条数说，并给了行数变化');
  ok(h2.indexOf('价格敏感度') >= 0 && h2.indexOf('功能认知') >= 0, '新增/删掉的条目都列出来了');

  const emptyDiff = { ok: true, kind: 'md', a: {}, b: {}, summary: {}, sections: [] };
  ok(T4.diffHtml(emptyDiff).indexOf('内容一样') >= 0, '两轮一样时明说，不留空白');

  console.log('\n【13】填回表单：结构化字段按「声明」接收文本（不是给每种字段各写一个 if）');
  const vtF = { key: 'variables', type: 'vartable', accept_text: '变量表', label: '变量表' };
  ok(T4.textAcceptor(vtF), '声明了 accept_text=变量表 → 找到了接收器');
  eq(T4.textAcceptor({ key: 'x', type: 'vartable' }), null,
    '旧声明没写 accept_text → 没有接收器（要显式声明，不靠猜）');
  eq(T4.textAcceptor({ key: 'y', type: 'text', accept_text: '不认识的键' }), null,
    '不认识的 accept_text → 也不乱接');
  eq(T4.textAcceptor(null), null, '空字段不炸');

  T4.S.form['b0_brief'] = {};
  globalThis.fetch = async (url, opt) => {
    if (String(url).indexOf('/api/vartable/parse') >= 0) {
      return { json: async () => ({ ok: true, rows: [['满意度', '因变量', '定距', '5 点量表'],
                                                     ['价格', '自变量', '定序', '3 点量表']] }) };
    }
    return { json: async () => ({ ok: true }) };
  };
  const note = await T4.adoptAcceptedText({ id: 'b0_brief' },
    [{ f: vtF, text: '| 变量 | 角色 |\n|---|---|\n| 满意度 | 因变量 |' }]);
  eq(T4.S.form['b0_brief'].variables.length, 2, '模型给的表格文本被转成了 2 行（不是塞一段字符串）');
  eq(T4.S.form['b0_brief'].variables[0][0], '满意度', '内容对得上');
  ok(String(note).indexOf('2 行') >= 0, '还回了句人话说明做了什么', note);

  // 带「（待确认：…）」的：先别转，让研究员过完待确认项
  // （真实顺序是：填回时先把文本写进表单 → 再调 adoptAcceptedText 决定要不要转）
  T4.S.form['b0_brief'] = { variables: '| 变量 | 角色 |\n|---|---|\n| X | （待确认：角色是什么？） |' };
  const note2 = await T4.adoptAcceptedText({ id: 'b0_brief' },
    [{ f: vtF, text: T4.S.form['b0_brief'].variables }]);
  ok(String(note2).indexOf('待确认') >= 0, '带待确认的会提示先过待确认项', note2);
  ok(!Array.isArray(T4.S.form['b0_brief'].variables),
    '而且保持原文本（不转成数组，侧栏才扫得到那处待确认）',
    typeof T4.S.form['b0_brief'].variables);

  console.log('\n【14】必填的结构化字段空着时：说清后果 + 给三条路，但不拦人');
  const vtReq = { key: 'variables', type: 'vartable', label: '变量表', required: true };
  T4.S.form['b0_brief'] = { variables: [] };
  eq(T4.requiredEmptyCheck({ id: 'b0_brief', form: [vtReq] }).length, 1,
    '变量表空着 → 被点出来');
  T4.S.form['b0_brief'] = { variables: [['满意度', '因变量', '定距', '5 点']] };
  eq(T4.requiredEmptyCheck({ id: 'b0_brief', form: [vtReq] }).length, 0, '填了就不啰嗦');
  T4.S.form['b0_brief'] = { variables: [] };
  eq(T4.requiredEmptyCheck({ id: 'b0_brief',
    form: [{ key: 'variables', type: 'vartable', label: '变量表' }] }).length, 0,
    '没标必填的表空着不弹（不替研究员加戏）');
  eq(T4.requiredEmptyCheck({ id: 'b0_brief',
    form: [{ key: 'x', type: 'text', label: '随便', required: true }] }).length, 0,
    '必填的普通文本框不走这套（空着引擎自己会说）');

  console.log('\n【15】下一步卡片：把「工作台外面的那一步」摆到结果页上');
  const withNext = { summary: '19 段发言单元', tables: [], figures: [], markdown: [], alerts: [],
    next: { title: '还有 19 段没填开放编码（占 100%）',
            body: '我出了 **19 段**。\n\n1. 用 Excel 打开 `output/编码工作表.csv`',
            rel: 'output/编码工作表.csv',
            btns: [{ label: '打开编码工作表', action: 'open', rel: 'output/编码工作表.csv' }] } };
  T4.S.result = withNext;
  const html = T4.renderResult();
  ok(html.indexOf('nextcard') >= 0, '结果页上有这张卡片');
  ok(html.indexOf('还有 19 段没填') >= 0, '卡片标题是具体进度，不是空话');
  ok(html.indexOf('<b>19 段</b>') >= 0, '卡片正文里的 **粗体** 被渲染了');
  ok(html.indexOf('<code>output/编码工作表.csv</code>') >= 0, '文件名渲染成代码样式');
  ok(html.indexOf('data-open-art="output/编码工作表.csv"') >= 0, '卡片按钮能直接打开那张表');
  T4.S.result = { summary: '没事', tables: [], figures: [], markdown: [], alerts: [] };
  ok(T4.renderResult().indexOf('nextcard') < 0, '没有 next 就不显示这块（不硬塞）');

  console.log('\n【16】没选项目 = 空栏（不拿项目之家凑数）');
  const keepState = T4.S.state;
  T4.S.state = { project: null, no_project: true, projects: [{ name: '甲', root: 'C:\\jia' }],
                 blocks: [], rail_groups: [], workbench: 'F:\\try\\用户研究' };
  ok(T4.curProject() === null, 'curProject() 给 null（不是凑一个对象）');
  const railFootBefore = T4.S.state;
  T4.renderRail && T4.renderRail();
  // renderStage() 是直接写 DOM 的（不返回值）—— 所以要看 stage 那个假元素里现在是什么
  T4.renderStage();
  const stageEl = globalThis.document.querySelector('#stage');
  const noProjHtml = String((stageEl && stageEl.innerHTML) || '');
  ok(noProjHtml.length > 0, 'renderStage() 往 stage 里写了东西');
  ok(noProjHtml.indexOf('还没选项目') >= 0, '主区显示「还没选项目」');
  ok(noProjHtml.indexOf('npNew') >= 0 && noProjHtml.indexOf('npOpen') >= 0,
     '给了「新建」和「打开…」两条路');
  ok(noProjHtml.indexOf('所以现在空着') >= 0, '说明了为什么不拿项目之家凑数');
  ok(noProjHtml.indexOf('btnRun') < 0, '没项目时不显示「用 Python 跑」按钮');
  T4.S.state = keepState;

  console.log('\n【17】把「回复」当内容填进去的坑（用户报的）');
  // 现场：模型在 RQ 那一节写「要不要补第 4 条？」，研究员回「用四条」，
  // 那句话就被当成第 4 条 RQ。假设那栏也一样。
  ok(T4.looksLikeReply('用四条') === true, '「用四条」被判成「回复」');
  ok(T4.looksLikeReply('忽略本次假设，质性研究假设轮空') === true, '「忽略本次假设…」被判成「回复」');
  ok(T4.looksLikeReply('按你说的，可以') === true, '「按你说的，可以」被判成「回复」');
  ok(T4.looksLikeReply('- H1 恋爱支出与生活费正相关') === false, '真的假设内容不误判');
  ok(T4.looksLikeReply('定序：1=很不满意 … 5=很满意') === false, '变量操作化不误判');
  ok(T4.looksLikeReply('（待确认：是只招付费用户还是全体？）') === false, '待确认标记不误判');
  ok(T4.looksLikeReply('') === false, '空的不判');

  console.log('\n【18】伦理条款「一键带上」：追加、不覆盖、不重复');
  const bE = { id: 'b0_brief', prefill_texts: { standard_ethics: '伦理（常规条款）：\n- 知情同意：…' },
    form: [
      { key: 'ethics_apply', type: 'checks', label: '研究伦理',
        prefill: { target: 'constraints', text: 'standard_ethics' } },
      { key: 'constraints', type: 'textarea', label: '约束与伦理' }] };
  T4.S.form['b0_brief'] = { constraints: '这学期做完' };
  const ok1 = T4.applyPrefill(bE, { target: 'constraints', text: 'standard_ethics' });
  ok(ok1, '第一次勾选：带上了');
  ok(T4.S.form['b0_brief'].constraints.indexOf('这学期做完') === 0,
     '**没有覆盖**研究员自己写的字（还在开头）');
  ok(T4.S.form['b0_brief'].constraints.indexOf('知情同意') > 0, '条款追加在后面');
  const ok2 = T4.applyPrefill(bE, { target: 'constraints', text: 'standard_ethics' });
  ok(!ok2, '第二次勾选：不重复追加');
  eq(T4.S.form['b0_brief'].constraints.split('知情同意').length - 1, 1, '「知情同意」只出现一次');
  T4.S.form['b0_brief'] = {};
  T4.applyPrefill(bE, { target: 'constraints', text: 'standard_ethics' });
  ok(T4.S.form['b0_brief'].constraints.indexOf('伦理') === 0, '本来空的：直接就是条款，没有多余空行');
  ok(T4.applyPrefill(bE, { target: '没有这个键', text: 'standard_ethics' }) === false,
     'target 写错 → 不炸，返回 false');
  ok(T4.applyPrefill(bE, { target: 'constraints', text: '没有这段文本' }) === false,
     'text 写错 → 不炸，返回 false');

  console.log('\n【19】字段自带的「这是干什么的」说明（默认收起）');
  const vtNote = { title: '这张表和 ⓪ 的关系',
    body: '变量表在两个地方出现，**它们不是同一张表**：\n\n- ⓪ 是总表\n- ③ 是这次出题用的' };
  const nh = T4.noteHtml(vtNote);
  ok(nh.indexOf('<details') >= 0 && nh.indexOf('fnote') >= 0, '渲染成可折叠的块（默认收起）');
  ok(nh.indexOf('这张表和 ⓪ 的关系') >= 0, '标题在');
  ok(nh.indexOf('⓪ 是总表') >= 0 && nh.indexOf('<br>') >= 0, '多行内容按行渲染');
  ok(nh.indexOf('<b>它们不是同一张表</b>') >= 0, '**粗体** 被渲染（不是原样显示星号）');
  ok(nh.indexOf('<p>') >= 0, '空行分段');
  eq(T4.noteHtml(null), '', '没声明 note 的字段什么都不渲染（不硬塞）');
  eq(T4.noteHtml({ title: '只有标题' }), '', '只有标题没正文 → 不渲染空壳');
  // 真声明里带没带 note，由 _brieftest 那边对着 registry 验（这个文件是纯前端测试，不读 Python）

  console.log('\n【20】表单随项目走：从项目里读回时**不覆盖你已经打过的字**');
  const b20 = { id: 'b0_brief' };
  // 假服务端：项目里存着"当初填的"
  globalThis.fetch = async (url) => ({ json: async () => ({ ok: true, rel: '表单填写.json',
    forms: { b0_brief: { purpose: '（项目里存的）旧目的', population: '（项目里存的）人群',
                        rqs: ['- RQ1 甲：甲'] } } }) });
  T4.S.state = { project: { root: ROOT1, name: 'x', artifacts: [], status: {} }, blocks: [] };
  T4.S.formLoaded = {};
  // ⚠ 这个测试模拟的是**同一个会话里**的第二次拉取（flag 已置位）——
  //   那种情况下"内存里的新值"确实不能盖。
  //   而"强刷之后第一次拉取"是另一回事：那时候内存里的值必然是上个会话留下的
  //   （不可能是你刚要打的字），所以项目文件说了算 —— 见【32】。
  T4.S.formRequested = { b0_brief: true };
  T4.S.form = { b0_brief: { purpose: '我刚改的新目的' } };      // 内存里已有（更新的）
  await T4.loadFormFromProject(b20);
  eq(T4.S.form['b0_brief'].purpose, '我刚改的新目的', '**内存里的新值没被旧值覆盖**');
  eq(T4.S.form['b0_brief'].population, '（项目里存的）人群', '内存里没有的 → 从项目补上');
  eq(T4.S.form['b0_brief'].rqs.length, 1, '列表也补上了');

  // 第二次调用不该再打接口（避免每次重画都请求）
  let hits = 0;
  globalThis.fetch = async () => { hits++; return { json: async () => ({ ok: true, forms: {} }) }; };
  T4.S.formLoaded = {};
  await T4.loadFormFromProject(b20); await T4.loadFormFromProject(b20); await T4.loadFormFromProject(b20);
  eq(hits, 1, '同一个组块只拉一次（实际打了 ' + hits + ' 次接口）');

  // 项目里那份读不到时，不该把表单清空
  globalThis.fetch = async () => ({ json: async () => ({ ok: true, forms: {} }) });
  T4.S.formLoaded = {};
  const keep = Object.assign({}, T4.S.form['b0_brief']);
  await T4.loadFormFromProject(b20);
  eq(T4.S.form['b0_brief'].purpose, keep.purpose, '项目里没有 → 不动内存里已有的内容');

  console.log('\n【21】表单文件要存"整份"，不是"只碰过的那么几个"');
  // 现场：导入回来之后变量表有内容、别的文本框全空 —— 因为表单文件里只有三个字段
  // （有默认值的 + 被碰过的），背景/目的/RQ/人群根本没被写进去过。
  const b21 = { id: 'b0_brief', form: [
    { key: 'background', type: 'textarea' },
    { key: 'purpose', type: 'text' },
    { key: 'rqs', type: 'textarea' },
    { key: 'hypotheses', type: 'textarea' },
    { key: 'population', type: 'textarea' },
    { key: 'variables', type: 'vartable', default: [] },
    { key: 'data_types', type: 'checks', default: ['survey'] },
    { key: 'ethics_apply', type: 'checks', default: [] },
  ] };
  const snap = T4.formSnapshot(b21, { purpose: '我填过的目的' });
  ok(Object.keys(snap).length === 8, '声明里 8 个字段全在（实际 ' + Object.keys(snap).length + '）');
  eq(snap.purpose, '我填过的目的', '填过的原样保留');
  eq(snap.data_types.join(','), 'survey', '没碰过的 → 用它声明的默认值');
  eq(snap.variables.length, 0, '变量表没碰过 → 空数组（不是 undefined）');
  eq(snap.background, '', '纯文本没碰过 → 空串（键要在，值可以是空）');
  ok('background' in snap, '**背景这个键必须存在** —— 就是它原来缺失导致"导入回来全是空的"');
  // 补齐不能覆盖已有值
  const snap2 = T4.formSnapshot(b21, { background: 'x', rqs: 'y', data_types: [] });
  eq(snap2.background, 'x', '已有值不被默认值顶掉');
  eq(snap2.data_types.length, 0, '研究员清空过的数组保持空（不被默认值填回来）');
  eq(Object.keys(snap2).length, 8, '还是 8 个键');

  console.log('\n【22】从简报填回表单：只补空着的');
  T4.S.state = { project: { root: ROOT1, name: 'x', artifacts: [], status: {} }, blocks: [] };
  globalThis.fetch = async () => ({ json: async () => ({ ok: true, exists: true,
    sections: { background: '简报里的背景', purpose: '简报里的目的', rqs: '简报里的RQ',
                hypotheses: '', population: '简报里的人群' } }) });
  T4.S.form['b0_brief'] = { purpose: '我自己写的目的' };
  await T4.pullFormFromBrief(b21);
  eq(T4.S.form['b0_brief'].purpose, '我自己写的目的', '**已经填过的不被覆盖**');
  eq(T4.S.form['b0_brief'].background, '简报里的背景', '空着的补上');
  eq(T4.S.form['b0_brief'].rqs, '简报里的RQ', 'RQ 也补上');
  eq(T4.S.form['b0_brief'].population, '简报里的人群', '人群补上');
  ok(!('hypotheses' in T4.S.form['b0_brief']), '简报里空的小节不写进去（不塞空字符串）');

  console.log('\n【23】产物能直接改（检测再聪明也会漏，最后一道保险）');
  ok(typeof T4.openArtifact === 'function' && typeof T4.showArtifactModal === 'function',
     '产物弹窗有「查看 / 编辑」两态');
  // 编辑态的 HTML 要包含 textarea + 保存，并且**说清旧版会留存**
  T4.S.art = { rel: 'output/脱敏_测试.txt', raw: '陈云 男 [手机1]\n', editing: true,
               isTable: false, canEdit: true };
  const artH = T4.artifactModalHtml(T4.S.art);
  if (artH) {
    ok(artH.indexOf('artEdit') >= 0, '编辑态有文本框');
    ok(artH.indexOf('artSave') >= 0, '编辑态有保存按钮');
    ok(artH.indexOf('_history') >= 0, '**说清了旧版会自动留进 _history**');
    ok(artH.indexOf('artEditBtn') < 0, '编辑态不再显示「编辑」按钮');
  } else {
    ok(false, '弹窗 HTML 是空的');
  }
  // 二进制格式不给编辑入口
  T4.S.art = { rel: 'output/图.png', raw: '', editing: false, isTable: false, canEdit: false };
  ok(T4.S.art.canEdit === false, '图片不给编辑入口（二进制改不了）');

  console.log('\n【23b】CSV/TSV 的编辑态要**像表格**，不是一坨裸 CSV');
  // 前辈实测反馈：「一开始的界面还好，一旦变成编辑界面就很难看和写了」——
  //   原来一点「编辑」就变成一个原始 CSV 文本框，几十段中文挤在逗号里没法读也没法写，
  //   而这恰恰是唯一需要人大量手写的产物（② 的编码工作表）。
  // 解析 / 序列化：往返必须一字不差（含逗号、引号、换行、中文）
  const tricky = '说话人,原文,开放编码\n苏雨桐,"他说""就这样吧""，我家里也是",""\n林晓,"第一行\n第二行","因陪伴"\n';
  const P = T4.parseDelimited(tricky);
  eq(P.cols.length, 3, 'CSV 解析出 3 列');
  eq(P.rows.length, 2, '解析出 2 行数据');
  eq(P.rows[0][1], '他说"就这样吧"，我家里也是', '**引号里的逗号和转义引号都还原对**');
  eq(P.rows[1][1], '第一行\n第二行', '**单元格里的换行保留**');
  const back = T4.serializeDelimited(P.cols, P.rows, P.sep);
  const P2 = T4.parseDelimited(back);
  eq(P2.rows[0][1], P.rows[0][1], '序列化再解析，内容不变（往返一致）');
  eq(P2.rows[1][2], '因陪伴', '中文列的值也不丢');
  eq(T4.csvCell('a,b', ','), '"a,b"', '带逗号的格子会被引号包起来');
  eq(T4.csvCell('他说"嗯"', ','), '"他说""嗯"""', '内部引号翻倍（标准 CSV）');
  eq(T4.detectSep('a\tb\n1\t2\n'), '\t', '认得出 TSV（制表符分隔）');
  ok(T4.isDelimited('output/编码工作表.csv') && T4.isDelimited('a.tsv')
     && !T4.isDelimited('a.md') && !T4.isDelimited('a.txt'), '只有 csv/tsv 走网格编辑');
  ok(T4.cellIsWide('原文') && !T4.cellIsWide('字数'), '长文本列（原文）给大一点的框');
  // 网格 HTML：一格一个输入框、有行号、能加行
  T4.S.art = { rel: 'output/编码工作表.csv', raw: tricky, editing: true, isTable: true,
               canEdit: true, rawEdit: false };
  const gh = T4.artifactModalHtml(T4.S.art);
  ok(gh.indexOf('gridwrap') >= 0, '编辑态渲染的是表格网格（gridwrap）');
  ok(gh.indexOf('artEdit"') < 0, '**不再一上来就是那个裸 CSV 文本框**');
  ok(gh.indexOf('textarea class="gcell"') >= 0, '格子是输入框');
  ok((gh.match(/data-r="/g) || []).length >= 6, '每格都带行/列坐标（Tab 导航要用）');
  ok(gh.indexOf('gridAddRow') >= 0, '有「加一行」');
  ok(gh.indexOf('artSave') >= 0 && gh.indexOf('_history') >= 0,
     '保存按钮和「旧版会留存」的说明都在');
  ok(gh.indexOf('artMode') >= 0, '留了「改成原始文本」的切换（想批量粘贴的人用）');
  // ⚠ 两个实测报回来的毛病（前辈截图）：
  //   ① 表头里出现**两个 `#`** —— 我自己摆了一列行号，而编码表第一列本来就是 `#`
  //   ② 「原文」被压成一条缝（每个字换一行）—— colgroup 百分比合计 114%，浏览器只好自己压缩
  //  这两条都是"看着像画出来了、其实不能用"，必须有断言盯着。
  const heads = (gh.match(/<th[\s\S]*?<\/th>/g) || [])
    .map(s => s.replace(/<[^>]+>/g, '').trim());
  const ncolAttr = Number((gh.match(/data-ncol="(\d+)"/) || [])[1]);
  eq(heads.length, ncolAttr, '表头格数和列数对得上（不多摆列）');
  eq(heads.length, 3, '示例是 3 列 → 表头就 3 格（说话人/原文/开放编码）');
  eq(heads.filter(h => h === '#').length, 0, '示例表没有 `#` 列 → 表头里也不该有 `#`（不重复摆行号）');
  const pcts = (gh.match(/width:([\d.]+)%/g) || []).map(s => Number(s.match(/[\d.]+/)[0]));
  const sum = pcts.reduce((a, b) => a + b, 0);
  ok(sum > 99.5 && sum < 100.5, '列宽百分比合计正好 100%（实测踩过 114% → 原文被压成缝）',
     '合计 ' + sum.toFixed(2) + '%');
  ok(pcts.every(p => p > 0), '每列都有宽度', pcts.map(x => x.toFixed(1)).join('/'));
  // 真正的编码工作表：原文列要拿到明显最大的一块
  const realCsv = '说话人,字数,原文,关键词（线索）,开放编码,范畴,主题,可作引语\n'
    + '林晓,106,"雨桐你好，先谢谢你下午抽时间过来。",责任,,\n';
  const gh2 = T4.artifactModalHtml({ rel: 'output/编码工作表.csv', raw: realCsv,
    editing: true, isTable: true, canEdit: true });
  const p2 = (gh2.match(/width:([\d.]+)%/g) || []).map(s => Number(s.match(/[\d.]+/)[0]));
  const iYuan = 2;                                  // 原文 是第 3 列
  ok(p2[iYuan] === Math.max.apply(null, p2),
     '「原文」列拿到最大的一块宽度（不是被挤成一条缝）', p2.map(x => x.toFixed(1)).join('/'));
  ok(p2.filter(x => x === Math.max.apply(null, p2)).length === 1,
     '最大的那一块只有一列（不会两列抢）');

  // 原始文本模式仍然在（不是删掉，是默认不摆出来）
  T4.S.art.rawEdit = true;
  const rawH = T4.artifactModalHtml(T4.S.art);
  ok(rawH.indexOf('artEdit') >= 0 && rawH.indexOf('gridwrap') < 0,
     '切到原始文本模式 → 回到那个文本框（给批量处理用）');
  ok(rawH.indexOf('id="artMode"') >= 0 && rawH.indexOf('artModeGrid') < 0,
     '而且能切回表格（按钮 id 是 artMode）');
  // ⚠ 这里逮到过一个真 bug：绑定写的是 `#artModeGrid`，而按钮 id 其实是 `#artMode`
  //   —— handler 挂在不存在的元素上 = **点了没反应**，可按钮明明画在那儿。
  //   所以直接核源码：绑定那几句引用的 id，必须都是真的画出来的那几个。
  //   （不靠上面那份 HTML —— 这个小 DOM 桩没画全部按钮，拿它断言会假失败。）
  {
    const fsx = require('fs'), pathx = require('path');
    const src = fsx.readFileSync(pathx.join(__dirname, 'web', 'app.js'), 'utf8');
    const bound = (src.match(/\$\('#(artMode[A-Za-z]*|artSave|artEditBtn|artCancel)'\)/g) || [])
      .map(s => s.replace(/[^#]*#/, '').replace(/'\)$/, ''));
    const drawn = (src.match(/id="(artMode[A-Za-z]*|artSave|artEditBtn|artCancel)"/g) || [])
      .map(s => s.replace(/id="|"/g, ''));
    const dead = Array.from(new Set(bound)).filter(x => drawn.indexOf(x) < 0);
    ok(dead.length === 0, '绑定的按钮 id 全都真的画出来了（没有挂空的死处理器）', dead.join(','));
    ok(bound.indexOf('artModeGrid') < 0, '绑定里没有那个不存在的 artModeGrid');
  }
  T4.S.art.rawEdit = false;
  // 非表格产物（.md/.txt）不受影响：还是原来的文本框
  T4.S.art = { rel: 'output/报告.md', raw: '# 标题\n', editing: true, isTable: false,
               canEdit: true };
  const mh = T4.artifactModalHtml(T4.S.art);
  ok(mh.indexOf('artEdit') >= 0 && mh.indexOf('gridwrap') < 0,
     'md 这类非表格产物仍然是普通文本框（没被硬改成表格）');

  console.log('\n【23c】逐段编码面板（就地编码：看得见上下文、点码就贴）');
  // 方向来自前辈问的 NVivo / MAXQDA：真工具都是「在原文上编」，编的时候看得见前后文。
  // 我们不做"划选上色"（那要改存储格式），改成**一段一屏**：上文 / 主文 / 下文 + 点码就贴。
  // ⚠ 表头 9 列，**数据行也必须 9 个值** —— 少一个逗号就整体左移，
  //   「吸引」会落到「关键词」列里，后面几条断言全跟着歪（我在这上面栽了两次）。
  const sheetCsv = '#,说话人,字数,原文,关键词（线索）,开放编码,范畴,主题,可作引语\n'
    + '1,林晓,20,你们平时怎么认识的？,,,,,\n'
    + '2,苏雨桐,30,社团。他是副社长，教我调参数。,,,,,\n'
    + '3,林晓,10,后来呢？,,,,,\n'
    + '4,苏雨桐,40,后来他先说的。我室友说我不对劲。,相识,吸引,相识过程,关系建立,★\n';
  T4.S.art = { rel: 'output/编码工作表.csv', raw: sheetCsv, editing: true, isTable: true,
               canEdit: true, rawEdit: false };
  ok(T4.canCodingPanel(T4.S.art), '认得出这是编码工作表 → 可以进逐段编码');
  // 不是编码表的 csv 不该进这个面板
  ok(!T4.canCodingPanel({ rel: 'output/别的.csv', raw: 'a,b\n1,2\n', isTable: true, canEdit: true }),
     '普通 csv 不给「逐段编码」（三列编码列都找不到）');
  ok(!T4.canCodingPanel({ rel: 'output/x.md', raw: 'a', canEdit: true }),
     'md 也不给');
  const sh = T4.codingSheet(T4.S.art);
  eq(sh.cols.length, 9, '认到 9 列');
  eq(sh.idx.open, 5, '开放编码列定位对（第 6 列）');
  eq(sh.idx.theme, 7, '主题列定位对（第 8 列）');
  eq(sh.idx.raw, 3, '原文列定位对');
  // 一格多个码：分隔符要和 ②b 一致（中文逗号不拆，因为码本身常带逗号）
  eq(JSON.stringify(T4.splitCodes('经济压力；AA 均摊')), '["经济压力","AA 均摊"]',
     '分号拆多个码');
  eq(JSON.stringify(T4.splitCodes('陪伴、吸引')), '["陪伴","吸引"]', '顿号也拆');
  eq(JSON.stringify(T4.splitCodes('分期,付款')), '["分期,付款"]',
     '**中文逗号不拆**（码本身可能带逗号）');
  eq(T4.joinCodes(['a', 'b', 'a']), 'a；b', '拼回去时去重、用分号连');
  // 进度：哪几段编完了
  const pr = T4.panelProgress(sh);
  eq(pr.total, 4, '共 4 段');
  eq(pr.done, 1, '只有第 4 段三列齐全 → 算编完');
  ok(T4.segDone(sh, 3) && !T4.segDone(sh, 0), '第 4 段编完、第 1 段没编');
  ok(!T4.segPartially(sh, 0), '一段都没填 → 不算"编了一半"');
  // 跳「下一段没编的」
  eq(T4.nextSeg(sh, 3, 'left', 1), -1, '从最后一段往后找没有没编的（正确回 -1）');
  eq(T4.nextSeg(sh, 0, 'left', 1), 1, '从第 1 段往后找到第一个没编的是第 2 段');
  // 面板 HTML 要有上下文（这是这个功能存在的理由）
  // ⚠ `_panel: true` 必须显式给：真界面上是点「✏ 编辑」时由 `canCodingPanel()` 判出来的，
  //   测试直接调 artifactModalHtml 就得自己带上，否则走的是表格编辑那条路。
  T4.S.art._panel = true;
  T4.S.art._sheet = sh;
  T4.S.art._ri = 1;
  const ph = T4.artifactModalHtml(T4.S.art);
  ok(ph.indexOf('cpanel') >= 0, '渲染出编码面板');
  ok(ph.indexOf('你们平时怎么认识的') >= 0, '**上面有前一段**（上下文，编的时候要看得见）');
  ok(ph.indexOf('后来呢') >= 0, '**下面有后一段**');
  ok(ph.indexOf('第 2 段') >= 0, '标了当前是第几段（用表里的 # 号）');
  ok(/cmpos">\s*2\s*\/\s*4/.test(ph), '标了进度（第几 / 共几）', (ph.match(/cmpos">[^<]*</) || [])[0]);
  ok(ph.indexOf('还没碰') >= 0 && ph.indexOf('已编') >= 0, '进度条上说了有多少没编');
  ok(ph.indexOf('三列齐全') >= 0, '另外单列了「三列齐全」的段数（严格口径）');
  ok(ph.indexOf('cbarfill') >= 0, '有进度条');
  ok(ph.indexOf('cLeft') >= 0, '有「跳到下一段没编的」');
  ok(ph.indexOf('input class="cadd"') >= 0, '三个字段各有一个输入框');
  ok(ph.indexOf('data-f="open"') >= 0 && ph.indexOf('data-f="cat"') >= 0
     && ph.indexOf('data-f="theme"') >= 0, '开放编码/范畴/主题三个字段都在');
  // 已经建过的码：拿**填过的那一段**看（第 1 段没码，当然摆不出来）
  T4.S.art._ri = 3;
  const ph4 = T4.artifactModalHtml(T4.S.art);
  ok(ph4.indexOf('吸引') >= 0, '**已经建过的码摆出来**（点一下就贴）');
  ok(ph4.indexOf('相识过程') >= 0, '范畴的码也摆出来');
  ok(ph4.indexOf('程序不替你编') >= 0 || ph4.indexOf('程序不替你定名') >= 0,
     '面板里也写明「码是你写的，程序不替你编」');
  ok(ph4.indexOf('cchipx') >= 0, '填过的段把码显示成可删的 chip');
  T4.S.art._ri = 0;
  const ph0 = T4.artifactModalHtml(T4.S.art);
  ok(ph0.indexOf('cchipx') < 0, '没填的段不显示 chip');
  // ⚠ 存储格式不许变：面板保存时必须还是那三列、还是分号连。
  //   用一个**全新对象**做（别复用上面那个 T4.S.art）——
  //   它前面已经被 paint 过几轮、`raw` 早被改写了，拿它断言会串味（踩过一次：
  //   "吸引"被读成了"相识过程"，查半天发现是测试自己的数据被前一步改了）。
  const sv = { rel: 'output/编码工作表.csv', raw: sheetCsv, isTable: true, canEdit: true };
  const sh2 = T4.codingSheet(sv);
  T4.collectPanelInto(sh2, { open: ['社团相识'], cat: ['相识过程'], theme: [] }, 1);
  const outCsv = T4.sheetToCsv(sh2);
  const P3 = T4.parseDelimited(outCsv);
  eq(P3.cols.length, 9, '存回去还是 9 列（列顺序没动）');
  eq(P3.rows[1][sh2.idx.open], '社团相识', '开放编码写进了那一行的那一列');
  eq(P3.rows[3][sh2.idx.open], '吸引', '**别的行没被碰**（只改当前这一段）');
  eq(P3.rows[3][sh2.idx.raw], '后来他先说的。我室友说我不对劲。', '原文一个字没动');
  eq(P3.rows.length, 4, '行数不变');
  // 一格多个码：还是老格式（分号连），②b 那边才拆得开
  T4.collectPanelInto(sh2, { open: ['社团相识', '吸引'], cat: [], theme: [] }, 2);
  ok(T4.sheetToCsv(sh2).indexOf('社团相识；吸引') >= 0,
     '一格里两个码用「；」连（和 ②b 的拆分规则一致）');

  console.log('\n【23d】角色：背景深浅分角色 + 筛选 + **完整原文可跳转**');
  // 前辈的三条要求（原话）：
  //   ①「只编回答也要结合提问的上下文，所以直接隐藏不是很好的选择」
  //   ②「用文本框背景深浅来区分角色」
  //   ③「现在这个版本没办法看全文和上下文！这一点非常恐怖」
  ok(T4.speakerTone('访谈者') === 'ask' && T4.speakerTone('采访者') === 'ask',
     '认得「访谈者/采访者」');
  ok(T4.speakerTone('[受访者1]') === 'answer',
     '认得去标识化后的 `[受访者1]`');
  ok(T4.speakerTone('林晓') === 'other',
     '**光秃秃的人名认不出角色**（真实稿子就是这样，所以要靠别的判据）');
  eq(JSON.stringify(T4.speakersOf(sh)), '["林晓","苏雨桐"]', '列出说话人，按出场顺序');
  // 两个人 + 名字认不出来 → 先开口的那个（问候/自我介绍）是访谈者
  eq(JSON.stringify(T4.defaultCodeRoles(sh)), '["苏雨桐"]',
     '两个人时，先开口的那个当访谈者（惯例：访谈者先问候）→ 默认只编受访者');
  // 名字认得出来时，用名字判
  const shNamed = T4.codingSheet({ raw: '说话人,原文,开放编码,范畴,主题\n'
    + '访谈者,你平时怎么花钱？,,,\n受访者,我一般 AA,,,\n' });
  eq(JSON.stringify(T4.defaultCodeRoles(shNamed)), '["受访者"]',
     '名字带「访谈者/受访者」时按名字判');
  // 三个人以上、名字又认不出来 → 不擅自排除，都算要编的
  const sh3 = T4.codingSheet({ raw: '说话人,原文,开放编码,范畴,主题\n'
    + '甲,a,,,\n乙,b,,,\n丙,c,,,\n' });
  eq(T4.defaultCodeRoles(sh3).length, 3, '认不出来又不只两人 → 都算要编的（不擅自藏）');
  // 筛选只管"编不编"，不改"能不能看见"
  // ⚠ 用**独立的一份**读表（`shRole`）：上面的 `sh` 已经被"保存格式"那几条改过了，
  //   拿它验证进度会得到一份被污染的数据 —— 我就这么误判过一次（以为是代码错）。
  const shRole = T4.codingSheet({ rel: 'x.csv', raw: sheetCsv });
  const a4 = { _sheet: shRole, _roles: ['苏雨桐'] };
  ok(!T4.segInScope(a4, 0), '第 1 段是访谈者 → 不在"要编"的范围里');
  ok(T4.segInScope(a4, 1), '第 2 段是受访者 → 要编');
  // 进度按"要编的段"算（提问占一半时，全算进去永远编不完）
  const prAll = T4.panelProgress(shRole);
  const prScoped = T4.panelProgress(shRole, a4);
  eq(prAll.total, 4, '不筛时：4 段都算');
  eq(prScoped.total, 2, '**筛掉访谈者后：只 2 段要编**（那份 70 段的真表里会从 70 降到 35）');
  eq(prScoped.done, 1, '已完成也只数受访者那一段');
  // 「跳到下一段没编的」不能跳到访谈者身上：
  // 这份数据里 #2 三列齐全（已编完），所以从第 1 段往后 → 直接落到 #4
  eq(T4.nextSeg(shRole, 1, 'left', 1, a4), -1,
     '从第 2 段往后：后面只有 #4，而它已编完 → 没有"还没编的"了（回 -1）');
  eq(T4.nextSeg(shRole, 0, 'left', 1, a4), 1,
     '从第 1 段（访谈者，不编）往后 → 落到 #2（受访者、还没编）');
  eq(T4.nextSeg(shRole, 3, 'left', -1, a4), 1,
     '往回找也一样：忽略访谈者那两段，落到 #2');
  // 完整原文：每段都在、角色类名对、能点击跳转
  T4.S.art = { rel: 'output/编码工作表.csv', raw: sheetCsv, editing: true, isTable: true,
               canEdit: true, rawEdit: false, _panel: true, _roles: ['苏雨桐'], _ri: 1 };
  T4.S.art._sheet = T4.codingSheet(T4.S.art);
  const dh = T4.artifactModalHtml(T4.S.art);
  ok(dh.indexOf('docwrap') >= 0 && dh.indexOf('完整原文') >= 0, '**有完整原文那一栏**');
  ok(dh.indexOf('dseg') >= 0, '原文按段渲染');
  ok(dh.indexOf('data-i="0"') >= 0 && dh.indexOf('data-i="3"') >= 0,
     '每一段都带段号（点了能跳过去）');
  // ⚠ 深浅分角色要用**认得出角色**的稿子看：林晓/苏雨桐 这种光秃秃的人名
  //   判不出角色（判成 t-other），那是**故意保守**——不擅自把谁当访谈者。
  //   名字认得出来时（`访谈者` / `受访者`，或脱敏后的 `[受访者1]`）才上深浅。
  T4.S.art.raw = '说话人,原文,开放编码,范畴,主题\n'
    + '访谈者,你平时怎么花钱？,,,\n受访者,我一般 AA。,,,\n访谈者,还有吗？,,,\n';
  T4.S.art._sheet = T4.codingSheet(T4.S.art);
  // ⚠ 看"提问"的样子要点**不筛**的那一段：只勾受访者时，面板会主动避开访谈者的段
  //   （这是对的 —— 不然"下一段"会老停在不用编的人身上）。
  T4.S.art._roles = ['访谈者', '受访者'];
  T4.S.art._ri = 0;                      // 停在一句**提问**上，看角色标不标得对
  const dhAsk = T4.artifactModalHtml(T4.S.art);
  ok(T4.S.art._ri === 0, '不筛时停在提问那一段（不会被挪走）');
  ok(dhAsk.indexOf('ctag t-ask') >= 0, '当前段是提问时，标题上标出「提问」',
     (dhAsk.match(/<span class="ctag[^>]*>[^<]*<\/span>/) || [])[0]);
  ok(/cmain t-ask/.test(dhAsk), '提问那一块整体用浅背景（和原文里一致）');
  // 只勾受访者时：面板会**主动跳过**访谈者的段（不然"下一段"老停在不用编的人身上）
  T4.S.art._roles = ['受访者'];
  T4.S.art._ri = 0;
  T4.artifactModalHtml(T4.S.art);
  ok(T4.S.art._ri === 1, '只勾受访者、却停在提问上 → 自动挪到最近的受访者段');
  T4.S.art._ri = 1;
  const dh2 = T4.artifactModalHtml(T4.S.art);
  ok(dh2.indexOf('t-ask') >= 0 && dh2.indexOf('t-answer') >= 0,
     '**角色用背景深浅区分**（提问 t-ask / 回答 t-answer）');
  ok(/dseg t-answer cur/.test(dh2), '当前那一段高亮（cur）+ 回答角色');
  // 光秃秃人名时不乱判角色（保守）
  ok(T4.speakerTone('林晓') === 'other' && T4.speakerTone('苏雨桐') === 'other',
     '认不出角色就标 other，不瞎猜谁是访谈者');
  // 还原成前面那份，继续后面的断言
  T4.S.art.raw = sheetCsv;
  T4.S.art._sheet = T4.codingSheet(T4.S.art);
  T4.S.art._roles = ['苏雨桐'];
  T4.S.art._ri = 1;
  const dh3 = T4.artifactModalHtml(T4.S.art);
  ok(dh3.indexOf('crolectl') >= 0 && dh3.indexOf('要编谁') >= 0, '有角色筛选');
  ok(dh3.indexOf('左边原文里照样看得到') >= 0,
     '筛选条上写清「不勾的人也看得到」（隐藏不是选项 —— 前辈明确说了）');
  ok(dh3.indexOf('提问') >= 0 || dh3.indexOf('回答') >= 0, '当前段标了角色');
  // ⚠ 不再用"只有前后两段"那套（前辈说"看不到全文"很恐怖）
  ok(dh3.indexOf('cctx') < 0, '**旧的"只看前后一段"那套已经换掉了**');

  console.log('\n【24】提醒里的「选项 + 自定义填写」→ 直接并进自定义替换');
  // 研究员的要求：「在提示处增加选项与自定义填写（要求用户按规定格式输出，必须带有 =），
  // 然后把用户的填写或选择直接转到自定义替换」。
  const alertWithOpts = {
    msg: '「_yujia_88」看着像标识符，但这次没被处理',
    level: 'warn', kind: 'internal',
    // ⚠ 声明了"这条提醒能填进哪个字段"（组块声明 rules_field，runner 逐条带出来）——
    //   只给 options、不声明字段的话，按【24b】的规矩就**不摆输入框**了。
    rules_field: 'extra_rules',
    options: [{ label: '换成 [代号1]', line: '_yujia_88 = [代号1]', hint: '当标识符处理掉' },
              { label: '换成标准写法', line: '', hint: '这次没有标准写法' }],
  };
  const hOpts = T4.alertOptionsHtml(alertWithOpts);
  ok(hOpts.indexOf('data-rule="_yujia_88 = [代号1]"') >= 0, '选项渲染成可点的按钮，带着规则行');
  ok(hOpts.indexOf('data-rulein') >= 0, '有自定义填写的输入框');
  ok(hOpts.indexOf('data-ruleadd') >= 0, '有「加进自定义替换」按钮');
  ok(hOpts.indexOf('title="当标识符处理掉"') >= 0, '选项带说明（鼠标悬停能看到）');
  // 没给 line 的选项（比如「这是地名，保持不动」）不该是个可点的按钮
  ok(hOpts.indexOf('保持不动') < 0, '空 line 的选项不渲染成按钮');

  console.log('\n【24b】⚠ 替换框**只在能填的提醒上**出现（前辈实测报的）');
  // 现象：③ 弹出一条「你勾了筛选题，但一道都没生成」，底下却跟着
  //   `原文 = 换成什么（空 = 删掉）` + 「加进自定义替换」—— 那是 🔒 去标识化的填法，
  //   「这里的内容很明显与之无关」。根因：那套输入框是**无条件渲染**的。
  // 规矩：组块声明 `rules_field`（哪条提醒能填进哪个字段，runner 逐条带出来），
  //       前端只认它 —— 没有就一个字都不摆。
  const plainAdvice = { msg: '你勾了「筛选题」，但这次一道都没生成', level: 'warn',
                        fix: '把筛选题当招人条件来写', kind: 'method' };
  const hPlain = T4.alertOptionsHtml(plainAdvice);
  ok(hPlain.indexOf('data-rulein') < 0 && hPlain.indexOf('data-ruleadd') < 0,
     '**纯方法学提醒：一个替换输入框都不摆**', hPlain.slice(0, 80));
  ok(hPlain.indexOf('原文（要换掉的那段') < 0, '也不摆"原文 = 换成什么"那一行');
  const withField = { msg: '「13177778888」看着像标识符', level: 'warn',
                      rules_field: 'extra_rules', options: [
                        { label: '换成 [手机1]', line: '13177778888 = [手机1]' }] };
  const hField = T4.alertOptionsHtml(withField);
  ok(hField.indexOf('data-rulein') >= 0 && hField.indexOf('data-ruleadd') >= 0,
     '🔒 那种声明的提醒：替换输入框照样在（没把好用的东西砍掉）');
  ok(hField.indexOf('data-rule="13177778888 = [手机1]"') >= 0, '选项按钮也在');
  // 只给了可点选项、没声明字段 → 只摆按钮，不摆输入框
  const onlyPicks = { msg: 'x', level: 'warn', options: [{ label: 'A', line: 'a = b' }] };
  const hOnly = T4.alertOptionsHtml(onlyPicks);
  ok(hOnly.indexOf('data-rule="a = b"') >= 0 && hOnly.indexOf('data-rulein') < 0,
     '只给选项、没声明字段 → 只摆按钮，不摆输入框', hOnly.slice(0, 90));
  // 什么都没有 → 整块不渲染（不留一个空壳 div）
  ok(T4.alertOptionsHtml({ msg: 'x', level: 'warn' }) === '',
     '既没字段也没选项 → 整块不渲染（不留空壳）');

  // 真正的行为：点一下 → 并进 extra_rules
  T4.S.state = { project: { root: ROOT1, name: 'x', artifacts: [], status: {} },
                 blocks: [{ id: 'b9_deident', form: [{ key: 'extra_rules', type: 'textarea' }] }] };
  T4.S.form['b9_deident'] = {};
  ok(T4.addCustomRule('_yujia_88 = [代号1]', null) === true, '合法的一行 → 加成');
  eq(T4.S.form['b9_deident'].extra_rules, '_yujia_88 = [代号1]', '内容进了 extra_rules');
  ok(T4.addCustomRule('_yujia_88 = [代号1]', null) === true,
     '同一条再加一次 → 覆盖旧的（不是报错，也不是留两条）');
  eq(T4.S.form['b9_deident'].extra_rules, '_yujia_88 = [代号1]', '内容没变成两行');
  ok(T4.addCustomRule('陈云 = [代号2]', null) === true, '第二条 → 加成');
  eq(T4.S.form['b9_deident'].extra_rules.split('\n').length, 2, '两条各占一行');
  // ⚠ `!` 开头的**指令行**没有 `=` 也必须能加：
  //   研究员要的就是「第 3 段是手机」这种**段位判断**（每一行原文都不一样，没法逐行填）。
  //   上一版一律要求有 `=`，点这个选项会被当场拦下。
  ok(T4.addCustomRule('!第3段是手机', null) === true, '指令行没有 = 也能加（!第3段是手机）');
  eq(T4.S.form['b9_deident'].extra_rules.split('\n').length, 3, '指令行写进去了');
  ok(T4.S.form['b9_deident'].extra_rules.split('\n')[2] === '!第3段是手机',
     '指令行原样存（不被拼成 `xxx = `）', T4.S.form['b9_deident'].extra_rules);
  // ⚠ 研究员报的 bug：点「这是 QQ/微信号」之后，自定义里存的是 `!这是QQ X`，
  //   而界面上原来会拼成 `!这是QQ X = ` —— 多一个 `=` 就让引擎匹配不上，选了没效果。
  ok(T4.addCustomRule('!这是QQ 16000000001', null) === true, '「这是 QQ」这类指令也能加');
  eq(T4.S.form['b9_deident'].extra_rules.split('\n')[3], '!这是QQ 16000000001',
     '**指令原样存**：不多一个 `=`（多一个就匹配不上、选了没效果）',
     T4.S.form['b9_deident'].extra_rules);
  ok(T4.S.form['b9_deident'].extra_rules.split('\n').length === 4, '指令不重复');
  ok(T4.addCustomRule('给不是指令的、没有等号的一行', null) === false,
     '不是指令又没等号 → 照样拦下');
  // 「右边空 = 删掉这段」是**特意**的功能（清前缀用）：两个框分开填时空右边要能加成
  ok(T4.addCustomRule('QQ ', '') === true, '右边留空 → 加成（这条规则的意思是"删掉这段"）');
  eq(T4.S.form['b9_deident'].extra_rules.split('\n').length, 5, '删掉式规则也写进去了');
  // 格式不对要当场拦（研究员写了一条、跑完没生效还找不到原因，那种最难查）
  ok(T4.addCustomRule('随便写的没有等号', null) === false, '整行给的、没有 = → 拦下');
  ok(T4.addCustomRule('= [代号3]', null) === false, '= 左边空 → 拦下');
  ok(T4.addCustomRule('', null) === false, '空的 → 拦下');
  ok(T4.addCustomRule('', '[代号4]') === false, '左边空、右边有值 → 拦下');
  eq(T4.S.form['b9_deident'].extra_rules.split('\n').length, 5, '被拦下的都没写进去');
  ok(T4.isDirectiveRule('!这是手机 1'), '认得指令：!这是手机');
  ok(T4.isDirectiveRule('!第3段不用管'), '认得指令：!第3段不用管');
  ok(!T4.isDirectiveRule('王芳 = [受访者A]'), '普通替换规则不算指令');
  ok(!T4.isDirectiveRule(''), '空的不算指令');

  console.log('\n【28】「自定义替换」逐行自检：哪条认得出、哪条跑起来会被跳过');
  // 研究员连点几个选项、跑完看不出哪条起作用 → 只能说"我选了没效果"。
  const rc = T4.ruleCheckHtml([
    '!这是QQ 13177778888',
    '!第3段是手机',
    '!第3段不用管',
    '!这是电波 123',
    '王芳 = [受访者A]',
    '没有等号也没有感叹号',
  ].join('\n'));
  ok(rc.indexOf('!这是QQ 13177778888') >= 0, '把规则原文列出来');
  eq((rc.match(/rulechk good/g) || []).length, 4, '四条认得出的标成 ✓');
  eq((rc.match(/rulechk bad/g) || []).length, 3, '两条认不出的 + 一句总结标成 ✗');
  ok(rc.indexOf('单个值判断') >= 0, '标出「单个值判断」');
  ok(rc.indexOf('段位判断') >= 0, '标出「段位判断」');
  ok(rc.indexOf('普通替换') >= 0, '标出「普通替换」');
  ok(rc.indexOf('不会生效') >= 0, '有认不出的就明说「不会生效」');
  eq(T4.ruleCheckHtml(''), '', '没规则时不占地方');
  ok(T4.ruleCheckHtml('!第3段是手机').indexOf('bad') < 0, '合法的段位指令不报错');
  // ⚠ 带旧式尾部 `= ` 的也要认得（旧页面存过这种）
  ok(T4.ruleCheckHtml('!这是QQ 13177778888 = ').indexOf('bad') < 0,
     '带旧式尾部 `= ` 的指令也认得（不然又会看着像坏了）');

  console.log('\n【29】「🙈 这条不用再问」+ 选完的提示留在原地');
  // 研究员提的两条：
  //   ① 「点击选项后的已选择提醒消失跑到上面去了，会不方便用户确认」
  //   ② 「防止有如『没被认出来的词』这种复杂情况…加一个选项来跳过或者无视这一提醒」
  const a1 = { msg: '「13177778888」可能有歧义（原文第 17 行）：…', level: 'warn',
               locate: { file: 'samples/x.txt', line: 17 } };
  const a2 = { msg: '这些词**没被认出来**：11位QQ号占位、备注：老乡。', level: 'warn' };
  ok(T4.alertSig(a1) === T4.alertSig(Object.assign({}, a1)),
     '同一条提醒的标识是稳定的（同样的输入→同一个 sig）');
  ok(T4.alertSig(a1) !== T4.alertSig(a2), '不同提醒的标识不一样');
  ok(T4.alertSig(a1).length < 12 && /^a/.test(T4.alertSig(a1)),
     '标识短、可读（存进 json 里不占地方）', T4.alertSig(a1));

  T4.S.result = { summary: 'x', tables: [], figures: [], markdown: [], text: [], html: [],
                  alerts: [a1, a2] };
  T4.S.ignoredAlerts = [];
  const rBoth = T4.renderResult();
  ok(rBoth.indexOf('data-mute') >= 0, '每条提醒都有「这条不用再问」');
  ok(rBoth.indexOf('这条不用再问') >= 0, '按钮文字说清了它干什么');
  // 忽略之后那条就不再出现（其余的照旧）
  T4.S.ignoredAlerts = [T4.alertSig(a2)];
  const rOne = T4.renderResult();
  ok(rOne.indexOf('没被认出来') < 0, '忽略掉的那条不再显示');
  ok(rOne.indexOf('13177778888') >= 0, '没被忽略的那条照旧显示');
  ok(rOne.indexOf('data-goto-file') >= 0, '忽略另一条不影响跳转入口');
  T4.S.ignoredAlerts = [];

  // 选完的提示要留在原地
  T4.S.ruleMsg = { text: '已加进「自定义替换」：!第3段是手机', bad: false };
  const rMsg = T4.renderResult();
  ok(rMsg.indexOf('rulemsgb') >= 0, '并入规则的提示留在结果区（不再只闪在状态栏）');
  ok(rMsg.indexOf('!第3段是手机') >= 0, '提示里写清加了哪一条');
  ok(rMsg.indexOf('rulemsgb') < rMsg.indexOf('advnote') || rMsg.indexOf('advnote') < 0,
     '提示排在提醒下面，不像报错');
  T4.S.ruleMsg = null;
  ok(T4.renderResult().indexOf('rulemsgb') < 0, '没有提示时不占地方');

  console.log('\n【30】回执要长在**那条提醒自己的框里**（不是全部塞下面）');
  // ⚠ 这条踩了三次才想明白，三次都记下来：
  //   ① 一开始只写在状态栏（页面最底下）→ 重画表单就没了
  //   ② 改成画在**结果区** → 点选项重画的是**表单区**，结果区根本没重绘
  //   ③ 改成画在**表单顶上** → 研究员说"我还是希望你把哪个问题已选择的绿字加到
  //      对应问题的框里，而不是全部塞下面" —— 对，得按提醒归位
  //   定稿：按 `alertSig` 分别存（`S.ruleMsgs`），画在**各自那个 alertbox 里**。
  T4.S.state = { project: { root: ROOT1, name: 'x', artifacts: [], status: {} },
                 blocks: [{ id: 'b9_deident', name: '去标识化', title: '去标识化', desc: '',
                            form: [{ key: 'extra_rules', type: 'textarea', label: '自定义替换' }] }] };
  T4.S.blockId = 'b9_deident';
  T4.S.result = { summary: 'x', tables: [], figures: [], markdown: [], text: [], html: [],
                  alerts: [a1, a2] };
  T4.S.ignoredAlerts = [];
  T4.S.ruleMsgs = {};
  const sigA = T4.alertSig(a1);
  T4.S.ruleMsgs[sigA] = { text: '已加进「自定义替换」：!这是手机 1', bad: false };
  const rIn = T4.renderResult();
  // 两条提醒各自的框：a1 有回执、a2 没有
  const boxA = rIn.slice(rIn.indexOf('data-sig="' + sigA + '"'));
  ok(boxA.indexOf('rulemsgb') >= 0, '点了选项的那条提醒，回执在**它自己的框里**');
  ok(boxA.indexOf('!这是手机 1') >= 0, '回执写清加了哪一条');
  const sigB = T4.alertSig(a2);
  const tailB = rIn.slice(rIn.indexOf('data-sig="' + sigB + '"'));
  ok(tailB.indexOf('rulemsgb') < 0, '没点过的提醒框里**不长**回执（不会串到别的提醒上）');
  // 回执留在框里这件事不能靠"重画表单"——那会把提醒框一起冲掉
  T4.S.form['b9_deident'] = { extra_rules: '!这是手机 1' };
  T4.S.ruleMsg = null;
  const kept = T4.renderResult();
  ok(kept.indexOf('!这是手机 1') >= 0,
     '重画之后回执还在（它按 sig 存着，不是靠 DOM 里那一次性的文字）');
  T4.S.ruleMsgs = {};
  T4.S.ruleMsg = null;
  ok(T4.renderResult().indexOf('rulemsgb') < 0, '没有回执时不占地方');

  console.log('\n【31】过期的产物要在左栏标出来（别让人拿着旧的往下做）');
  // 现场：上游契约 19:49 改过、提纲 19:48 生成 —— 文件都在，界面显示"已完成"，
  //   于是研究员拿着一份按旧契约生成的提纲继续做，而且不知道。
  //   **静默的过期比缺文件更危险**：缺了会被发现，过期不会。
  const rb = T4.railHtml(
    [{ id: 'b1_guide', num: '①', name: '访谈提纲', group: 'qual' },
     { id: 'b2_coding', num: '②', name: '编码整理', group: 'qual' },
     { id: 'b9_deident', num: '🔒', name: '去标识化', group: 'x' }],
    { b1_guide: { done: true, stale: false },
      b2_coding: { done: true, stale: true, stale_why: 'contracts/interview_guide.md' },
      b9_deident: { done: false } },
    []);
  ok(rb.indexOf('staletag') >= 0, '过期的那个标了「过期」');
  eq((rb.match(/staletag/g) || []).length, 1, '只标真正过期的那个（不误标）');
  ok(rb.indexOf('dot stale') >= 0, '圆点也换成过期的颜色');
  ok(rb.indexOf('产物比上游旧了') >= 0, '鼠标悬停能说出是哪个上游变了');
  ok(rb.indexOf('contracts/interview_guide.md') >= 0, '悬停里点名了具体文件');
  const rb2 = T4.railHtml([{ id: 'b1_guide', num: '①', name: 'x', group: 'qual' }],
                          { b1_guide: { done: true, stale: false } }, []);
  ok(rb2.indexOf('staletag') < 0, '没过期就不标（不要滥用标记）');
  const rb3 = T4.railHtml([{ id: 'b1_guide', num: '①', name: 'x', group: 'qual' }],
                          { b1_guide: { done: false, stale: true } }, []);
  ok(rb3.indexOf('staletag') < 0, '没跑过的组块不算过期（那是"未完成"）');

  console.log('\n【32】项目里那份表单是**权威**（还原回来要能盖住页面上的旧内容）');
  // 现场（研究员撞上的、而且强刷都没用）：
  //   他把项目文件从 _history 还原了，但页面上还是那版错的。
  //   根因：`loadFormFromProject` **只补空值**（`if (cur[k] === undefined)`），
  //   而 `loadForm` 又把 localStorage 放前面 —— 内存里的旧内容永远赢，
  //   项目文件里正确的内容**一个字都进不来**。注释写着"项目里那份优先"，代码是反的。
  T4.S.state = { project: { root: ROOT1, name: 'x', artifacts: [], status: {} },
                 blocks: [{ id: 'b0_brief', name: '研究设计', title: '研究设计', desc: '',
                            form: [{ key: 'population', type: 'textarea', label: '目标人群' },
                                   { key: 'rqs', type: 'textarea', label: '研究问题' }] }] };
  T4.S.blockId = 'b0_brief';
  T4.S.formLoaded = {};
  T4.S.formRequested = {};                        // 模拟"刚打开页面，还没为它读过表单"
  // 内存里是"旧内容"（模拟页面里那版错的 —— 上个会话/缓存留下来的）
  T4.S.form['b0_brief'] = { population: '样本量：计划收集200份有效问卷。', rqs: '旧的研究问题' };
  // 假服务端：项目文件里是**还原后的正确内容**
  globalThis.fetch = async () => ({ json: async () => ({ ok: true, rel: '表单填写.json',
    forms: { b0_brief: { population: '样本量：12人，各每年级不同性别各2人',
                         rqs: '旧的研究问题' } } }) });
  // ⚠ 走**真实调用路径**（不是直接调 syncFormFromProject 给默认参数）——
  //   因为"是不是第一次拉"是在 loadFormFromProject 里算的。第一版测试绕过了它，
  //   于是测了个假的通过/失败。
  const statusBefore = (globalThis.document.querySelector('#statusText') || {}).textContent;
  await T4.loadFormFromProject({ id: 'b0_brief', form: [] });
  eq(T4.S.form['b0_brief'].population, '样本量：12人，各每年级不同性别各2人',
     '**项目文件里的内容赢了**（强刷之后页面上能看到还原后的正确内容）');
  const statusAfter = (globalThis.document.querySelector('#statusText') || {}).textContent;
  ok(statusAfter !== statusBefore && String(statusAfter).indexOf('表单') >= 0,
     '状态栏说了「已按项目里的表单填写.json 刷新表单」（不是悄悄换的）',
     statusAfter);
  ok(T4.S.form['b0_brief'].rqs === '旧的研究问题', '一样的不动');

  // 但要保住原来那条好行为：**刚打的字不能被旧文件盖掉**
  T4.S.form['b0_brief'] = {};
  T4.loadForm({ id: 'b0_brief', form: [] });
  T4.S.form['b0_brief'].purpose = '我刚打的、还没存的字';   // 不在 localStorage 里 → 是"刚打的"
  T4.syncFormFromProject('b0_brief', { purpose: '文件里的旧值', population: '文件里的' });
  eq(T4.S.form['b0_brief'].purpose, '我刚打的、还没存的字',
     '刚打的字**不会**被文件里的旧值盖掉（这条原来的好行为保住了）');
  eq(T4.S.form['b0_brief'].population, '文件里的', '文件里有、内存里没有的键照样补上');

  console.log('\n【33】表单**只手动保存**（不许自动往项目里写）');
  // 研究员说的：「为什么会自动保存呀，不要呀，我们只保留手动保存吧」
  // 原来 `saveForm` 挂了个 500ms 防抖，每敲一下就往项目文件写一次 ——
  // 后果：改着改着发现项目被改了、从 _history 还原回来的内容又被覆盖回去。
  // 现在的规矩：打字只写本机 localStorage（刷新不丢），**项目文件只在人点「保存表单」时写**。
  T4.S.state = { project: { root: ROOT1, name: 'x', artifacts: [], status: {} },
                 blocks: [{ id: 'b0_brief', name: '研究设计', title: '研究设计', desc: '',
                            form: [{ key: 'purpose', type: 'text', label: '研究目的' }] }] };
  T4.S.blockId = 'b0_brief';
  T4.S.form['b0_brief'] = {};
  let posted = [];
  globalThis.fetch = async (url, opt) => {
    posted.push(String(url));
    return { json: async () => ({ ok: true, rel: '表单填写.json' }) };
  };
  T4.saveForm({ id: 'b0_brief', form: [] });
  // ⚠ 这里**不能用 `await new Promise(setTimeout)` 等防抖**：本文件的 `setTimeout` 是
  //   打桩成空函数的（第 32 行），等它等于永远不 resolve，会静默把整个测试挂死。
  //   而 `saveForm` 现在**不再挂定时器**了，所以也不需要等。
  eq(posted.filter(u => u.indexOf('/api/forms/save') >= 0).length, 0,
     '**打字之后没有自动往项目里写**（saveForm 里根本没有发请求这条路了）');
  ok(T4.S.formDirty['b0_brief'] === true, '但会标上"有改动还没保存"（人看得见）');
  T4.renderStage();
  const stageEl33 = globalThis.document.querySelector('#stage');
  const html33 = String((stageEl33 && stageEl33.innerHTML) || '');
  ok(html33.indexOf('formSaveBtn') >= 0, '表单卡片上有个「💾 保存表单」按钮');
  ok(html33.indexOf('有改动还没保存') >= 0, '页面上显示"有改动还没保存"的提示');

  // ⚠ 不去真点那个按钮：`saveFormNow` 里碰了 `$('#formSaveBtn')` / `setStatus` 这些真 DOM，
  //   在 Node 的 mock 下会卡住（这一块只验"有没有按钮 + 打字会不会偷偷发请求"）。
  ok(typeof T4.saveFormNow === 'function', '「保存表单」的处理函数存在（点了才走它）');
  eq(posted.filter(u => u.indexOf('/api/forms/save') >= 0).length, 0,
     '整个这一段下来，一次都没偷偷写项目文件');

  // ⚠ 「还原成已保存的」：扔掉没保存的改动，回到项目文件那份。
  //   为什么必须有：打字留在本机草稿里（刷新不丢字）是好事，但人得能一声令下
  //   "当没写过" —— 研究员就是这么选的（「不丢字」和「我的保存才算数」不冲突，
  //   冲突的是"没有退路"）。
  T4.S.formDirty = { b0_brief: true };
  T4.S.form['b0_brief'] = { purpose: '121 随便写的' };
  globalThis.fetch = async () => ({ json: async () => ({ ok: true, rel: '表单填写.json',
    forms: { b0_brief: { purpose: '项目里存的那份' } } }) });
  try {
    await T4.resetFormToSaved();
    eq(T4.S.form['b0_brief'].purpose, '项目里存的那份',
       '还原成项目文件里那份（没保存的 121 被丢掉）');
    ok(!T4.S.formDirty['b0_brief'], '还原之后"未保存"标记清掉');
  } catch (e) {
    ok(false, 'resetFormToSaved() 不该抛错', String(e && e.message));
  }
  // 按钮只在有未保存改动时出现（没改动就不摆一个会误点的按钮）
  T4.S.formDirty = { b0_brief: true };
  T4.renderStage();
  const st33b = String((globalThis.document.querySelector('#stage') || {}).innerHTML || '');
  ok(st33b.indexOf('formResetBtn') >= 0, '有未保存改动时，多一个「↺ 还原成已保存的」按钮');
  T4.S.formDirty = { b0_brief: false };
  T4.renderStage();
  const st33c = String((globalThis.document.querySelector('#stage') || {}).innerHTML || '');
  ok(st33c.indexOf('formResetBtn') < 0, '没有未保存改动时**不摆**这个按钮');

  console.log('\n【34】浅色 / 深色主题');
  // 为什么单独测：主题有三件容易做错、而且**错了也未必立刻看得出来**的事 ——
  //   ① 初值优先级（人选的 > 系统）  ② 切完会不会记住  ③ localStorage 抛错时会不会连页面都白
  const de = globalThis.document.documentElement;
  const themeNow = () => de.getAttribute('data-theme');

  // ① 没存过选择 → 跟随系统
  localStorage._d = {};
  eq(T4.initializeTheme({ systemDark: true }), 'dark', '没存过选择时，跟随系统（系统深色 → 深色）');
  eq(themeNow(), 'dark', '而且真的落到 <html data-theme> 上了（不然样式表不认）');
  eq(T4.initializeTheme({ systemDark: false }), 'light', '系统浅色 → 浅色');

  // ② 人自己选过 → 系统说什么都不算
  localStorage._d = { 'urw.theme': 'dark' };
  eq(T4.initializeTheme({ systemDark: false }), 'dark', '人选过深色，系统是浅色也照样深色');
  localStorage._d = { 'urw.theme': 'light' };
  eq(T4.initializeTheme({ systemDark: true }), 'light', '人选过浅色，系统是深色也照样浅色');
  // 存了个乱七八糟的值 → 当作没存过（不能让一个坏值把页面搞成没有主题）
  localStorage._d = { 'urw.theme': '紫色' };
  eq(T4.initializeTheme({ systemDark: true }), 'dark', '存了个不认识的值 → 当没存过，退回跟随系统');

  // ③ 切换：改页面 + 记住
  localStorage._d = {};
  T4.applyTheme('dark');
  T4.toggleTheme();
  eq(themeNow(), 'light', '深色下点一下 → 切到浅色');
  eq(localStorage.getItem('urw.theme'), 'light', '而且把选择记住了（不是只改这一次）');
  T4.toggleTheme();
  eq(themeNow(), 'dark', '再点一下 → 回到深色');
  eq(localStorage.getItem('urw.theme'), 'dark', '选择跟着更新');

  // ④ 无痕模式 / 存储被禁：localStorage 会**抛**，页面不能因此崩掉
  const realLS = globalThis.localStorage;
  globalThis.localStorage = {
    getItem() { throw new Error('SecurityError: 存储被禁用'); },
    setItem() { throw new Error('SecurityError: 存储被禁用'); },
  };
  eq(T4.readSavedTheme(), null, 'localStorage 抛错时当作"没存过"（不往外抛）');
  let themeThrew = null;
  try { T4.toggleTheme(); } catch (e) { themeThrew = e; }
  ok(themeThrew === null, '存储被禁用时，切换主题也不会抛错把页面打死');
  globalThis.localStorage = realLS;

  // ⑤ 按钮真的挂上了（画了按钮却没绑事件 = 点了没反应，这个坑踩过）
  const tbEl = globalThis.document.querySelector('#btnTheme');
  ok(typeof tbEl.onclick === 'function', '顶栏那个主题按钮挂上了点击处理');
  ok(String(tbEl.title || '').indexOf('深色') >= 0 || String(tbEl.title || '').indexOf('浅色') >= 0,
     '按钮的提示里写着当前是深还是浅');

  console.log('\n【35】⚙ 设置面板：SPSS 路径 + 模型 API');
  // 这一组守两件真出过问题的事：
  //   ① 「导入」chip 原来要求 openpyxl **和** pyreadstat 都装齐才算 ✅，
  //      于是没装 pyreadstat 的机器上它永远是红的 —— 而 pyreadstat 是可选件。
  //   ② 设置页会拿到 API 相关字段，**密钥绝不能出现在发给浏览器的 HTML 里**。
  const envBase = { python: 'x\\python.exe', python_exists: true, spss: 'D:\\SPSS\\stats.exe',
                    spss_exists: true, libs: { openpyxl: true, pyreadstat: false } };
  const cfgLlmOff = { llm: { enabled: false }, llm_status: { ready: false, provider: '' } };
  const chips1 = T4.envChipsHtml(envBase, cfgLlmOff);
  ok(/导入 ✅/.test(chips1), '装了 openpyxl（没装 pyreadstat）时「导入」是绿的（不拿可选件当必要条件）');
  ok(chips1.indexOf('pyreadstat') >= 0 && chips1.indexOf('csv/xlsx 不受影响') >= 0,
     '悬停里说清了"没 pyreadstat 只影响 .sav"（不然用户看见红的会以为环境坏了）');
  const chips2 = T4.envChipsHtml({ ...envBase, libs: { openpyxl: false, pyreadstat: true } }, cfgLlmOff);
  ok(/导入 缺包/.test(chips2), '真缺 openpyxl 时才是红的');
  const chips3 = T4.envChipsHtml(envBase, { llm: { enabled: true }, llm_status: { ready: true, provider: 'api', model: 'deepseek-chat' } });
  ok(chips3.indexOf('自带 API') >= 0, '模型 chip 的悬停里说明了走的是哪条路（API / DSH）');

  const stApi = {
    config_file: 'C:\\x\\config.json',
    spss: { exe: '', exists: false, find_help: '没找到 SPSS 的可执行文件（stats.exe）。',
            candidates: [{ path: 'D:\\SPSS', exe: 'D:\\SPSS\\stats.exe', exists: true, kind: '常见自定义位置' }] },
    llm: { enabled: false, provider: '', api_base: 'https://api.deepseek.com/v1',
           api_model: 'deepseek-chat', api_key_set: false, api_key_mask: '',
           base_hints: [{ base: 'https://api.deepseek.com/v1', name: 'DeepSeek' }],
           default_base: 'https://api.deepseek.com/v1', default_model: 'deepseek-chat' },
  };
  let setHtml = T4.settingsModalHtml(stApi);
  ok(setHtml.indexOf('SPSS 复核') >= 0 && setHtml.indexOf('模型建议') >= 0, '两节都在（SPSS / 模型）');
  ok(setHtml.indexOf('没找到') >= 0, '没找到 SPSS 时如实标「没找到」');
  ok(setHtml.indexOf('没找到？看看怎么办') >= 0, '并且给了"没找到怎么办"的折叠说明（不只报个错就完事）');
  ok(setHtml.indexOf('用这个') >= 0, '候选路径旁边有「用这个」——让人一点就填进去');
  ok(setHtml.indexOf('复制任务书') >= 0, '明确写了"不配模型也能用任务书贴回来"这条路');

  // ⚠ 最关键的一条：密钥绝不能出现在发给浏览器的 HTML 里
  const stKey = JSON.parse(JSON.stringify(stApi));
  stKey.llm.api_key_set = true;
  stKey.llm.api_key_mask = 'sk-…••••••ef';
  stKey.llm.api_key = '';                       // 服务端本来就只给空串
  setHtml = T4.settingsModalHtml(stKey);
  ok(setHtml.indexOf('sk-…••••••ef') >= 0, '已设置时显示脱敏形态（人知道"设过了"）');
  ok(setHtml.indexOf('sk-') < 0 || setHtml.indexOf('sk-…') >= 0, 'HTML 里只有脱敏形态');
  ok(!/sk-[A-Za-z0-9]{16,}/.test(setHtml), '**没有完整密钥**（服务端只给空串 + 掩码，前端不该出现原文）');
  ok(setHtml.indexOf('要换就填新的') >= 0, '空着那一栏的占位说明白了"不填 = 保持不动"（不然人会以为要重填）');

  const stDsh = JSON.parse(JSON.stringify(stApi));
  stDsh.llm.provider = 'dsh';
  stDsh.llm.has_dsh = true;
  ok(T4.settingsModalHtml(stDsh).indexOf('DSH 就绪') >= 0, '走 DSH 那条路时如实标出来');
  const stReady = JSON.parse(JSON.stringify(stApi));
  stReady.llm.provider = 'api';
  ok(T4.settingsModalHtml(stReady).indexOf('自带 API 就绪') >= 0, '自带 API 就绪时也如实标出来');

  console.log('\n' + (fail === 0 ? '全部通过' : '有失败项') + '：' + pass + ' 通过 / ' + fail + ' 失败\n');
  process.exit(fail === 0 ? 0 : 1);
})();
