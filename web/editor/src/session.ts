/** SciPlot live session controller. Native Veusz owns document values and history. */
export type Field = {setting_path:string; editor:string; current_value:unknown; choices?:string[]; minimum?:number|null; maximum?:number|null; label:string; section?:string; help_text?:string}
export type NativeObject = {type:string; name:string; fields:Field[]; parent?:string; sample?:string; label?:string; drag_handle?:{kind:'key';bounds:[number,number,number,number]}}
export type NativeState = {session_id:string; revision:number; document_sha256:string; figure_id:string; document?:string; title?:string; objects:Record<string,NativeObject>; preview:{url:string;width:number;height:number;sha256:string}; can_undo:boolean;can_redo:boolean;dirty:boolean;selected_object_path?:string;session_error?:string|null;[key:string]:unknown}
export type Draft = {key:string;objectPath:string;text:unknown;value:unknown;generation:number;valid:boolean;error?:string}
export type Snapshot = {state:NativeState|null;drafts:Map<string,Draft>;busy:string|null;error:string|null;result:string|null;frameRevision:number|null;paused:boolean;previewNonce:number}
export type FetchLike = (input:string,init?:RequestInit)=>Promise<Pick<Response,'ok'|'status'|'json'>>
const same = (a:unknown,b:unknown) => JSON.stringify(a)===JSON.stringify(b)
export const treeTabStop = (visible:string[],selected:string):string|undefined => visible.includes(selected)?selected:visible[0]
export const isTextTarget = (target:unknown):boolean => {
 const el=target as {tagName?:string;type?:string;isContentEditable?:boolean;closest?:(s:string)=>unknown}|null
 if(!el) return false
 if(el.isContentEditable || el.closest?.('[contenteditable="true"]')) return true
 return el.tagName==='TEXTAREA' || el.tagName==='SELECT' || (el.tagName==='INPUT' && !['checkbox','radio','button','submit','range','color'].includes(el.type||''))
}
export function shortcutAction(event:{key:string;metaKey?:boolean;ctrlKey?:boolean;altKey?:boolean;shiftKey?:boolean;target?:unknown}):'undo'|'redo'|'save'|null {
 if(!(event.metaKey||event.ctrlKey)||event.altKey) return null
 const key=event.key.toLowerCase()
 if(key==='s') return 'save'
 if(key==='z'&&!isTextTarget(event.target)) return event.shiftKey?'redo':'undo'
 return null
}
export function parseField(field:Field, raw:unknown):{valid:boolean;value:unknown;error?:string} {
 const fail=(error:string)=>({valid:false,value:raw,error})
 const text=String(raw??'').trim()
 if(field.editor==='boolean'||field.editor==='bool') return typeof raw==='boolean'?{valid:true,value:raw}:fail('请选择开或关。')
 if(field.editor==='choice'||field.editor==='enum') return (field.choices??[]).includes(text)?{valid:true,value:text}:fail('请选择当前图形支持的值。')
 if(field.editor==='integer'||field.editor==='number'||field.editor==='number_or_auto') {
  if(field.editor==='number_or_auto'&&text==='Auto') return {valid:true,value:'Auto'}
  const value=Number(text)
  if(!text||!Number.isFinite(value)||(field.editor==='integer'&&!Number.isInteger(value))) return fail(field.editor==='integer'?'请输入整数。':'请输入有限数值。')
  if(field.minimum!=null&&value<field.minimum) return fail(`最小值为 ${field.minimum}。`)
  if(field.maximum!=null&&value>field.maximum) return fail(`最大值为 ${field.maximum}。`)
  return {valid:true,value}
 }
 if(field.editor==='distance') {
  const match=/^(\d+(?:\.\d*)?|\.\d+)\s*(pt|mm|cm|in|inch)$/.exec(text)
  if(!match||!Number.isFinite(Number(match[1]))||Number(match[1])<=0) return fail('请输入正数和单位，例如 8pt 或 0.3mm。')
  return {valid:true,value:text}
 }
 if(field.editor==='float_list') {
  try {
   if(text&&!text.startsWith('[')&&text.split(/[,，]/).some(part=>!part.trim())) return fail('逗号之间需要填写数值；留空整个输入框恢复自动。')
   const value:unknown=text.startsWith('[')?JSON.parse(text):text?text.split(/[,，\s]+/).map(Number):[]
   if(!Array.isArray(value)||value.length>32||value.some(v=>typeof v!=='number'||!Number.isFinite(v))||value.some((v,i)=>i>0&&v<=value[i-1])) return fail('请输入递增且不重复的数值，最多 32 个；留空恢复自动。')
   return {valid:true,value}
  }catch{return fail('请输入数值列表，例如 0, 10, 20。')}
 }
 if(field.editor==='color') {
  // Exact names and color validity are checked by QColor on the native side.
  if(!text||text.length>100||/[\r\n]/.test(text)) return fail('请输入不透明颜色名称或 RGB 色号。')
  return {valid:true,value:text}
 }
 if(field.editor==='text'||field.editor==='string') return {valid:true,value:String(raw??'')}
 return fail('此属性当前没有可用的编辑控件。')
}
export function displayValue(value:unknown):string {
 return Array.isArray(value)?value.join(', '):value==null?'':String(value)
}
export class SessionController {
 state:NativeState|null=null
 drafts=new Map<string,Draft>()
 busy:string|null=null
 error:string|null=null
 result:string|null=null
 frameRevision:number|null=null
 previewNonce=0
 paused=false
 private pending=new Map<string,Draft>()
 private inFlight=new Map<string,Draft>()
 private timer:ReturnType<typeof setTimeout>|undefined
 private generation=0
 private request=0
 private clientId=crypto.randomUUID()
 private token:string
 private fetcher:FetchLike
 private debounce:number
 private listeners=new Set<()=>void>()
 private currentSnapshot:Snapshot=this.makeSnapshot()
 constructor(token:string,fetcher:FetchLike=(input,init)=>globalThis.fetch(input,init),debounce=250){this.token=token;this.fetcher=fetcher;this.debounce=debounce}
 private makeSnapshot():Snapshot{return {state:this.state,drafts:new Map(this.drafts),busy:this.busy,error:this.error,result:this.result,frameRevision:this.frameRevision,paused:this.paused,previewNonce:this.previewNonce}}
 snapshot=()=>this.currentSnapshot
 subscribe=(fn:()=>void)=>{this.listeners.add(fn);return()=>{this.listeners.delete(fn)}}
 private emit(){this.currentSnapshot=this.makeSnapshot();for(const fn of this.listeners)fn()}
 private headers(){return {'Content-Type':'application/json','X-SciPlot-Token':this.token}}
 private field(path:string,key:string){return this.state?.objects[path]?.fields.find(f=>f.setting_path===key)}
 private receive(state:NativeState|undefined){
  if(!state||!Number.isInteger(state.revision)||!state.objects||!state.preview) return
  if(this.state&&state.session_id===this.state.session_id&&state.revision<this.state.revision)return
  if(this.state&&state.session_id!==this.state.session_id){
   this.frameRevision=null
   if(this.drafts.size){this.paused=true;this.error='原生会话已更换。输入草稿已保留；请确认重新载入，或放弃未应用输入。'}
  }
  this.state=state
 }
 async load(){
  if(this.busy)return
  this.busy='loading';this.error=null;this.emit()
  try{const response=await this.fetcher('/api/state',{headers:this.headers()});const data=await response.json();if(!response.ok)throw new Error(data.error?.message||'无法连接原生编辑会话。');this.receive(data.state??data);this.previewNonce++;if(!this.state)throw new Error('原生会话返回了无法识别的状态。')}
  catch(error){this.error=String(error instanceof Error?error.message:error)}
  finally{this.busy=null;this.emit()}
 }
 setDraft(objectPath:string,field:Field,text:unknown){
  const parsed=parseField(field,text)
  const draft:Draft={key:field.setting_path,objectPath,text,value:parsed.value,generation:++this.generation,valid:parsed.valid,error:parsed.error}
  this.drafts.set(draft.key,draft)
  if(parsed.valid&&(!same(parsed.value,this.field(objectPath,draft.key)?.current_value)||this.inFlight.has(draft.key)))this.pending.set(draft.key,draft)
  else {this.pending.delete(draft.key);if(parsed.valid&&!this.inFlight.has(draft.key))this.drafts.delete(draft.key)}
  this.result=null
  clearTimeout(this.timer)
  if(!this.paused)this.timer=setTimeout(()=>{void this.flush()},this.debounce)
  this.emit()
 }
 markFrame(revision:number){if(revision===this.state?.revision){this.frameRevision=revision;this.emit()}}
 frameFailed(revision:number){if(revision===this.state?.revision){this.frameRevision=null;this.error='原生预览加载失败。请重试连接；当前修改仍保留在会话中。';this.emit()}}
 get hasDrafts(){return this.drafts.size>0}
 get readyForFrameAction(){return !!this.state&&this.frameRevision===this.state.revision&&!this.busy&&!this.drafts.size&&!this.paused&&!this.state.stale}
 async flush():Promise<void>{
  clearTimeout(this.timer)
  if(this.busy||this.paused||!this.state||!this.pending.size)return
  const sent=new Map(this.pending);this.pending.clear()
  const changes=[]
  for(const [key,draft] of sent){
   const field=this.field(draft.objectPath,key)
   if(!field){this.paused=true;this.error='对象或属性已变化，草稿尚未应用。请重新载入文档。';this.pending.set(key,draft);continue}
   if(same(field.current_value,draft.value)){if(this.drafts.get(key)?.generation===draft.generation)this.drafts.delete(key);sent.delete(key);continue}
   changes.push({object_path:draft.objectPath,setting_path:key,expected_value:field.current_value,value:draft.value})
  }
  if(this.paused){for(const [key,draft] of sent)if(!this.pending.has(key))this.pending.set(key,draft);this.emit();return}
  if(!changes.length){this.emit();return}
  this.inFlight=sent
  const success=await this.send('set',{changes})
  if(success){for(const [key,draft] of sent)if(this.drafts.get(key)?.generation===draft.generation)this.drafts.delete(key)}
  else {for(const [key,draft] of sent)if(!this.pending.has(key)&&this.drafts.get(key)?.generation===draft.generation)this.pending.set(key,draft);this.paused=true}
  this.inFlight.clear();this.emit()
  if(success&&this.pending.size)await this.flush()
 }
 private async send(action:string,extra:Record<string,unknown>={}):Promise<boolean>{
  if(!this.state||this.busy)return false
  this.busy=action;this.error=null;this.emit()
  const request_id=`${this.clientId}:${++this.request}`
  try{
   const response=await this.fetcher('/api/command',{method:'POST',headers:this.headers(),body:JSON.stringify({request_id,revision:this.state.revision,action,...extra})})
   const payload=await response.json()
   this.receive(payload.state)
   if(!response.ok||payload.error)throw new Error(payload.error?.message||`原生操作失败 (${response.status})。`)
   if(!payload.state)throw new Error('操作没有返回原生文档状态，请重新连接核实。')
   if(payload.selected_object_path&&this.state)this.state={...this.state,selected_object_path:payload.selected_object_path}
   if(payload.hit?.object_path&&this.state)this.state={...this.state,selected_object_path:payload.hit.object_path}
   if(action==='save'||action==='export'){
    const result=payload.result
    this.result=typeof result==='string'?result:result?.message|| (action==='save'?'已保存原生 VSZ 文档。':'已完成原生导出。')
    if(result?.paths)this.result+=' '+(Array.isArray(result.paths)?result.paths.join(' · '):String(result.paths))
   }
   return true
  }catch(error){this.error=error instanceof Error?error.message:String(error);return false}
  finally{this.busy=null;this.emit()}
 }
 async action(action:'undo'|'redo'|'hit'|'move_key'|'save'|'export'|'reload',extra:Record<string,unknown>={}):Promise<boolean>{
  if(!this.state||this.busy)return false
  if(action!=='reload'&&(this.drafts.size||this.paused||this.state.stale))return false
  if(['hit','move_key','save','export'].includes(action)&&!this.readyForFrameAction)return false
  if(action==='undo'&&!this.state.can_undo||action==='redo'&&!this.state.can_redo)return false
  const success=await this.send(action,['hit','move_key'].includes(action)?{...extra,preview_revision:this.frameRevision}:extra)
  if(success&&action==='reload'){this.pending.clear();this.drafts.clear();this.paused=false;this.result='已重新载入已保存的原生文档。'}
  this.emit();if(success&&this.pending.size&&!this.paused)void this.flush();return success
 }
 async retry(){
  if(this.busy)return
  // A failed network response may already have applied. Read native values before rebasing.
  await this.load()
  if(this.error){this.paused=true;this.emit();return}
  this.paused=false;this.emit();await this.flush()
 }
 operationRejected(message:string){this.error=message;this.emit()}
 discardDrafts(){clearTimeout(this.timer);this.pending.clear();this.drafts.clear();this.paused=false;this.error=null;this.emit()}
 dispose(){clearTimeout(this.timer);this.listeners.clear()}
}
