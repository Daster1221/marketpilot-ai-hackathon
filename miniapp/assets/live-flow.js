"use strict";
const liveFlow={step:0,task:"",workflow:null,clarification:"",facts:[],ideas:[],idea:0,question:"",post:null,editorBody:null,editorDirty:false,instruction:"",busy:false,error:""};
const liveJobKey="salstek-active-job";
function safePostHTML(value){
 const doc=new DOMParser().parseFromString(String(value||""),'text/html');
 const allowed=new Set(['B','I','U','S','BLOCKQUOTE','TG-SPOILER','TG-EMOJI','BR']);
 function clean(node){if(node.nodeType===3)return document.createTextNode(node.textContent);if(node.nodeType!==1)return document.createTextNode('');const el=document.createElement(allowed.has(node.tagName)?node.tagName.toLowerCase():'span');if(node.tagName==='BLOCKQUOTE'&&node.hasAttribute('expandable'))el.setAttribute('expandable','');if(node.tagName==='TG-EMOJI'&&/^[0-9]{1,25}$/.test(node.getAttribute('emoji-id')||'')){el.setAttribute('emoji-id',node.getAttribute('emoji-id'));el.title='Premium-эмодзи отображается в Telegram';}for(const child of node.childNodes)el.append(clean(child));return el;}
 const out=document.createElement('div');for(const node of doc.body.childNodes)out.append(clean(node));return out.innerHTML;
}
function savedLiveJob(){try{return JSON.parse(localStorage.getItem(liveJobKey)||'null');}catch{localStorage.removeItem(liveJobKey);return null;}}
function requestFingerprint(payload){let hash=2166136261;for(const char of JSON.stringify(payload)){hash=Math.imul(hash^char.charCodeAt(0),16777619);}return String(hash>>>0);}
async function resumeLiveJob(saved){
 let id=saved.id;
 if(!id&&saved.key){const found=await api('./job-requests/'+encodeURIComponent(saved.key));id=found.job_id;}
 if(!id){localStorage.removeItem(liveJobKey);throw new Error('Запрос не дошёл до сервера. Тема сохранена, повторите действие.');}
 return await pollLiveJob(id);
}
async function liveJob(payload){
 const previous=savedLiveJob(),fingerprint=requestFingerprint(payload);
 if(previous){
  if(previous.fingerprint!==fingerprint)throw new Error('Сначала завершите предыдущую задачу: закройте и откройте Mini App для восстановления результата.');
  return await resumeLiveJob(previous);
 }
 const key=crypto.randomUUID();
 const saved={key,operation:payload.operation,fingerprint,topic:liveFlow.task,workflow:liveFlow.workflow};
 localStorage.setItem(liveJobKey,JSON.stringify(saved));
 let started;
 try{started=await api('./workflow',{method:'POST',body:JSON.stringify({...payload,request_id:key})});}
 catch(error){
  if(error.status&&error.status<500){localStorage.removeItem(liveJobKey);throw error;}
  const recovered=await api('./job-requests/'+encodeURIComponent(key)).catch(()=>null);
  if(!recovered?.job_id)throw error;
  started=recovered;
 }
 localStorage.setItem(liveJobKey,JSON.stringify({...saved,id:started.job_id}));
 return await pollLiveJob(started.job_id);
}
async function pollLiveJob(id){
 let failures=0;
 for(let i=0;i<300;i++){
  let job;
  try{job=await api('./jobs/'+id);failures=0;}
  catch(error){if(error.status===403||error.status===400||++failures>3)throw error;await new Promise(r=>setTimeout(r,1000*failures));continue;}
  if(job.status==='done'){localStorage.removeItem(liveJobKey);return job.result;}
  if(job.status==='failed'){localStorage.removeItem(liveJobKey);throw new Error(job.result.detail||'Не удалось обработать задачу.');}
  await new Promise(resolve=>setTimeout(resolve,i<10?700:1500));
 }
 throw new Error('Задача ещё обрабатывается. Откройте приложение позже: результат сохранится.');
}
async function saveLiveEdits(){
 if(!liveFlow.editorDirty)return;
 liveFlow.post=await api('./posts/'+liveFlow.post.id,{method:'PATCH',body:JSON.stringify({rev:liveFlow.post.rev,body:liveFlow.editorBody??captureLiveEditor()})});
 liveFlow.editorBody=null;liveFlow.editorDirty=false;
}
async function refreshLiveData(){if(!demo)state.data=await api('./data');}
function acceptLiveResult(result){
 if(result.calendar){state.tab='plan';state.screen='root';state.planFilter='all';state.day='';state.month=dayKey(result.posts[0].due).slice(0,7);liveCompose.message='Готово: '+result.posts.length+' поста добавлены в календарь.';}
 if(result.workflow_id)liveFlow.workflow=result.workflow_id;
 if(result.posts?.length){if(liveFlow.post?.id!==result.posts[0].id){liveFlow.editTarget='text';liveFlow._instructions={};}else if(liveFlow._instructions){liveFlow._instructions[liveFlow.editTarget||'text']='';}liveFlow.editorBody=null;liveFlow.editorDirty=false;liveFlow.instruction='';if(state.data){const ids=new Set(result.posts.map(p=>p.id));state.data.posts=[...result.posts,...state.data.posts.filter(p=>!ids.has(p.id))];}liveFlow.post=result.posts[0];liveFlow.step=3;liveFlow.question='';}
 if(result.scheduled)liveFlow.step=4;
 else if(result.question){liveFlow.question=result.question;liveFlow.facts=result.facts||liveFlow.facts;liveFlow.step=1;}
 else if(result.ideas){liveFlow.ideas=result.ideas;liveFlow.facts=result.facts||[];liveFlow.idea=0;liveFlow.question='';liveFlow.step=2;}
}
async function runLiveOperation(operation,extra={}){
 if(liveFlow.busy)return;
 liveFlow.operation=operation;liveFlow.busy=true;liveFlow.error='';render();
 try{
  if(['rewrite','schedule','image'].includes(operation)){await saveLiveEdits();extra.rev=liveFlow.post.rev;}
  const result=await liveJob({operation,task:liveFlow.task,workflow_id:liveFlow.workflow,idea:liveFlow.idea,...extra});
  acceptLiveResult(result);try{await refreshLiveData();}catch{liveFlow.error='Результат сохранён. Список обновится после восстановления связи.';}
 }catch(error){liveFlow.error=error.message;}
 finally{liveFlow.busy=false;render();}
}
async function ensureLiveImage(post){
 if(!post.has_image||(liveFlow.imagePostId===post.id&&liveFlow.imagePostRev===post.rev))return;
 liveFlow.imagePostId=post.id;liveFlow.imagePostRev=post.rev;
 if(liveFlow.imageUrl)URL.revokeObjectURL(liveFlow.imageUrl);
 liveFlow.imageUrl=null;
 try{
  const response=await fetch('./post-images/'+post.id,{headers:{'X-Telegram-Init-Data':initData}});
  if(!response.ok)return;
  const blob=await response.blob();
  if(liveFlow.post?.id!==post.id||liveFlow.imagePostId!==post.id||liveFlow.imagePostRev!==post.rev)return;
  liveFlow.imageUrl=URL.createObjectURL(blob);render();
 }catch{/* The saved text remains editable when the image connection fails. */}
}
function showLiveFlow(){
 const p=liveFlow,names=['Тема','Уточнения','Идеи','Текст','Готово'];
 const progress=`<ol class="flow-steps" aria-label="Этапы создания публикации">${names.map((n,i)=>`<li class="${i<p.step?'complete':i===p.step?'active':''}" ${i===p.step?'aria-current="step"':''}><span>${i<p.step?'✓':i===p.step?'●':''}</span><small>${n}</small></li>`).join('')}</ol>`;
 let content='',label='Продолжить';
 if(p.step===0){content=designBubble('Расскажите о событии: что произошло или планируется, для кого пишем и что важно сообщить.')+`<label class="live-topic">Тема и материалы<textarea id="live-task" maxlength="6000" rows="7" placeholder="Например: 20 ноября проводим экскурсию для студентов…">${escapeHTML(p.task)}</textarea><button type="button" class="button secondary" data-record-voice="topic">${microphoneIcon()} Надиктовать</button></label>`;label='Собрать факты и идеи';}
 if(p.step===1){content=designBubble(escapeHTML(p.question))+`<div class="clarification-card">${p.facts.map(f=>`<p><b>${escapeHTML(f.label)}:</b> ${escapeHTML(f.value)}</p>`).join('')}<label class="live-topic">Ваше уточнение<textarea id="live-clarification" rows="5" maxlength="4000" placeholder="Ответьте на вопросы или исправьте факты">${escapeHTML(p.clarification)}</textarea><button type="button" class="button secondary" data-record-voice="clarification">${microphoneIcon()} Надиктовать ответ</button></label></div>`;label='Продолжить';}
 if(p.step===2){content=designBubble('Факты собраны. Выберите подачу будущего поста.')+`<details class="live-facts"><summary>Собранные факты</summary>${p.facts.map(f=>`<p><b>${escapeHTML(f.label)}:</b> ${escapeHTML(f.value)}</p>`).join('')}</details><div class="flow-ideas" role="radiogroup" aria-label="Подача публикации">${p.ideas.map((idea,i)=>`<button type="button" class="flow-idea ${p.idea===i?'selected':''}" role="radio" aria-checked="${p.idea===i}" data-live-idea="${i}"><span class="radio-mark"></span><span><strong>${escapeHTML(idea.title)}</strong><small>${escapeHTML(idea.angle)}</small></span></button>`).join('')}</div>`;label='Создать черновик';}
 if(p.step===3&&p.post){ensureLiveImage(p.post);content=designBubble('Черновик сохранён и уже доступен в боте. Отредактируйте текст или напишите пожелание ниже.')+`<article class="draft-preview"><header>${icon('file')}<strong>Черновик публикации</strong><small>№${p.post.id}</small></header>${p.post.has_image&&p.imageUrl&&p.imagePostId===p.post.id?`<img src="${p.imageUrl}" alt="Изображение публикации" style="width:100%;display:block;border-radius:14px">`:""}<div class="draft-preview-body" contenteditable="true" role="textbox" aria-label="Текст черновика" id="live-editor">${safePostHTML(p.editorBody??p.post.body_html??p.post.body)}</div>${p.post.warnings?.length?`<details class="live-facts"><summary>Заметки редактору (${p.post.warnings.length})</summary>${p.post.warnings.map(x=>`<p>${escapeHTML(x)}</p>`).join('')}</details>`:''}</article><div class="flow-secondary"><button class="button secondary" data-live-action="ideas">Другой подход</button><button class="button secondary" data-live-action="open-bot">Открыть в боте</button></div>`+scheduleControls(p.post)+vkControls(p.post);label='Сохранить правки';}
 if(p.step===4){content=`<div class="flow-finish"><span class="finish-icon">✓</span><h1>${p.post?.delivery_state==='queued'?'Запланировано!':'Сохранено!'}</h1><p>Пост №${p.post?.id||''} доступен в Mini App и Telegram-боте.</p><small>${p.post?.delivery_state==='queued'?'Отправлю '+escapeHTML(dateText(p.post.due,{day:'numeric',month:'long',hour:'2-digit',minute:'2-digit'}))+' по времени Уфы. Компьютер и бот должны работать.':'Публикацию можно отправить из карточки поста в боте.'}</small></div>`;label='Мои посты';}
 return `<section class="design-flow"><header class="flow-head"><button data-live-action="back" aria-label="Назад" ${p.busy?'disabled':''}>‹</button><span class="flow-logo">${icon('layers')}</span><span><strong>AI-маркетолог</strong><small>Создание публикации</small></span></header>${progress}<div class="flow-content">${content}${p.error?`<p class="live-error" role="alert">${escapeHTML(p.error)}</p>`:''}${p.busy?`<div class="live-loading" role="status"><span></span><span></span><span></span> ${p.operation==='calendar_plan'?'Готовлю посты, изображения и даты…':p.operation==='generate'?'Создаю текст и изображение…':p.operation==='image'?'Создаю изображение по теме поста…':'Готовлю результат…'}</div>`:''}</div><button type="button" class="button primary flow-next" data-live-action="next" aria-busy="${p.busy}" ${p.busy?'disabled':''}>${p.busy?'<span class="button-spinner" aria-hidden="true"></span> Готовлю…':label}${p.busy?"":"<span>→</span>"}</button>${p.step===3?`<div class="flow-secondary" role="group" aria-label="Что редактируем"><button class="button ${p.editTarget!=='image'?'primary':'secondary'}" data-live-action="edit-text" ${p.busy?'disabled':''}>Текст</button><button class="button ${p.editTarget==='image'?'primary':'secondary'}" data-live-action="edit-image" ${p.busy?'disabled':''}>Изображение</button></div>${p.editTarget==='image'?'<small>Новый вариант изображения. Генерация оплачивается; текст поста сохраняется.</small>':''}<form id="live-comment" class="flow-composer"><input name="instruction" aria-label="Что изменить в посте" maxlength="${p.editTarget==='image'?1200:4000}" placeholder="${p.editTarget==='image'?'Что изменить в изображении?':'Что изменить в тексте?'}" value="${escapeHTML(p.instruction)}" ${p.busy?'disabled':''}><button type="submit" aria-label="Применить правку" ${p.busy?'disabled':''}>${icon('send')}</button><button type="button" data-record-voice="instruction" aria-label="Надиктовать правку">${microphoneIcon()}</button></form>`:''}</section>`;
}
function captureLiveEditor(){const el=document.getElementById('live-editor');return el?el.innerHTML.replace(/<\/(div|p)>/gi,'\n').replace(/<(div|p)(\s[^>]*)?>/gi,''):liveFlow.post?.body||'';}
async function liveClick(event){
 const button=event.target.closest('[data-live-action],[data-live-idea],[data-preview-action],[data-preview-voice],[data-live-edit]');if(!button)return false;
 event.preventDefault();event.stopImmediatePropagation();if(liveFlow.busy||liveCompose.recording||liveCompose.processing)return true;
 if(button.dataset.liveEdit){try{liveFlow.post=await api('./posts/'+button.dataset.liveEdit);liveFlow.editTarget='text';liveFlow._instructions={};liveFlow.editorBody=null;liveFlow.editorDirty=false;liveFlow.instruction='';liveFlow.step=3;liveFlow.workflow=null;liveFlow.ideas=[];liveFlow.error='';state.tab='chat';state.screen='root';render();}catch(e){liveFlow.error=e.message;render();}return true;}
 if(button.hasAttribute('data-preview-voice')){if(tg?.openTelegramLink)tg.openTelegramLink(botLink);else window.open(botLink);return true;}
 if(button.hasAttribute('data-live-idea')){liveFlow.idea=Number(button.dataset.liveIdea);render();return true;}
 const action=button.dataset.liveAction||button.dataset.previewAction;
 if(action==='edit-image'||action==='edit-text'){liveFlow._instructions=liveFlow._instructions||{};liveFlow._instructions[liveFlow.editTarget||'text']=liveFlow.instruction;liveFlow.editTarget=action==='edit-image'?'image':'text';liveFlow.instruction=liveFlow._instructions[liveFlow.editTarget]||'';render();return true;}
 if(action==='home-create'){liveFlow.operation='plan';state.tab='chat';state.screen='root';liveFlow.step=0;render();return true;}
 if(action==='back'){if(liveFlow.step===2)liveFlow.step=1;else if(liveFlow.step===3){if(liveFlow.ideas.length)liveFlow.step=2;else{state.tab='work';state.screen='list';state.filter='all';}}else{state.tab='work';}render();return true;}
 if(action==='ideas'){if(liveFlow.ideas.length)liveFlow.step=2;else{liveFlow.task=liveFlow.post?.title||'';liveFlow.workflow=null;liveFlow.step=0;}render();return true;}
 if(action==='open-bot'){const url=botLink+'?start=post_'+liveFlow.post.id;if(tg?.openTelegramLink)tg.openTelegramLink(url);else window.open(url);return true;}
 if(action==='schedule'){const due=document.getElementById('schedule-due')?.value;if(!due){liveFlow.error='Выберите дату и время.';render();return true;}await runLiveOperation('schedule',{post_id:liveFlow.post.id,rev:liveFlow.post.rev,due});return true;}
 if(action==='unschedule'){await runLiveOperation('unschedule',{post_id:liveFlow.post.id,rev:liveFlow.post.rev});return true;}
 if(action==='next'){
  if(liveFlow.step===0){liveFlow.task=document.getElementById('live-task').value.trim();if(!liveFlow.task){liveFlow.error='Сначала опишите событие.';render();return true;}liveFlow.workflow=null;await runLiveOperation(liveFlow.operation==='calendar_plan'?'calendar_plan':'plan');}
  else if(liveFlow.step===1){liveFlow.clarification=document.getElementById('live-clarification').value.trim();if(!liveFlow.clarification){liveFlow.error='Добавьте уточнение.';render();return true;}await runLiveOperation('plan',{clarification:liveFlow.clarification});if(!liveFlow.error)liveFlow.clarification='';}
  else if(liveFlow.step===2)await runLiveOperation('generate');
  else if(liveFlow.step===3){liveFlow.busy=true;liveFlow.error='';render();try{await saveLiveEdits();liveFlow.step=4;try{await refreshLiveData();}catch{liveFlow.error='Пост сохранён. Список обновится после восстановления связи.';}}catch(e){liveFlow.error=e.message;}finally{liveFlow.busy=false;render();}}
  else{await refreshLiveData();state.tab='work';state.screen='list';state.filter='all';render();}
 }
 return true;
}
document.addEventListener('click',event=>{if(!demo)liveClick(event).catch(e=>{liveFlow.error=e.message;liveFlow.busy=false;render();});},true);
document.addEventListener('submit',event=>{
 if(demo||!['ai-form','design-form','live-comment'].includes(event.target.id))return;
 event.preventDefault();event.stopImmediatePropagation();if(liveFlow.busy||liveCompose.recording||liveCompose.processing)return;
 if(event.target.id==='ai-form'){
  const text=event.target.elements.task.value.trim();if(!text)return;
  Object.assign(liveFlow,{step:0,task:text,workflow:null,error:'',post:null,facts:[],ideas:[]});state.tab='chat';state.screen='root';render();runLiveOperation(liveCompose.mode==='plan'||/контент[\s-]*план/i.test(text)?'calendar_plan':'plan');
 }else if(event.target.id==='live-comment'){
  const instruction=event.target.elements.instruction.value.trim();if(!instruction)return;
  runLiveOperation(liveFlow.editTarget==='image'?'image':'rewrite',{post_id:liveFlow.post.id,rev:liveFlow.post.rev,instruction});
 }
},true);
document.addEventListener('paste',event=>{if(!demo&&event.target.closest('#live-editor')){event.preventDefault();document.execCommand('insertText',false,event.clipboardData.getData('text/plain'));}});
document.addEventListener('visibilitychange',()=>{if(!document.hidden&&!demo&&state.data&&!liveFlow.busy)refreshLiveData().then(()=>{if(state.screen!=='post'&&state.tab!=='chat')render();}).catch(()=>{});});

