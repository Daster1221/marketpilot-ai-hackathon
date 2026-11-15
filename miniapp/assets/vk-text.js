const vkUI={busy:false,post:null,preview:null,sent:null,error:''};
function vkControls(post){
 if(!post?.vk_available)return '';
 vkUI.details=post;
 const current=vkUI.post===post.id,preview=current?vkUI.preview:null;
 const sent=current&&vkUI.sent||post.vk_delivery?.state==='sent'&&post.vk_delivery;
 return `<section class="schedule-card vk-text-card"><h2>ВКонтакте · только текст</h2><p>Без изображения. Выделения и спойлеры станут обычным текстом. Отправка в Telegram остаётся отдельной.</p>${sent?`<a class="button secondary" href="${escapeHTML(sent.url)}" target="_blank" rel="noopener">Открыть публикацию в ВК</a>`:preview?`<p>${escapeHTML(preview.community_url)}</p><pre class="vk-text-preview">${escapeHTML(preview.text)}</pre><button type="button" class="button primary" data-vk-action="confirm" data-vk-post="${post.id}" ${vkUI.busy?'disabled':''}>${vkUI.busy?'<span class="button-spinner" aria-hidden="true"></span> Отправляю…':'Подтвердить публикацию текста'}</button><button type="button" class="button secondary" data-vk-action="cancel" data-vk-post="${post.id}" ${vkUI.busy?'disabled':''}>Отмена</button>`:`<button type="button" class="button secondary" data-vk-action="preview" data-vk-post="${post.id}" ${vkUI.busy?'disabled':''}>${vkUI.busy?'<span class="button-spinner" aria-hidden="true"></span> Готовлю…':'Предпросмотр для ВК'}</button>`}${current&&vkUI.error?`<p class="live-error" role="alert">${escapeHTML(vkUI.error)}</p>`:''}</section>`;
}
function renderVK(){
 const card=document.querySelector('.vk-text-card');
 if(state.screen==='post'&&card&&vkUI.details){card.outerHTML=vkControls(vkUI.details);return;}
 render();
}
document.addEventListener('click',async e=>{
 const button=e.target.closest('[data-vk-action]');if(!button||vkUI.busy||liveFlow.busy)return;
 const pid=Number(button.dataset.vkPost),action=button.dataset.vkAction;
 if(action==='cancel'){vkUI.preview=null;renderVK();return;}
 vkUI.post=pid;vkUI.error='';vkUI.busy=true;renderVK();
 try{
  if(liveFlow.post?.id===pid&&liveFlow.editorDirty){await saveLiveEdits();if(action==='confirm'){vkUI.preview=null;throw new Error('Текст изменён. Откройте новый предпросмотр перед отправкой.');}}
  if(action==='preview'){
   const post=await api('./posts/'+pid);const result=await liveJob({operation:'vk_preview',post_id:pid,rev:post.rev});vkUI.preview=result.vk_preview;vkUI.sent=null;
  }else if(action==='confirm'&&vkUI.preview?.post_id===pid){
   const result=await liveJob({operation:'vk_publish',post_id:pid,rev:vkUI.preview.rev,nonce:vkUI.preview.nonce});vkUI.sent=result.vk_sent;vkUI.preview=null;
  }
 }catch(error){vkUI.error=error.message;}
 finally{vkUI.busy=false;renderVK();}
});
