const D = JSON.parse(document.getElementById('data').textContent);
const $ = (id) => document.getElementById(id);
const UI_ZH = {
  'shots':'镜头',
  'Screening':'放映',
  'Final cut':'最终成片',
  'Story evidence':'故事依据',
  'Premise':'创意前提',
  'Lore':'世界设定',
  'Direction':'导演意图',
  'Script':'剧本',
  'Scenes':'场景',
  'Continuity library':'资产库',
  'Cast':'角色',
  'Movie sets':'场景资产',
  'Props':'道具',
  'BGM':'背景音乐',
  'Render evidence':'渲染证据',
  'Shot review':'镜头审阅',
  'Model calls':'模型调用',
  'Episode production archive':'单集制作档案',
  'Archive in progress':'制作档案整理中',
  'materializing evidence chain':'正在汇总证据链',
  'Project':'项目',
  'Episode':'单集',
  'Shots on record':'已记录镜头',
  '01 · Origin':'01 · 起点',
  '02 · Story bible':'02 · 故事圣经',
  '03 · Directorial intent':'03 · 导演意图',
  '04 · Narrative':'04 · 叙事',
  '05 · Breakdown':'05 · 拆解',
  '06 · Continuity':'06 · 连续性',
  '07 · Continuity':'07 · 连续性',
  '08 · Continuity':'08 · 连续性',
  '09 · Sound':'09 · 声音',
  '10 · Render history':'10 · 渲染历史',
  '11 · Audit trail':'11 · 审计记录',
  'The original creative input — every shot traces back here.':'最初的创意输入，每个镜头都可追溯至此',
  'Original creative input':'原始创意输入',
  'World, tone, and visual motifs — project and episode level.':'项目与单集层面的世界、基调和视觉母题',
  'Tone, audiovisual strategy, references, and key imagery.':'基调、视听策略、参考和关键意象',
  'The merged full script — the unified narrative.':'合并后的完整剧本与统一叙事',
  'Script and storyboard broken down by scene.':'按场景拆分的剧本与分镜',
  'References, attributes, soul cards, and voices.':'参考图、属性、角色灵魂卡和声音',
  'Project-global and episode-local sets, with source paths.':'项目全局和单集局部场景及其来源路径',
  'Key props, state images, and notes.':'关键道具、状态图和说明',
  'Preview project-level background music.':'预览项目级背景音乐',
  'Full trial-and-error record — compare videos, prompts, and reviews per version.':'完整试错记录，可逐版本比较视频、提示词和审阅结果',
  'Calls grouped by shot — click a row for raw JSON.':'按镜头汇总调用，点击行查看原始 JSON',
  'Complete one selection per shot, then copy the handoff for the agent.':'每个镜头选择一个候选后，复制结果交给 Agent。',
  'Copy selections for agent':'复制选择结果',
  'Image evidence':'图片证据',
  'Select this take':'选择此候选',
  'Select + copy for Agent':'选择并复制给 Agent',
  'Copy selection for Agent':'复制选择给 Agent',
  'Primary':'主图',
  'Pending':'待应用',
  'Candidate':'候选图',
  'Recommended':'Agent 推荐',
  'Agent recommendation':'Agent 推荐',
  'Accept + copy for Agent':'接受并复制给 Agent',
  'Candidates':'候选图',
  'Rendered':'已渲染',
  'Not rendered':'未渲染',
  'Final selection':'最终选择',
  'Choose a candidate from the list.':'请从右侧候选图中选择',
  'No storyboard reference selected':'尚未选择分镜参考图',
  'asset · up / down':'资产 · 上 / 下',
  'candidate · left / right':'候选图 · 左 / 右',
  'Premise':'创意前提',
  'Assets':'资产',
  'Board':'分镜',
  'Renders':'渲染',
  'Final':'成片',
  'Final cut ready':'最终成片已就绪',
  'Archive in progress':'制作档案整理中',
  'Visual style':'视觉风格',
  'Emotional tone':'情绪基调',
  'Camera language':'镜头语言',
  'Pacing curve':'节奏曲线',
  'Director reference':'导演参考',
  'Narrator':'旁白',
  'Shot kinds target':'镜头类型目标',
  'Motifs':'视觉母题',
  'Director prompt':'导演提示词',
  'Static panel prompt':'静态分镜提示词',
  'Prompt evidence':'提示词证据',
  'Render shot prompt':'实际渲染提示词',
  'Visual prompt':'画面提示词',
  'Post voice script':'后期配音文本',
  'Speech script':'台词文本',
  'Not sent to the video model':'不会发送给视频模型',
  'Prompt contract':'提示词合同',
  'model speech':'模型发声',
  'post voice':'后期配音',
  'silent':'无对白',
  'generated text off':'禁止生成文字',
  'generated text allowed':'允许生成文字',
  'Temporal beats':'时序动作',
  'Reference contract':'参考契约',
  'Camera path':'摄影机路径',
  'Ending composition':'结束构图',
  'micro shot · 2-5s':'微镜头 · 2–5 秒',
  'core shot · 6-10s':'常规镜头 · 6–10 秒',
  'extended shot · 11-15s':'延长镜头 · 11–15 秒',
  'exceptional long take · 16-30s':'例外长镜头 · 16–30 秒',
  'Critique':'审阅意见',
  'Screenplay':'剧本正文',
  'Characters':'角色',
  'Action':'动作',
  'Dialog':'对白',
};
const viewerLanguageKey = 'spark-video:viewer-language';
let viewerLanguage = D.viewer_language === 'zh' ? 'zh' : 'en';
const originalText = new WeakMap();
const translatedAttributes = new WeakMap();
const translateTree = (root = document.body) => {
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  let node;
  while ((node = walker.nextNode())) {
    if (!node.parentElement || ['SCRIPT','STYLE','PRE','CODE'].includes(node.parentElement.tagName)) continue;
    if (!originalText.has(node)) originalText.set(node, node.nodeValue);
    const source = originalText.get(node);
    const trimmed = source.trim();
    const translated = viewerLanguage === 'zh' ? UI_ZH[trimmed] : null;
    node.nodeValue = translated
      ? source.replace(trimmed, translated)
      : source;
  }
  root.querySelectorAll?.('[aria-label],[title]').forEach(el => {
    if (!translatedAttributes.has(el)) {
      translatedAttributes.set(el, {
        aria: el.getAttribute('aria-label'),
        title: el.getAttribute('title'),
      });
    }
    const source = translatedAttributes.get(el);
    for (const [attr, value] of [['aria-label', source.aria], ['title', source.title]]) {
      if (value == null) continue;
      el.setAttribute(attr, viewerLanguage === 'zh' && UI_ZH[value] ? UI_ZH[value] : value);
    }
  });
};
const syncLanguageToggle = () => {
  const button = $('language-toggle');
  if (!button) return;
  button.innerHTML = `<span class="${viewerLanguage === 'en' ? 'active' : ''}">EN</span><i>/</i><span class="${viewerLanguage === 'zh' ? 'active' : ''}">CH</span>`;
  button.setAttribute(
    'aria-label',
    viewerLanguage === 'zh' ? 'Switch to English' : 'Switch to Chinese',
  );
  document.documentElement.lang = viewerLanguage === 'zh' ? 'zh-CN' : 'en';
};
const setViewerLanguage = language => {
  viewerLanguage = language === 'zh' ? 'zh' : 'en';
  localStorage.setItem(viewerLanguageKey, viewerLanguage);
  translateTree();
  syncLanguageToggle();
};
const languageObserver = new MutationObserver(records => {
  records.forEach(record => record.addedNodes.forEach(node => {
    if (node.nodeType === Node.ELEMENT_NODE) translateTree(node);
  }));
});
languageObserver.observe(document.body, {childList:true, subtree:true});
$('language-toggle')?.addEventListener('click', () =>
  setViewerLanguage(viewerLanguage === 'zh' ? 'en' : 'zh')
);
setViewerLanguage(viewerLanguage);
const esc = (s) => (s == null ? '' : String(s).replace(/[&<>"']/g, c => (
  {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])));
const md = (txt) => {
  if (!txt) return '<div class="empty">This material has not been generated yet.</div>';
  try { return marked.parse(txt); } catch (e) { return '<pre>' + esc(txt) + '</pre>'; }
};
const missing = (msg) => `<div class="empty">${esc(msg || 'This material has not been generated yet.')}</div>`;

// ---- overview progress + navigation
const hasAssets = (...groups) => groups.some(g => (g||[]).some(x => (x.entities||[]).length));
const progress = [
  ['01','Premise',Boolean(D.premise)],
  ['02','Lore',Boolean((D.lore_sections||[]).length || D.lore)],
  ['03','Script',Boolean(D.script)],
  ['04','Assets',hasAssets(D.cast_groups,D.set_groups,D.prop_groups)],
  ['05','Board',Boolean((D.scenes||[]).length || (D.shots||[]).length)],
  ['06','Renders',Boolean((D.shots||[]).some(s => (s.versions||[]).length))],
  ['07','Final',Boolean(D.final)],
];
$('hero-progress').innerHTML = progress.map(([n,label,ready]) => `<div class="stage ${ready?'ready':''}"><i class="stage-dot"></i><span>${n}</span>${label}</div>`).join('');
const done = progress.filter(x => x[2]).length;
$('hero-status').textContent = D.final ? 'Final cut ready' : 'Archive in progress';
const audioSummary = D.audio?.mode
  ? ` · ${D.audio.mode}${D.audio.presenter ? ` · ${D.audio.presenter}` : ''}${D.audio.voice ? ` / ${D.audio.voice}` : ''}`
  : '';
$('hero-status-detail').textContent = `${done} / ${progress.length} stages on record · ${D.video_model || 'model n/a'}${audioSummary}`;
const fitHeroTitle = () => {
  const title = document.querySelector('.hero h1');
  if (!title) return;
  title.style.fontSize = '';
  let size = parseFloat(getComputedStyle(title).fontSize);
  const available = title.parentElement.clientWidth;
  while (title.scrollWidth > available && size > 24) {
    size -= 1;
    title.style.fontSize = `${size}px`;
  }
};
requestAnimationFrame(fitHeroTitle);
if (document.fonts?.ready) document.fonts.ready.then(fitHeroTitle);
window.addEventListener('resize', fitHeroTitle);
const navShell = document.querySelector('nav');
const navToggle = $('nav-toggle');
const navLinks = [...document.querySelectorAll('nav a:not(.shot-subnav-link)')];
const mobileNav = window.matchMedia('(max-width: 980px)');
const setNavOpen = (open) => {
  navShell.classList.toggle('open', open);
  navToggle.setAttribute('aria-expanded', String(open));
  navToggle.setAttribute('aria-label', open ? 'Collapse production navigation' : 'Expand production navigation');
};
navToggle.addEventListener('click', () => setNavOpen(!navShell.classList.contains('open')));
let navCorrectTimer = 0;
const smoothScrollTo = (el) => {
  if (!el) return;
  el.scrollIntoView({behavior:'smooth', block:'start'});
  clearTimeout(navCorrectTimer);
  navCorrectTimer = setTimeout(() => {
    const margin = parseFloat(getComputedStyle(el).scrollMarginTop) || 0;
    if (Math.abs(el.getBoundingClientRect().top - margin) > 160) el.scrollIntoView({behavior:'instant', block:'start'});
  }, 2400);
};
['wheel', 'touchmove'].forEach(type => window.addEventListener(type, () => clearTimeout(navCorrectTimer), {passive:true}));
navLinks.forEach(link => link.addEventListener('click', event => {
  event.preventDefault();
  smoothScrollTo(document.querySelector(link.getAttribute('href')));
  if (mobileNav.matches) setNavOpen(false);
}));
mobileNav.addEventListener('change', e => { if (!e.matches) setNavOpen(false); });
const observed = navLinks.map(a => document.querySelector(a.getAttribute('href'))).filter(Boolean);
let navFramePending = false;
const syncMainNavigation = () => {
  navFramePending = false;
  const marker = window.innerHeight * .28;
  let current = observed[0];
  observed.forEach(section => { if (section.getBoundingClientRect().top <= marker) current = section; });
  if (window.scrollY + window.innerHeight >= document.documentElement.scrollHeight - 4) current = observed.at(-1);
  if (current) navLinks.forEach(a => a.classList.toggle('active', a.getAttribute('href') === `#${current.id}`));
};
window.addEventListener('scroll', () => {
  if (!navFramePending) { navFramePending = true; requestAnimationFrame(syncMainNavigation); }
}, {passive:true});
syncMainNavigation();

