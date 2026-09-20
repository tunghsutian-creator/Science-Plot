import type {NativeState} from './session'

/** Keep the last loaded native image mounted until the replacement has loaded. */
export type PreviewFrame = {state:NativeState;nonce:number}
export const previewFrameKey=(frame:PreviewFrame)=>`${frame.state.session_id}:${frame.state.revision}:${frame.nonce}`
export function previewFrames(current:PreviewFrame|null,loaded:PreviewFrame|null):PreviewFrame[]{
 if(!current)return []
 return [...(loaded&&previewFrameKey(loaded)!==previewFrameKey(current)?[loaded]:[]),current]
}
