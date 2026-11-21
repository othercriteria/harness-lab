const {spawn} = require('node:child_process');
const assert = require('node:assert/strict');
const chrome = spawn('/nix/store/vwbfyyhnf2i46qlfibxs4qfaxrkjzwc3-google-chrome-157.0.8103.50/share/google/chrome/chrome', ['--headless','--disable-gpu','--disable-background-networking','--disable-dev-shm-usage','--no-first-run','--user-data-dir=/tmp/profile','--remote-debugging-pipe','about:blank'],{stdio:['ignore','ignore','inherit','pipe','pipe']});
let seq=0, buffer=''; const pending = new Map();
chrome.stdio[4].setEncoding('utf8');
chrome.stdio[4].on('data',chunk=>{
  buffer += chunk; let end;
  while ((end=buffer.indexOf('\0'))>=0) {
    const m=JSON.parse(buffer.slice(0,end)); buffer=buffer.slice(end+1);
    if (m.id && pending.has(m.id)) {
      const {resolve,reject}=pending.get(m.id);pending.delete(m.id);
      m.error?reject(Error(JSON.stringify(m.error))):resolve(m.result);
    }
  }
});
chrome.on('exit',code=>{for(const {reject} of pending.values())reject(Error('Browser exited '+code));});
function rpc(method,params={},sessionId) {
  const id=++seq;
  return new Promise((resolve,reject)=>{pending.set(id,{resolve,reject});chrome.stdio[3].write(JSON.stringify({id,method,params,sessionId})+'\0');});
}
(async()=>{
  const {targetId}=await rpc('Target.createTarget',{url:'about:blank'});
  const {sessionId}=await rpc('Target.attachToTarget',{targetId,flatten:true});
  const call=(m,p)=>rpc(m,p,sessionId);
  async function evaluate(expression) {
    const r=await call('Runtime.evaluate',{expression,returnByValue:true});
    if(r.exceptionDetails)throw Error(JSON.stringify(r.exceptionDetails));
    return r.result.value;
  }
  await call('Page.navigate',{url:'file:///tmp/crossing.html'});
  let ready=false;
  for(let n=0;n<80;n++){if(await evaluate('!!document.getElementById("event-count")?.textContent')){ready=true;break;}await new Promise(r=>setTimeout(r,50));}
  assert.ok(ready);
  async function key(right){
    const key=right?'ArrowRight':'ArrowLeft', vk=right?39:37;
    for(const type of ['rawKeyDown','keyUp'])await call('Input.dispatchKeyEvent',{type,key,code:key,windowsVirtualKeyCode:vk,nativeVirtualKeyCode:vk});
  }
  const state=()=>evaluate(`({event:document.querySelector('#scrub').value,marker:document.querySelector('#marker').textContent,ballots:document.querySelectorAll('#current .ballots span').length,focus:document.activeElement.id||document.activeElement.tagName})`);
  await evaluate("for(let i=0;i<4;i++)document.querySelector('#next').click()");
  const set=async i=>evaluate(`document.querySelector('#scrub').value=${i};document.querySelector('#scrub').dispatchEvent(new Event('input'));document.activeElement.blur()`);
  const focus=async sel=>evaluate(`document.querySelector(${JSON.stringify(sel)}).focus()`);
  const current=async()=>evaluate(`({i:+document.querySelector('#scrub').value,count:document.querySelector('#event-count').textContent,marker:document.querySelector('#marker').textContent,floor:document.querySelector('#floor .piece')?.closest('button')?.title,ballot:document.querySelector('#current').textContent,votes:document.querySelectorAll('#current .ballots span').length,proposed:!!document.querySelector('.tile.proposed'),log:document.querySelectorAll('#log li').length,focus:document.activeElement.id||document.activeElement.tagName,tile:document.activeElement.title?.split(' · ').slice(0,2).join(' · '),turn:document.querySelector('#turn').value,inspect:document.querySelector('#tile').value})`);
  const max=await evaluate("+document.querySelector('#scrub').max");
  const data={}; 
  await set(4);await key(true);data.right=await current();await set(5);await key(false);data.left=await current();
  await set(0);await key(false);await key(false);data.first=await current();await set(max);await key(true);await key(true);data.last=await current();
  for(const id of ['scrub','turn','tile']){
    await set(4);await focus('#'+id);await key(true);data[id]=await current();
  }
  await set(4);await focus('.tile.start');data.tileBefore=await current();await key(true);data.retained=await current();
  await set(2);await focus('.tile:not(.start):not(.exit)');await key(false);data.missing=await current();
  await set(1);await focus('#prev');await key(false);data.disabled=await current();
  data.max=max;data.hint=await evaluate("document.querySelector('.playback').innerText");
  console.log(JSON.stringify(data));
})().catch(e=>{console.error(e);process.exitCode=1;}).finally(()=>chrome.kill());