// ---- markdown sections
$('x-premise').innerHTML = D.premise
  ? `<details class="premise-panel">
      <summary>Original creative input</summary>
      <div class="md">${md(D.premise)}</div>
      ${D.premise_source ? `<div class="premise-source">source · <code>${esc(D.premise_source)}</code></div>` : ''}
    </details>`
  : missing('(no initialPrompt.md / premise.md found in project or episode dir)');
const renderLoreSections = () => {
  const sections = D.lore_sections || [];
  if (sections.length) {
    return sections.map(s => {
      const fm = s.frontmatter || {};
      const imagery = fm.imagery_system && typeof fm.imagery_system === 'object' ? fm.imagery_system : {};
      const asList = value => Array.isArray(value) ? value : (value ? [value] : []);
      const tagGroup = (label, values, tone = '') => asList(values).length
        ? `<div class="lore-tag-group ${tone}"><b>${label}</b><div>${asList(values).map(value => `<span>${esc(String(value))}</span>`).join('')}</div></div>`
        : '';
      const genres = asList(fm.genre);
      const hasSummary = Object.keys(fm).length > 0;
      const summary = hasSummary ? `<div class="lore-bible">
        <div class="lore-bible-head">
          <div><div class="lore-bible-label">Story bible</div><h4>${esc(fm.title || s.label || 'Untitled project')}</h4></div>
          <div class="lore-bible-meta">${genres.map(value => `<span>${esc(String(value))}</span>`).join('')}${fm.duration_target_s ? `<span>${esc(fm.duration_target_s)}s</span>` : ''}</div>
        </div>
        ${(fm.mood_anchor || fm.visual_style) ? `<div class="lore-bible-foundation">
          ${fm.mood_anchor ? `<div><b>Mood anchor</b><p>${esc(fm.mood_anchor)}</p></div>` : ''}
          ${fm.visual_style ? `<div><b>Visual style</b><p>${esc(fm.visual_style)}</p></div>` : ''}
        </div>` : ''}
        <div class="lore-bible-tags">
          ${tagGroup('Forbidden', fm.forbidden, 'forbidden')}
          ${tagGroup('Visual motifs', imagery.motifs)}
          ${tagGroup('Highlight elements', imagery.highlight_elements)}
        </div>
      </div>` : '';
      return `<div class="scope-block">
      <div class="scope-head">
        <h3>${esc(s.label || s.scope || 'Lore')}</h3>
        <span class="scope-badge ${esc(s.scope || '')}">${esc(s.scope || '')}</span>
      </div>
      ${s.source ? `<div class="source-line">source · <code>${esc(s.source)}</code></div>` : ''}
      ${summary}
      ${s.body ? `<div class="md lore-body">${md(s.body)}</div>` : ''}
    </div>`;
    }).join('');
  }
  return D.lore ? `<div class="md">${md(D.lore)}</div>` : missing('(no lore.md found)');
};
$('x-lore').innerHTML = renderLoreSections();
const renderScript = source => {
  if (!source) return missing('(no script.md found)');
  const lines = source.replace(/\r\n?/g, '\n').split('\n');
  let documentTitle = '';
  const scenes = [];
  let current = null;
  lines.forEach(line => {
    const sceneMatch = line.match(/^##\s+(.+)$/);
    if (sceneMatch) {
      current = {title:sceneMatch[1].trim(), lines:[]};
      scenes.push(current);
      return;
    }
    const titleMatch = line.match(/^#\s+(.+)$/);
    if (!current && titleMatch && !documentTitle) { documentTitle = titleMatch[1].trim(); return; }
    if (current) current.lines.push(line);
  });
  if (!scenes.length) return `<div class="md">${md(source)}</div>`;
  const knownFields = new Map([
    ['characters','characters'],['角色','characters'],['人物','characters'],
    ['action','action'],['动作','action'],['visual','action'],['画面','action'],
    ['dialog','dialog'],['dialogue','dialog'],['对白','dialog'],['台词','dialog'],
    ['type','meta'],['类型','meta'],['estimated duration','meta'],['duration','meta'],['预计时长','meta'],['时长','meta'],
    ['pacing','meta'],['节奏','meta'],
    ['backstory','context'],['背景','context'],['narration','dialog'],['旁白','dialog'],['beats','context'],['节拍','context'],
  ]);
  const classifyField = (label, sceneCharacters = new Set()) => {
    const normalized = label.trim().toLowerCase();
    const knownType = knownFields.get(normalized);
    const isSpeaker = !knownType && (
      [...sceneCharacters].some(name => label === name || label.startsWith(`${name}（`) || label.startsWith(`${name} (`))
      || /(旁白|voiceover|narrator)/i.test(label)
    );
    return {type:knownType || (isSpeaker ? 'dialog' : 'context'), speaker:isSpeaker};
  };
  const parseBlocks = (sourceLines, sceneCharacters) => {
    const blocks = [];
    let active = null;
    const flush = () => {
      if (!active) return;
      active.content = active.lines.join('\n').trim();
      if (active.content || active.label) blocks.push(active);
      active = null;
    };
    sourceLines.forEach(line => {
      const field = line.match(/^\s*(?:[-*]\s+)?\*\*([^*]+)\*\*\s*[:：]\s*(.*)$/);
      if (field) {
        flush();
        const label = field[1].trim();
        active = {...classifyField(label, sceneCharacters), label, lines:[field[2]]};
      } else if (line.trim() || active) {
        if (!active) active = {type:'action', label:'Action', speaker:false, lines:[]};
        active.lines.push(line);
      }
    });
    flush();
    return blocks;
  };
  const renderScene = (scene, index) => {
    const sceneCharacters = new Set();
    scene.lines.forEach(line => {
      const field = line.match(/^\s*(?:[-*]\s+)?\*\*([^*]+)\*\*\s*[:：]\s*(.*)$/);
      if (!field || knownFields.get(field[1].trim().toLowerCase()) !== 'characters') return;
      field[2].split(/[,，、]/).map(name => name.trim()).filter(Boolean).forEach(name => sceneCharacters.add(name));
    });
    const beatStart = scene.lines.findIndex(line => /^\s*\d+[.)]\s+\*\*[^*]+\*\*\s*[:：]/.test(line));
    const blocks = parseBlocks(beatStart >= 0 ? scene.lines.slice(0, beatStart) : scene.lines, sceneCharacters)
      .filter(block => !/^(beats|节拍)$/i.test(block.label));
    const characterBlocks = blocks.filter(block => block.type === 'characters');
    const metaBlocks = blocks.filter(block => block.type === 'meta');
    const storyBlocks = blocks.filter(block => !['characters','meta'].includes(block.type));
    const beats = [];
    if (beatStart >= 0) {
      let beat = null;
      let part = null;
      const flushPart = () => {
        if (!part || !beat) return;
        part.content = part.lines.join('\n').trim();
        if (part.content || part.label) beat.parts.push(part);
        part = null;
      };
      scene.lines.slice(beatStart).forEach(line => {
        const numbered = line.match(/^\s*(\d+)[.)]\s+\*\*([^*]+)\*\*\s*[:：]\s*(.*)$/);
        const field = line.match(/^\s*(?:[-*]\s+)?\*\*([^*]+)\*\*\s*[:：]\s*(.*)$/);
        if (numbered) {
          flushPart();
          beat = {number:numbered[1], parts:[]};
          beats.push(beat);
          const label = numbered[2].trim();
          part = {...classifyField(label, sceneCharacters), label, lines:[numbered[3]]};
        } else if (field && beat) {
          flushPart();
          const label = field[1].trim();
          part = {...classifyField(label, sceneCharacters), label, lines:[field[2]]};
        } else if (beat && (line.trim() || part)) {
          if (!part) part = {type:'context', label:'Notes', speaker:false, lines:[]};
          part.lines.push(line);
        }
      });
      flushPart();
    }
    const renderBlock = block => `<div class="script-block script-${block.type}">
      <div class="script-block-label">${block.speaker ? 'Dialog' : esc(block.label)}</div>
      <div class="script-block-content">${block.speaker ? `<b>${esc(block.label)}</b>` : ''}<div class="md">${md(block.content)}</div></div>
    </div>`;
    const renderBeat = beat => `<article class="script-beat">
      <div class="script-beat-index"><span>Beat</span><b>${String(beat.number).padStart(2,'0')}</b></div>
      <div class="script-beat-parts">${beat.parts.map(part => {
        const durationMatch = part.content.match(/(?:建议时长|duration)\s*[:：]\s*([^。\n]+)/i);
        const content = durationMatch ? part.content.replace(durationMatch[0], '').trim() : part.content;
        return `<div class="script-beat-part script-beat-${part.type}">
          <div class="script-beat-label">${esc(part.label)}${durationMatch ? `<span>${esc(durationMatch[1].trim())}</span>` : ''}</div>
          <div class="md">${md(content)}</div>
        </div>`;
      }).join('')}</div>
    </article>`;
    return `<article class="script-scene">
      <header class="script-scene-head"><span>${String(index + 1).padStart(2,'0')}</span><h4>${esc(scene.title)}</h4></header>
      ${(characterBlocks.length || metaBlocks.length) ? `<div class="script-scene-meta">
        ${characterBlocks.map(block => `<div class="script-characters"><b>${esc(block.label)}</b>${block.content.split(/[,，、]/).filter(Boolean).map(name => `<span>${esc(name.trim())}</span>`).join('')}</div>`).join('')}
        ${metaBlocks.map(block => `<div><b>${esc(block.label)}</b><span>${esc(block.content)}</span></div>`).join('')}
      </div>` : ''}
      <div class="script-scene-body">${storyBlocks.map(renderBlock).join('')}${beats.length ? `<div class="script-beats">${beats.map(renderBeat).join('')}</div>` : ''}</div>
    </article>`;
  };
  return `${documentTitle ? `<div class="script-document-title"><span>Screenplay</span><h3>${esc(documentTitle)}</h3></div>` : ''}<div class="script-scenes">${scenes.map(renderScene).join('')}</div>`;
};
$('x-script').innerHTML = renderScript(D.script);