setInterval(()=>{
 if(demo||document.hidden||!state.data||liveFlow.busy||state.saving||state.tab==='chat'||state.tab==='profile'||state.screen==='post')return;
 const active=document.activeElement;if(active?.matches('input,textarea,[contenteditable]'))return;
 const previous=JSON.stringify(state.data.posts.map(p=>[p.id,p.rev,p.status]));
 refreshLiveData().then(()=>{if(previous!==JSON.stringify(state.data.posts.map(p=>[p.id,p.rev,p.status])))render();}).catch(()=>{});
},15000);

document.addEventListener('input',event=>{if(event.target.id==='live-editor'){liveFlow.editorBody=captureLiveEditor();liveFlow.editorDirty=true;}if(event.target.matches('#live-comment [name=instruction]'))liveFlow.instruction=event.target.value;});

function scheduleControls(post){
 const due=post.due?new Date(post.due):new Date(Date.now()+3600000);
 const value=new Date(due.getTime()+5*3600000).toISOString().slice(0,16);
 return `<section class="schedule-card"><h2>Публикация по времени</h2><p>Канал подключён · Уфа, UTC+5</p>${post.delivery_state==='queued'?`<p>Отправка: ${escapeHTML(dateText(post.due,{day:'numeric',month:'long',hour:'2-digit',minute:'2-digit'}))}</p><button class="button secondary" data-live-action="unschedule">Снять с расписания</button>`:`<label>Дата и время<input type="datetime-local" id="schedule-due" value="${value}"></label><button type="button" class="button primary" data-live-action="schedule">Согласовать и запланировать</button>`}</section>`;
}

document.addEventListener('click',event=>{const spoiler=event.target.closest('.post-body tg-spoiler');if(spoiler)spoiler.classList.toggle('revealed');});
