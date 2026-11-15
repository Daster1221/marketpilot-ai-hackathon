const fs=require('fs'),vm=require('vm'),assert=require('assert');
let handler;const sent=[],card={outerHTML:''};
const context=vm.createContext({
 document:{addEventListener:(_,fn)=>{handler=fn;},querySelector:()=>card},
 state:{screen:'post'},liveFlow:{busy:false,post:null},escapeHTML:v=>String(v??''),
 render(){throw new Error('VK card must not replace post with dashboard');},
 api:async()=>({id:1,rev:4}),
 liveJob:async p=>{sent.push(p);return p.operation==='vk_preview'?{vk_preview:{post_id:1,rev:4,nonce:'human-review',text:'Готовый текст',community_url:'https://vk.ru/club123'}}:{vk_sent:{url:'https://vk.ru/wall-123_77'}};}
});
vm.runInContext(fs.readFileSync(require('path').join(__dirname,'../assets/vk-text.js'),'utf8'),context);
vm.runInContext('vkControls({id:1,vk_available:true})',context);
const event=action=>({target:{closest:()=>({dataset:{vkPost:'1',vkAction:action}})}});
(async()=>{
 await handler(event('preview'));assert(card.outerHTML.includes('Готовый текст'));assert(card.outerHTML.includes('Подтвердить публикацию'));
 assert.equal(sent.length,1);await handler(event('confirm'));
 assert.equal(sent[1].operation,'vk_publish');assert.equal(sent[1].nonce,'human-review');
 assert(!('image' in sent[1]));assert(card.outerHTML.includes('wall-123_77'));
 console.log('VK text preview and explicit confirmation passed');
})().catch(e=>{console.error(e);process.exitCode=1;});