// ---- direction
if (D.direction) {
  const dd = D.direction;
  const decisions = dd.audiovisual_decisions || dd.viewing_decisions || {};
  const tones = dd.tone_dimensions || {};
  const toneText = [tones.primary, tones.secondary].filter(Boolean).join(' · ') || dd.tone || decisions.tone || '';
  const skipKeys = new Set(toneText && decisions.tone === toneText ? ['tone'] : []);
  const motifs = (dd.imagery_system && typeof dd.imagery_system === 'object' && dd.imagery_system.motifs) || [];
  const narrator = dd.narrator || null;
  const shotKinds = dd.shot_kinds_target || null;
  const labelDirectionKey = key => String(key)
    .replace(/^scene0?/, 'Scene ')
    .replace(/_/g, ' ')
    .replace(/\b\w/g, c => c.toUpperCase());
  const flatLead = [
    ['Visual style', dd.visual_style],
    ['Emotional tone', toneText],
  ].filter(([,value]) => value);
  const flatStrategy = [
    ['Camera language', dd.camera_style],
  ].filter(([,value]) => value);
  const colorGrade = dd.color_grade && typeof dd.color_grade === 'object' ? dd.color_grade : {};
  const soundDesign = dd.sound_design && typeof dd.sound_design === 'object' ? dd.sound_design : {};
  const sceneId = key => key.match(/^scene[_-]?(\d+)/i)?.[1] || key;
  const sceneKeys = [...Object.keys(colorGrade)];
  Object.keys(soundDesign).forEach(key => {
    if (!sceneKeys.some(existing => sceneId(existing) === sceneId(key))) sceneKeys.push(key);
  });
  const sceneDirection = sceneKeys.map((key, index) => {
    const sceneNumber = sceneId(key);
    const soundKey = Object.keys(soundDesign).find(candidate =>
      candidate === key || sceneId(candidate) === sceneNumber
    );
    const color = colorGrade[key];
    const sound = soundDesign[soundKey];
    return `<article class="direction-scene">
      <div class="direction-scene-index">${String(index + 1).padStart(2, '0')}</div>
      <div><h4>${esc(labelDirectionKey(key))}</h4>
        ${color ? `<p><b>Color</b>${esc(color)}</p>` : ''}
        ${sound ? `<p><b>Sound</b>${esc(sound)}</p>` : ''}
      </div>
    </article>`;
  }).join('');
  const decisionRows = Object.entries(decisions).filter(([k]) => !skipKeys.has(k));
  const renderDirectionValue = (value, depth = 0) => {
    if (value == null || value === '') return '';
    if (Array.isArray(value)) {
      return `<div class="direction-value-list">${value.map(item =>
        (item && typeof item === 'object')
          ? `<div class="direction-value-group">${renderDirectionValue(item, depth + 1)}</div>`
          : `<span>${esc(String(item))}</span>`
      ).join('')}</div>`;
    }
    if (typeof value === 'object') {
      return `<div class="direction-value-map">${Object.entries(value).map(([key,item]) => {
        const rendered = renderDirectionValue(item, depth + 1);
        return rendered ? `<div class="direction-value-row"><b>${esc(labelDirectionKey(key))}</b>${rendered}</div>` : '';
      }).join('')}</div>`;
    }
    return `<p>${esc(String(value))}</p>`;
  };
  const renderPacingCurve = value => {
    if (!value) return '';
    if (!Array.isArray(value) || !value.length || !value.every(item => item && typeof item === 'object')) {
      return `<section class="pacing-curve"><div class="direction-group-label">Pacing curve</div>${renderDirectionValue(value)}</section>`;
    }
    return `<section class="pacing-curve">
      <div class="pacing-curve-head"><div class="direction-group-label">Pacing curve</div><span>external tempo / internal pressure</span></div>
      <div class="pacing-track">${value.map((item, index) => {
        const scene = item.scene || item.id || `S${String(index + 1).padStart(2, '0')}`;
        const external = item.external ?? item.pace ?? item.tempo ?? '';
        const internal = item.internal ?? item.emotion ?? item.pressure ?? '';
        const extras = Object.entries(item).filter(([key]) => !['scene','id','external','pace','tempo','internal','emotion','pressure'].includes(key));
        return `<article class="pacing-step">
          <div class="pacing-scene"><i></i><b>${esc(scene)}</b><span>${String(index + 1).padStart(2, '0')}</span></div>
          ${external !== '' ? `<p><b>External</b><span>${esc(external)}</span></p>` : ''}
          ${internal !== '' ? `<p><b>Internal</b><span>${esc(internal)}</span></p>` : ''}
          ${extras.map(([key, itemValue]) => `<p><b>${esc(labelDirectionKey(key))}</b><span>${esc(typeof itemValue === 'string' ? itemValue : JSON.stringify(itemValue))}</span></p>`).join('')}
        </article>`;
      }).join('')}</div>
    </section>`;
  };
  const renderMotifs = value => value.length ? `<section class="direction-motifs">
    <div class="direction-group-label">Motifs</div>
    <div class="direction-motif-grid">${value.map((motif, index) => {
      const name = typeof motif === 'string' ? motif : (motif.name || motif.title || 'Untitled motif');
      const meaning = typeof motif === 'object' ? motif.meaning : '';
      const landings = typeof motif === 'object' && Array.isArray(motif.landings) ? motif.landings : [];
      return `<article class="direction-motif"><span>${String(index + 1).padStart(2, '0')}</span><div><b>${esc(name)}</b>${meaning ? `<p>${esc(meaning)}</p>` : ''}${landings.length ? `<div class="direction-motif-landings">${landings.map(landing => `<i>${esc(landing)}</i>`).join('')}</div>` : ''}</div></article>`;
    }).join('')}</div>
  </section>` : '';
  const renderDirectionSequence = (key, value) => `<section class="direction-data-sequence">
    <div class="direction-group-label">${esc(labelDirectionKey(key))}</div>
    <div class="direction-data-track">${value.map((item, index) => {
      const entries = Object.entries(item);
      const identityKey = ['scene','id','name','title','shot','episode'].find(candidate => item[candidate] != null && item[candidate] !== '');
      const identity = identityKey ? item[identityKey] : `${labelDirectionKey(key)} ${index + 1}`;
      const details = entries.filter(([itemKey]) => itemKey !== identityKey);
      return `<article class="direction-data-step">
        <div class="direction-data-step-head"><i></i><b>${esc(identity)}</b><span>${String(index + 1).padStart(2, '0')}</span></div>
        <div class="direction-data-fields">${details.map(([itemKey,itemValue]) => `<div><b>${esc(labelDirectionKey(itemKey))}</b>${renderDirectionValue(itemValue)}</div>`).join('')}</div>
      </article>`;
    }).join('')}</div>
  </section>`;
  const consumedDirectionKeys = new Set([
    'title','mode','project','episode','visual_style','tone','camera_style','pacing_curve','color_grade','sound_design',
    'audiovisual_decisions','viewing_decisions','tone_dimensions','director_reference',
    'imagery_system','narrator','shot_kinds_target',
  ]);
  const additionalEntries = Object.entries(dd).filter(([key,value]) =>
    !consumedDirectionKeys.has(key) && value != null && value !== ''
  );
  const toneExtras = Object.fromEntries(Object.entries(tones).filter(([key]) => !['primary','secondary'].includes(key)));
  if (Object.keys(toneExtras).length) additionalEntries.push(['tone_details', toneExtras]);
  const imageryExtras = dd.imagery_system && typeof dd.imagery_system === 'object'
    ? Object.fromEntries(Object.entries(dd.imagery_system).filter(([key]) => key !== 'motifs'))
    : {};
  if (Object.keys(imageryExtras).length) additionalEntries.push(['imagery_details', imageryExtras]);
  const sequenceEntries = additionalEntries.filter(([,value]) =>
    Array.isArray(value) && value.length && value.every(item => item && typeof item === 'object' && !Array.isArray(item))
  );
  const cardEntries = additionalEntries.filter(entry => !sequenceEntries.includes(entry));
  const additionalSequences = sequenceEntries.map(([key,value]) => renderDirectionSequence(key, value)).join('');
  const additionalDirection = cardEntries.map(([key,value]) => `<article class="direction-dynamic-card">
    <div class="direction-group-label">${esc(labelDirectionKey(key))}</div>
    ${renderDirectionValue(value)}
  </article>`).join('');
  const directionMeta = [
    ['Project', dd.project],
    ['Episode', dd.episode],
  ].filter(([,value]) => value != null && value !== '');
  $('x-direction').innerHTML = `
    ${(D.direction_source || directionMeta.length) ? `<div class="direction-source-row">
      ${D.direction_source ? `<div class="source-line">source · <code>${esc(D.direction_source)}</code></div>` : '<div></div>'}
      ${directionMeta.length ? `<div class="direction-meta">${directionMeta.map(([label,value]) => `<span><b>${label}</b>${esc(value)}</span>`).join('')}</div>` : ''}
    </div>` : ''}
    ${(dd.title || dd.mode || flatLead.length || dd.director_reference) ? `<div class="direction-lead">
      <div class="direction-kicker">${dd.mode ? `<span>${esc(dd.mode)}</span>` : ''}${dd.title ? esc(dd.title) : 'Directorial compass'}</div>
      ${flatLead.map(([label,value]) => `<div class="direction-statement"><b>${label}</b><p>${esc(value)}</p></div>`).join('')}
      ${dd.director_reference ? `<div class="direction-statement"><b>Director reference</b><p>${esc(dd.director_reference)}</p></div>` : ''}
    </div>` : ''}
    ${flatStrategy.length ? `<div class="direction-strategy">${flatStrategy.map(([label,value]) => `<div><b>${label}</b>${renderDirectionValue(value)}</div>`).join('')}</div>` : ''}
    ${renderPacingCurve(dd.pacing_curve)}
    ${decisionRows.length ? `<div class="direction-strategy">${decisionRows.map(([k,v]) => `<div><b>${esc(labelDirectionKey(k))}</b><p>${esc(typeof v === 'string' ? v : JSON.stringify(v, null, 0))}</p></div>`).join('')}</div>` : ''}
    ${sceneDirection ? `<div class="direction-sequence"><div class="direction-group-label">Scene color & sound map</div>${sceneDirection}</div>` : ''}
    ${narrator ? `<div class="card"><h3 style="margin-top:0">Narrator</h3>${Object.entries(narrator).map(([k,v]) => `<div style="margin:4px 0;font-size:13px;"><b>${esc(k)}:</b> <span style="color:var(--mute)">${esc(String(v))}</span></div>`).join('')}</div>` : ''}
    ${shotKinds ? `<div class="card"><h3 style="margin-top:0">Shot kinds target</h3>${Object.entries(shotKinds).map(([k,v]) => `<span class="kpill">${esc(k)} ${Math.round(v*100)}%</span>`).join(' ')}</div>` : ''}
    ${renderMotifs(motifs)}
    ${additionalSequences}
    ${additionalDirection ? `<div class="direction-dynamic">${additionalDirection}</div>` : ''}
  `;
} else { $('x-direction').innerHTML = missing('(no director.json / direction.json)'); }

