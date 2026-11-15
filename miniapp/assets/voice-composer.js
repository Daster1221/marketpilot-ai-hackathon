"use strict";
const liveCompose={mode:'post',draft:'',message:'',recording:false,processing:false,target:'task',error:'',phase:'',success:false};
let voiceRecorder=null,voiceStream=null,voiceTimer=null;
const pendingVoiceKey="salstek-pending-voice";
function microphoneIcon(){return '<svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true"><rect x="9" y="2" width="6" height="13" rx="3"/><path d="M5 10v2a7 7 0 0 0 14 0v-2M12 19v3m-4 0h8"/></svg>';}
function homeComposer(){return `<section class="task-studio"><div class="studio-modes" role="group" aria-label="Что создать"><button type="button" data-compose-mode="post" aria-pressed="${liveCompose.mode==='post'}">Пост</button><button type="button" data-compose-mode="plan" aria-pressed="${liveCompose.mode==='plan'}">Контент-план</button></div><h2>${liveCompose.mode==='plan'?'Неделя начинается с идеи':'О чём расскажем?'}</h2><p>${liveCompose.mode==='plan'?'ИИ выберет даты и подготовит тексты для календаря.':'Расскажите своими словами или запишите голосом.'}</p><form id="ai-form"><textarea name="task" id="home-task" maxlength="6000" rows="4" aria-label="Задача для ИИ" placeholder="${liveCompose.mode==='plan'?'Подготовь 3 поста на неделю о работе нашего предприятия…':'Например: приглашаем студентов на экскурсию 20 ноября…'}">${escapeHTML(liveCompose.draft)}</textarea><div class="studio-actions"><button type="button" class="voice-button" data-record-voice="task" aria-label="Записать голосом" ${liveCompose.processing?'disabled':''}>${microphoneIcon()}</button><button type="submit" class="button primary" ${liveFlow.busy||liveCompose.processing||liveCompose.recording?'disabled':''}>${liveFlow.busy||liveCompose.processing?'<span class="button-spinner" aria-hidden="true"></span> Готовлю…':liveCompose.mode==='plan'?'Создать план':'Создать с ИИ'} ${liveFlow.busy||liveCompose.processing?'':'<span>→</span>'}</button></div></form><small>Текстом или голосом · До 3 минут</small><button type="button" class="recover-voice" data-recover-voice>Вернуть последнюю расшифровку</button></section>`;}
function paintVoiceStatus(){
 let box=document.getElementById('voice-status');
 if(!box){box=document.createElement('div');box.id='voice-status';box.setAttribute('role','status');box.setAttribute('aria-live','polite');document.body.append(box);}
 const active=liveCompose.recording||liveCompose.processing;
 box.hidden=!(active||liveCompose.error||liveCompose.success);
 const animation='<span class="voice-bars" aria-hidden="true"><i></i><i></i><i></i><i></i><i></i></span>';
 const title=liveCompose.recording?'Записываю голос':liveCompose.phase==='upload'?'Отправляю запись':liveCompose.phase==='permission'?'Открываю микрофон':'Распознаю голос';
 const detail=liveCompose.recording?'Когда закончите, нажмите «Остановить»':liveCompose.phase==='permission'?'Разрешите доступ к микрофону':'Не закрывайте приложение. Текст появится в поле.';
 box.innerHTML=active?`${animation}<span class="voice-status-copy"><strong>${title}</strong><small>${detail}</small></span>${liveCompose.recording?'<button type="button" data-stop-voice>Остановить</button>':''}`:`<span class="voice-status-copy"><strong>${liveCompose.success?'Голос распознан':'Не удалось обработать голос'}</strong><small>${escapeHTML(liveCompose.error||'Текст добавлен в поле. Проверьте его и продолжайте.')}</small></span><button type="button" data-dismiss-voice>Закрыть</button>${liveCompose.error?'<button type="button" class="voice-recover-action" data-recover-voice>Вернуть последнюю расшифровку</button>':''}`;
 document.querySelectorAll('[data-record-voice]').forEach(el=>{el.classList.toggle('is-recording',liveCompose.recording);el.classList.toggle('is-transcribing',liveCompose.processing);el.disabled=liveCompose.processing;el.setAttribute('aria-busy',String(liveCompose.processing));});
 document.querySelectorAll('#ai-form button[type=submit],[data-live-action=next],#live-comment button[type=submit]').forEach(el=>{el.disabled=Boolean(active||liveFlow.busy);});
}
function voiceError(error){
 if(error.name==='SyntaxError'||error.name==='TypeError')return 'Не удалось отправить запись из Telegram. Попробуйте снова или выберите аудиофайл.';
 return error.message||'Не удалось распознать голос. Попробуйте ещё раз.';
}
function voiceTarget(name){return name==='task'?document.querySelector('#home-task'):name==='topic'?document.querySelector('#live-task'):name==='clarification'?document.querySelector('#live-clarification'):document.querySelector('#live-comment [name="instruction"]');}
async function uploadVoice(blob,target,postId){
 liveCompose.processing=true;liveCompose.success=false;liveCompose.error='';liveCompose.phase='upload';paintVoiceStatus();
 try{
  if(blob.size>5*1024*1024)throw new Error('Запись больше 5 МБ. Запишите сообщение короче.');
  const audio=await blob.arrayBuffer();
  const mime=(blob.type||'application/octet-stream').split(';')[0];
  const key=crypto.randomUUID();
  localStorage.setItem(pendingVoiceKey,JSON.stringify({key,target,postId}));
  let job;
  try{
   const response=await fetch(new URL('./transcribe',window.location.href).href,{method:'POST',headers:{'X-Telegram-Init-Data':initData,'X-Request-ID':key,'Content-Type':mime},body:audio});
   job=await response.json();if(!response.ok)throw new Error(job.detail||'Не удалось отправить запись.');
  }catch(error){
   // Safari/tunnel may lose the upload ACK after the server has saved the job.
   // GET by the SAME request key recovers it without sending audio twice.
   for(let attempt=0;attempt<4;attempt++){
    const recovered=await api('./job-requests/'+encodeURIComponent(key)).catch(()=>null);
    if(recovered?.job_id){job=recovered;break;}
    await new Promise(resolve=>setTimeout(resolve,1000));
   }
   if(!job?.job_id)throw error;
  }
  liveCompose.phase='recognize';paintVoiceStatus();
  let result;
  for(let i=0;i<300;i++){
   const current=await api('./jobs/'+job.job_id);
   if(current.status==='failed')throw new Error(current.result.detail||'Не удалось распознать запись.');
   if(current.status==='done'){result=current.result;break;}
   await new Promise(r=>setTimeout(r,1000));
  }
  if(!result)throw new Error('Распознавание задерживается. Результат можно вернуть кнопкой ниже.');
  localStorage.removeItem(pendingVoiceKey);
  const el=voiceTarget(target);
  if(!el||(target==='instruction'&&liveFlow.post?.id!==postId)){
   liveCompose.draft=[liveCompose.draft,result.transcript].filter(Boolean).join('\n');
   liveCompose.error='Речь сохранена в поле задачи на главной.';
  }else{el.value=[el.value,result.transcript].filter(Boolean).join('\n').slice(0,Number(el.maxLength)>0?el.maxLength:6000);el.dispatchEvent(new Event('input',{bubbles:true}));liveCompose.success=true;}
 }catch(error){liveCompose.error=voiceError(error);}
 finally{liveCompose.processing=false;paintVoiceStatus();}
}
async function recoverVoice(){
 if(liveCompose.processing||liveCompose.recording||liveFlow.busy)return;
 liveCompose.processing=true;liveCompose.phase='recognize';liveCompose.error='';liveCompose.success=false;paintVoiceStatus();
 try{
  const pending=JSON.parse(localStorage.getItem(pendingVoiceKey)||'null');
  let result;
  if(pending?.key){
   const found=await api('./job-requests/'+encodeURIComponent(pending.key));
   if(found.job_id){
    const current=await api('./jobs/'+found.job_id);
    if(current.status==='queued'||current.status==='running')throw new Error('Запись ещё распознаётся. Попробуйте вернуть её немного позже.');
    if(current.status==='failed')throw new Error(current.result.detail||'Не удалось распознать запись.');
    result=current.result;
   }
  }
  result=result||await api('./last-transcript');
  const target=pending?.target||liveCompose.target||'task';
  const el=voiceTarget(target);
  if(el&&(target!=='instruction'||pending?.postId===liveFlow.post?.id)){
   el.value=[el.value,result.transcript].filter(Boolean).join('\n').slice(0,el.maxLength>0?el.maxLength:6000);el.dispatchEvent(new Event('input',{bubbles:true}));
  }else{
   liveCompose.draft=[liveCompose.draft,result.transcript].filter(Boolean).join('\n');
   liveCompose.error='Расшифровка добавлена в поле задачи на главной.';
  }
  localStorage.removeItem(pendingVoiceKey);liveCompose.success=true;
 }catch(error){liveCompose.error=voiceError(error);}
 finally{liveCompose.processing=false;paintVoiceStatus();}
}
function stopVoice(){if(voiceRecorder?.state==='recording')voiceRecorder.stop();}
async function recordVoice(target){
 if(liveCompose.processing||liveFlow.busy)return;
 if(liveCompose.recording){stopVoice();return;}
 liveCompose.error='';liveCompose.success=false;liveCompose.phase='permission';liveCompose.processing=true;paintVoiceStatus();liveCompose.target=target;const postId=liveFlow.post?.id;
 if(!navigator.mediaDevices?.getUserMedia||!window.MediaRecorder){liveCompose.processing=false;liveCompose.error='Микрофон недоступен в этом Telegram. Можно прикрепить аудиофайл.';paintVoiceStatus();pickVoice(target,postId);return;}
 try{
  voiceStream=await navigator.mediaDevices.getUserMedia({audio:true});
  // Let WebKit choose its native audio container (AAC/MP4 on iPhone).
  voiceRecorder=new MediaRecorder(voiceStream);const chunks=[];let bytes=0;
  voiceRecorder.ondataavailable=event=>{if(event.data.size){chunks.push(event.data);bytes+=event.data.size;if(bytes>5*1024*1024)stopVoice();}};
  voiceRecorder.onstop=()=>{clearTimeout(voiceTimer);voiceStream?.getTracks().forEach(t=>t.stop());liveCompose.recording=false;uploadVoice(new Blob(chunks,{type:voiceRecorder.mimeType}),target,postId);};
  voiceRecorder.onerror=()=>{stopVoice();liveCompose.error='Не удалось записать голос. Попробуйте аудиофайл.';paintVoiceStatus();};
  voiceRecorder.start(1000);liveCompose.processing=false;liveCompose.recording=true;voiceTimer=setTimeout(stopVoice,180000);paintVoiceStatus();
 }catch(error){liveCompose.processing=false;voiceStream?.getTracks().forEach(t=>t.stop());liveCompose.error=error.name==='NotAllowedError'?'Разрешите доступ к микрофону в Telegram или прикрепите аудиофайл.':'Микрофон недоступен. Попробуйте аудиофайл.';paintVoiceStatus();pickVoice(target,postId);}
}
function pickVoice(target,postId){const input=document.createElement('input');input.type='file';input.accept='audio/*';input.onchange=()=>{if(input.files[0])uploadVoice(input.files[0],target,postId);};input.click();}
document.addEventListener('input',event=>{if(event.target.id==='home-task')liveCompose.draft=event.target.value;if(event.target.id==='live-task')liveFlow.task=event.target.value;if(event.target.id==='live-clarification')liveFlow.clarification=event.target.value;});
document.addEventListener('click',event=>{
 if(demo)return;const el=event.target.closest('[data-compose-mode],[data-open-calendar-plan],[data-record-voice],[data-stop-voice],[data-dismiss-voice],[data-recover-voice]');if(!el)return;
 event.preventDefault();event.stopImmediatePropagation();
 if(el.hasAttribute('data-stop-voice'))return stopVoice();
 if(el.hasAttribute('data-recover-voice'))return void recoverVoice();
 if(el.hasAttribute('data-dismiss-voice')){liveCompose.error='';liveCompose.success=false;paintVoiceStatus();return;}
 if(el.hasAttribute('data-record-voice'))return void recordVoice(el.dataset.recordVoice);
 liveCompose.mode=el.dataset.composeMode||'plan';if(el.hasAttribute('data-open-calendar-plan')){state.tab='work';state.screen='root';}
 render();document.getElementById('home-task')?.focus();
},true);
