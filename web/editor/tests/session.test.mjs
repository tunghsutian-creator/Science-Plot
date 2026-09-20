import test from 'node:test'
import assert from 'node:assert/strict'
import {SessionController,parseField,shortcutAction,treeTabStop} from '../src/session.ts'
const key='/page/graph/curve/PlotLine/color'
const objectPath='/page/graph/curve'
const field=(value='black')=>({setting_path:key,editor:'color',current_value:value,label:'Color'})
const state=(revision=1,value='black',extra={})=>({session_id:'native-1',revision,document_sha256:'abc',figure_id:'f1',objects:{[objectPath]:{type:'xy',name:'curve',fields:[field(value)]}},preview:{url:`/api/preview?revision=${revision}`,width:600,height:550,sha256:String(revision)},can_undo:revision>1,can_redo:false,dirty:revision>1,...extra})
const response=(payload,ok=true)=>({ok,status:ok?200:409,json:async()=>payload})
const deferred=()=>{let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b});return {promise,resolve,reject}}
const pause=()=>new Promise(resolve=>setImmediate(resolve))
function setup(handler,initial=state()){
 const requests=[]
 const controller=new SessionController('proof-token',async(url,options)=>{
  if(url==='/api/state')return response(initial)
  const body=JSON.parse(options.body);requests.push(body)
  assert.equal(options.headers['X-SciPlot-Token'],'proof-token')
  return handler(body,requests.length)
 },100000)
 return {controller,requests}
}
test('edits serialize; inflight response preserves newer draft and next expected value',async()=>{
 const first=deferred(),second=deferred()
 const {controller:c,requests}=setup((_,n)=>n===1?first.promise:second.promise)
 await c.load();c.setDraft(objectPath,field(),'red');const work=c.flush()
 c.setDraft(objectPath,field(),'blue');c.setDraft(objectPath,field(),'green')
 assert.equal(requests.length,1)
 first.resolve(response({state:state(2,'red')}));await pause()
 assert.equal(requests.length,2);assert.equal(c.snapshot().drafts.get(key).text,'green')
 assert.equal(requests[1].revision,2)
 assert.deepEqual(requests[1].changes,[{object_path:objectPath,setting_path:key,expected_value:'red',value:'green'}])
 second.resolve(response({state:state(3,'green')}));await work
 assert.equal(c.state.revision,3);assert.equal(c.drafts.size,0);assert.equal(c.state.objects[objectPath].fields[0].current_value,'green');c.dispose()
})
test('returning to baseline during inflight edit queues a real revert',async()=>{
 const first=deferred()
 const {controller:c,requests}=setup((_,n)=>n===1?first.promise:response({state:state(3,'black')}))
 await c.load();c.setDraft(objectPath,field(),'red');const work=c.flush();c.setDraft(objectPath,field(),'black')
 first.resolve(response({state:state(2,'red')}));await work
 assert.equal(requests.length,2);assert.equal(requests[1].changes[0].value,'black');assert.equal(requests[1].changes[0].expected_value,'red');c.dispose()
})
test('invalid input is retained without a request; correcting it applies',async()=>{
 const numberField={setting_path:key,editor:'number',current_value:3,minimum:0,label:'Size'}
 const initial=state();initial.objects[objectPath].fields=[numberField]
 const {controller:c,requests}=setup(()=>response({state:state(2,4)}),initial)
 await c.load();c.setDraft(objectPath,numberField,'-');await c.flush()
 assert.equal(requests.length,0);assert.equal(c.snapshot().drafts.get(key).text,'-');assert.equal(c.snapshot().drafts.get(key).valid,false)
 c.setDraft(objectPath,numberField,'4');await c.flush();assert.equal(requests.length,1);assert.equal(requests[0].changes[0].value,4);c.dispose()
})
test('failed native mutation preserves draft, pauses automatic sends and can recover',async()=>{
 const {controller:c,requests}=setup((_,n)=>n===1?response({error:{code:'invalid',message:'bad native color'},state:state(1)},false):response({state:state(2,'blue')}))
 await c.load();c.setDraft(objectPath,field(),'bad-color');await c.flush()
 assert.equal(c.paused,true);assert.equal(c.error,'bad native color');assert.equal(c.drafts.get(key).text,'bad-color')
 c.setDraft(objectPath,field(),'blue');await c.flush();assert.equal(requests.length,1)
 await c.retry();assert.equal(requests.length,2);assert.equal(c.paused,false);assert.equal(c.drafts.size,0);assert.equal(c.error,null);c.dispose()
})
test('network-lost response retries from current native state without applying twice',async()=>{
 let current=state(),commands=0
 const c=new SessionController('token',async(url)=>{
  if(url==='/api/state')return response(current)
  commands++;current=state(2,'red');throw new Error('connection lost after apply')
 },100000)
 await c.load();c.setDraft(objectPath,field(),'red');await c.flush()
 assert.equal(c.paused,true);await c.retry()
 assert.equal(commands,1);assert.equal(c.state.revision,2);assert.equal(c.drafts.size,0);assert.equal(c.paused,false);c.dispose()
})
test('newer current state is not overwritten by an older response',async()=>{
 let reads=0
 const c=new SessionController('token',async()=>response(++reads===1?state(5,'green'):state(2,'red')))
 await c.load();await c.load();assert.equal(c.state.revision,5);assert.equal(c.state.objects[objectPath].fields[0].current_value,'green');c.dispose()
})
test('frame-bound actions require current image load, no pending drafts and matching revision',async()=>{
 const {controller:c,requests}=setup(body=>response({state:state(body.revision+1,'red'),selected_object_path:objectPath}))
 await c.load();assert.equal(await c.action('hit',{x:2,y:3}),false)
 c.markFrame(1);assert.equal(await c.action('hit',{x:2,y:3}),true);assert.equal(requests[0].preview_revision,1)
 assert.equal(await c.action('save'),false);c.markFrame(1);assert.equal(c.readyForFrameAction,false)
 c.markFrame(2);c.setDraft(objectPath,field('red'),'blue');assert.equal(await c.action('save'),false);c.discardDrafts();assert.equal(c.readyForFrameAction,true);c.dispose()
})
test('native undo and redo use current state revision; history is not simulated locally',async()=>{
 const initial=state(4,'green',{can_undo:true})
 const {controller:c,requests}=setup(body=>response({state:body.action==='undo'?state(5,'red',{can_redo:true}):state(6,'green')}),initial)
 await c.load();await c.action('undo');await c.action('redo')
 assert.deepEqual(requests.map(r=>[r.action,r.revision]),[['undo',4],['redo',5]]);assert.equal(c.state.objects[objectPath].fields[0].current_value,'green');c.dispose()
})
test('browser reload and another controller never reuse command request IDs',async()=>{
 const ids=[]
 for(let i=0;i<2;i++){
  const {controller:c}=setup(body=>{ids.push(body.request_id);return response({state:state(2,'red')})})
  await c.load();c.setDraft(objectPath,field(),'red');await c.flush();c.dispose()
 }
 assert.notEqual(ids[0],ids[1]);assert.ok(ids.every(id=>id.length>30))
})
test('failed reload retains local drafts; successful confirmed reload discards them',async()=>{
 const {controller:c}=setup((_,n)=>n===1?response({error:{message:'cannot reload'},state:state()},false):response({state:state(2)}))
 await c.load();c.setDraft(objectPath,field(),'red');assert.equal(await c.action('reload'),false);assert.equal(c.drafts.size,1)
 assert.equal(await c.action('reload'),true);assert.equal(c.drafts.size,0);assert.equal(c.paused,false);c.dispose()
})
test('input undo belongs to the browser; document undo and save have precise shortcuts',()=>{
 for(const target of [{tagName:'INPUT',type:'text'},{tagName:'TEXTAREA'},{tagName:'SELECT'},{isContentEditable:true}]){
  assert.equal(shortcutAction({key:'z',metaKey:true,target}),null)
  assert.equal(shortcutAction({key:'Z',ctrlKey:true,shiftKey:true,target}),null)
  assert.equal(shortcutAction({key:'s',metaKey:true,target}),'save')
 }
 assert.equal(shortcutAction({key:'z',metaKey:true,target:{tagName:'DIV'}}),'undo')
 assert.equal(shortcutAction({key:'Z',ctrlKey:true,shiftKey:true}),'redo')
 assert.equal(shortcutAction({key:'z',metaKey:true,altKey:true}),null)
})
test('capability parsers preserve native units and reject invalid semantic inputs',()=>{
 assert.deepEqual(parseField({...field(),editor:'distance'},'0.3mm'),{valid:true,value:'0.3mm'})
 assert.equal(parseField({...field(),editor:'distance'},'8').valid,false)
 assert.equal(parseField({...field(),editor:'distance'},'-1pt').valid,false)
 assert.deepEqual(parseField({...field(),editor:'float_list'},'0, 10, 20'),{valid:true,value:[0,10,20]})
 assert.equal(parseField({...field(),editor:'float_list'},'20, 10').valid,false)
 assert.deepEqual(parseField({...field(),editor:'number_or_auto'},'Auto'),{valid:true,value:'Auto'})
 assert.equal(parseField({...field(),editor:'number'},'Infinity').valid,false)
 assert.equal(parseField({...field(),editor:'choice',choices:['solid','dashed']},'other').valid,false)
})
test('manual tick input never invents zero or drops a missing comma-separated value',()=>{
 const ticks={...field(),editor:'float_list'}
 for(const text of [', 1, 2','， 1 2','1,,2','1, ， 2','1, 2,','1, 2，']){
  assert.equal(parseField(ticks,text).valid,false,text)
 }
 for(const [text,value] of [['',[ ]],['   ',[]],['0 1 2',[0,1,2]],['0, 1，2',[0,1,2]],['[0, 1, 2]',[0,1,2]]]){
  assert.deepEqual(parseField(ticks,text),{valid:true,value},text)
 }
})
test('filtered and collapsed object trees retain a visible keyboard entry',()=>{
 const curve='/page/graph/curve',axis='/page/graph/axis',graph='/page/graph'
 assert.equal(treeTabStop([graph,curve,axis],curve),curve)
 assert.equal(treeTabStop([axis],curve),axis)
 assert.equal(treeTabStop(['/page',graph],curve),'/page')
 assert.equal(treeTabStop([],curve),undefined)
})
test('replacement native session preserves drafts and invalidates loaded frame',async()=>{
 let reads=0
 const c=new SessionController('token',async()=>response(++reads===1?state():state(1,'black',{session_id:'native-2'})),100000)
 await c.load();c.markFrame(1);c.setDraft(objectPath,field(),'red');await c.load()
 assert.equal(c.paused,true);assert.equal(c.drafts.get(key).text,'red');assert.equal(c.frameRevision,null);assert.equal(c.readyForFrameAction,false);c.dispose()
})
test('native selection does not strand edits typed while hit testing is in flight',async()=>{
 const hit=deferred()
 const {controller:c,requests}=setup((body)=>body.action==='hit'?hit.promise:response({state:state(2,'red')}))
 await c.load();c.markFrame(1);const picking=c.action('hit',{x:1,y:1})
 c.setDraft(objectPath,field(),'red');await c.flush();assert.equal(requests.length,1)
 hit.resolve(response({state:state()}));await picking;await pause()
 assert.equal(requests.length,2);assert.equal(requests[1].action,'set');assert.equal(c.drafts.size,0);c.dispose()
})
test('default browser transport binds native fetch to its global receiver',async()=>{
 const original=globalThis.fetch
 globalThis.fetch=async function(){assert.equal(this,globalThis);return response(state())}
 try{const c=new SessionController('token');await c.load();assert.equal(c.error,null);assert.equal(c.state.revision,1);c.dispose()}
 finally{globalThis.fetch=original}
})
test('legend drag is bound to the loaded native frame and sends PNG-space offsets',async()=>{
 const {controller:c,requests}=setup(()=>response({state:state(2)}))
 await c.load();assert.equal(await c.action('move_key',{object_path:'/page/graph/key',dx:20,dy:10}),false)
 c.markFrame(1);assert.equal(await c.action('move_key',{object_path:'/page/graph/key',dx:20,dy:10}),true)
 assert.deepEqual([requests[0].action,requests[0].preview_revision,requests[0].dx,requests[0].dy],['move_key',1,20,10]);c.dispose()
})
test('a retained old preview cannot select, move, save or export a newer native state',async()=>{
 const {controller:c,requests}=setup(()=>response({state:state(2,'red')}))
 await c.load();c.markFrame(1);c.setDraft(objectPath,field(),'red');await c.flush()
 assert.equal(c.frameRevision,1);assert.equal(c.state.revision,2)
 c.markFrame(1)
 for(const action of ['hit','move_key','save','export'])assert.equal(await c.action(action,{x:2,y:3,object_path:'/key',dx:1,dy:1}),false)
 assert.equal(requests.length,1);c.markFrame(2);assert.equal(c.readyForFrameAction,true);c.dispose()
})
test('reconnection retries the same preview URL with a fresh image identity',async()=>{
 const {previewFrameKey,previewFrames}=await import('../src/preview.ts')
 const {controller:c}=setup(()=>response({state:state()}))
 await c.load();c.markFrame(1)
 const loaded={state:c.state,nonce:c.previewNonce},firstKey=previewFrameKey(loaded)
 c.frameFailed(1);await c.load()
 const retry={state:c.state,nonce:c.previewNonce}
 assert.equal(retry.state.preview.url,loaded.state.preview.url)
 assert.notEqual(previewFrameKey(retry),firstKey)
 assert.equal(c.readyForFrameAction,false)
 const waiting=previewFrames(retry,loaded)
 assert.equal(waiting.length,2);assert.equal(waiting[0],loaded)
 assert.equal(previewFrameKey(waiting[0]),firstKey)
 c.markFrame(1);assert.equal(c.readyForFrameAction,true)
 assert.deepEqual(previewFrames(retry,retry),[retry]);c.dispose()
})
test('publish accepts a saved figure and retains saved state when export fails before a safe retry',async()=>{
 const {controller:c,requests}=setup((body,n)=>n===1?response({state:state(2,'red',{dirty:false}),error:{message:'PDF export failed'}},false):response({state:state(3,'red',{dirty:false}),result:{message:'Delivery updated'}}),state(1,'red',{dirty:true}))
 await c.load();c.markFrame(1)
 assert.equal(await c.action('publish'),false)
 assert.equal(c.state.dirty,false);assert.match(c.result,/已保存/);assert.equal(c.error,'PDF export failed')
 assert.equal(await c.action('publish'),false,'new saved state must load its own frame before retry')
 c.markFrame(2);assert.equal(await c.action('publish'),true)
 assert.deepEqual(requests.map(r=>r.action),['publish','publish']);assert.equal(c.result,'Delivery updated');c.dispose()
})
test('switch never drops dirty changes or invalid drafts without an explicit discard',async()=>{
 const {controller:c,requests}=setup(()=>response({state:state(2,'black',{figure_id:'f2',session_id:'native-2',dirty:false})}),state(1,'red',{dirty:true}))
 await c.load();c.markFrame(1)
 assert.equal(await c.switchFigure('f2'),false)
 c.setDraft(objectPath,{...field(),editor:'distance'},'-')
 assert.equal(await c.switchFigure('f2','save'),false);assert.equal(requests.length,0)
 assert.equal(await c.switchFigure('f2','discard'),true)
 assert.equal(requests[0].discard,true);assert.equal(c.state.figure_id,'f2');assert.equal(c.drafts.size,0);assert.equal(c.paused,false);assert.equal(c.frameRevision,null);c.dispose()
})
test('save then switch serializes revisions and stops if saving fails',async()=>{
 const {controller:c,requests}=setup(body=>body.action==='save'?response({state:state(2,'red',{dirty:false})}):response({state:state(3,'black',{figure_id:'f2',session_id:'native-2',dirty:false})}),state(1,'red',{dirty:true}))
 await c.load();c.markFrame(1);assert.equal(await c.switchFigure('f2','save'),true)
 assert.deepEqual(requests.map(r=>[r.action,r.revision]),[['save',1],['switch',2]])
 assert.equal(requests[1].discard,undefined);assert.equal(c.frameRevision,null);c.dispose()
 const failed=setup(()=>response({state:state(1,'red',{dirty:true}),error:{message:'Cannot save'}},false),state(1,'red',{dirty:true}))
 await failed.controller.load();failed.controller.markFrame(1)
 assert.equal(await failed.controller.switchFigure('f2','save'),false);assert.equal(failed.requests.length,1);assert.equal(failed.controller.state.figure_id,'f1');failed.controller.dispose()
})
test('failed discard and switch preserves the old figure and every draft',async()=>{
 const {controller:c,requests}=setup(()=>response({state:state(),error:{message:'Cannot open figure'}},false))
 await c.load();c.setDraft(objectPath,field(),'blue')
 assert.equal(await c.switchFigure('f2','discard'),false)
 assert.equal(c.state.figure_id,'f1');assert.equal(c.drafts.get(key).text,'blue');assert.equal(c.paused,true)
 await c.flush();assert.equal(requests.length,1);c.dispose()
})
test('ambiguous switch response cannot replay old drafts into a different figure',async()=>{
 let current=state(),commands=0
 const c=new SessionController('token',async(url)=>{
  if(url==='/api/state')return response(current)
  commands++;current=state(2,'black',{figure_id:'f2',session_id:'native-2',dirty:false});throw new Error('connection lost after switch')
 },100000)
 await c.load();c.setDraft(objectPath,field(),'blue');await c.switchFigure('f2','discard')
 await c.retry();assert.equal(commands,1);assert.equal(c.state.figure_id,'f2');assert.equal(c.drafts.get(key).text,'blue');assert.equal(c.paused,true);assert.match(c.error,/旧输入不会应用/)
 c.setDraft(objectPath,field(),'red');assert.equal(c.drafts.get(key).text,'blue')
 c.discardDrafts();assert.equal(c.paused,false);assert.equal(c.drafts.size,0);c.dispose()
})
test('switching figures never shows a previous figure as the pending current preview',async()=>{
 const {previewFrames}=await import('../src/preview.ts')
 const loaded={state:state(),nonce:1}
 const differentSession={state:state(2,'black',{session_id:'native-2',figure_id:'f2'}),nonce:1}
 const differentFigure={state:state(2,'black',{figure_id:'f2'}),nonce:1}
 assert.deepEqual(previewFrames(differentSession,loaded),[differentSession])
 assert.deepEqual(previewFrames(differentFigure,loaded),[differentFigure])
 const sameFigure={state:state(2,'red'),nonce:1}
 assert.deepEqual(previewFrames(sameFigure,loaded),[loaded,sameFigure])
})
