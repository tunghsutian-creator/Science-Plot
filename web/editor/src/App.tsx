import {useEffect,useRef,useState,useSyncExternalStore,type KeyboardEvent as ReactKeyboardEvent} from 'react'
import {SessionController,displayValue,shortcutAction,treeTabStop,type Field,type Snapshot} from './session'
import {TextInput,ColorField} from './vendor/tavotto/Input'
import {Badge} from './vendor/tavotto/Badge'
import {treeIndent} from './vendor/tavotto/tree'
import {previewFrameKey as frameKey,previewFrames,type PreviewFrame} from './preview'
const token=document.querySelector<HTMLMetaElement>('meta[name="sciplot-token"]')?.content??''
export const controller=new SessionController(token)
const shortPath=(path:string)=>path.split('/').filter(Boolean).at(-1)||'文档'
const typeNames:Record<string,string>={document:'文档',page:'页面',graph:'绘图区',xy:'曲线',axis:'坐标轴',label:'标注',key:'图例',colorbar:'色标',image:'图像',contour:'等高线',boxplot:'箱线图'}
const supportedEditors=new Set(['color','distance','number','integer','number_or_auto','choice','enum','bool','boolean','float_list','text','string'])
function colorHex(value:string){
 if(/^#[\da-f]{6}$/i.test(value))return value
 const canvas=document.createElement('canvas');const context=canvas.getContext('2d')
 if(!context)return '#000000'
 context.fillStyle=value
 const color=context.fillStyle
 return /^#[\da-f]{6}$/i.test(color)?color:'#000000'
}
function errorText(snapshot:Snapshot){
 if(snapshot.state?.session_error)return snapshot.state.session_error
 if(snapshot.error)return snapshot.error
 if(snapshot.state?.stale)return '保存图、项目或源数据已在其他地方变化。请重新载入后继续编辑。'
 const invalid=[...snapshot.drafts.values()].find(d=>!d.valid)
 return invalid?.error??null
}
function useCanvas(snapshot:Snapshot){
 const box=useRef<HTMLDivElement>(null), image=useRef<HTMLImageElement>(null)
 const [view,setView]=useState({zoom:1,x:0,y:0,fit:true})
 const [dragging,setDragging]=useState(false)
 const drag=useRef<{x:number;y:number;startX:number;startY:number;moved:boolean;pointer:number;mode:'pan'|'key';objectPath?:string;revision:number;scale:number}|null>(null)
 const state=snapshot.state
 const fit=()=>{
  if(!box.current||!state)return
  const zoom=Math.max(.01,Math.min((box.current.clientWidth-56)/state.preview.width,(box.current.clientHeight-56)/state.preview.height,2))
  setView({zoom,x:0,y:0,fit:true})
 }
 const zoom=(factor:number)=>setView(v=>({...v,zoom:Math.max(.025,Math.min(8,v.zoom*factor)),fit:false}))
 useEffect(()=>{if(view.fit)fit()},[state?.preview.width,state?.preview.height])
 useEffect(()=>{const node=box.current;if(!node)return;const observer=new ResizeObserver(()=>{if(view.fit)fit()});observer.observe(node);return()=>observer.disconnect()},[state?.preview.width,state?.preview.height,view.fit])
 const pick=async(clientX:number,clientY:number)=>{
  if(!image.current||!state||!controller.readyForFrameAction)return null
  const rect=image.current.getBoundingClientRect()
  if(clientX<rect.left||clientX>rect.right||clientY<rect.top||clientY>rect.bottom)return null
  const x=(clientX-rect.left)*state.preview.width/rect.width,y=(clientY-rect.top)*state.preview.height/rect.height
  const success=await controller.action('hit',{x,y})
  return success?controller.state?.selected_object_path??null:null
 }
 return {box,image,view,drag,dragging,setDragging,setView,fit,zoom,pick}
}
export function App(){
 const snapshot=useSyncExternalStore(controller.subscribe,controller.snapshot)
 const {state,drafts,busy,result,frameRevision}=snapshot
 const [selected,setSelected]=useState('')
 const [loadedFrame,setLoadedFrame]=useState<PreviewFrame|null>(null)
 const [query,setQuery]=useState('')
 const [collapsed,setCollapsed]=useState(new Set<string>())
 const [leftOpen,setLeftOpen]=useState(()=>window.innerWidth>530),[rightOpen,setRightOpen]=useState(()=>window.innerWidth>800)
 const [confirmReload,setConfirmReload]=useState(false),[showAbout,setShowAbout]=useState(false)
 const reloadDialog=useRef<HTMLDialogElement>(null),aboutDialog=useRef<HTMLDialogElement>(null)
 const propertyScroll=useRef<HTMLDivElement>(null)
 const canvas=useCanvas(snapshot)
 const spacePan=useRef(false)
 const [keyOffset,setKeyOffset]=useState({x:0,y:0})
 const error=errorText(snapshot)
 const frameReady=!!state&&frameRevision===state.revision
 const currentFrame=state?{state,nonce:snapshot.previewNonce}:null
 const frames=previewFrames(currentFrame,loadedFrame)
 const cleanQueue=!busy&&!drafts.size&&!snapshot.paused&&!state?.stale
 const mutateReady=!!state&&cleanQueue&&frameReady
 const objects=state?.objects??{}
 const paths=Object.keys(objects)
 useEffect(()=>{void controller.load()},[])
 useEffect(()=>{if(propertyScroll.current)propertyScroll.current.scrollTop=0},[selected,state?.session_id])
 useEffect(()=>{
  if(selected&&objects[selected])return
  const initial=state?.selected_object_path
  setSelected(initial&&objects[initial]?initial:paths.find(p=>(objects[p].fields??[]).length)||paths[0]||'')
 },[state?.session_id,state?.revision])
 useEffect(()=>{
  const onKey=(event:globalThis.KeyboardEvent)=>{
   if(reloadDialog.current?.open||aboutDialog.current?.open)return
   const action=shortcutAction(event)
   if(!action)return
   event.preventDefault()
   void controller.action(action)
  }
  window.addEventListener('keydown',onKey)
  return()=>window.removeEventListener('keydown',onKey)
 },[])
 useEffect(()=>{if(confirmReload)reloadDialog.current?.showModal();else reloadDialog.current?.close()},[confirmReload])
 useEffect(()=>{if(showAbout)aboutDialog.current?.showModal();else aboutDialog.current?.close()},[showAbout])
 useEffect(()=>{const handler=(e:BeforeUnloadEvent)=>{if(controller.state?.dirty||controller.hasDrafts){e.preventDefault();e.returnValue=''}};window.addEventListener('beforeunload',handler);return()=>window.removeEventListener('beforeunload',handler)},[])
 const selectedObject=objects[selected]
 const keyBounds=selectedObject?.drag_handle?.kind==='key'?selectedObject.drag_handle.bounds:null
 const visible=paths.filter(path=>{
  if(query.trim())return `${path} ${objects[path].name} ${objects[path].label??objects[path].sample??''} ${typeNames[objects[path].type]??''}`.toLowerCase().includes(query.trim().toLowerCase())
  return ![...collapsed].some(parent=>path!==parent&&path.startsWith(parent+'/'))
 })
 const hasChildren=(path:string)=>paths.some(p=>p!==path&&p.startsWith(path+'/'))
 const tabStop=treeTabStop(visible,selected)
 const toggle=(path:string)=>setCollapsed(prev=>{const next=new Set(prev);next.has(path)?next.delete(path):next.add(path);return next})
 const treeKey=(event:ReactKeyboardEvent,path:string)=>{
  const at=visible.indexOf(path);let target:string|undefined
  if(event.key==='Enter'||event.key===' '){if(event.target===event.currentTarget){event.preventDefault();setSelected(path)}return}
  if(event.key==='ArrowDown')target=visible[Math.min(visible.length-1,at+1)]
  else if(event.key==='ArrowUp')target=visible[Math.max(0,at-1)]
  else if(event.key==='Home')target=visible[0]
  else if(event.key==='End')target=visible.at(-1)
  else if(event.key==='ArrowRight'&&hasChildren(path)){setCollapsed(prev=>{const next=new Set(prev);next.delete(path);return next});event.preventDefault();return}
  else if(event.key==='ArrowLeft'){if(hasChildren(path)&&!collapsed.has(path)){toggle(path);event.preventDefault();return}target=path.slice(0,path.lastIndexOf('/'))}
  if(target&&objects[target]&&visible.includes(target)){event.preventDefault();setSelected(target);requestAnimationFrame(()=>document.getElementById('object-'+encodeURIComponent(target))?.focus())}
 }
 const status=state?.session_error?'会话已停止':state?.stale?'文档已变化':busy==='loading'?'正在连接':snapshot.paused?'修改失败':busy==='set'?'正在渲染':drafts.size?'修改待处理':busy==='save'?'正在保存':busy==='export'?'正在导出':busy?'正在处理':!frameReady?'正在加载预览':state?.dirty?'尚未保存':'已保存'
 const statusTone=state?.stale||snapshot.paused?'danger':drafts.size||busy||!frameReady?'warn':state?.dirty?'accent':'ok'
 return <div className="editor-app">
  <a className="skip-link" href="#native-canvas">跳到画布</a>
  <header className="app-bar">
   <a className="brand" href="#native-canvas">SciPlot<span>实时编辑</span></a>
   <div className="document-title"><strong>{state?.title||state?.figure_id||'原生图形'}</strong><span>{state?.document?shortPath(state.document):'Veusz 原生文档'}</span></div>
   <div className="top-actions">
    <button onClick={()=>setShowAbout(true)} className="quiet">关于</button>
    <button onClick={()=>setConfirmReload(true)} disabled={!state||!!busy} title="重新读取已保存的 VSZ">重新载入</button>
    <button onClick={()=>void controller.action('undo')} disabled={!cleanQueue||!state?.can_undo} title="撤销 · ⌘/Ctrl Z">撤销</button>
    <button onClick={()=>void controller.action('redo')} disabled={!cleanQueue||!state?.can_redo} title="重做 · ⌘/Ctrl Shift Z">重做</button>
    <button onClick={()=>void controller.action('export')} disabled={!mutateReady||state?.dirty} title={state?.dirty?'请先保存原生文档':'按当前已保存文档导出'}>导出</button>
    <button className="primary" onClick={()=>void controller.action('save')} disabled={!mutateReady||!state?.dirty}>保存 VSZ</button>
   </div>
  </header>
  <div className="state-bar" role="status" aria-live="polite"><Badge tone={statusTone}>{status}</Badge><span>{state?`版本 ${state.revision}`:'本机编辑会话'}</span><span className="state-description">{result||'点击图形或左侧对象，再在右侧修改属性。'}</span><span className="engine-label" title={state?.checked_at?`最近证据检查：${state.checked_at}`:undefined}>Veusz 原生绘图</span></div>
  {error&&<div className="error-banner" role="alert"><div><strong>{state?.session_error?'原生会话已停止':snapshot.paused?'修改未完成':'需要处理'}</strong><p>{error}</p>{drafts.size>0&&<p>输入内容已保留；画布显示最近一次成功的原生渲染。</p>}</div><div className="error-actions">{!state?.session_error&&snapshot.paused&&<button onClick={()=>void controller.retry()} disabled={!!busy}>重试修改</button>}{drafts.size>0&&<button onClick={()=>controller.discardDrafts()} disabled={!!busy}>放弃未应用输入</button>}{state?.session_error?<button onClick={()=>setConfirmReload(true)} disabled={!!busy}>重新载入原生会话</button>:!drafts.size&&<button onClick={()=>void controller.load()} disabled={!!busy}>重新连接</button>}</div></div>}
  <main className={`editing-workspace ${!leftOpen?'left-closed':''} ${!rightOpen?'right-closed':''}`}>
   <aside className="object-panel" hidden={!leftOpen} aria-label="对象与样品"><div className="panel-heading"><h2>对象与样品</h2><span>{paths.length}</span><button onClick={()=>setLeftOpen(false)} aria-label="收起对象列表" className="icon-button">×</button></div><div className="object-search"><TextInput aria-label="搜索对象或样品" value={query} onChange={e=>setQuery(e.target.value)} placeholder="搜索对象、样品…"/></div>
    <div className="object-tree" role="tree" aria-label="原生文档对象">
     {visible.map(path=>{const item=objects[path],children=hasChildren(path);return <div key={path} role="treeitem" id={'object-'+encodeURIComponent(path)} aria-selected={selected===path} aria-expanded={children?!collapsed.has(path):undefined} aria-level={Math.max(1,path.split('/').filter(Boolean).length)} tabIndex={tabStop===path?0:-1} className={`object-row ${selected===path?'selected':''}`} style={treeIndent(Math.max(0,path.split('/').filter(Boolean).length-1))} onClick={()=>setSelected(path)} onKeyDown={e=>treeKey(e,path)} title={path}><button className="tree-expander" tabIndex={-1} aria-label={collapsed.has(path)?'展开对象':'折叠对象'} aria-hidden={!children} disabled={!children} onClick={e=>{e.stopPropagation();toggle(path)}}>{children?(collapsed.has(path)?'›':'⌄'):''}</button><span className={`object-symbol type-${item.type}`} aria-hidden>{item.type==='xy'?'∿':item.type==='axis'?'⊥':item.type==='label'?'T':'▢'}</span><span className="object-name">{item.label||item.sample||item.name||shortPath(path)}<small>{typeNames[item.type]||item.type}</small></span>{item.fields?.length>0&&<span className="editable-dot" title="具有可编辑属性" aria-label="可编辑"/>}</div>})}
     {paths.length===0&&<p className="panel-empty">{busy?'正在读取原生对象…':'尚未载入文档。'}</p>}
     {paths.length>0&&visible.length===0&&<p className="panel-empty">没有匹配的对象。</p>}
    </div><div className="panel-footnote">对象直接来自当前 Veusz 文档。</div>
   </aside>
   <section className="canvas-panel" aria-label="实时原生画布">
    <div className="canvas-toolbar"><div className="canvas-context">{!leftOpen&&<button onClick={()=>setLeftOpen(true)}>对象</button>}<span>{selectedObject?selectedObject.label||selectedObject.sample||selectedObject.name:'选择图中对象'}</span></div><div className="canvas-controls"><button onClick={()=>canvas.zoom(1/1.2)} disabled={!state} aria-label="缩小">−</button><output aria-label="缩放比例">{Math.round(canvas.view.zoom*100)}%</output><button onClick={()=>canvas.zoom(1.2)} disabled={!state} aria-label="放大">+</button><button onClick={canvas.fit} disabled={!state}>适合窗口</button><button aria-expanded={rightOpen} onClick={()=>setRightOpen(!rightOpen)}>属性</button></div></div>
    <div ref={canvas.box} id="native-canvas" className={`native-canvas ${canvas.dragging?'dragging':''}`} tabIndex={0} role="region" aria-label="原生图形；点击选择，拖动平移，加减键缩放，0 键适合窗口"
     onPointerDown={event=>{
      if((event.button!==0&&event.button!==1)||!state||canvas.drag.current)return
      const rect=canvas.image.current?.getBoundingClientRect()
      let mode:'pan'|'key'='pan'
      if(event.button===0&&!spacePan.current&&keyBounds&&rect&&controller.readyForFrameAction){
       const x=(event.clientX-rect.left)/canvas.view.zoom,y=(event.clientY-rect.top)/canvas.view.zoom
       if(x>=keyBounds[0]&&x<=keyBounds[0]+keyBounds[2]&&y>=keyBounds[1]&&y<=keyBounds[1]+keyBounds[3])mode='key'
      }
      canvas.drag.current={x:event.clientX,y:event.clientY,startX:canvas.view.x,startY:canvas.view.y,moved:false,pointer:event.pointerId,mode,objectPath:mode==='key'?selected:undefined,revision:state.revision,scale:canvas.view.zoom}
      setKeyOffset({x:0,y:0});event.currentTarget.setPointerCapture(event.pointerId);event.currentTarget.focus();event.preventDefault()
     }}
     onPointerMove={event=>{
      const drag=canvas.drag.current;if(!drag||drag.pointer!==event.pointerId)return
      const dx=event.clientX-drag.x,dy=event.clientY-drag.y
      if(Math.abs(dx)+Math.abs(dy)>4)drag.moved=true
      if(drag.moved){canvas.setDragging(true);if(drag.mode==='key')setKeyOffset({x:dx,y:dy});else canvas.setView(v=>({...v,x:drag.startX+dx,y:drag.startY+dy,fit:false}))}
     }}
     onPointerUp={event=>{
      const drag=canvas.drag.current;if(!drag||drag.pointer!==event.pointerId)return
      canvas.drag.current=null;canvas.setDragging(false);setKeyOffset({x:0,y:0})
      if(event.currentTarget.hasPointerCapture(event.pointerId))event.currentTarget.releasePointerCapture(event.pointerId)
      if(drag?.moved&&drag.mode==='key'){
       if(drag.revision!==controller.state?.revision||!controller.readyForFrameAction)controller.operationRejected('拖动期间原生画布已变化，请在最新预览上重新拖动图例。')
       else void controller.action('move_key',{object_path:drag.objectPath,dx:(event.clientX-drag.x)/drag.scale,dy:(event.clientY-drag.y)/drag.scale})
      }else if(drag&&!drag.moved&&event.button===0&&!spacePan.current)void canvas.pick(event.clientX,event.clientY).then(path=>{if(path)setSelected(path)})
     }}
     onPointerCancel={event=>{if(canvas.drag.current?.pointer!==event.pointerId)return;canvas.drag.current=null;canvas.setDragging(false);setKeyOffset({x:0,y:0})}}
     onLostPointerCapture={event=>{if(canvas.drag.current?.pointer!==event.pointerId)return;canvas.drag.current=null;canvas.setDragging(false);setKeyOffset({x:0,y:0})}}
     onBlur={()=>{spacePan.current=false}}
     onKeyUp={event=>{if(event.code==='Space'){spacePan.current=false;event.preventDefault()}}}
     onKeyDown={event=>{if(event.code==='Space'){spacePan.current=true;event.preventDefault();return}if(event.metaKey||event.ctrlKey||event.altKey)return;if(['+','=','-','0'].includes(event.key)){event.preventDefault();event.key==='0'?canvas.fit():canvas.zoom(event.key==='-'?1/1.2:1.2)}}}>
     {frames.map(frame=>{const current=frameKey(frame)===frameKey(currentFrame!);return <img ref={current?canvas.image:undefined} key={frameKey(frame)} src={frame.state.preview.url} alt={current?'当前 Veusz 文档的原生渲染':''} aria-hidden={!current} draggable={false} width={frame.state.preview.width} height={frame.state.preview.height} style={{width:frame.state.preview.width,height:frame.state.preview.height,opacity:current&&!frameReady?0:1,transform:`translate(-50%, -50%) translate(${canvas.view.x}px, ${canvas.view.y}px) scale(${canvas.view.zoom})`}} onLoad={()=>{if(current&&controller.state?.revision===frame.state.revision&&controller.state?.session_id===frame.state.session_id){setLoadedFrame(frame);controller.markFrame(frame.state.revision);if(canvas.view.fit)canvas.fit()}}} onError={()=>{if(current)controller.frameFailed(frame.state.revision)}}/>})}
     {state&&keyBounds&&frameReady&&<div className="key-selection" aria-hidden style={{left:`calc(50% + ${canvas.view.x+(keyBounds[0]-state.preview.width/2)*canvas.view.zoom+keyOffset.x}px)`,top:`calc(50% + ${canvas.view.y+(keyBounds[1]-state.preview.height/2)*canvas.view.zoom+keyOffset.y}px)`,width:keyBounds[2]*canvas.view.zoom,height:keyBounds[3]*canvas.view.zoom}}><span>拖动图例</span></div>}
     {!state&&<div className="canvas-placeholder"><div className="empty-sheet"><span>SciPlot</span><p>{busy?'正在打开原生文档…':'无法读取原生文档'}</p>{!busy&&<button onClick={()=>void controller.load()}>重新连接</button>}</div></div>}
     {state&&!frameReady&&<div className="canvas-loading" role="status">正在载入版本 {state.revision} 的预览…</div>}
    </div><div className="canvas-footer"><span>{frameReady?'预览已同步':state?'正在等待原生预览':'等待连接'}</span><span>{keyBounds?'拖动选中图例 · 空格拖动平移':'点击选中 · 拖动平移'} · + / − 缩放 · 0 适合窗口</span><span>{state?`${state.preview.width} × ${state.preview.height} px`:''}</span></div>
   </section>
   <aside className="property-panel" hidden={!rightOpen} aria-label="原生属性"><div className="panel-heading"><h2>属性</h2><button onClick={()=>setRightOpen(false)} aria-label="收起属性" className="icon-button">×</button></div>
    <div ref={propertyScroll} className="property-scroll">{selectedObject?<><div className="selected-heading"><span>{typeNames[selectedObject.type]||selectedObject.type}</span><h3>{selectedObject.label||selectedObject.sample||selectedObject.name||shortPath(selected)}</h3><p title={selected}>{selected}</p></div>
     {(selectedObject.fields??[]).length===0?<div className="unsupported"><strong>此对象暂无开放的编辑属性</strong><p>可从对象列表选择曲线、坐标轴或图例。这里仅展示原生文档当前允许修改的属性。</p></div>:<><p className="editing-hint">输入后自动生成原生预览；保存后写入 VSZ。</p>{(selectedObject.fields??[]).map(field=><PropertyField key={selected+field.setting_path} objectPath={selected} field={field} snapshot={snapshot}/>)}</>}
    </>:<p className="panel-empty">在图中点击，或从左侧选择一个对象。</p>}
    </div><div className="panel-footnote">{state?.dirty?'修改尚未保存；原始数据保持不变。':'显示当前原生文档属性。'}</div>
   </aside>
  </main>
  <dialog ref={reloadDialog} className="confirm-dialog" onCancel={()=>setConfirmReload(false)} onClose={()=>setConfirmReload(false)} aria-labelledby="reload-title"><h2 id="reload-title">重新载入已保存文档？</h2><p>当前未保存的原生修改和未应用输入将被放弃。已保存的 VSZ 会重新载入。</p><div className="dialog-actions"><button autoFocus onClick={()=>setConfirmReload(false)}>保留当前编辑</button><button className="primary" onClick={()=>{setConfirmReload(false);void controller.action('reload')}}>重新载入</button></div></dialog>
  <dialog ref={aboutDialog} className="about-dialog" onCancel={()=>setShowAbout(false)} onClose={()=>setShowAbout(false)} aria-labelledby="about-title"><div className="panel-heading"><h2 id="about-title">关于 SciPlot 实时编辑</h2><button onClick={()=>setShowAbout(false)}>关闭</button></div><p>属性修改、点击选择、预览和撤销由同一个原生 Veusz 文档会话执行。保存会通过 SciPlot 现有的独立 preview / apply 事务检查与写入，导出沿用 SciPlot 的数据审计和交付流程。</p><p>部分界面控件与设计主题接收自 <a href="https://github.com/Tavotto/Tavotto/tree/4cf5b8c658b06dbd6e1fc8a569fee85ef5d62186">Tavotto</a>，按 AGPL-3.0-only 使用并修改。这是 SciPlot 界面，不代表 Tavotto 官方版本。</p><p><a href="./tavotto-LICENSE.txt" target="_blank" rel="noreferrer">完整许可证</a> · <a href="./THIRD_PARTY.md" target="_blank" rel="noreferrer">代码来源与修改记录</a> · <a href="./dependency-LICENSES.txt" target="_blank" rel="noreferrer">依赖许可证</a></p></dialog>
 </div>
}
function PropertyField({objectPath,field,snapshot}:{objectPath:string;field:Field;snapshot:Snapshot}){
 const draft=snapshot.drafts.get(field.setting_path)
 const raw=draft?draft.text:field.current_value
 const value=displayValue(raw)
 const error=draft?.valid===false?draft.error:undefined
 const id='field-'+encodeURIComponent(field.setting_path)
 const disabled=!!snapshot.state?.stale||snapshot.busy==='save'||snapshot.busy==='export'||snapshot.busy==='reload'||snapshot.busy==='loading'
 const change=(value:unknown)=>controller.setDraft(objectPath,field,value)
 const help=field.editor==='distance'?'包含单位，例如 8pt / 0.3mm':field.editor==='float_list'?'递增数值，用逗号分隔；留空为自动':field.help_text
 if(!supportedEditors.has(field.editor))return <div className="property-field readonly-field"><label>{field.label}</label><span>{displayValue(field.current_value)}</span><small>此属性暂未提供编辑控件。</small></div>
 return <div className={`property-field ${error?'field-error':''}`} data-setting-path={field.setting_path}>
  <div className="field-label"><label htmlFor={id}>{field.label}</label>{draft&&<span className="field-pending">{error?'输入未完成':'待同步'}</span>}</div>
  {field.editor==='choice'||field.editor==='enum'?<select id={id} value={value} onChange={e=>change(e.target.value)} disabled={disabled} aria-invalid={!!error}>{!(field.choices??[]).includes(value)&&<option value={value}>{value}（当前值）</option>}{(field.choices??[]).map(choice=><option key={choice} value={choice}>{choice}</option>)}</select>:field.editor==='boolean'||field.editor==='bool'?<label className="boolean-control"><input type="checkbox" id={id} checked={Boolean(raw)} onChange={e=>change(e.target.checked)} disabled={disabled}/><span>{raw?'开启':'关闭'}</span></label>:<div className={field.editor==='color'?'color-control':'value-control'}>{field.editor==='color'&&<fieldset disabled={disabled}><ColorField value={colorHex(value)} onChange={change} ariaLabel={field.label}/></fieldset>}<TextInput id={id} value={value} onChange={e=>change(e.target.value)} disabled={disabled} invalid={!!error} inputMode={['number','integer','number_or_auto'].includes(field.editor)?'decimal':undefined} aria-describedby={error||help?id+'-help':undefined}/></div>}
  {(error||help)&&<small id={id+'-help'} className={error?'validation-error':'field-help'}>{error||help}</small>}
 </div>
}
