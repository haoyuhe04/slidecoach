const $=s=>document.querySelector(s);
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
let user=null,health={},course=null,session=null,currentPage=1,selected=new Set(),pending=false,helpContent='',sourceContent=null;
const requestKeys=new Map();
const keyFor=s=>{if(!requestKeys.has(s))requestKeys.set(s,crypto.randomUUID());return requestKeys.get(s)};
const clearKeys=()=>requestKeys.clear();
function toast(text){$('#toast').textContent=text;$('#toast').hidden=false;setTimeout(()=>$('#toast').hidden=true,4500)}
async function api(path,options={}){const r=await fetch('/api'+path,{credentials:'same-origin',...options,headers:options.body instanceof FormData?{}:{'Content-Type':'application/json',...options.headers}});let data;try{data=await r.json()}catch{throw new Error('服务没有返回有效结果，请稍后重试。')}if(!r.ok){if(r.status===401&&user){user=null;authView()}throw new Error(typeof data.detail==='string'?data.detail:r.status===422?'填写内容不符合要求，请检查输入。':'操作失败，请重试。')}return data}
const post=(path,data={})=>api(path,{method:'POST',body:JSON.stringify(data)});
function showError(e){toast(e.message||String(e));const el=$('#pageError');if(el)el.textContent=e.message||String(e)}
async function run(title,fn){if(pending)return;pending=true;$('#busyTitle').textContent=title;$('#busy').hidden=false;document.querySelectorAll('button[data-mutate]').forEach(b=>b.disabled=true);try{await fn()}catch(e){showError(e)}finally{pending=false;$('#busy').hidden=true;document.querySelectorAll('button[data-mutate]').forEach(b=>b.disabled=false);if($('#hint')&&session?.turns.at(-1)?.hints>=2)$('#hint').disabled=true}}
function modal(html){window.SlideCoachVoice?.stop();$('#dialogContent').innerHTML=html;window.SlideCoachVoice?.mount($('#dialogContent'),toast);$('#dialog').showModal()}
const iconPaths={
  arrow:'<path d="M4 12h15m-6-6 6 6-6 6"/>',
  upload:'<path d="M12 16V4m-5 5 5-5 5 5M4 16v4h16v-4"/>',
  file:'<path d="M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9zM14 3v6h6M8 13h8M8 17h5"/>',
  book:'<path d="M12 5v15M3 4c4-1 6 0 9 2 3-2 5-3 9-2v14c-4-1-6 0-9 2-3-2-5-3-9-2z"/>',
  chat:'<path d="M21 11a8 8 0 0 1-8 8H8l-5 3V8a6 6 0 0 1 6-6h4a8 8 0 0 1 8 9Z"/><path d="M7 8h10M7 12h7"/>',
  check:'<path d="m5 12 4 4L19 6"/>',
  list:'<path d="M9 6h12M9 12h12M9 18h12M3 6h.01M3 12h.01M3 18h.01"/>',
  trash:'<path d="M3 6h18M9 6V3h6v3M5 6l1 15h12l1-15M10 10v7M14 10v7"/>',
  clock:'<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
  info:'<circle cx="12" cy="12" r="9"/><path d="M12 11v6M12 7h.01"/>',
  spark:'<path d="m12 3 2.5 6.5L21 12l-6.5 2.5L12 21l-2.5-6.5L3 12l6.5-2.5z"/>',
  pause:'<path d="M8 5v14M16 5v14"/>'
};
function icon(name){return `<svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${iconPaths[name]||iconPaths.book}</svg>`}
function setView(name,label){
  if(document.body.dataset.view!==name)window.scrollTo(0,0);
  window.SlideCoachVoice?.stop();
  document.body.dataset.view=name;
  $('#pageContext').textContent=label;
  $('#mobileNav').hidden=!user;$('#mobileLogout').hidden=!user;
  if(user)$('#avatar').textContent=Array.from(user.name)[0]||'我';
  document.querySelectorAll('[data-nav]').forEach(b=>{
    const active=b.dataset.nav===(['history','summary'].includes(name)?'history':'library');
    b.classList.toggle('active',active);
    active?b.setAttribute('aria-current','page'):b.removeAttribute('aria-current');
  });
  document.title=label+' · SlideCoach';
}
function modelBanner(){
  const b=$('#modelBanner');
  b.classList.toggle('needs-setup',!health.model_configured);
  b.textContent=health.model_configured?'依据课件 · 保留理解的证据':'模型待配置，请完成服务器配置';
}
function resetView(){helpContent='';sourceContent=null;clearKeys();$('#pageError')?.remove();}
async function init(){health=await api('/health');modelBanner();try{user=await api('/me')}catch{}if(user){$('#nav').hidden=false;$('#username').textContent=user.name;await library()}else authView();}
function authView(){
  user=null;$('#nav').hidden=true;setView('auth','欢迎回来');
  $('#main').innerHTML=`<div class="auth-layout"><section class="auth-intro"><span class="eyebrow">SLIDECOACH · 课程复习助手</span><h1>把看过的知识，<br>变成讲得清的理解<span class="accent-dot">。</span></h1><p>带上你的课件。我们一起整理重点，<br>练习表达，再把没讲清楚的地方补上。</p><div class="auth-features"><div>${icon('file')}<span>课件整理成考点</span></div><div>${icon('chat')}<span>用自己的话讲清楚</span></div><div>${icon('check')}<span>每次反馈，都有依据</span></div></div><div class="auth-signature">从一份课件，开始你的下一轮复习。</div></section><section class="auth card"><div class="auth-greeting">你好，学习者</div><h2>开始你的复习</h2><p class="muted">登录后，接着上次的理解继续。</p><form id="authForm"><label for="authName">用户名</label><input id="authName" required minlength="2" maxlength="32" autocomplete="username" placeholder="你的用户名"><label for="authPass">密码</label><input id="authPass" type="password" required minlength="8" maxlength="128" autocomplete="current-password" placeholder="至少 8 个字符"><p id="pageError" class="error" role="alert"></p><button class="primary full" data-mutate type="submit">登录，开始复习 ${icon('arrow')}</button><button class="auth-register full" data-mutate type="button" id="register">还没有账号？创建账号</button></form><p class="auth-note">课件和学习记录按账号独立保存。</p></section></div>`;
  const submit=route=>run(route==='/register'?'创建账号':'登录',async()=>{user=await post(route,{name:$('#authName').value.trim(),password:$('#authPass').value});$('#nav').hidden=false;$('#username').textContent=user.name;await library()});
  $('#authForm').onsubmit=e=>{e.preventDefault();submit('/login')};$('#register').onclick=()=>{if($('#authForm').reportValidity())submit('/register')};
}
async function library(){
  resetView();setView('library','我的课件');const items=await api('/courses');
  $('#main').innerHTML=`<section class="library-hero"><div class="hero-copy"><span class="eyebrow">属于你的学习空间</span><h1>课件里的知识，<br>值得再讲一遍<span class="accent-dot">。</span></h1><p>把零散页面整理成复习重点。<br>从一道问答，或一段自己的讲解开始。</p><a class="text-link" href="/api/demo">没有课件？下载示例 PPTX ${icon('arrow')}</a></div><section class="upload-panel"><div class="upload-heading"><span class="upload-symbol">${icon('upload')}</span><span class="upload-step">开始一轮新复习</span></div><h2>把课件交给我们</h2><p>自动归纳考点，留出时间理解。</p><label class="file-picker"><input type="file" id="uploadFile" accept=".pptx,.pdf" aria-label="选择 PPTX 或 PDF"><span class="file-picker-title">${icon('file')}选择 PPTX 或 PDF</span><span id="fileName">点击选择一份课程材料</span></label><button class="upload-submit" id="upload" data-mutate>上传并整理考点 ${icon('arrow')}</button><div class="upload-note">每份不超过 25 MB / 100 页</div><div id="pageError" class="error" role="alert"></div></section></section><div class="section-heading"><div><span class="eyebrow">继续学习</span><h2>我的课件 <span class="count">${items.length}</span></h2></div><span class="small muted">随时回来，按自己的节奏复习。</span></div><section class="library ${!items.length?'is-empty':''}">${items.map((c,i)=>`<article class="card course course-tone-${i%3}"><div class="row spread"><span class="document-symbol">${icon('file')}</span><span class="file-meta">${esc(c.kind.toUpperCase())} <span>·</span> ${c.pages} 页</span></div><h2 title="${esc(c.title)}">${esc(c.title)}</h2><div class="course-footer"><button class="course-open" data-course="${c.id}">打开课件 ${icon('arrow')}</button><button class="icon-button course-delete" data-delete-course="${c.id}" aria-label="删除课件 ${esc(c.title)}" title="删除课件">${icon('trash')}</button></div></article>`).join('')||`<div class="empty library-empty"><span class="empty-symbol">${icon('book')}</span><h3>第一份课件，就是起点</h3><p>上传课程材料，或先用示例体验一轮复习。</p></div>`}</section>`;
  $('#uploadFile').onchange=()=>{$('#fileName').textContent=$('#uploadFile').files[0]?.name||'点击选择一份课程材料'};
  $('#upload').onclick=()=>run('整理你的课件',async()=>{const f=$('#uploadFile').files[0];if(!f)throw new Error('请先选择一份课件。');const form=new FormData();form.append('file',f);const result=await api('/courses',{method:'POST',body:form});if(result.duplicate)toast('这份课件已在学习空间，为你直接打开。');await openCourse(result.id)});
  document.querySelectorAll('[data-course]').forEach(b=>b.onclick=()=>run('打开核心考点',()=>openCourse(b.dataset.course)));
  document.querySelectorAll('[data-delete-course]').forEach(b=>b.onclick=()=>{if(confirm('删除这份课件、原文件和关联复习记录？此操作不可撤销。'))run('删除课件',async()=>{await api('/courses/'+b.dataset.deleteCourse,{method:'DELETE'});await library()})});
}

