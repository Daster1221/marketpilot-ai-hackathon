// Regression checks for binary audio transport and visible asynchronous states.
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const status={hidden:true,innerHTML:'',setAttribute(){}};
const field={value:'Исходная задача',maxLength:6000,dispatchEvent(){}};
let finishUpload,finishRecognition,request;
const stored=new Map();
const context=vm.createContext({
 localStorage:{getItem:key=>stored.get(key)||null,setItem:(key,value)=>stored.set(key,value),removeItem:key=>stored.delete(key)},
 document:{getElementById:()=>status,querySelector:()=>field,querySelectorAll:()=>[],addEventListener(){}},
 window:{location:{href:'https://example.test/?version=13'}},
 escapeHTML:x=>x,liveFlow:{busy:false,post:null},initData:'fake-init',
 crypto:{randomUUID:()=> 'fixture-request'},URL,Blob,Event,setTimeout,clearTimeout,
 fetch:async(url,options)=>{request={url,options};return await new Promise(r=>finishUpload=r);},
 api:async()=>await new Promise(r=>finishRecognition=r)
});
vm.runInContext(fs.readFileSync('miniapp/assets/voice-composer.js','utf8'),context);
(async()=>{
 const done=vm.runInContext("uploadVoice(new Blob(['audio'],{type:'audio/mp4; codecs=mp4a.40.2'}),'task')",context);
 await new Promise(setImmediate);
 assert.match(status.innerHTML,/Отправляю запись/);assert.match(status.innerHTML,/voice-bars/);
 assert.equal(request.url,'https://example.test/transcribe');
 assert.equal(request.options.headers['Content-Type'],'audio/mp4');
 assert.equal(Object.prototype.toString.call(request.options.body),'[object ArrayBuffer]');
 finishUpload({ok:true,json:async()=>({job_id:'fixture-job'})});
 await new Promise(setImmediate);
 assert.match(status.innerHTML,/Распознаю голос/);assert.equal(status.hidden,false);
 finishRecognition({status:'done',result:{transcript:'За месяц'}});
 await done;
 assert.equal(field.value,'Исходная задача\nЗа месяц');
 assert.match(status.innerHTML,/Голос распознан/);
 assert.equal(vm.runInContext('liveCompose.processing',context),false);
 assert.match(vm.runInContext("voiceError({name:'SyntaxError',message:'The string did not match the expected pattern.'})",context),/Попробуйте снова/);
 // The upload reached the server, but Safari did not receive its JSON ACK.
 // Recover by request key and never send the audio a second time.
 let uploads=0;
 context.fetch=async()=>{uploads++;throw new SyntaxError('The string did not match the expected pattern.');};
 context.api=async path=>path.startsWith('./job-requests/')?{job_id:'saved-job'}:{status:'done',result:{transcript:'Восстановленный текст'}};
 await vm.runInContext("uploadVoice(new Blob(['audio'],{type:'audio/mp4'}),'task')",context);
 assert.equal(uploads,1);assert.match(field.value,/Восстановленный текст$/);
 assert.equal(stored.size,0);assert.match(status.innerHTML,/Голос распознан/);
 context.api=async()=>({transcript:'Предыдущая запись'});
 await vm.runInContext('recoverVoice()',context);
 assert.match(field.value,/Предыдущая запись$/);
 console.log('Voice UI and Safari transport regression checks passed.');
})().catch(error=>{console.error(error);process.exitCode=1;});
