/* Shared company knowledge and consultant; no archive is stored in browser prompts. */
const marketerDraftKey='salstek-marketer-draft';
function readMarketerDraft(){try{return sessionStorage.getItem(marketerDraftKey)||'';}catch{return '';}}
function storeMarketerDraft(value){try{if(value)sessionStorage.setItem(marketerDraftKey,value);else sessionStorage.removeItem(marketerDraftKey);}catch{}}
const marketerUI={loaded:false,loading:false,busy:false,topicBusy:null,documents:[],history:[],plan:[],text:readMarketerDraft(),error:'',notice:''};
async function loadMarketer(){
 if(demo||marketerUI.loading)return;
 marketerUI.loading=true;
 try{const result=await api('./knowledge');Object.assign(marketerUI,result);marketerUI.loaded=true;}
 catch(e){marketerUI.error=e.message;}
 finally{marketerUI.loading=false;if(state.screen==='marketer')render();}
}
function showMarketer(){
 if(demo&&!marketerUI.loaded){marketerUI.loaded=true;marketerUI.plan=[{topic:"Старт футбольного матча между командами предприятия",angle:"Приглашаем коллег поддержать игроков и рассказываем о предстоящей встрече."},{topic:"Годовщина цеха",angle:"Вспоминаем историю и рассказываем о людях."},{topic:"Финал футбольного турнира",angle:"Подводим итоги после подтверждения результата."}];}
 if(!marketerUI.loaded&&!marketerUI.loading&&!marketerUI.error)loadMarketer();
 const m=marketerUI;
 return heading('Маркетолог',{back:true})+`<div class="panel marketer-intro"><h2>Планируем и создаём вместе</h2><p>Учитываю компанию, документы и ваши посты. Что подготовим?</p><div class="marketer-shortcuts"><button type="button" data-marketer-prompt="Предложи контент-план на неделю по нашим материалам">План на неделю</button><button type="button" data-create>Новый пост</button></div></div>
 <details class="panel marketer-documents"><summary>Документы компании${m.documents.length?` · ${m.documents.length}`:""}</summary><p>PDF, DOCX, TXT, MD до 5 МБ. Документ изучается один раз; дальше используются короткие выжимки. Сканам нужен текстовый слой.</p><label class="button secondary">Загрузить документ<input id="company-document" type="file" accept=".pdf,.docx,.txt,.md" ${m.busy?'disabled':''} hidden></label>${m.documents.map(d=>`<div class="row"><span class="row-copy"><strong>${escapeHTML(d.name)}</strong><small>${d.state==='ready'?'Изучен':'Обрабатывается'}</small></span><button class="button secondary" data-document-delete="${d.id}" ${m.busy?'disabled':''}>Удалить</button></div>`).join('')}</details>
 ${m.plan.length?`<details class="panel marketer-documents"><summary>Контент-план · ${m.plan.length} ${new Intl.PluralRules("ru").select(m.plan.length)==="one"?"тема":new Intl.PluralRules("ru").select(m.plan.length)==="few"?"темы":"тем"}</summary>${m.plan.map((p,i)=>`<div class="marketer-plan-topic"><span class="row-copy"><strong>${escapeHTML(p.topic)}</strong><small>${escapeHTML(p.angle)}</small></span><button class="button secondary" data-marketer-topic="${i}" aria-busy="${m.topicBusy===i}" ${m.busy?'disabled':''}> ${m.topicBusy===i?'<span class="button-spinner" aria-hidden="true"></span> Готовлю тему…':"Создать пост"}</button></div>`).join('')}</details>`:''}
 <div class="marketer-history" aria-live="polite">${m.history.map(x=>`<article class="panel ${x.role==='user'?'marketer-user':''}"><small>${x.role==='user'?'Вы':'Маркетолог'}</small><div class="post-body">${x.role==='user'?escapeHTML(x.text).replace(/\n/g,'<br>'):safePostHTML(x.text)}</div></article>`).join('')}</div>
 ${m.notice&&!m.busy?`<p role="status">${escapeHTML(m.notice)}</p>`:''}${m.busy||m.loading?'<div class="live-loading" role="status"><span></span><span></span><span></span> '+(m.loading?'Загружаю память…':m.notice||'Маркетолог готовит ответ…')+'</div>':''}
 <form id="marketer-form" class="panel marketer-form">${m.error?`<div class="live-error" role="alert">${escapeHTML(m.error)}<br><small>Текст ниже сохранён. Можно исправить его и отправить снова.</small></div>`:""}<label>Задача маркетологу<textarea id="marketer-question" rows="4" maxlength="4000" placeholder="Предложи контент-план на неделю с учётом наших документов и последних постов" ${m.busy?'disabled':''}>${escapeHTML(m.text)}</textarea></label><button class="button primary" type="submit" aria-busy="${m.busy}" ${m.busy||demo?'disabled':''}>${m.busy?'<span class="button-spinner" aria-hidden="true"></span> Обрабатываю…':m.error?"Попробовать снова":"Отправить задачу"}</button><small>Публикация только после вашего согласования.</small></form>`;
}
document.addEventListener('input',e=>{if(e.target.id==='marketer-question'){marketerUI.text=e.target.value;storeMarketerDraft(marketerUI.text);}});
document.addEventListener('submit',async e=>{
 if(e.target.id!=='marketer-form')return;e.preventDefault();if(marketerUI.busy||!marketerUI.text.trim())return;
 marketerUI.busy=true;marketerUI.error='';marketerUI.notice='';render();
 try{const result=await liveJob({operation:'marketer',text:marketerUI.text});marketerUI.history=result.history;marketerUI.text='';storeMarketerDraft('');if(result.plan_saved){marketerUI.notice='Контент-план сохранён и доступен в боте.';await loadMarketer();}}
 catch(error){marketerUI.error=error.message;}
 finally{marketerUI.busy=false;render();}
});
document.addEventListener('change',async e=>{
 if(e.target.id!=='company-document')return;const file=e.target.files?.[0];if(!file||marketerUI.busy)return;
 if(file.size>5*1024*1024){marketerUI.error='Документ должен быть не больше 5 МБ.';render();return;}
 marketerUI.busy=true;marketerUI.error='';marketerUI.notice='Изучаю документ…';render();
 const key=crypto.randomUUID();
 try{
  let started;
  try{const response=await fetch('./documents',{method:'POST',headers:{'X-Telegram-Init-Data':initData,'X-Filename':encodeURIComponent(file.name),'X-Request-ID':key,'Content-Type':'application/octet-stream'},body:file});started=await response.json();if(!response.ok)throw Object.assign(new Error(started.detail||'Не удалось загрузить файл.'),{status:response.status});}
  catch(error){if(error.status)throw error;started=await api('./job-requests/'+encodeURIComponent(key));if(!started.job_id)throw new Error('Файл не загружен. Повторите загрузку.');}
  localStorage.setItem(liveJobKey,JSON.stringify({id:started.job_id,key,operation:'document'}));
  const result=await pollLiveJob(started.job_id);marketerUI.notice=result.cached?'Документ уже был изучен.':'Документ изучен. Выжимка сохранена.';await loadMarketer();
 }catch(error){marketerUI.error=error.message;marketerUI.notice='';}
 finally{marketerUI.busy=false;render();}
});
document.addEventListener('click',async e=>{
 const quick=e.target.closest('[data-marketer-prompt]');if(quick&&!marketerUI.busy){marketerUI.text=quick.dataset.marketerPrompt;storeMarketerDraft(marketerUI.text);render();document.getElementById('marketer-question')?.focus();return;}
 const enter=e.target.closest('[data-section="marketer"]');if(enter){marketerUI.loaded=false;marketerUI.error='';return;}
 const topic=e.target.closest('[data-marketer-topic]');if(topic&&!marketerUI.busy){
  const index=Number(topic.dataset.marketerTopic),item=marketerUI.plan[index];if(!item)return;
  if(demo){liveFlow.task=item.topic+'\n'+item.angle;liveFlow.step=0;state.tab='chat';state.screen='root';render();return;}
  marketerUI.busy=true;marketerUI.topicBusy=index;marketerUI.error='';render();
  try{
   const result=await liveJob({operation:'plan_topic',plan_nonce:marketerUI.plan_nonce,topic_index:index});
   liveFlow.task=result.task;liveFlow.workflow=result.workflow_id;liveFlow.post=null;liveFlow.step=0;liveFlow.clarification='';liveFlow.error='';acceptLiveResult(result);
   state.tab='chat';state.screen='root';
  }catch(error){marketerUI.error=error.message;}
  finally{marketerUI.busy=false;marketerUI.topicBusy=null;render();}
  return;
 }
 const button=e.target.closest('[data-document-delete]');if(!button||marketerUI.busy)return;
 marketerUI.busy=true;marketerUI.error='';render();
 try{const result=await liveJob({operation:'document_delete',document_id:Number(button.dataset.documentDelete)});marketerUI.documents=result.documents;marketerUI.notice='Документ удалён из знаний компании.';}
 catch(error){marketerUI.error=error.message;}
 finally{marketerUI.busy=false;render();}
});

document.addEventListener("focusin",e=>{if(e.target.matches("textarea,input:not([type=file])"))document.body.classList.add("editing-field");});
document.addEventListener("focusout",e=>{if(!e.relatedTarget?.matches("textarea,input:not([type=file])"))document.body.classList.remove("editing-field");});