let customTopics=false, outlineBusy=false, outlineError='', chatMessages=[];
let coursePrefs={mode:'quiz',level:'基础理解',minutes:10,persist:true};
function rememberCoursePrefs(){
  if($('#newMode'))coursePrefs={mode:$('#newMode').value,level:$('#newLevel').value,minutes:Number($('#newMinutes').value),persist:$('#persist').checked};
}
async function openCourse(id){
  course=await api('/courses/'+id);selected=new Set();customTopics=false;outlineError='';
  coursePrefs={mode:'quiz',level:'基础理解',minutes:10,persist:true};
  outlineBusy=!course.outline&&health.model_configured;renderCourse();
  if(outlineBusy)await buildOutline();
}
async function buildOutline(){
  outlineBusy=true;outlineError='';renderCourse();
  try{await post('/courses/'+course.id+'/outline');course=await api('/courses/'+course.id);}
  catch(e){outlineError=e.message;}
  finally{outlineBusy=false;renderCourse();}
}
function recommendedTopics(){
  const all=course.outline?.topics||[];
  const n=coursePrefs.minutes===0?all.length:coursePrefs.minutes<=10?2:3;
  return all.slice(0,n);
}
function renderCourse(){
  const all=course.outline?.topics||[],recommended=recommendedTopics(),excluded=course.outline?.excluded_pages||[];
  setView('course','核心考点');
  $('#main').innerHTML=`<div class="page-heading"><div><div class="course-context">${icon('file')}<span title="${esc(course.title)}">${esc(course.title)}</span></div><h1>先把这几个重点讲清楚</h1><p class="muted">按知识主题复习，课件依据随时可查。</p></div><div class="heading-actions"><button id="courseChat" class="quiet-button" title="和 AI 一起学习这份课件">${icon('chat')}AI 助教</button><button id="inspectMaterial" class="quiet-button">查看 / 修正识别内容</button></div></div>${excluded.length?`<details class="material-note"><summary>${icon('info')} ${excluded.length} 页文字不足，已暂时排除，不影响其余考点复习</summary><p>涉及第 ${excluded.join('、')} 页。可通过“查看 / 修正识别内容”补充文字。</p></details>`:''}<div class="course-layout ${!all.length?'preparing':''}"><section class="topics-section"><div class="section-heading compact"><h2>核心考点</h2>${all.length?`<span class="small muted">已整理为 ${all.length} 个主题</span>`:''}</div>${outlineBusy?`<div class="card empty"><span class="spinner inline-spinner"></span><h3>正在读懂这份课件</h3><p>把相关页面归在一起，整理成适合复习的主题。</p></div>`:!all.length?`<div class="card empty"><span class="empty-symbol">${icon('book')}</span><h3>${health.model_configured?'再整理一下复习重点':'先配置模型，再开始复习'}</h3><p>${esc(outlineError||'课件已保存，整理完成后即可开始。')}</p><button class="primary" id="retryOutline" data-mutate>${health.model_configured?'整理核心考点':'重试模型连接'} ${icon('arrow')}</button></div>`:`<div class="topic-grid">${all.map((t,i)=>`<article class="topic-card ${!customTopics&&recommended.some(x=>x.id===t.id)?'recommended':''}"><div class="row spread"><span class="topic-number">${String(i+1).padStart(2,'0')}</span>${!customTopics&&recommended.some(x=>x.id===t.id)?'<span class="pill recommended-pill">本轮推荐</span>':''}</div><h3>${customTopics?`<label class="topic-choice"><input type="checkbox" data-topic="${esc(t.id)}" aria-label="选择考点 ${esc(t.title)}" ${selected.has(t.id)?'checked':''}><span>${esc(t.title)}</span></label>`:esc(t.title)}</h3><p>${esc(t.objective)}</p><details class="small topic-evidence"><summary>查看课件依据</summary><p>相关页面：${t.pages.join('、')}</p><blockquote>第 ${t.evidence_page} 页：${esc(t.evidence)}</blockquote></details></article>`).join('')}</div><div class="row topic-selection"><button class="text-link" id="toggleTopics">${customTopics?'恢复推荐安排':'我想自己选考点'}</button>${customTopics?`<span class="small muted" id="topicCount">已选 ${selected.size} 个考点</span>`:''}</div><p class="footer-note">考点依据课件归纳，按基础到应用排列，不代表老师公布的考试范围。</p>`}</section>${all.length?`<aside class="review-plan card"><span class="eyebrow">按你的节奏</span><h2>安排这一轮</h2><p class="small muted">选好方式，其余交给我们。</p><label class="field">复习方式<select id="newMode"><option value="quiz" ${coursePrefs.mode==='quiz'?'selected':''}>问答练习</option><option value="teach" ${coursePrefs.mode==='teach'?'selected':''}>讲给同学听</option></select></label><label class="field">可用时间<select id="newMinutes"><option value="10" ${coursePrefs.minutes===10?'selected':''}>10 分钟</option><option value="20" ${coursePrefs.minutes===20?'selected':''}>20 分钟</option><option value="0" ${coursePrefs.minutes===0?'selected':''}>不限时</option></select></label><div class="plan-recommendation" id="recommendation">${customTopics?'勾选左侧考点，按自己的节奏复习。':`<span class="label">本轮推荐 ${recommended.length} 个考点</span>${recommended.map(t=>`<div>${icon('check')}<span>${esc(t.title)}</span></div>`).join('')}`}</div><details class="plan-options"><summary>更多设置</summary><label class="field">练习重点<select id="newLevel"><option ${coursePrefs.level==='基础理解'?'selected':''}>基础理解</option><option ${coursePrefs.level==='辨析与应用'?'selected':''}>辨析与应用</option></select></label><label class="switch"><input type="checkbox" id="persist" ${coursePrefs.persist?'checked':''}>保存记录，供下次继续</label><p class="small muted">关闭后，本轮结束或退出登录时删除记录；未结束的临时记录到期后清理。课件单独保存。</p></details><button class="primary full" id="start" data-mutate>${customTopics?'开始所选考点':'开始推荐复习'} ${icon('arrow')}</button><p class="plan-footnote">先独立表达，需要时再寻求帮助。</p></aside>`:''}</div><div id="pageError" class="error" role="alert"></div>`;
  $('#courseChat').onclick=()=>openChat(course.id);
  $('#inspectMaterial').onclick=()=>inspectMaterial();
  if($('#retryOutline'))$('#retryOutline').onclick=()=>run('整理核心考点',async()=>{health=await api('/health');modelBanner();await buildOutline()});
  if(!all.length)return;
  $('#toggleTopics').onclick=()=>{rememberCoursePrefs();customTopics=!customTopics;if(customTopics&&!selected.size)selected=new Set(recommended.map(t=>t.id));renderCourse()};
  document.querySelectorAll('[data-topic]').forEach(el=>el.onchange=()=>{el.checked?selected.add(el.dataset.topic):selected.delete(el.dataset.topic);$('#topicCount').textContent='已选 '+selected.size+' 个考点'});
  $('#newMinutes').onchange=()=>{rememberCoursePrefs();renderCourse()};
  $('#start').onclick=()=>run('安排复习考点',async()=>{
    rememberCoursePrefs();if(customTopics&&!selected.size)throw new Error('请选择至少一个考点，或恢复推荐安排。');
    const choice={course_id:course.id,topics:customTopics?[...selected]:[],recommended:!customTopics,...coursePrefs};
    const r=await post('/sessions',{...choice,request_key:keyFor('new:'+JSON.stringify(choice))});
    clearKeys();await loadSession(r.id);if(health.model_configured)await generateNext('adaptive');
  });
}
async function openChat(id){
  resetView();course=await api('/courses/'+id);
  chatMessages=(await api('/courses/'+id+'/chat')).messages;
  renderChat();
}
function chatSuggestions(){
  const topics=course.outline?.topics||[];
  return ['总结这份课件的核心内容',...topics.slice(0,2).map(t=>`用一个例子解释「${t.title}」`)].slice(0,3);
}
function chatMessageView(m){
  if(m.role==='user')return `<div class="chat-msg user"><div class="bubble user"><div class="label"><span class="speaker-avatar">我</span>我的问题</div><div class="student-text">${esc(m.content)}</div></div></div>`;
  return `<div class="chat-msg assistant"><div class="bubble ai"><div class="feedback-heading"><span class="ai-avatar">${icon('spark')}</span><div><strong>AI 助教</strong><span>只依据课件回答</span></div>${m.insufficient?'<span class="pill warning">课件未涵盖</span>':''}</div><p>${esc(m.content).replace(/\n/g,'<br>')}</p>${m.citations?.length?`<div class="chat-citations"><div class="label">课件依据</div>${m.citations.map(c=>`<details class="chat-citation"><summary>第 ${c.page} 页</summary><blockquote>${esc(c.text)}</blockquote></details>`).join('')}</div>`:''}</div></div>`;
}
function renderChat(){
  setView('chat','AI 助教');
  $('#main').innerHTML=`<div class="page-heading chat-heading"><div><button class="text-link" id="backCourse">${icon('arrow')}返回核心考点</button><div class="course-context">${icon('file')}<span title="${esc(course.title)}">${esc(course.title)}</span></div><h1>AI 助教</h1><p class="muted">和 AI 一起学习这份课件：随时提问、查看依据。对话会保存，可随时清空。</p></div>${chatMessages.length?'<button class="quiet-button" id="clearChat" data-mutate>清空对话</button>':''}</div>
  <div class="chat-layout"><section class="card chat-shell"><div class="chat-thread" id="chatThread">${chatMessages.length?chatMessages.map(chatMessageView).join(''):`<div class="chat-empty"><span class="empty-symbol">${icon('chat')}</span><h2>和 AI 助教一起读懂课件</h2><p>${health.model_configured?'提问后，AI 会先查阅相关页面，再回答并给出页码依据。':'模型尚未配置，配置后即可开始。'}</p><div class="chat-suggestions">${chatSuggestions().map(s=>`<button class="chat-suggestion" data-suggestion="${esc(s)}">${esc(s)}</button>`).join('')}</div></div>`}</div>
  <form id="chatForm" class="chat-composer"><textarea id="chatInput" maxlength="2000" rows="3" placeholder="例如：为什么第二次握手要同时确认双方？" ${health.model_configured?'':'disabled'}></textarea><div class="chat-composer-foot"><span class="small muted">Enter 发送，Shift+Enter 换行 · 最多 2000 字</span><button class="primary" type="submit" data-mutate ${health.model_configured?'':'disabled'}>发送 ${icon('arrow')}</button></div></form>
  <div id="pageError" class="error" role="alert"></div></section></div>`;
  window.SlideCoachVoice?.mount($('#chatForm'),toast);
  $('#backCourse').onclick=()=>renderCourse();
  if($('#clearChat'))$('#clearChat').onclick=()=>{if(confirm('清空这份课件的全部对话？不可撤销。'))run('清空对话',async()=>{await api('/courses/'+course.id+'/chat',{method:'DELETE'});chatMessages=[];renderChat()})};
  document.querySelectorAll('[data-suggestion]').forEach(b=>b.onclick=()=>{$('#chatInput').value=b.dataset.suggestion;$('#chatInput').focus()});
  $('#chatForm').onsubmit=e=>{e.preventDefault();sendChat()};
  $('#chatInput').onkeydown=e=>{if(e.key==='Enter'&&!e.shiftKey&&!e.isComposing){e.preventDefault();sendChat()}};
  const thread=$('#chatThread');thread.scrollTop=thread.scrollHeight;
}
function sendChat(){
  const text=$('#chatInput').value.trim();if(!text)return;
  run('查阅课件并回答',async()=>{
    await post('/courses/'+course.id+'/chat',{message:text,request_key:keyFor('chat:'+course.id+':'+text)});
    clearKeys();chatMessages=(await api('/courses/'+course.id+'/chat')).messages;renderChat();
  });
}
function inspectMaterial(number=course.pages[0].number){
  const p=course.pages.find(x=>x.number===number);
  modal(`<h2>查看 / 修正识别内容</h2><p class="small muted">这里用于核对来源或修正识别问题，普通复习无需逐页操作。修改后会重新整理考点。</p><label>页面 <select id="repairPage">${course.pages.map(x=>`<option value="${x.number}" ${x.number===number?'selected':''}>第 ${x.number} 页 · ${esc(x.title)}</option>`).join('')}</select></label><a class="button" href="/api/courses/${course.id}/download">下载原文件</a>${course.kind==='pdf'?`<details class="gap"><summary>查看 PDF 原页</summary><img class="preview" src="/api/courses/${course.id}/preview/${number}" alt="第 ${number} 页原图"></details>`:''}<p class="small warning">${esc(p.warning)}</p><label for="repairTitle">页面标题</label><input id="repairTitle" value="${esc(p.title)}" maxlength="100"><label for="repairText">识别文字</label><textarea id="repairText" rows="9">${esc(p.text)}</textarea><button id="saveRepair" class="primary gap" data-mutate>保存修正并重新整理</button>`);
  $('#repairPage').onchange=()=>{const n=Number($('#repairPage').value);$('#dialog').close();inspectMaterial(n)};
  $('#saveRepair').onclick=()=>run('保存修正并整理考点',async()=>{
    await api(`/courses/${course.id}/pages/${number}`,{method:'PUT',body:JSON.stringify({title:$('#repairTitle').value,text:$('#repairText').value,confirmed:true})});
    $('#dialog').close();course=await api('/courses/'+course.id);selected=new Set();customTopics=false;await buildOutline();
  });
}

