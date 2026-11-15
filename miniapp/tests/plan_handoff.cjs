const fs=require('fs'),vm=require('vm'),assert=require('assert');
const handlers={},captured=[];let finish;
const context=vm.createContext({
 sessionStorage:{getItem:()=>null,setItem(){},removeItem(){}},
 document:{addEventListener:(type,fn)=>(handlers[type]??=[]).push(fn),getElementById:()=>({focus(){}})},
 demo:false,escapeHTML:v=>String(v??''),heading:()=>'',safePostHTML:v=>v,
 state:{screen:'marketer',tab:'work'},liveFlow:{},render(){},
 liveJob:payload=>{captured.push(payload);return new Promise(resolve=>{finish=resolve;});},
 acceptLiveResult:r=>{context.liveFlow.received=r;},Intl
});
vm.runInContext(fs.readFileSync(require('path').join(__dirname,'../assets/marketer.js'),'utf8'),context);
vm.runInContext(`marketerUI.loaded=true;marketerUI.plan_nonce='saved-nonce';marketerUI.plan=[{topic:'Матч',angle:'Приглашение'}]`,context);
(async()=>{
 const pending=handlers.click[0]({target:{closest:s=>s==='[data-marketer-topic]'?{dataset:{marketerTopic:'0'}}:null}});
 assert.equal(captured[0].operation,'plan_topic');assert.equal(captured[0].plan_nonce,'saved-nonce');assert.equal(captured[0].topic_index,0);
 const busyHTML=vm.runInContext('showMarketer()',context);
 assert(busyHTML.includes('button-spinner'));assert(busyHTML.includes('Готовлю тему'));
 finish({workflow_id:'existing-facts',task:'Матч',facts:[{label:'Дата',value:'20 ноября'}],ideas:[]});await pending;
 assert.equal(context.liveFlow.workflow,'existing-facts');assert.equal(context.liveFlow.received.facts[0].value,'20 ноября');
 assert.equal(vm.runInContext('marketerUI.busy',context),false);assert.equal(context.state.tab,'chat');
 console.log('Plan handoff and in-button loading passed');
})().catch(e=>{console.error(e);process.exitCode=1;});
