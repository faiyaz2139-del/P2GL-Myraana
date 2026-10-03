import { env } from 'cloudflare:workers';
import type { Job } from './types';
export function runtime(){return env as unknown as {DB:D1Database;BUCKET:R2Bucket;ANTHROPIC_API_KEY?:string;CLAUDE_MODEL?:string;OPENAI_API_KEY?:string;OPENAI_MODEL?:string;AI_PRIMARY_PROVIDER?:string;AI_FALLBACK_ENABLED?:string};}
export function db(){const binding=runtime().DB;if(!binding)throw new Error('Persistent database is unavailable.');return binding;}
export const now=()=>new Date().toISOString();
export async function read<T=any>(id:string):Promise<T|null>{const r=await db().prepare('SELECT data, revision FROM records WHERE id=?').bind(id).first<any>();return r?{...JSON.parse(r.data),revision:r.revision}:null;}
export async function insert(id:string,kind:string,data:any){await db().prepare('INSERT INTO records (id,kind,data) VALUES (?,?,?)').bind(id,kind,JSON.stringify(data)).run();}
export async function list<T=any>(kind:string):Promise<T[]>{const r=await db().prepare('SELECT data,revision FROM records WHERE kind=? ORDER BY rowid DESC').bind(kind).all<any>();return r.results.map(x=>({...JSON.parse(x.data),revision:x.revision}));}
export async function save(job:Job,lock:string){job.updated=now();const r=await db().prepare('UPDATE records SET data=?, revision=revision+1, locked_at=? WHERE id=? AND lock=?').bind(JSON.stringify(job),Date.now(),job.id,lock).run();if(!r.meta.changes)throw new Error('Execution lease expired. Refresh the job.');job.revision++;}
export async function lock(id:string):Promise<string>{const token=crypto.randomUUID();const r=await db().prepare('UPDATE records SET lock=?,locked_at=? WHERE id=? AND (lock IS NULL OR locked_at<?)').bind(token,Date.now(),id,Date.now()-120000).run();if(!r.meta.changes)throw new Error('This job is already being updated. Please wait and refresh.');return token;}
export async function unlock(id:string,token:string){await db().prepare('UPDATE records SET lock=NULL,locked_at=NULL WHERE id=? AND lock=?').bind(id,token).run();}
export async function hash(bytes:Uint8Array|string){const b=typeof bytes==='string'?new TextEncoder().encode(bytes):bytes;const h=await crypto.subtle.digest('SHA-256',b as BufferSource);return Array.from(new Uint8Array(h)).map(x=>x.toString(16).padStart(2,'0')).join('');}