async function loadSession(id){session=await api('/sessions/'+id);course=await api('/courses/'+session.course_id);helpContent='';sourceContent=null;renderSession();}
const latestTurn=()=>session.turns.at(-1);
const verdicts={correct:'本次回答正确',partial:'还差一点',incorrect:'需要修正',uncertain:'先核实再判断'};
const coverageLabels={covered:'已讲清',partial:'可以展开',missing:'尚未讲到',uncertain:'需要澄清'};
function teachingFeedback(result){
  if(result?.kind!=='teaching_review')return '';
  return `<div class="coverage-grid">${result.coverage.map(row=>`<article class="coverage-item coverage-${esc(row.status)}"><div class="row spread"><strong>${row.status==='covered'?icon('check'):icon('list')}${esc(row.keyword)}</strong><span class="pill coverage-badge">${coverageLabels[row.status]}</span></div><p>${esc(row.note)}</p>${row.student_quote?`<details class="small"><summary>你讲到的内容</summary><blockquote>${esc(row.student_quote)}</blockquote></details>`:''}</article>`).join('')}</div>${result.corrections.length?`<div class="corrections"><h3>需要修正的理解</h3>${result.corrections.map(c=>`<div class="correction"><div class="small muted">你的说法：${esc(c.claim)}</div><p>${esc(c.correction)}</p><details class="small"><summary>对照课件依据</summary>${c.sources.map(s=>`<blockquote>第 ${s.page} 页：${esc(s.text)}</blockquote>`).join('')}</details></div>`).join('')}</div>`:''}${result.suggestion?`<p class="teaching-suggestion">${icon('arrow')}<span>${esc(result.suggestion)}</span></p>`:''}`;
}
function studentText(answer){
  if(answer.length<=180)return esc(answer);
  return `<details class="student-transcript"><summary><span class="student-excerpt">${esc(answer.slice(0,115).replace(/\s+/g,' '))}…</span><span class="transcript-toggle">展开完整讲解 · ${Array.from(answer).length} 字</span></summary><div class="student-full">${esc(answer)}</div></details>`;
}
function attemptView(a,isTeaching=false){
  const review=a.review;
  return `<article class="attempt"><div class="bubble user"><div class="label"><span class="speaker-avatar">我</span>${isTeaching?'我的讲解':'我的回答'}<span class="response-type">${a.independent?'首次独立表达':'已获得帮助或补充表达'}</span></div><div class="student-text">${studentText(a.answer)}</div></div><div class="bubble ai"><div class="feedback-heading"><span class="ai-avatar">${icon('spark')}</span><div><strong>${a.disputed?'待核实 · 已暂停本次判断':review?'原反馈（已采用下方复核意见）':isTeaching?'讲授覆盖反馈':esc(verdicts[a.feedback.verdict])}</strong><span>对照课件，看看哪里还能讲得更清楚</span></div></div><p>${esc(a.feedback.explanation)}</p>${teachingFeedback(a.feedback)}${a.feedback.next_question?`<p class="next-prompt">${esc(a.feedback.next_question)}</p>`:''}${review?`<div class="review-result"><div class="label">复核意见${a.disputed?' · 等待你核对':''}</div><p>${esc(review.explanation)}</p>${teachingFeedback(review)}${a.disputed&&review.verdict!=='uncertain'?`<button data-accept-review="${a.id}" data-mutate>采用复核结果</button>`:''}</div>`:''}<div class="feedback-actions"><button class="text-link" data-dispute="${a.id}">我不同意这次评价</button></div></div></article>`;
}
function attemptsView(attempts,isTeaching){
  return attempts.map((a,i)=>i===attempts.length-1?attemptView(a,isTeaching):`<details class="past-attempt" ${a.disputed?'open':''}><summary>第 ${i+1} 次${isTeaching?'讲解':'作答'}<span class="small muted">${a.disputed?'待核实':'查看原文与反馈'}</span></summary>${attemptView(a,isTeaching)}</details>`).join('');
}
function renderSession(){
  const t=latestTurn(),brief=t?.teaching_brief,isTeaching=!!brief,teachMode=(t?.mode||session.mode)==='teach';
  const p=course.pages.find(p=>p.number===(t?.page_number||session.page_numbers[0]));
  const elapsed=Math.floor((Date.now()/1000-session.created)/60),draftKey=t?`slidecoach-draft:${user.id}:${t.id}`:null;
  const sourceView=sourceContent?`<span class="pill">已查看来源 · 计入帮助记录</span><blockquote class="help">${esc(sourceContent.evidence)}</blockquote>${course.kind==='pdf'?(sourceContent.pages||[{number:p.number}]).map(sp=>`<details><summary>查看第 ${sp.number} 页原图</summary><img class="preview" src="/api/courses/${course.id}/preview/${sp.number}" alt="第 ${sp.number} 页"></details>`).join(''):''}<div class="source-text">${esc(sourceContent.text)}</div>`:`<div class="empty"><h3>${teachMode?'先把你理解的内容讲出来':'先用自己的话回答'}</h3><p>需要时可回看课件。我们会记录你使用了哪些帮助。</p>${t?'<button id="source" data-mutate>回看相关课件</button>':''}</div>`;
  const sourcePanel=`<section class="card source-panel"><h2>课件依据</h2>${sourceView}<p class="small muted gap">评价存在争议时可以申请复核；有争议的反馈暂不用于确认掌握。</p></section>`;
  const topicTitle=isTeaching?brief.title:t?.topic_title||session.topic_plan?.[0]?.title||p.title;
  setView('practice',teachMode?'讲授自测':'问答练习');
  const previousCoverage=t?.attempts.at(-1)?.feedback?.coverage||[];
  const outlinePanel=isTeaching?`<aside class="lecture-outline"><div class="outline-card"><div class="row spread"><span class="eyebrow">本次提纲</span>${icon('list')}</div><h2>顺着思路，讲给我听</h2><div class="teaching-keywords" aria-label="讲授关键词">${brief.outline.map((point,i)=>{const cov=previousCoverage.find(r=>r.keyword===point.keyword);return `<div class="keyword"><span class="keyword-number">${String(i+1).padStart(2,'0')}</span><div><strong>${esc(point.keyword)}</strong>${cov?`<span class="outline-status status-${esc(cov.status)}">${coverageLabels[cov.status]}</span>`:''}</div></div>`}).join('')}</div><div class="outline-note">${icon('info')}<p>提纲只提示方向。你可以举例、联系其他知识点，也可以自由组织顺序。</p></div></div></aside>`:'';
  $('#main').innerHTML=`
    <div class="page-heading session-heading"><div><div class="course-context">${icon('file')}<span title="${esc(course.title)}">${esc(course.title)}</span></div><span class="eyebrow">${teachMode?'本次讲授':'本次练习'} <span class="eyebrow-separator">/</span> 本轮 ${session.turns.length} 次练习${session.minutes?' · '+session.minutes+' 分钟':''}</span><h1>${esc(topicTitle)}</h1><p class="muted">${isTeaching?'用自己的话讲清楚，没讲到的地方，我们一起补上。':'先说出你的理解，再对照课件补全思路。'}</p></div><div class="session-actions"><button class="quiet-button" id="pause" data-mutate>${icon('pause')}暂停</button><button id="finish" data-mutate>结束并回顾 ${icon('arrow')}</button></div></div>
    ${session.minutes&&elapsed>=session.minutes?'<div class="alert">已到你设置的复习时间。可以先回顾本轮，也可以继续。</div>':''}
    <div class="${isTeaching?'teaching-workspace':'workspace'}">
      <section class="practice-panel">
        <div class="practice-tools"><span class="mode-label">${icon(teachMode?'chat':'book')}${teachMode?'讲授式自测':'问答练习'}</span><label class="mode-switch">下一轮模式 <select id="turnMode"><option value="quiz" ${session.mode==='quiz'?'selected':''}>问答</option><option value="teach" ${session.mode==='teach'?'selected':''}>讲授</option></select></label></div>
        ${t?`
          ${isTeaching?'':`<div class="question">${esc(t.question)}</div>${teachMode?'<p class="small muted">这是一条旧版讲授记录，点击“重新准备提纲”可开始开放讲授。</p>':''}`}
          <div class="${isTeaching?'teaching-history':'timeline'}">${attemptsView(t.attempts,isTeaching)}</div>
          ${helpContent?`<div class="help">${helpContent}</div>`:''}
          <form id="answerForm" class="answer-composer"><div class="composer-heading"><label for="answer">${isTeaching?(t.attempts.length?'继续补充你的讲解':'向 AI 同学讲解这个主题'):(teachMode?'讲给 AI 同学听':'写下答案与理由')}</label><span class="small muted">${isTeaching?'顺序由你决定':'先独立想一想'}</span></div><textarea id="answer" class="answer-input ${isTeaching?'teaching-input':''}" maxlength="6000" required placeholder="${isTeaching?(t.attempts.length?'补充还没展开的部分，或修正刚才的说法。不必重新讲全文。':'从你最熟悉的部分说起。试着像给同学讲课一样，结合例子讲清楚。'):'写下你的判断，也说说为什么。'}">${esc(sessionStorage.getItem(draftKey)||'')}</textarea><div class="composer-meta"><span id="draftState">草稿仅保存在当前浏览器，提交后写入记录。</span><span id="answerCount">${(sessionStorage.getItem(draftKey)||'').length} / 6000</span></div><div class="composer-submit"><button class="primary" type="submit" data-mutate>${isTeaching?(t.attempts.length?'提交补充讲解':'完成讲解，检查覆盖情况'):'提交并获得反馈'} ${icon('arrow')}</button></div><div class="learning-help"><span>需要一点帮助？</span><button type="button" id="hint" class="text-link" data-mutate>${isTeaching?'给我组织思路的提示':t.hints===0?'给我一点提示':'再具体一点'}</button><button type="button" id="reveal" class="text-link" data-mutate>${isTeaching?'查看课件参考要点':'查看完整解释'}</button></div></form><div class="practice-next"><button id="same" class="quiet-button" data-mutate>${teachMode?'重新准备提纲':'同一知识点换题'}</button><button id="next" class="quiet-button" data-mutate>${teachMode?'继续下一个主题':'安排下一题'} ${icon('arrow')}</button></div>`:
          `<div class="empty practice-empty"><span class="empty-symbol">${icon(teachMode?'chat':'book')}</span><h2>${teachMode?'这一轮，你来主讲':'准备好检验一下理解了吗？'}</h2><p>${esc(session.topic_plan?.map(t=>t.title).join('、')||'已选课件范围')}</p><button class="primary" id="firstQuestion" data-mutate>${teachMode?'生成讲授提纲':'生成第一题'} ${icon('arrow')}</button>${!health.model_configured?'<p class="warning">模型尚未配置，课件与范围已保存。</p>':''}</div>`}
        <div id="pageError" class="error" role="alert"></div>
      </section>
      ${isTeaching?outlinePanel:sourcePanel}
    </div>
    ${isTeaching?`<details class="teaching-source"><summary>${icon('book')}<span>需要时回看相关课件<small>查看课件后，会如实计入帮助记录</small></span></summary>${sourcePanel}</details>`:''}`;
  window.SlideCoachVoice?.mount($('#answerForm')||$('#main'),toast);
  $('#pause').onclick=()=>run('暂停复习',async()=>{await post('/sessions/'+session.id+'/pause');await historyView()});
  $('#finish').onclick=()=>run('整理本轮回顾',async()=>renderSummary(await post('/sessions/'+session.id+'/end')));
  if(!t){$('#firstQuestion').onclick=()=>run(session.mode==='teach'?'准备讲授提纲':'生成第一题',()=>generateNext('adaptive'));return;}
  $('#answer').oninput=()=>{sessionStorage.setItem(draftKey,$('#answer').value);$('#draftState').textContent='草稿已保存在当前浏览器';$('#answerCount').textContent=$('#answer').value.length+' / 6000'};
  $('#answerForm').onsubmit=e=>{e.preventDefault();run(isTeaching?'对照课件检查讲授覆盖':'核对回答与课件依据',async()=>{const text=$('#answer').value.trim();await post('/turns/'+t.id+'/answer',{answer:text,request_key:keyFor('answer:'+t.id+':'+text)});sessionStorage.removeItem(draftKey);clearKeys();session=await api('/sessions/'+session.id);renderSession()})};
  const help=kind=>run('打开学习帮助',async()=>{const r=await post('/turns/'+t.id+'/help',{kind});session=await api('/sessions/'+session.id);if(kind==='source')sourceContent=r;else helpContent=`<div class="label">${kind==='reveal'?(isTeaching?'课件参考要点 · 已记录为使用帮助':'完整解释 · 已记录为使用帮助'):'思路提示'}</div>${esc(r.text)}${r.evidence?'<div class="label gap">课件原文</div>'+esc(r.evidence):''}`;renderSession();if(kind==='source'&&$('.teaching-source'))$('.teaching-source').open=true});
  if($('#source'))$('#source').onclick=()=>help('source');$('#hint').onclick=()=>help(t.hints===0?'hint1':'hint2');if(t.hints>=2)$('#hint').disabled=true;$('#reveal').onclick=()=>help('reveal');
  $('#same').onclick=()=>run('准备下一轮练习',()=>generateNext('same'));
  $('#next').onclick=()=>run('安排下一轮',()=>generateNext($('#turnMode').value==='teach'?'next':'adaptive'));
  $('#turnMode').onchange=()=>{const teach=$('#turnMode').value==='teach';$('#same').textContent=teach?'重新准备提纲':'同一知识点换题';$('#next').textContent=teach?'继续下一个主题':'安排下一题'};
  document.querySelectorAll('[data-accept-review]').forEach(b=>b.onclick=()=>run('更新复习记录',async()=>{await post('/attempts/'+b.dataset.acceptReview+'/accept-review');session=await api('/sessions/'+session.id);renderSession();toast('已采用复核结果，原反馈与异议继续保留。')}));
  document.querySelectorAll('[data-dispute]').forEach(b=>b.onclick=()=>{modal(`<h2>核对这次反馈</h2><p>请指出具体分歧或课件依据。提交后先标为待核实。</p><label for="disputeReason">说明你的分歧</label><textarea id="disputeReason" maxlength="3000" placeholder="哪部分判断有误？你在讲解或课件哪里说明过？"></textarea><button id="submitDispute" class="primary gap" data-mutate>提交异议并复核</button>`);$('#submitDispute').onclick=()=>run('重新核对反馈',async()=>{const reason=$('#disputeReason').value.trim();if(reason.length<2)throw new Error('请写下具体分歧。');const r=await post('/attempts/'+b.dataset.dispute+'/dispute',{reason});$('#dialog').close();session=await api('/sessions/'+session.id);renderSession();toast(r.message)})});
}