// ---- scenes
$('x-scenes').innerHTML = (D.scenes && D.scenes.length) ? D.scenes.map(s => `
  <details><summary>${esc(s.name)}${s.json && s.json.shots ? ' · '+s.json.shots.length+' shots' : ''}</summary>
    <div class="md">${md(s.body)}</div>
  </details>`).join('') : missing('(no scenes/)');

// ---- entity grids
const assetSelectionKey = `spark-video:${D.project}:${D.episode}:asset-selections`;
let pendingAssetSelections = {};
try { pendingAssetSelections = JSON.parse(localStorage.getItem(assetSelectionKey) || '{}'); }
catch (_) { pendingAssetSelections = {}; }
const entitySelectionKey = (kind, e) => `${kind}:${e.scope || 'global'}:${e.name}`;
const pendingAssetImage = key => {
  const selection = pendingAssetSelections[key];
  return typeof selection === 'string' ? selection : selection?.image;
};
const renderEntity = (e, kind='asset') => {
  const images = [...new Set(e.images || [])];
  const selectionKey = entitySelectionKey(kind, e);
  const pending = pendingAssetImage(selectionKey);
  const manifestPortrait = images.includes(e.selected_image) ? e.selected_image : null;
  const recommendation = images.includes(e.recommended_image) ? e.recommended_image : null;
  const portrait = images.includes(pending) ? pending : (recommendation || manifestPortrait || images[0]);
  const extraImages = images.filter(u => u !== portrait);
  const hasPending = Boolean(pending && pending !== manifestPortrait && images.includes(pending));
  const showingRecommendation = !hasPending && recommendation === portrait;
  const fm = e.frontmatter || {};
  const fmKeys = ['age','gender','occupation','archetype','voice_style'].filter(k => fm[k]);
  const soulLabel = (fmKeys.length || (e.audios||[]).length) ? 'Soul card' : 'Asset notes';
  return `<div class="entity" data-asset-key="${esc(selectionKey)}" data-asset-kind="${esc(kind)}" data-asset-name="${esc(e.name)}" data-asset-scope="${esc(e.scope || 'global')}" data-manifest-image="${esc(manifestPortrait || '')}" data-recommended-image="${esc(recommendation || '')}" data-asset-images="${esc(JSON.stringify(images))}">
    <div class="entity-visual">
      ${portrait ? `<img class="entity-backdrop" src="${portrait}" alt="" aria-hidden="true" loading="lazy" decoding="async"><img class="entity-main-image" src="${portrait}" data-asset-url="${portrait}" alt="${esc(e.name)}" loading="lazy" decoding="async">` : `<div class="empty">Reference image pending</div>`}
      ${portrait ? `<span class="entity-primary-badge${hasPending ? ' pending' : (showingRecommendation ? ' recommended' : '')}">${hasPending ? 'Pending' : (showingRecommendation ? 'Default' : (manifestPortrait ? 'Primary' : 'Candidate'))}</span>` : ''}
    </div>
    <div class="entity-info">
      <h4>${esc(e.name)}</h4>
      ${fmKeys.length ? `<div class="fm">${fmKeys.map(k=>`<span><b>${k}</b>: ${esc(fm[k])}</span>`).join('')}</div>` : ''}
      ${(e.audios||[]).map(u=>`<audio controls src="${u}"></audio>`).join('')}
      <div class="entity-soul">
        <div class="entity-soul-label">${soulLabel}</div>
        <div class="entity-soul-scroll">
          ${e.body ? `<div class="md">${md(e.body)}</div>` : `<div class="prompt-missing">Reference notes pending.</div>`}
          ${extraImages.length ? `<div class="entity-candidates-head"><span>Candidates</span><b>${extraImages.length}</b></div><div class="entity-extra-images">${extraImages.map(u=>`<img src="${u}" data-asset-url="${u}" alt="${esc(e.name)} candidate" loading="lazy" decoding="async">`).join('')}</div>` : ''}
        </div>
      </div>
    </div>
  </div>`;
};
const renderEntityGroups = (groups, fallbackItems, emptyMsg, kind) => {
  groups = groups || [];
  if (!groups.length && (fallbackItems||[]).length) {
    return `<div class="grid">${fallbackItems.map(e => renderEntity(e, kind)).join('')}</div>`;
  }
  if (!groups.length) return missing(emptyMsg);
  return groups.map(g => {
    const items = g.entities || [];
    const manifest = g.manifest
      ? `<span>manifest · ${g.manifest_url ? `<a class="path-link" href="${esc(g.manifest_url)}" target="_blank" rel="noopener" title="Open manifest"><code>${esc(g.manifest)}</code></a>` : `<code>${esc(g.manifest)}</code>`}</span>`
      : '';
    const root = g.source_root
      ? `<span>folder · <code>${esc(g.source_root)}</code></span>`
      : '';
    return `<div class="scope-block">
      <div class="scope-head">
        <h3>${esc(g.label || g.scope || 'Assets')}</h3>
        <span class="scope-badge ${esc(g.scope || '')}">${esc(g.scope || '')}</span>
        <span class="kpill">${items.length} items</span>
      </div>
      ${(root || manifest) ? `<div class="source-line">${[root, manifest].filter(Boolean).join(' · ')}</div>` : ''}
      ${items.length ? `<div class="grid">${items.map(e => renderEntity(e, kind)).join('')}</div>` : `<div class="empty">(manifest or folder exists, but no entity folders were found)</div>`}
    </div>`;
  }).join('');
};
$('x-cast').innerHTML = renderEntityGroups(D.cast_groups, D.cast, '(no cast)', 'cast');
$('x-sets').innerHTML = renderEntityGroups(D.set_groups, D.sets, '(no movie-set/)', 'set');
$('x-props').innerHTML = renderEntityGroups(D.prop_groups, D.props, '(no props/)', 'prop');

// ---- bgm
$('x-bgm').innerHTML = (D.bgm||[]).length ? D.bgm.map(b => `<div class="card"><b>${esc(b.name)}</b><br><audio controls src="${b.url}" style="width:100%"></audio></div>`).join('') : missing('(no bgm/)');

// ---- shots
const storyboardSelectionKey = `spark-video:${D.project}:${D.episode}:storyboard-selections`;
let pendingStoryboardSelections = {};
try {
  const stored = JSON.parse(localStorage.getItem(storyboardSelectionKey) || '{}');
  const viewerUrl = new URL(location.href);
  const legacyAttached = JSON.parse(viewerUrl.searchParams.get('sv-selection') || '{}');
  const compactTakes = (viewerUrl.searchParams.get('sv') || '').split('.');
  const compactAttached = Object.fromEntries((D.shots || []).map((shot, index) => {
    const take = Number(compactTakes[index] || 0);
    const candidate = shot.storyboard_panel?.candidates?.[take - 1];
    return candidate ? [shot.id, candidate.id] : null;
  }).filter(Boolean));
  const attached = {...legacyAttached, ...compactAttached};
  pendingStoryboardSelections = {...stored, ...attached};
} catch (_) {}

const renderReview = (r, promptHtml, taskId) => {
  const bd = r?.breakdown || {};
  const verdict = r?.verdict || 'UNKNOWN';
  const score = typeof r?.score === 'number' ? r.score : null;
  const ringColor = verdict === 'ACCEPT' ? 'var(--good)' : (verdict === 'REJECT' ? 'var(--bad)' : 'var(--ice)');
  const ringScale = score != null && score <= 10 ? 10 : 100;
  const ring = score == null
    ? `<div class="score-ring no-score"><span>—</span></div>`
    : `<div class="score-ring" style="--pct:${Math.max(0, Math.min(100, score / ringScale * 100))};--ring-color:${ringColor}"><span>${esc(score)}</span></div>`;
  const bars = Object.keys(bd).length ? `<div class="breakdown">${Object.entries(bd).map(([k,v]) => {
    const val = Number(v);
    const pct = Number.isFinite(val) ? Math.max(0, Math.min(10, val)) * 10 : 0;
    return `<div class="axis"><span class="axis-name">${esc(k)}</span><span class="axis-track"><i style="width:${pct}%"></i></span><span class="axis-val">${esc(v)}</span></div>`;
  }).join('')}</div>` : '';
  return `<div class="review">
    <div class="score-row">${ring}
      <div class="score-side">
        <span class="verdict ${esc(verdict)}">${esc(verdict)}</span>
        ${taskId ? `<div class="score-task">task · ${esc(taskId)}</div>` : ''}
      </div>
    </div>
    ${bars}
    <div class="review-prompt"><div class="review-prompt-label">Render shot prompt</div><div class="render-prompt-scroll">${promptHtml}</div></div>
    ${r?.critique ? `<div class="critique-panel"><div class="critique-label">Critique</div><div class="critique">${esc(r.critique)}</div></div>` : ''}
  </div>`;
};

const effectiveShotReview = shot => {
  const versions = shot.versions || [];
  if (shot.winner_version != null) {
    return versions.find(version => version.version === shot.winner_version)?.review;
  }
  return versions
    .filter(version => version.review)
    .reduce((latest, version) => (
      !latest || Number(version.version) > Number(latest.version) ? version : latest
    ), null)?.review;
};

