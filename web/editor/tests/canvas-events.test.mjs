import test from 'node:test'
import assert from 'node:assert/strict'
import {readFileSync} from 'node:fs'
import ts from 'typescript'

// Execute the actual JSX handlers with a minimal pointer surface. This catches
// accidental removal of the UI pointer guards without duplicating their logic.
const source=readFileSync(new URL('../src/App.tsx',import.meta.url),'utf8')
const ast=ts.createSourceFile('App.tsx',source,ts.ScriptTarget.Latest,true,ts.ScriptKind.TSX)
const callbackNames=['onPointerDown','onPointerMove','onPointerUp','onPointerCancel','onLostPointerCapture']
const callbacks=new Map()
function visit(node){
 if(ts.isJsxAttribute(node)&&callbackNames.includes(node.name.getText(ast))){
  assert.equal(callbacks.has(node.name.getText(ast)),false,'canvas handlers must be unambiguous')
  callbacks.set(node.name.getText(ast),node.initializer.expression.getText(ast))
 }
 ts.forEachChild(node,visit)
}
visit(ast)

function harness(){
 const commands=[],captures=new Set(),state={revision:7}
 const canvas={drag:{current:null},image:{current:{getBoundingClientRect:()=>({left:0,top:0})}},
  view:{zoom:1,x:0,y:0},setDragging(){},setView(){},pick:async()=>null}
 const controller={state,readyForFrameAction:true,action:(...args)=>commands.push(args),operationRejected:message=>assert.fail(message)}
 const names=['canvas','state','controller','spacePan','keyBounds','selected','setKeyOffset','setSelected']
 const values=[canvas,state,controller,{current:false},[0,0,50,50],'/page/graph/key',()=>{},()=>{}]
 const handlers=Object.fromEntries([...callbacks].map(([name,code])=>[name,
  new Function(...names,ts.transpileModule('return ('+code+')',{compilerOptions:{target:ts.ScriptTarget.ES2022}}).outputText)(...values)]))
 const surface={setPointerCapture:id=>captures.add(id),hasPointerCapture:id=>captures.has(id),
  releasePointerCapture:id=>captures.delete(id),focus(){}}
 const event=(pointerId,clientX=10,clientY=10)=>({pointerId,clientX,clientY,button:0,currentTarget:surface,preventDefault(){}})
 return {canvas,commands,captures,handlers,event}
}

test('a second pointer cannot replace or finish the active legend drag',()=>{
 const {canvas,commands,captures,handlers:h,event:e}=harness()
 h.onPointerDown(e(1));h.onPointerDown(e(2,20,20))
 assert.equal(canvas.drag.current.pointer,1)
 assert.deepEqual([...captures],[1])
 h.onPointerMove(e(2,30,30));h.onPointerUp(e(2,100,100))
 assert.equal(canvas.drag.current.pointer,1);assert.deepEqual(commands,[])
 h.onPointerMove(e(1,25,35));h.onPointerUp(e(1,25,35))
 assert.deepEqual(commands,[['move_key',{object_path:'/page/graph/key',dx:15,dy:25}]])
 assert.equal(canvas.drag.current,null)
})

for(const callback of ['onPointerCancel','onLostPointerCapture'])test(`${callback} only cancels its own active pointer`,()=>{
 const {canvas,commands,handlers:h,event:e}=harness()
 h.onPointerDown(e(1));h.onPointerMove(e(1,15,15));h[callback](e(2))
 assert.equal(canvas.drag.current.pointer,1)
 h[callback](e(1));assert.equal(canvas.drag.current,null)
 h.onPointerUp(e(1,100,100));assert.deepEqual(commands,[])
})
