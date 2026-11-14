"use strict";
// UI preview only. No recording, AI requests, scheduling or publication.
const designPreview = {step: 0, voice: false, topic: "Нужно сделать пост про предстоящую экскурсию на производство для студентов.", audience: "Для студентов", date: "", accents: ["Производственный процесс"], idea: 0};
const designIdeas = [
  ["Имиджевый", "Показать, как предприятие знакомит молодёжь с современной промышленностью."],
  ["Информационный", "Рассказать, как пройдёт экскурсия и что участники увидят."],
  ["Репортажный", "Сделать акцент на впечатлениях участников после проведения."]
];
function designWave(){return `<span class="voice-wave" aria-hidden="true">${Array.from({length:30},(_,i)=>`<i style="height:${[7,15,11,23,17,28,12,20][i%8]}px"></i>`).join("")}</span><small>0:24</small>`;}
function designVoice(){return `<div class="voice-record"><span class="voice-play" aria-hidden="true">▶</span>${designWave()}</div>`;}
function designBubble(text){return `<div class="agent-line"><span class="agent-mark">${icon("layers")}</span><div class="agent-bubble">${text}</div></div>`;}
function showDesignFlow(){
 const names=["Тема","Уточнения","Идеи","Текст","Готово"],p=designPreview;
 const stepper=`<ol class="flow-steps" aria-label="Этапы создания публикации">${names.map((name,i)=>`<li class="${i<p.step?'complete':i===p.step?'active':''}" ${i===p.step?'aria-current="step"':''}><span>${i<p.step?'✓':i===p.step?'●':''}</span><small>${name}</small></li>`).join("")}</ol>`;
 const audience={"Для студентов":"студентов","Для партнёров":"партнёров","Для сотрудников":"сотрудников","Другая аудитория":"гостей"}[p.audience];
 let content="",action="";
 if(p.step===0){content=`<div class="flow-user">${p.voice ? designVoice() : ""}<div class="transcript"><small>${p.voice ? "Транскрипция · пример" : "Ваша тема"}</small><p>${escapeHTML(p.topic)}</p><time>14:30</time></div></div>${designBubble('Отлично! Я зафиксировал тему публикации. Теперь уточним несколько деталей, чтобы пост получился точным и интересным.')}`;action='Продолжить';}
 if(p.step===1){content=designBubble('Уточните, пожалуйста:')+`<div class="clarification-card"><fieldset><legend>${icon('users')}Для кого экскурсия?</legend>${['Для студентов','Для партнёров','Для сотрудников','Другая аудитория'].map(x=>`<label><input type="radio" name="preview-audience" value="${x}" ${p.audience===x?'checked':''}>${x}</label>`).join('')}</fieldset><fieldset><legend>${icon('calendar')}Когда планируется экскурсия?</legend><input class="flow-date" type="date" aria-label="Дата экскурсии" value="${p.date}" data-preview-date><small class="field-hint">Дату можно уточнить позже</small></fieldset><fieldset><legend>${icon('sparkle')}Что важно показать?</legend>${['Производственный процесс','Современные технологии','Сотрудников предприятия'].map(x=>`<label><input type="checkbox" value="${x}" data-preview-accent ${p.accents.includes(x)?'checked':''}>${x}</label>`).join('')}</fieldset></div>`;action='Далее';}
 if(p.step===2){content=designBubble('На основе информации предлагаю 3 подхода к публикации. Какой выберем?')+`<div class="flow-ideas" role="radiogroup" aria-label="Подход к публикации">${designIdeas.map(([title,copy],i)=>`<button type="button" class="flow-idea ${p.idea===i?'selected':''}" role="radio" aria-checked="${p.idea===i}" data-preview-idea="${i}"><span class="radio-mark"></span><span><strong>${title}</strong><small>${copy}</small></span></button>`).join('')}</div>`;action='Создать черновик';}
 if(p.step===3){content=designBubble('Вот черновик по выбранной идее. Посмотрите и предложите правки, чтобы доработать текст.')+`<article class="draft-preview"><header>${icon('file')}<strong>Черновик публикации</strong><span aria-hidden="true">${icon('file')}</span></header><div class="draft-preview-body" contenteditable="true" role="textbox" aria-label="Текст демонстрационного черновика"><p><strong>Салаватстекло открывает двери для ${audience}!</strong></p><p>Приглашаем на экскурсию по производству, где можно увидеть, как рождается современное стекло, познакомиться с технологиями и узнать о работе предприятия.</p><p>В центре внимания: ${escapeHTML(p.accents.join(', ').toLowerCase()||'знакомство с производством')}. После экскурсии можно будет задать вопросы специалистам.</p></div><footer>Пример текста для демонстрации дизайна</footer></article><div class="flow-secondary"><button class="button secondary" data-preview-action="ideas">${icon('arrow')}Другой вариант</button><button class="button secondary" data-preview-action="clarify">${icon('settings')}Уточнить</button></div>`;action='Согласовать и запланировать';}
 if(p.step===4){content=`<div class="flow-finish"><span class="finish-icon">✓</span><h1>Всё готово!</h1><p>Так будет выглядеть завершение работы над публикацией.</p><small>Это предпросмотр макета. Пост не создан и не запланирован.</small></div>`;action='На главную';}
 return `<section class="design-flow"><header class="flow-head"><button type="button" data-preview-action="back" aria-label="Назад">‹</button><span class="flow-logo">${icon('layers')}</span><span><strong>AI-маркетолог</strong><small>Создание публикации</small></span><span class="flow-kebab" aria-label="Предпросмотр">···</span></header>${stepper}<div class="flow-content">${content}</div><button type="button" class="button primary flow-next" data-preview-action="next">${p.step===3?'✓':''} ${action}<span>${p.step===3?'':'→'}</span></button><form id="design-form" class="flow-composer"><span aria-hidden="true">${icon('clip')}</span><input name="comment" aria-label="Комментарий к макету" placeholder="Напишите сообщение…" maxlength="1200"><button type="submit" aria-label="Отправить комментарий">${icon('send')}</button></form></section>`;
}
document.addEventListener('click',event=>{
 if(!demo)return;
 const button=event.target.closest('[data-preview-action],[data-preview-idea],[data-preview-voice]');if(!button)return;
 event.preventDefault();event.stopImmediatePropagation();
 if(button.hasAttribute('data-preview-voice')){designPreview.voice=!designPreview.voice;render();return;}
 if(button.hasAttribute('data-preview-idea')){designPreview.idea=Number(button.dataset.previewIdea);render();return;}
 const action=button.dataset.previewAction;
 if(action==='home-create'){state.tab='chat';state.screen='root';designPreview.step=0;}
 else if(action==='ideas')designPreview.step=2;
 else if(action==='clarify')designPreview.step=1;
 else if(action==='back'){if(designPreview.step)designPreview.step--;else state.tab='work';}
 else if(action==='next'){if(designPreview.step<4)designPreview.step++;else{state.tab='work';designPreview.step=0;}}
 render();window.scrollTo(0,0);
},true);
document.addEventListener('change',event=>{const el=event.target;if(el.name==='preview-audience')designPreview.audience=el.value;if(el.hasAttribute('data-preview-date'))designPreview.date=el.value;if(el.hasAttribute('data-preview-accent'))designPreview.accents=Array.from(document.querySelectorAll('[data-preview-accent]:checked'),x=>x.value);});
document.addEventListener('submit',event=>{
 if(!demo)return;
 if(!['ai-form','design-form'].includes(event.target.id))return;
 event.preventDefault();event.stopImmediatePropagation();
 const value=(event.target.elements.task||event.target.elements.comment)?.value.trim();
 if(event.target.id==='ai-form'){designPreview.topic=value||designPreview.topic;designPreview.step=0;state.tab='chat';state.screen='root';render();window.scrollTo(0,0);}
 else if(value){event.target.reset();const notice=document.createElement('p');notice.className='preview-comment';notice.textContent='Комментарий в макете: '+value;document.querySelector('.flow-content').append(notice);}
},true);