const shotsHtml = (D.shots||[]).map((shot, si) => {
  const versions = shot.versions || [];
  const storyboardPanel = shot.storyboard_panel || {};
  const storyboardCandidates = storyboardPanel.candidates || [];
  const chosenCandidate = storyboardPanel.confirmed
    ? storyboardPanel.selected_candidate
    : (pendingStoryboardSelections[shot.id] || storyboardPanel.selected_candidate);
  const panelPrompt = storyboardPanel.prompt || shot.animatic_prompt;
  const directorPromptBlock = shot.prompt
    ? `<div class="prompt-evidence-block"><div class="prompt-evidence-label">Visual prompt <span>· ${(shot.prompt||'').length} chars</span></div><div class="prompt-copy">${esc(shot.prompt)}</div></div>`
    : `<div class="prompt-missing">Director prompt has not been recorded for this shot.</div>`;
  const speechSourceLabel = shot.speech_source === 'model'
    ? 'model speech'
    : (shot.speech_source === 'post_tts' ? 'post voice' : 'silent');
  const referenceItems = [
    ...(shot.characters||[]).map(name => `character · ${name}`),
    ...(shot.set_id ? [`set · ${shot.set_id}`] : []),
    ...(shot.props||[]).map(name => `prop · ${name}`),
    ...(shot.use_prev_last_frame_as_first ? ['previous frame'] : []),
  ];
  const transition = shot.transition_from_previous;
  const transitionValues = transition ? [
    ...((transition.preserve||[]).map(item => `preserve · ${item}`)),
    ...((transition.allow_change||[]).map(item => `allow change · ${item}`)),
  ] : [];
  const promptContract = `<div class="prompt-contract">
    <div class="prompt-contract-head"><b>Prompt contract</b><span>${esc(speechSourceLabel)}</span></div>
    <div class="prompt-contract-flags">
      ${shot.cinematic_budget?.label ? `<span>${esc(shot.cinematic_budget.label)}</span>` : ''}
      <span>${shot.allow_generated_text ? 'generated text allowed' : 'generated text off'}</span>
      ${shot.visual_speech_mode && String(shot.visual_speech_mode).toLowerCase() !== 'none' ? `<span>${esc(shot.visual_speech_mode)}</span>` : ''}
    </div>
    <div class="prompt-contract-section"><b>Reference contract</b>${referenceItems.length ? `<div class="contract-values">${referenceItems.map(item => `<span>${esc(item)}</span>`).join('')}</div>` : '<p>—</p>'}</div>
    ${transition ? `<div class="prompt-contract-section"><b>Transition · ${esc(transition.type)}</b>${transitionValues.length ? `<div class="contract-values">${transitionValues.map(item => `<span>${esc(item)}</span>`).join('')}</div>` : '<p>Only the transition type is constrained.</p>'}</div>` : ''}
    ${shot.long_take_reason ? `<div class="prompt-contract-section"><b>Long-take reason</b><p>${esc(shot.long_take_reason)}</p></div>` : ''}
    ${shot.speech_text ? `<div class="speech-script"><b>${shot.speech_source === 'post_tts' ? 'Post voice script' : 'Speech script'}</b>${shot.speech_source === 'post_tts' ? '<i>Not sent to the video model</i>' : ''}<p>${esc(shot.speech_text)}</p></div>` : ''}
    ${(shot.beats||[]).length ? `<div class="temporal-beats"><b>Temporal beats</b>${shot.beats.map(beat => `<p><span>${esc(beat.start_s)}-${esc(beat.end_s)}s</span>${esc(beat.action)}</p>`).join('')}</div>` : ''}
    ${shot.camera_path ? `<div class="prompt-contract-section"><b>Camera path</b><p>${esc(shot.camera_path)}</p></div>` : ''}
    ${shot.end_composition ? `<div class="prompt-contract-section"><b>Ending composition</b><p>${esc(shot.end_composition)}</p></div>` : ''}
  </div>`;
  const staticPromptBlock = panelPrompt
    ? `<div class="prompt-evidence-block"><div class="prompt-evidence-label">Static panel prompt <span>· ${panelPrompt.length} chars</span></div><div class="prompt-copy">${esc(panelPrompt)}</div></div>`
    : `<div class="prompt-missing">Static panel prompt has not been recorded for this shot.</div>`;
  const shotPromptBlock = `<div class="storyboard-ref-head"><b>Prompt evidence</b><span>contract · visual · static</span></div><div class="prompt-stack">${promptContract}${directorPromptBlock}${staticPromptBlock}</div>`;
  const panelStatus = storyboardPanel.confirmed
    ? 'confirmed'
    : (chosenCandidate ? 'selected · awaiting gate' : (storyboardCandidates.length ? 'choose one take' : 'not generated'));
  const chosenCandidateIndex = storyboardCandidates.findIndex(candidate => candidate.id === chosenCandidate);
  const chosenCandidateData = chosenCandidateIndex >= 0 ? storyboardCandidates[chosenCandidateIndex] : null;
  const finalSelection = chosenCandidateData
    ? `<div class="storyboard-final" data-candidate="${esc(chosenCandidateData.id)}">
        <div class="storyboard-final-head"><span>Final selection</span><b>take ${String(chosenCandidateIndex + 1).padStart(2,'0')}</b></div>
        <div class="storyboard-final-frame">${chosenCandidateData.image_url
          ? `<img src="${chosenCandidateData.image_url}" alt="${esc(shot.id)} final storyboard selection" loading="lazy" decoding="async">`
          : `<div class="empty">Selected image unavailable</div>`}</div>
      </div>`
    : `<div class="storyboard-final" data-candidate="">
        <div class="storyboard-final-head"><span>Final selection</span><b>pending</b></div>
        <div class="storyboard-final-frame"><div class="empty">Choose a candidate from the list.</div></div>
      </div>`;
  const candidateGrid = storyboardCandidates.length
    ? `<div class="storyboard-selection-layout">
        ${finalSelection}
        <aside class="storyboard-candidate-rail">
          <div class="storyboard-candidate-rail-head"><b>Candidates</b><span>${storyboardCandidates.length} takes</span></div>
          <div class="storyboard-candidate-list">${storyboardCandidates.map((candidate, index) => `
            <div class="storyboard-candidate ${candidate.id===chosenCandidate?'selected':''}" data-candidate="${esc(candidate.id)}">
              ${candidate.image_url
                ? `<img src="${candidate.image_url}" alt="${esc(shot.id)} storyboard take ${index + 1}" loading="lazy" decoding="async">`
                : `<div class="empty">Candidate image unavailable</div>`}
              <span class="candidate-take">take ${String(index + 1).padStart(2,'0')}</span>
              <button class="candidate-select" type="button" data-shot="${esc(shot.id)}" data-candidate="${esc(candidate.id)}" ${storyboardPanel.confirmed?'disabled':''}>${storyboardPanel.confirmed ? (candidate.id===chosenCandidate?'Locked selection':'Gate locked') : (candidate.id===chosenCandidate?'Selected':'Select take')}</button>
            </div>`).join('')}</div>
        </aside>
      </div>`
    : `<div class="empty">Static storyboard candidates have not been generated yet.</div>`;
  const storyboardEvidence = `<div class="shot-evidence">
    <div class="storyboard-ref">
      <div class="storyboard-ref-head"><b>Storyboard reference</b><span class="panel-state ${storyboardPanel.confirmed?'confirmed':''}">${panelStatus}</span></div>
      ${candidateGrid}
      <div class="storyboard-decision">
        <span>${chosenCandidate ? `choice · ${esc(chosenCandidate)}` : 'Select one take to prepare the handoff.'}</span>
        <span class="selection-handoff">${storyboardPanel.confirmed ? 'Locked · reopen Gate 2 to change' : (chosenCandidate ? 'Ready · confirm at Gate 2' : 'Awaiting selection')}</span>
      </div>
    </div>
    <div class="shot-intent">${shotPromptBlock}</div>
  </div>`;
  const winner = shot.winner_version;
  const executedVersion = versions.find(version => version.version === winner) || versions[versions.length - 1];
  const provider = String(executedVersion?.provider || shot.provider || '').toLowerCase().replace('_', '-');
  const command = String(executedVersion?.command || '').toLowerCase();
  const wanVersion = String(executedVersion?.model || '').trim();
  const isWan = provider === 'wan' || provider === 'wan-cli';
  const wanFeature = command === 'omni2video'
    ? 'omni'
    : (command === 'reference2video'
      ? 'reference'
      : (command === 'videoedit'
        ? 'edit'
        : (command === 'text2video'
          ? 't2v'
          : (['frame2video', 'image2video'].includes(command) ? 'i2v' : null))));
  const featureLabel = executedVersion
    ? (isWan
      ? `${wanVersion || 'wan'}${wanFeature ? ` · ${wanFeature}` : ''}`
      : executedVersion.kind)
    : '';
  const featureMeta = featureLabel ? `<span class="pill">${esc(featureLabel)}</span>` : '';
  const renderComplete = versions.length > 0;
  const renderBadge = `<span class="render-state ${renderComplete ? 'complete' : 'missing'}">${renderComplete ? 'Rendered' : 'Not rendered'}</span>`;
  const shotHead = `<div class="shot-head">
      <span class="id">${esc(shot.id)}</span>
      <div class="shot-meta">
        ${shot.scene ? `<span class="pill">${esc(shot.scene)}</span>` : ''}
        ${featureMeta}
        ${shot.duration ? `<span class="pill">${shot.duration}s</span>` : ''}
        ${renderBadge}
      </div>
      ${shot.narrative_purpose ? `<div class="purpose">${esc(shot.narrative_purpose)}</div>` : ''}
    </div>`;
  if (!versions.length) {
    return `<div id="shot-${esc(shot.id)}" class="shot review-pending render-missing">
      ${shotHead}
      ${storyboardEvidence}
      <div class="empty" style="margin:18px">Video has not been generated for this shot yet.</div>
    </div>`;
  }
  const statusReview = effectiveShotReview(shot);
  const shotReviewClass = statusReview?.verdict === 'ACCEPT'
    ? 'review-accepted'
    : (statusReview?.verdict === 'REJECT' && winner != null
      ? 'review-overridden'
      : (statusReview?.verdict === 'REJECT' ? 'review-rejected' : 'review-pending'));
  const tabs = versions.map(v => `<div class="tab ${v.version===winner?'winner':''}" data-shot="${si}" data-ver="${v.version}">v${v.version}</div>`).join('');
  const renderPromptBlock = (v) => {
    // The storyboard's director prompt is shown once at the shot level
    // (shotPromptBlock below). Per-version, we surface:
    //   1. sent_prompt — pulled from logs/model_calls.jsonl --prompt arg.
    //      This is GROUND TRUTH — exactly what the video model received.
    //   2. prompt      — shots_state.json attempts[].prompt — what
    //      render_shot.py was invoked with. Should equal #1; if it does,
    //      we collapse the two into one block.
    const sent = v.sent_prompt;
    const rec = v.prompt;
    const same = (a, b) => (a||'').trim() === (b||'').trim();
    const out = [];
    if (sent) {
      out.push(`<div class="render-prompt-entry"><b>Actually sent · model_calls.jsonl</b><div class="prompt-copy">${esc(sent)}</div></div>`);
    }
    if (rec && !same(rec, sent)) {
      const warning = sent ? '<b>Recorded prompt · differs from sent</b>' : '';
      out.push(`<div class="render-prompt-entry">${warning}<div class="prompt-copy">${esc(rec)}</div></div>`);
    }
    return out.join('') || `<div class="empty">Render prompt has not been recorded.</div>`;
  };

  const panels = versions.map(v => `<div class="version-panel" data-shot="${si}" data-ver="${v.version}" style="display:none">
    <div class="version-body">
      <div class="version-media">
        <video controls playsinline preload="metadata" src="${v.clip_url}"${v.thumb_url ? ` poster="${v.thumb_url}"` : ''}></video>
      </div>
      <div>${renderReview(v.review, renderPromptBlock(v), v.task_id)}</div>
    </div>
  </div>`).join('');
  return `<div id="shot-${esc(shot.id)}" class="shot ${shotReviewClass} render-complete">
    ${shotHead}
    ${storyboardEvidence}
    <div class="tabs">${tabs}</div>
    ${panels}
  </div>`;
}).join('');
$('x-shots').innerHTML = shotsHtml || missing('(no shots)');