async function generateNext(focus){const mode=$('#turnMode')?.value||session.mode;await post('/sessions/'+session.id+'/next',{request_key:keyFor('next:'+session.id+':'+session.turns.length+':'+mode+':'+focus),mode,focus});clearKeys();helpContent='';sourceContent=null;session=await api('/sessions/'+session.id);renderSession();}
function formattedDate(value){return new Intl.DateTimeFormat('zh-CN',{month:'long',day:'numeric',hour:'2-digit',minute:'2-digit'}).format(new Date(value*1000))}
async function historyView(){
  resetView();setView('history','复习记录');const items=await api('/sessions');
  $('#main').innerHTML=`<div class="page-heading"><div><span class="eyebrow">理解的轨迹</span><h1>每一轮复习，都有迹可循</h1><p class="muted">回看你讲过的内容，也看看还没讲清楚的地方。</p></div><span class="record-count">${items.length} 轮复习</span></div><div class="history-list">${items.map(s=>`<article class="history-card"><span class="history-symbol">${icon(s.mode==='teach'?'chat':'book')}</span><div class="history-copy"><div class="row"><span class="pill ${s.status==='ended'?'good':''}">${s.status==='ended'?'已结束':s.status==='paused'?'已暂停':'进行中'}${!s.persist?' · 临时记录':''}</span><span class="small muted">${s.mode==='teach'?'讲授自测':'问答练习'} · ${formattedDate(s.updated)}</span></div><h2 title="${esc(s.title)}">${esc(s.title)}</h2></div><div class="history-actions">${s.status!=='ended'?`<button data-resume="${s.id}" class="primary">继续复习 ${icon('arrow')}</button>`:''}<button data-summary="${s.id}">回顾</button><button class="icon-button" data-delete-session="${s.id}" aria-label="删除复习记录 ${esc(s.title)}" title="删除记录">${icon('trash')}</button></div></article>`).join('')||`<div class="card empty"><span class="empty-symbol">${icon('clock')}</span><h3>给理解留下一份记录</h3><p>从一份课件开始，完成第一轮复习后再来看看。</p></div>`}</div>`;
  document.querySelectorAll('[data-resume]').forEach(b=>b.onclick=()=>loadSession(b.dataset.resume).catch(showError));
  document.querySelectorAll('[data-summary]').forEach(b=>b.onclick=()=>api('/sessions/'+b.dataset.summary+'/summary').then(renderSummary).catch(showError));
  document.querySelectorAll('[data-delete-session]').forEach(b=>b.onclick=()=>{if(confirm('删除这轮复习的回答、反馈与争议记录？不可撤销。'))run('删除记录',async()=>{await api('/sessions/'+b.dataset.deleteSession,{method:'DELETE'});await historyView()})});
}
function renderSummary(result){
  setView('summary','本轮回顾');const s=result.session,attempts=s.turns.reduce((n,t)=>n+t.attempts.length,0);
  $('#main').innerHTML=`<div class="page-heading"><div><span class="eyebrow">本轮回顾</span><h1>这轮复习，留下了什么？</h1><p class="muted">${result.rows.length} 个考点 · ${attempts} 次表达记录。判断与证据一起看，再决定下一步。</p></div><button id="backHistory">返回复习记录 ${icon('arrow')}</button></div>${result.deleted?'<div class="alert">这是一轮临时复习，服务器记录已删除，当前回顾仅显示在本页。</div>':''}<section class="card table-wrap"><table class="stats"><thead><tr><th>复习考点</th><th>当前证据</th><th>作答次数</th><th>下一步</th></tr></thead><tbody>${result.rows.map(r=>`<tr><td><strong>${esc(r.title)}</strong><div class="small muted">依据第 ${(r.pages||[r.page]).join('、')} 页</div></td><td><span class="pill ${r.state.includes('独立')?'good':r.state==='待核实'?'warning':''}">${esc(r.state)}</span></td><td>${r.attempts}</td><td>${esc(r.next)}</td></tr>`).join('')}</tbody></table><p class="footer-note">独立回答与帮助后完成分别记录。有争议或依据不足的评价，先保留为待核实。</p></section><div class="section-heading summary-heading"><h2>回到当时的思路</h2><span class="small muted">原始作答与反馈</span></div><section>${s.turns.map((t,i)=>`<details class="summary-turn"><summary><span class="turn-number">${String(i+1).padStart(2,'0')}</span><span><strong>${esc(t.teaching_brief?.title||t.topic_title||t.question)}</strong><small>第 ${t.page_number} 页 · 提示 ${t.hints} 级${t.revealed?' · 已看参考':''}${t.source_opened?' · 已回看材料':''}</small></span></summary><div class="summary-turn-body">${t.attempts.map(a=>attemptView(a,!!t.teaching_brief)).join('')||'<p class="muted">尚未作答。</p>'}</div></details>`).join('')}</section>`;
  $('#backHistory').onclick=()=>historyView().catch(showError);
  document.querySelectorAll('[data-dispute],[data-accept-review]').forEach(b=>b.hidden=true);
}
window.SlideCoachNotify=toast;$('#dialog').addEventListener('close',()=>window.SlideCoachVoice?.stop());
document.querySelectorAll('[data-nav]').forEach(b=>b.onclick=()=>{if(pending)return;({library,history:historyView}[b.dataset.nav])().catch(showError)});$('#logout').onclick=()=>run('退出登录',async()=>{await post('/logout');Object.keys(sessionStorage).filter(k=>k.startsWith('slidecoach-draft:')).forEach(k=>sessionStorage.removeItem(k));user=null;authView()});$('#mobileLogout').onclick=$('#logout').onclick;$('#appearance').onclick=()=>{document.body.classList.toggle('dark');localStorage.setItem('slidecoach-theme',document.body.classList.contains('dark')?'dark':'light');$('#appearance').setAttribute('aria-label',document.body.classList.contains('dark')?'切换浅色外观':'切换深色外观')};if(localStorage.getItem('slidecoach-theme')==='dark')document.body.classList.add('dark');$('#appearance').setAttribute('aria-label',document.body.classList.contains('dark')?'切换浅色外观':'切换深色外观');init().catch(showError);
