// Server-only provider protocol adapters. No browser imports.
export type Provider='claude'|'openai';
export type Block={type:'text';text:string}|{type:'tool_use';id:string;name:string;input:Record<string,unknown>};
export type History={role:'user'|'assistant';content:any}[];
export type ProviderConfig={provider:Provider;key:string;model:string};
export function providerOrder(env:{ANTHROPIC_API_KEY?:string;OPENAI_API_KEY?:string;CLAUDE_MODEL?:string;OPENAI_MODEL?:string;AI_PRIMARY_PROVIDER?:string;AI_FALLBACK_ENABLED?:string}):ProviderConfig[]{
 const primary:Provider=env.AI_PRIMARY_PROVIDER==='openai'?'openai':'claude';const order:Provider[]=env.AI_FALLBACK_ENABLED==='false'?[primary]:[primary,primary==='claude'?'openai':'claude'];
 return order.flatMap(provider=>{const key=provider==='claude'?env.ANTHROPIC_API_KEY:env.OPENAI_API_KEY;if(!key)return [];return [{provider,key,model:provider==='claude'?(env.CLAUDE_MODEL||'claude-sonnet-4-5'):(env.OPENAI_MODEL||'gpt-4.1')}];});
}
export function openAIInput(history:History){return history.flatMap(m=>{if(typeof m.content==='string')return [{role:m.role,content:m.content}];return m.content.map((b:any)=>b.type==='tool_use'?{type:'function_call',call_id:b.id,name:b.name,arguments:JSON.stringify(b.input)}:b.type==='tool_result'?{type:'function_call_output',call_id:b.tool_use_id,output:b.is_error?JSON.stringify({error:b.content}):b.content}:{role:m.role,content:b.text||''});});}
async function frames(response:Response,consume:(event:any)=>void){if(!response.body)throw new Error('Assistant response is empty.');const reader=response.body.getReader(),decoder=new TextDecoder();let buffer='';const parse=(s:string)=>{const lines=s.split('\n').filter(x=>x.startsWith('data:')).map(x=>x.slice(5).trimStart());const data=lines.join('\n');if(!data||data==='[DONE]')return;const ev=JSON.parse(data);consume(ev);};try{while(true){const chunk=await reader.read();if(chunk.done)break;buffer+=decoder.decode(chunk.value,{stream:true});buffer=buffer.replace(/\r\n/g,'\n');let end;while((end=buffer.indexOf('\n\n'))>=0){parse(buffer.slice(0,end));buffer=buffer.slice(end+2);}}if(buffer.trim())parse(buffer);}finally{reader.releaseLock();}}
export async function streamTurn(config:ProviderConfig,system:string,history:History,tools:any[],send:(text:string)=>void,fetcher:typeof fetch=fetch):Promise<Block[]>{
 const isClaude=config.provider==='claude';const response=await fetcher(isClaude?'https://api.anthropic.com/v1/messages':'https://api.openai.com/v1/responses',{method:'POST',headers:isClaude?{'content-type':'application/json','x-api-key':config.key,'anthropic-version':'2023-06-01'}:{'content-type':'application/json','Authorization':`Bearer ${config.key}`},body:JSON.stringify(isClaude?{model:config.model,max_tokens:900,system,tools,messages:history,stream:true}:{model:config.model,max_output_tokens:900,instructions:system,input:openAIInput(history),tools:tools.map(t=>({type:'function',name:t.name,description:t.description,parameters:t.input_schema,strict:true})),parallel_tool_calls:false,store:false,stream:true}),signal:AbortSignal.timeout(45000)});
 if(!response.ok)throw new Error(`Assistant request failed (${response.status}).`);
 const blocks:any[]=[];let text='',complete=false,output:any[]=[];
 await frames(response,ev=>{if(ev.type==='error'||ev.type==='response.failed'||ev.type==='response.incomplete')throw new Error('Assistant response could not finish.');
  if(isClaude){if(ev.type==='message_stop')complete=true;if(ev.type==='content_block_start')blocks[ev.index]={...ev.content_block,inputText:''};if(ev.type==='content_block_delta'){const b=blocks[ev.index];if(!b)throw new Error('Invalid assistant stream.');if(ev.delta.type==='text_delta'){b.text=(b.text||'')+ev.delta.text;send(ev.delta.text);}if(ev.delta.type==='input_json_delta')b.inputText+=ev.delta.partial_json;}}
  else{if(ev.type==='response.output_text.delta'){text+=ev.delta;send(ev.delta);}if(ev.type==='response.completed'){complete=true;output=ev.response?.output||[];}}
 });
 if(!complete)throw new Error('Assistant stream ended before completion. Retry your message.');
 if(isClaude)return blocks.filter(b=>b&&(b.type==='text'||b.type==='tool_use')).map(b=>b.type==='tool_use'?{type:'tool_use',id:b.id,name:b.name,input:b.inputText?JSON.parse(b.inputText):b.input||{}}:{type:'text',text:b.text||''});
 const result:Block[]=text?[{type:'text',text}]:[];for(const item of output){if(item.type==='function_call'){if(!item.call_id||!item.name)throw new Error('Invalid assistant tool request.');result.push({type:'tool_use',id:item.call_id,name:item.name,input:JSON.parse(item.arguments||'{}')});}}
 return result;
}
// Fallback is allowed only before any visible output or tool execution.
export async function firstTurn(configs:ProviderConfig[],system:string,history:History,tools:any[],send:(text:string)=>void,fetcher:typeof fetch=fetch){let visible=false;let last:unknown;for(const config of configs){try{const content=await streamTurn(config,system,history,tools,text=>{visible=true;send(text);},fetcher);return {config,content};}catch(e){last=e;if(visible)throw e;}}throw last||new Error('Assistant backend is not configured.');}