const shotEvidenceMedia = window.matchMedia('(min-width: 981px)');
let shotEvidenceFrame = 0;
const syncShotEvidenceHeights = () => {
  cancelAnimationFrame(shotEvidenceFrame);
  shotEvidenceFrame = requestAnimationFrame(() => {
    document.querySelectorAll('.shot-evidence').forEach(evidence => {
      const storyboard = evidence.querySelector('.storyboard-ref');
      const intent = evidence.querySelector('.shot-intent');
      if (!storyboard || !intent) return;
      intent.style.height = '';
      if (shotEvidenceMedia.matches) {
        intent.style.height = `${storyboard.getBoundingClientRect().height}px`;
      }
    });
  });
};
syncShotEvidenceHeights();
shotEvidenceMedia.addEventListener('change', syncShotEvidenceHeights);
window.addEventListener('resize', syncShotEvidenceHeights);
document.querySelectorAll('.storyboard-ref img').forEach(image => {
  if (!image.complete) image.addEventListener('load', syncShotEvidenceHeights, {once:true});
});
if ('ResizeObserver' in window) {
  const shotEvidenceObserver = new ResizeObserver(syncShotEvidenceHeights);
  document.querySelectorAll('.storyboard-ref').forEach(storyboard => shotEvidenceObserver.observe(storyboard));
}

const shotSubnav = $('shot-subnav');
const shotNavStatus = (shot) => {
  const statusReview = effectiveShotReview(shot);
  if (statusReview?.verdict === 'ACCEPT') return 'accepted';
  if (statusReview?.verdict === 'REJECT') return shot.winner_version != null ? 'overridden' : 'rejected';
  return 'pending';
};
const shotRenderStatus = shot => (shot.versions || []).length ? 'complete' : 'missing';
shotSubnav.innerHTML = (D.shots || []).map(shot =>
  `<a class="shot-subnav-link s-${shotNavStatus(shot)} r-${shotRenderStatus(shot)}" href="#shot-${esc(shot.id)}"><span>${esc(shot.id)}</span><i>${shotRenderStatus(shot)==='complete'?'done':'todo'}</i></a>`
).join('');
const shotSubnavLinks = [...shotSubnav.querySelectorAll('.shot-subnav-link')];
shotSubnavLinks.forEach(link => link.addEventListener('click', event => {
  event.preventDefault();
  smoothScrollTo(document.querySelector(link.getAttribute('href')));
  if (mobileNav.matches) setNavOpen(false);
}));
const shotNodes = [...document.querySelectorAll('.shot[id]')];
const shotObserver = new IntersectionObserver(entries => {
  const visible = entries.filter(entry => entry.isIntersecting).sort((a,b) => b.intersectionRatio - a.intersectionRatio)[0];
  if (!visible) return;
  shotSubnavLinks.forEach(link => link.classList.toggle('active', link.getAttribute('href') === `#${visible.target.id}`));
}, {rootMargin:'-18% 0px -58% 0px', threshold:[0,.15,.4]});
shotNodes.forEach(shot => shotObserver.observe(shot));

const storyboardDecisionPayload = () => Object.fromEntries(
  (D.shots || []).map(shot => {
    const selected = shot.storyboard_panel?.confirmed
      ? shot.storyboard_panel?.selected_candidate
      : (pendingStoryboardSelections[shot.id] || shot.storyboard_panel?.selected_candidate);
    return selected ? [shot.id, selected] : null;
  }).filter(Boolean)
);
const storyboardSelectionHandoff = () => {
  const payload = storyboardDecisionPayload();
  const lines = (D.shots || []).map(shot =>
    payload[shot.id] ? `${shot.id}=${payload[shot.id]}` : null
  ).filter(Boolean);
  return `Storyboard selections for ${D.project}/${D.episode}:\n${lines.join('\n')}`;
};
const attachStoryboardDecision = () => {
  const url = new URL(location.href);
  const payload = storyboardDecisionPayload();
  const takes = (D.shots || []).map(shot => {
    const candidateId = payload[shot.id];
    const candidates = shot.storyboard_panel?.candidates || [];
    const index = candidates.findIndex(candidate => candidate.id === candidateId);
    return index < 0 ? '0' : String(index + 1);
  });
  while (takes.at(-1) === '0') takes.pop();
  if (takes.length) url.searchParams.set('sv', takes.join('.'));
  else url.searchParams.delete('sv');
  url.searchParams.delete('sv-selection');
  try {
    history.replaceState(null, '', url.href);
  } catch (_) {
    // Embedded file:// viewers may treat each navigation as a unique origin.
    // The selection remains durable in localStorage even when the URL cannot update.
  }
};
attachStoryboardDecision();
const selectStoryboardCandidate = (shotId, candidateId) => {
  const shotData = (D.shots || []).find(shot => shot.id === shotId);
  if (!shotData || shotData.storyboard_panel?.confirmed) return;
  pendingStoryboardSelections[shotId] = candidateId;
  localStorage.setItem(storyboardSelectionKey, JSON.stringify(pendingStoryboardSelections));
  const button = document.querySelector(`.candidate-select[data-shot="${CSS.escape(shotId)}"][data-candidate="${CSS.escape(candidateId)}"]`);
  const ref = button?.closest('.storyboard-ref');
  if (!ref) return;
  ref.querySelectorAll('.storyboard-candidate').forEach(card => {
    const selected = card.dataset.candidate === candidateId;
    card.classList.toggle('selected', selected);
    const control = card.querySelector('.candidate-select');
    if (control) control.textContent = selected ? 'Selected' : 'Select take';
  });
  const chosen = (shotData.storyboard_panel?.candidates || []).find(candidate => candidate.id === candidateId);
  const chosenIndex = (shotData.storyboard_panel?.candidates || []).findIndex(candidate => candidate.id === candidateId);
  const final = ref.querySelector('.storyboard-final');
  if (final && chosen) {
    final.dataset.candidate = candidateId;
    const label = final.querySelector('.storyboard-final-head b');
    if (label) label.textContent = `take ${String(chosenIndex + 1).padStart(2,'0')}`;
    const frame = final.querySelector('.storyboard-final-frame');
    if (frame) frame.innerHTML = chosen.image_url
      ? `<img src="${esc(chosen.image_url)}" alt="${esc(shotId)} final storyboard selection" loading="lazy" decoding="async">`
      : `<div class="empty">Selected image unavailable</div>`;
  }
  const state = ref.querySelector('.panel-state');
  if (state) { state.textContent = 'selected · awaiting gate'; state.classList.remove('confirmed'); }
  const note = ref.querySelector('.storyboard-decision span');
  if (note) note.textContent = `choice · ${candidateId}`;
  const handoff = ref.querySelector('.selection-handoff');
  if (handoff) handoff.textContent = 'Ready · confirm at Gate 2';
  attachStoryboardDecision();
};
document.querySelectorAll('.candidate-select').forEach(button => button.addEventListener('click', async () => {
  selectStoryboardCandidate(button.dataset.shot, button.dataset.candidate);
  await copyStoryboardSelections(button.dataset.shot);
}));
const copyStoryboardSelections = async (shotId=null) => {
  const text = storyboardSelectionHandoff();
  try {
    await navigator.clipboard.writeText(text);
  } catch (_) {
    const area = document.createElement('textarea');
    area.value = text;
    area.style.position = 'fixed';
    area.style.opacity = '0';
    document.body.appendChild(area);
    area.select();
    document.execCommand('copy');
    area.remove();
  }
  if (shotId) {
    const button = document.querySelector(`.candidate-select[data-shot="${CSS.escape(shotId)}"]`);
    const handoff = button?.closest('.storyboard-ref')?.querySelector('.selection-handoff');
    if (handoff) handoff.textContent = viewerLanguage === 'zh' ? '已复制 · 粘贴给 Agent' : 'Copied · paste to Agent';
  }
};

// activate winner (or first) version on each shot
document.querySelectorAll('.shot').forEach((node, si) => {
  const tabs = node.querySelectorAll('.tab');
  if (!tabs.length) return;
  let initial = Array.from(tabs).find(t=>t.classList.contains('winner')) || tabs[0];
  const activate = (ver) => {
    node.querySelectorAll('.tab').forEach(t => t.classList.toggle('active', t.dataset.ver===String(ver)));
    node.querySelectorAll('.version-panel').forEach(p => p.style.display = (p.dataset.ver===String(ver)) ? '' : 'none');
  };
  activate(initial.dataset.ver);
  tabs.forEach(t => t.addEventListener('click', () => activate(t.dataset.ver)));
});

// ---- calls
const calls = D.calls || {};
const byShot = calls.by_shot || {};
const shotKeys = Object.keys(byShot).sort();
if (!shotKeys.length) {
  $('x-calls').innerHTML = missing('(no logs/model_calls.jsonl)');
} else {
  const rows = shotKeys.map(sid => {
    const s = byShot[sid];
    const kinds = Object.entries(s.kinds).map(([k,v])=>`${esc(k)}:${v}`).join(' · ');
    return `<tr class="row" data-shot="${esc(sid)}"><td>${esc(sid)}</td><td>${s.count}</td><td>${(s.duration_ms/1000).toFixed(2)}s</td><td>${kinds}</td></tr>`;
  }).join('');
  $('x-calls').innerHTML = `<div class="card" style="margin-bottom:10px;color:var(--mute);font-size:13px">total ${calls.total} calls — click a row for raw JSON</div>
    <div class="calls-wrap"><table><thead><tr><th>shot</th><th>count</th><th>duration</th><th>kinds</th></tr></thead><tbody>${rows}</tbody></table></div>`;
  document.querySelectorAll('.calls tr.row').forEach(r => r.addEventListener('click', () => {
    const sid = r.dataset.shot;
    const recs = (calls.raw||[]).filter(x => (x.shot_id||'_project_')===sid);
    $('modal-body').textContent = JSON.stringify(recs, null, 2);
    $('modal').classList.add('open');
  }));
}

$('modal').addEventListener('click', (e) => { if (e.target.id==='modal') $('modal').classList.remove('open'); });

// ---- final
if (D.final) {
  $('x-final').innerHTML = `<div class="card">
    <video controls playsinline preload="metadata" src="${D.final.url}"></video>
    <div class="final-file"><span>${esc(D.final.name)}</span><span>${(D.final.size_bytes/1024/1024).toFixed(1)} MB · FINAL MASTER</span></div>
  </div>`;
} else { $('x-final').innerHTML = missing('Final master pending. Upstream evidence remains available for review.'); }

