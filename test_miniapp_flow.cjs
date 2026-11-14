const assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs');
const stored=new Map(),calls=[];
const context=vm.createContext({
 localStorage:{getItem:k=>stored.get(k)||null,setItem:(k,v)=>stored.set(k,v),removeItem:k=>stored.delete(k)},
 document:{addEventListener(){},getElementById(){return null;}},setInterval(){},setTimeout,
 crypto:{randomUUID:()=> 'request-fixture'},demo:false,liveCompose:{},state:{data:{posts:[]}},render(){},
 api:async(path,options)=>{calls.push([path,options]);
  if(options?.method==='PATCH')return {id:1,rev:2,body:'Ручная правка'};
  if(path==='./workflow')return {job_id:'job-fixture'};
  if(path.startsWith('./jobs/'))return {status:'done',result:{posts:[{id:1,rev:3,body:'Правка ИИ'}]}};
  return {posts:[{id:1,rev:3,body:'Правка ИИ'}]};
 }
});
vm.runInContext(fs.readFileSync('miniapp/assets/live-flow.js','utf8'),context);
(async()=>{
 vm.runInContext("Object.assign(liveFlow,{post:{id:1,rev:1,body:'Старый текст'},editorBody:'Ручная правка',editorDirty:true,instruction:'Сократи'})",context);
 await vm.runInContext("runLiveOperation('rewrite',{post_id:1,rev:1,instruction:'Сократи'})",context);
 assert.equal(calls[0][0],'./posts/1');assert.equal(JSON.parse(calls[0][1].body).body,'Ручная правка');
 assert.equal(JSON.parse(calls[1][1].body).rev,2);
 assert.equal(vm.runInContext('liveFlow.post.rev',context),3);
 // Editing an image first saves the exact locally edited text, with the new revision.
 calls.length=0;
 vm.runInContext("Object.assign(liveFlow,{post:{id:1,rev:1,body:'Старый текст'},editorBody:'Мой новый текст',editorDirty:true,instruction:'Сделай фон светлее',editTarget:'image'})",context);
 await vm.runInContext("runLiveOperation('image',{post_id:1,rev:1,instruction:'Сделай фон светлее'})",context);
 assert.equal(calls[0][0],'./posts/1');assert.equal(JSON.parse(calls[0][1].body).body,'Мой новый текст');
 assert.equal(JSON.parse(calls[1][1].body).operation,'image');assert.equal(JSON.parse(calls[1][1].body).rev,2);
 // Saving failure must retain the local edit and comment, and never call AI.
 vm.runInContext("Object.assign(liveFlow,{editorBody:'Несохранённый текст',editorDirty:true,instruction:'Уточни'})",context);
 calls.length=0;context.api=async(path)=>{calls.push(path);throw new Error('Конфликт версий');};
 await vm.runInContext("runLiveOperation('rewrite',{post_id:1,rev:3,instruction:'Уточни'})",context);
 assert.equal(calls.length,1);assert.equal(vm.runInContext('liveFlow.editorBody',context),'Несохранённый текст');
 assert.equal(vm.runInContext('liveFlow.instruction',context),'Уточни');
 // Lost generation ACK recovers the same server job, never repeats generation.
 calls.length=0;context.api=async(path,options)=>{calls.push(path);
  if(path==='./workflow')throw new Error('Lost reply');
  if(path.startsWith('./job-requests/'))return {job_id:'saved-job'};
  return {status:'done',result:{facts:[],question:'Когда?'}};
 };
 const result=await vm.runInContext("liveJob({operation:'plan',task:'Событие'})",context);
 assert.equal(result.question,'Когда?');assert.equal(calls.filter(p=>p==='./workflow').length,1);assert.equal(stored.size,0);
 console.log('Edit preservation and generation recovery checks passed.');
})().catch(error=>{console.error(error);process.exitCode=1;});
