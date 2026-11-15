const usersUI={loaded:false,loading:false,busy:false,users:[],error:'',notice:'',id:''};
async function loadUsers(){
 if(usersUI.loading||demo)return;usersUI.loading=true;
 try{const data=await api('./users');usersUI.users=data.users;usersUI.loaded=true;}
 catch(e){usersUI.error=e.message;}
 finally{usersUI.loading=false;if(state.screen==='users')render();}
}
function showUsers(){
 if(demo&&!usersUI.loaded){usersUI.loaded=true;usersUI.users=[{id:123456789,name:'Администратор',username:'demo_admin',admin:true,removable:false},{id:234567890,name:'Участник команды',username:'demo_editor',admin:false,removable:true}];}
 if(!state.data.profile.can_manage_users)return heading('Пользователи',{back:true})+'<p>Управление доступом доступно владельцу.</p>';
 if(!usersUI.loaded&&!usersUI.loading&&!usersUI.error)loadUsers();
 const u=usersUI;
 return heading('Доступ к боту',{back:true})+`<p class="muted">Доступ действует в Telegram-боте и мини-аппе. Приглашённые пользователи не могут выдавать доступ другим.</p>
 <form id="user-add-form" class="panel access-add"><label>Telegram ID<input id="access-user-id" name="user_id" inputmode="numeric" pattern="[0-9]+" maxlength="16" placeholder="Например, 123456789" value="${escapeHTML(u.id)}" required ${u.busy||demo?'disabled':''}></label><button type="submit" class="button primary" ${u.busy||demo?'disabled':''}>${u.busy?'Сохраняю…':'Добавить пользователя'}</button><small>Узнать свой ID можно у @userinfobot. После добавления нужно открыть нашего бота и нажать «Начать». Ник появится из данных Telegram.</small></form>
 ${u.error?`<p class="live-error" role="alert">${escapeHTML(u.error)}</p>`:''}${u.notice?`<p class="access-notice" role="status">${escapeHTML(u.notice)}</p>`:''}
 <h2 class="access-title">Пользователи${u.loaded?' · '+u.users.length:''}</h2>${u.loading?'<p role="status">Загружаю список…</p>':''}<div class="panel">${u.users.map(x=>`<div class="row access-user"><span class="access-avatar" aria-hidden="true">${escapeHTML((x.name||x.username||'?').slice(0,1).toUpperCase())}</span><span class="row-copy"><strong>${escapeHTML(x.name||x.username&&'@'+x.username||'Пользователь '+x.id)}</strong><small>${x.username?'@'+escapeHTML(x.username)+' · ':''}ID ${x.id}</small><small>${x.admin?'Владелец':x.removable?'Доступ разрешён':'Постоянный доступ'}</small></span>${x.removable?`<button type="button" class="access-remove" data-access-remove="${x.id}" ${u.busy||demo?'disabled':''}>Убрать</button>`:''}</div>`).join('')}</div>`;
}
document.addEventListener('input',e=>{if(e.target.id==='access-user-id')usersUI.id=e.target.value;});
async function changeUser(action,id){
 if(usersUI.busy||demo)return;usersUI.busy=true;usersUI.error='';usersUI.notice='';render();
 try{const result=await api('./users',{method:'POST',body:JSON.stringify({action,user_id:id})});usersUI.users=result.users;usersUI.loaded=true;usersUI.notice=action==='remove'?'Доступ отозван.':'Пользователь добавлен. Можно открыть бота.';if(action!=='remove')usersUI.id='';}
 catch(e){usersUI.error=e.message;}
 finally{usersUI.busy=false;render();}
}
document.addEventListener('submit',e=>{if(e.target.id==='user-add-form'){e.preventDefault();void changeUser('add',usersUI.id);}});
document.addEventListener('click',e=>{
 const open=e.target.closest('[data-section="users"]');if(open){usersUI.loaded=false;usersUI.error='';return;}
 const remove=e.target.closest('[data-access-remove]');if(remove)void changeUser('remove',remove.dataset.accessRemove);
});