// ---- custom video controls
const fmtTime = s => {
  if (!isFinite(s) || s < 0) s = 0;
  s = Math.round(s);
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;
};
const VP_ICON = {
  play: '<svg viewBox="0 0 16 16"><path d="M4 2.3v11.4l9.4-5.7z"/></svg>',
  pause: '<svg viewBox="0 0 16 16"><path d="M3.4 2.4h3v11.2h-3zM9.6 2.4h3v11.2h-3z"/></svg>',
  vol: '<svg viewBox="0 0 16 16"><path d="M1.8 5.6v4.8h2.9l4 3.4V2.2l-4 3.4z"/><path d="M11 5.4a3.7 3.7 0 010 5.2M12.8 3.6a6.2 6.2 0 010 8.8" fill="none" stroke="currentColor" stroke-width="1.3" stroke-linecap="round"/></svg>',
  mute: '<svg viewBox="0 0 16 16"><path d="M1.8 5.6v4.8h2.9l4 3.4V2.2l-4 3.4z"/><path d="M10.8 6l4 4M14.8 6l-4 4" fill="none" stroke="currentColor" stroke-width="1.3" stroke-linecap="round"/></svg>',
  full: '<svg viewBox="0 0 16 16"><path d="M2.4 6V2.4H6M10 2.4h3.6V6M13.6 10v3.6H10M6 13.6H2.4V10" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>',
};
const upgradeVideo = video => {
  if (video.closest('.vplayer')) return;
  const wrap = document.createElement('div');
  wrap.className = 'vplayer';
  video.parentNode.insertBefore(wrap, video);
  wrap.appendChild(video);
  video.removeAttribute('controls');
  const syncAspect = () => {
    if (!video.videoWidth || !video.videoHeight) return;
    const media = wrap.closest('.version-media');
    const body = wrap.closest('.version-body');
    if (media) media.style.setProperty('--ar', `${video.videoWidth} / ${video.videoHeight}`);
    if (!media || !body) return;
    const ar = video.videoWidth / video.videoHeight;
    const fit = () => {
      const w = media.clientWidth;
      if (!w) return;
      const maxH = Math.min(window.innerHeight * 0.72, 680);
      const minH = 360;
      let h = w / ar;
      if (h > maxH) h = maxH;
      if (h < minH) h = minH;
      body.style.height = `${Math.round(h)}px`;
    };
    fit();
    if (!body._aspectRO) {
      body._aspectRO = new ResizeObserver(fit);
      body._aspectRO.observe(media);
    }
  };
  if (video.readyState >= 1) syncAspect();
  video.addEventListener('loadedmetadata', syncAspect);
  const bar = document.createElement('div');
  bar.className = 'vplayer-bar';
  bar.innerHTML = `
    <button class="vp-btn vp-play" type="button" aria-label="Play or pause">${VP_ICON.play}</button>
    <div class="vp-seek"><i class="vp-buffered"></i><i class="vp-played"></i><i class="vp-knob"></i></div>
    <span class="vp-time"><b>0:00</b> / 0:00</span>
    <button class="vp-btn vp-vol" type="button" aria-label="Mute or unmute">${VP_ICON.vol}</button>
    <button class="vp-btn vp-full" type="button" aria-label="Fullscreen">${VP_ICON.full}</button>`;
  wrap.appendChild(bar);
  const playBtn = bar.querySelector('.vp-play');
  const volBtn = bar.querySelector('.vp-vol');
  const fullBtn = bar.querySelector('.vp-full');
  const seek = bar.querySelector('.vp-seek');
  const played = bar.querySelector('.vp-played');
  const buffered = bar.querySelector('.vp-buffered');
  const knob = bar.querySelector('.vp-knob');
  const time = bar.querySelector('.vp-time');
  const syncPlay = () => {
    playBtn.innerHTML = video.paused ? VP_ICON.play : VP_ICON.pause;
    wrap.classList.toggle('playing', !video.paused);
  };
  const syncTime = () => {
    const d = video.duration || 0;
    const pct = d ? (video.currentTime / d) * 100 : 0;
    played.style.width = `${pct}%`;
    knob.style.left = `${pct}%`;
    time.innerHTML = `<b>${fmtTime(video.currentTime)}</b> / ${fmtTime(d)}`;
  };
  const syncBuffer = () => {
    try {
      const d = video.duration || 0;
      if (d && video.buffered.length) buffered.style.width = `${(video.buffered.end(video.buffered.length - 1) / d) * 100}%`;
    } catch (_) { /* no buffered range yet */ }
  };
  const syncVol = () => { volBtn.innerHTML = (video.muted || video.volume === 0) ? VP_ICON.mute : VP_ICON.vol; };
  const togglePlay = () => { if (video.paused) video.play(); else video.pause(); };
  playBtn.addEventListener('click', togglePlay);
  video.addEventListener('click', togglePlay);
  video.addEventListener('dblclick', () => fullBtn.click());
  volBtn.addEventListener('click', () => { video.muted = !video.muted; });
  fullBtn.addEventListener('click', () => {
    if (document.fullscreenElement) document.exitFullscreen();
    else wrap.requestFullscreen?.();
  });
  const seekTo = clientX => {
    const r = seek.getBoundingClientRect();
    const d = video.duration || 0;
    if (d) video.currentTime = Math.min(1, Math.max(0, (clientX - r.left) / r.width)) * d;
  };
  let scrubbing = false;
  seek.addEventListener('pointerdown', e => { scrubbing = true; seek.setPointerCapture(e.pointerId); seekTo(e.clientX); });
  seek.addEventListener('pointermove', e => { if (scrubbing) seekTo(e.clientX); });
  seek.addEventListener('pointerup', () => { scrubbing = false; });
  video.addEventListener('play', syncPlay);
  video.addEventListener('pause', syncPlay);
  video.addEventListener('ended', syncPlay);
  video.addEventListener('timeupdate', syncTime);
  video.addEventListener('durationchange', syncTime);
  video.addEventListener('loadedmetadata', () => { syncTime(); syncBuffer(); });
  video.addEventListener('progress', syncBuffer);
  video.addEventListener('volumechange', syncVol);
  let hideTimer = null;
  const poke = () => {
    wrap.classList.add('show-ui');
    clearTimeout(hideTimer);
    hideTimer = setTimeout(() => { if (!video.paused) wrap.classList.remove('show-ui'); }, 2200);
  };
  wrap.addEventListener('pointermove', poke);
  wrap.addEventListener('pointerleave', () => { clearTimeout(hideTimer); wrap.classList.remove('show-ui'); });
  video.addEventListener('pause', () => wrap.classList.add('show-ui'));
  syncPlay(); syncVol(); syncTime();
};
document.querySelectorAll('video').forEach(upgradeVideo);

const imageModal = $('image-modal');
const imageModalPreview = $('image-modal-preview');
const storyboardPreviewShots = (D.shots || []).filter(shot =>
  (shot.storyboard_panel?.candidates || []).some(candidate => candidate.image_url)
);
let imagePreviewState = null;
const selectedStoryboardCandidate = shot => shot.storyboard_panel?.confirmed
  ? shot.storyboard_panel?.selected_candidate
  : (pendingStoryboardSelections[shot.id] || shot.storyboard_panel?.selected_candidate);
const preloadStoryboardNeighbors = () => {
  if (!imagePreviewState || imagePreviewState.mode !== 'storyboard') return;
  const takesOf = s => (s.storyboard_panel?.candidates || []).filter(c => c.image_url);
  const preload = url => { if (url) { const img = new Image(); img.src = url; } };
  const shot = storyboardPreviewShots[imagePreviewState.shotIndex];
  const candidates = takesOf(shot);
  preload(candidates[(imagePreviewState.takeIndex + 1) % candidates.length]?.image_url);
  preload(candidates[(imagePreviewState.takeIndex - 1 + candidates.length) % candidates.length]?.image_url);
  const total = storyboardPreviewShots.length;
  [1, -1].forEach(direction => {
    const neighbor = storyboardPreviewShots[(imagePreviewState.shotIndex + direction + total) % total];
    const neighborTakes = takesOf(neighbor);
    const chosen = selectedStoryboardCandidate(neighbor);
    preload(neighborTakes[Math.max(0, neighborTakes.findIndex(c => c.id === chosen))]?.image_url);
  });
};
const renderStoryboardPreview = () => {
  if (!imagePreviewState || imagePreviewState.mode !== 'storyboard') return;
  const shot = storyboardPreviewShots[imagePreviewState.shotIndex];
  const candidates = (shot.storyboard_panel?.candidates || []).filter(candidate => candidate.image_url);
  imagePreviewState.takeIndex = (imagePreviewState.takeIndex + candidates.length) % candidates.length;
  const candidate = candidates[imagePreviewState.takeIndex];
  const selected = candidate.id === selectedStoryboardCandidate(shot);
  const confirmed = Boolean(shot.storyboard_panel?.confirmed);
  const stage = imageModalPreview.closest('.image-stage');
  const settle = () => stage.classList.remove('swapping');
  stage.classList.add('swapping');
  imageModalPreview.addEventListener('load', settle, {once:true});
  imageModalPreview.addEventListener('error', settle, {once:true});
  imageModalPreview.src = candidate.image_url;
  if (imageModalPreview.complete && imageModalPreview.naturalWidth) settle();
  preloadStoryboardNeighbors();
  imageModalPreview.alt = `${shot.id} storyboard take ${imagePreviewState.takeIndex + 1}`;
  $('image-modal-kicker').textContent = `Storyboard · ${imagePreviewState.shotIndex + 1} / ${storyboardPreviewShots.length}`;
  $('image-modal-shot').textContent = shot.id;
  $('image-modal-take').textContent = `Take ${String(imagePreviewState.takeIndex + 1).padStart(2, '0')} · ${imagePreviewState.takeIndex + 1} / ${candidates.length}`;
  $('image-modal-caption').textContent = candidate.task_id || candidate.source || candidate.id;
  $('image-modal-caption').hidden = false;
  const status = $('image-modal-status');
  status.className = `image-modal-status${selected ? ' selected' : ''}${confirmed ? ' locked' : ''}`;
  status.textContent = confirmed ? (selected ? 'Winner · gate locked' : 'Alternate · gate locked') : (selected ? 'Current selection' : 'Alternate candidate');
  const select = $('image-modal-select');
  select.hidden = false;
  select.disabled = confirmed;
  select.classList.toggle('selected', selected);
  select.textContent = confirmed ? (selected ? 'Locked selection' : 'Gate locked') : (selected ? 'Selected' : 'Select this take');
  $('image-modal-axis').hidden = false;
  $('image-axis-vertical-label').textContent = 'shot · up / down';
  $('image-axis-horizontal-label').textContent = 'candidate · left / right';
};
const moveStoryboardPreview = axis => {
  if (!imagePreviewState || imagePreviewState.mode !== 'storyboard') return;
  if (axis === 'shot-prev' || axis === 'shot-next') {
    const direction = axis === 'shot-prev' ? -1 : 1;
    imagePreviewState.shotIndex = (imagePreviewState.shotIndex + direction + storyboardPreviewShots.length) % storyboardPreviewShots.length;
    const shot = storyboardPreviewShots[imagePreviewState.shotIndex];
    const candidates = (shot.storyboard_panel?.candidates || []).filter(candidate => candidate.image_url);
    const chosen = selectedStoryboardCandidate(shot);
    imagePreviewState.takeIndex = Math.max(0, candidates.findIndex(candidate => candidate.id === chosen));
  } else {
    imagePreviewState.takeIndex += axis === 'take-prev' ? -1 : 1;
  }
  renderStoryboardPreview();
};
const assetPreviewEntities = (kind=null) => [...document.querySelectorAll('.entity[data-asset-key]')].filter(node =>
  !kind || node.dataset.assetKind === kind
).map(node => {
  let images = [];
  try { images = JSON.parse(node.dataset.assetImages || '[]'); } catch (_) {}
  return {
    node,
    key:node.dataset.assetKey,
    kind:node.dataset.assetKind,
    name:node.dataset.assetName,
    scope:node.dataset.assetScope,
    manifestImage:node.dataset.manifestImage,
    recommendedImage:node.dataset.recommendedImage,
    images:[...new Set(images)],
  };
}).filter(entity => entity.images.length);
const selectedAssetCandidate = entity => {
  const pending = pendingAssetImage(entity.key);
  if (entity.images.includes(pending)) return pending;
  if (entity.images.includes(entity.recommendedImage)) return entity.recommendedImage;
  return entity.images.includes(entity.manifestImage) ? entity.manifestImage : entity.images[0];
};
const preloadAssetNeighbors = () => {
  if (!imagePreviewState || imagePreviewState.mode !== 'entity') return;
  const entities = assetPreviewEntities(imagePreviewState.kind);
  const entity = entities[imagePreviewState.entityIndex];
  const preload = url => { if (url) { const image = new Image(); image.src = url; } };
  preload(entity.images[(imagePreviewState.candidateIndex + 1) % entity.images.length]);
  preload(entity.images[(imagePreviewState.candidateIndex - 1 + entity.images.length) % entity.images.length]);
  [1, -1].forEach(direction => {
    const neighbor = entities[(imagePreviewState.entityIndex + direction + entities.length) % entities.length];
    preload(selectedAssetCandidate(neighbor));
  });
};
const renderAssetPreview = () => {
  if (!imagePreviewState || imagePreviewState.mode !== 'entity') return;
  const entities = assetPreviewEntities(imagePreviewState.kind);
  imagePreviewState.entityIndex = (imagePreviewState.entityIndex + entities.length) % entities.length;
  const entity = entities[imagePreviewState.entityIndex];
  imagePreviewState.candidateIndex = (imagePreviewState.candidateIndex + entity.images.length) % entity.images.length;
  const image = entity.images[imagePreviewState.candidateIndex];
  const selected = image === selectedAssetCandidate(entity);
  const pending = pendingAssetImage(entity.key);
  const isPending = selected && pending === image && image !== entity.manifestImage;
  const isRecommendation = selected && !pending && image === entity.recommendedImage;
  const stage = imageModalPreview.closest('.image-stage');
  const settle = () => stage.classList.remove('swapping');
  stage.classList.add('swapping');
  imageModalPreview.addEventListener('load', settle, {once:true});
  imageModalPreview.addEventListener('error', settle, {once:true});
  imageModalPreview.src = image;
  if (imageModalPreview.complete && imageModalPreview.naturalWidth) settle();
  preloadAssetNeighbors();
  imageModalPreview.alt = `${entity.name} candidate ${imagePreviewState.candidateIndex + 1}`;
  $('image-modal-kicker').textContent = `${entity.kind} · ${imagePreviewState.entityIndex + 1} / ${entities.length}`;
  $('image-modal-shot').textContent = entity.name;
  $('image-modal-take').textContent = `Candidate ${String(imagePreviewState.candidateIndex + 1).padStart(2, '0')} · ${imagePreviewState.candidateIndex + 1} / ${entity.images.length}`;
  $('image-modal-caption').textContent = decodeURIComponent(image);
  $('image-modal-caption').hidden = false;
  const status = $('image-modal-status');
  status.className = `image-modal-status${selected ? ' selected' : ''}`;
  status.textContent = isPending ? 'Pending · paste to Agent' : (isRecommendation ? 'Agent default' : (selected ? 'Current primary' : 'Alternate candidate'));
  const select = $('image-modal-select');
  select.hidden = false;
  select.disabled = false;
  select.classList.toggle('selected', selected);
  select.textContent = selected && pending === image
    ? 'Copy selection for Agent'
    : (isRecommendation ? 'Using default' : 'Select + copy for Agent');
  $('image-modal-axis').hidden = false;
  $('image-axis-vertical-label').textContent = 'asset · up / down';
  $('image-axis-horizontal-label').textContent = 'candidate · left / right';
};
const moveAssetPreview = axis => {
  if (!imagePreviewState || imagePreviewState.mode !== 'entity') return;
  const entities = assetPreviewEntities(imagePreviewState.kind);
  if (axis === 'shot-prev' || axis === 'shot-next') {
    imagePreviewState.entityIndex += axis === 'shot-prev' ? -1 : 1;
    imagePreviewState.entityIndex = (imagePreviewState.entityIndex + entities.length) % entities.length;
    const entity = entities[imagePreviewState.entityIndex];
    imagePreviewState.candidateIndex = Math.max(0, entity.images.indexOf(selectedAssetCandidate(entity)));
  } else {
    imagePreviewState.candidateIndex += axis === 'take-prev' ? -1 : 1;
  }
  renderAssetPreview();
};
const copyText = async text => {
  try { await navigator.clipboard.writeText(text); }
  catch (_) {
    const area = document.createElement('textarea');
    area.value = text;
    area.style.position = 'fixed';
    area.style.opacity = '0';
    document.body.appendChild(area);
    area.select();
    document.execCommand('copy');
    area.remove();
  }
};
const assetSelectionHandoff = () => {
  const selections = Object.values(pendingAssetSelections).filter(value => value && typeof value === 'object');
  return `Apply these asset selections for ${D.project}/${D.episode}, rebuild manifests and Viewer:\n${JSON.stringify(selections, null, 2)}`;
};
const selectAssetCandidate = async () => {
  if (!imagePreviewState || imagePreviewState.mode !== 'entity') return;
  const entities = assetPreviewEntities(imagePreviewState.kind);
  const entity = entities[imagePreviewState.entityIndex];
  const image = entity.images[imagePreviewState.candidateIndex];
  pendingAssetSelections[entity.key] = {
    kind:entity.kind,
    scope:entity.scope,
    name:entity.name,
    image,
  };
  localStorage.setItem(assetSelectionKey, JSON.stringify(pendingAssetSelections));
  const main = entity.node.querySelector('.entity-main-image');
  const backdrop = entity.node.querySelector('.entity-backdrop');
  const oldMain = main?.dataset.assetUrl;
  const candidate = [...entity.node.querySelectorAll('.entity-extra-images img')]
    .find(item => item.dataset.assetUrl === image);
  if (candidate && oldMain && oldMain !== image) {
    candidate.src = oldMain;
    candidate.dataset.assetUrl = oldMain;
  }
  if (main) { main.src = image; main.dataset.assetUrl = image; }
  if (backdrop) backdrop.src = image;
  const badge = entity.node.querySelector('.entity-primary-badge');
  if (badge) {
    badge.textContent = image === entity.manifestImage ? 'Primary' : 'Pending';
    badge.classList.toggle('pending', image !== entity.manifestImage);
    badge.classList.remove('recommended');
  }
  await copyText(assetSelectionHandoff());
  renderAssetPreview();
  $('image-modal-caption').textContent = 'Selection copied · paste it into the Agent chat to apply it to the project.';
};
const moveImagePreview = axis => {
  if (imagePreviewState?.mode === 'storyboard') moveStoryboardPreview(axis);
  else if (imagePreviewState?.mode === 'entity') moveAssetPreview(axis);
};
const closeImagePreview = () => {
  imageModal.classList.remove('open');
  imageModalPreview.removeAttribute('src');
  imagePreviewState = null;
  document.body.classList.remove('image-preview-open');
};
document.addEventListener('click', e => {
  const previewImage = e.target.closest?.('.storyboard-candidate img,.storyboard-final img,.entity-main-image,.entity-extra-images img,.thumb');
  if (!previewImage) return;
  const candidateCard = previewImage.closest('.storyboard-candidate,.storyboard-final');
  if (candidateCard) {
    const shotNode = candidateCard.closest('.shot');
    const shotIndex = Array.from(document.querySelectorAll('.shot')).indexOf(shotNode);
    const shot = (D.shots || [])[shotIndex];
    const previewShotIndex = storyboardPreviewShots.findIndex(item => item.id === shot?.id);
    const candidates = (shot?.storyboard_panel?.candidates || []).filter(candidate => candidate.image_url);
    imagePreviewState = { mode:'storyboard', shotIndex:previewShotIndex, takeIndex:Math.max(0, candidates.findIndex(candidate => candidate.id === candidateCard.dataset.candidate)) };
    renderStoryboardPreview();
  } else if (previewImage.closest('.entity[data-asset-key]')) {
    const entityNode = previewImage.closest('.entity[data-asset-key]');
    const kind = entityNode.dataset.assetKind;
    const entities = assetPreviewEntities(kind);
    const entityIndex = entities.findIndex(entity => entity.node === entityNode);
    const candidateIndex = Math.max(0, entities[entityIndex].images.indexOf(previewImage.dataset.assetUrl));
    imagePreviewState = {mode:'entity', kind, entityIndex, candidateIndex};
    renderAssetPreview();
  } else {
    imagePreviewState = { mode:'single' };
    imageModalPreview.src = previewImage.currentSrc || previewImage.src;
    imageModalPreview.alt = previewImage.alt || 'Image preview';
    $('image-modal-kicker').textContent = 'Reference image';
    $('image-modal-shot').textContent = previewImage.alt || 'Image evidence';
    $('image-modal-take').textContent = '';
    $('image-modal-status').textContent = 'Read-only asset';
    $('image-modal-status').className = 'image-modal-status';
    $('image-modal-caption').textContent = previewImage.alt || '';
    $('image-modal-caption').hidden = true;
    $('image-modal-axis').hidden = true;
    $('image-modal-select').hidden = true;
  }
  imageModal.classList.add('open');
  document.body.classList.add('image-preview-open');
});
$('image-modal-axis').addEventListener('click', e => {
  const control = e.target.closest('[data-image-nav]');
  if (control) moveImagePreview(control.dataset.imageNav);
});
$('image-modal-select').addEventListener('click', async () => {
  if (imagePreviewState?.mode === 'storyboard') {
    const shot = storyboardPreviewShots[imagePreviewState.shotIndex];
    const candidates = (shot.storyboard_panel?.candidates || []).filter(candidate => candidate.image_url);
    selectStoryboardCandidate(shot.id, candidates[imagePreviewState.takeIndex].id);
    await copyStoryboardSelections(shot.id);
    renderStoryboardPreview();
  } else if (imagePreviewState?.mode === 'entity') {
    await selectAssetCandidate();
  }
});
$('image-modal-close').addEventListener('click', closeImagePreview);
imageModal.addEventListener('click', e => { if (e.target === imageModal) closeImagePreview(); });

document.addEventListener('keydown', e => {
  if (imageModal.classList.contains('open') && ['storyboard','entity'].includes(imagePreviewState?.mode)) {
    const axis = {ArrowUp:'shot-prev',ArrowDown:'shot-next',ArrowLeft:'take-prev',ArrowRight:'take-next'}[e.key];
    if (axis) { e.preventDefault(); moveImagePreview(axis); return; }
  }
  if (e.key === 'Escape') {
    $('modal').classList.remove('open');
    closeImagePreview();
    setNavOpen(false);
  }
});
