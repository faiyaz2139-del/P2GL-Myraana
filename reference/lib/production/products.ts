import {inspect,prepare,verify} from './pdf';
import type {Recipe,Inspection} from './types';
export interface ProductAdapter {
 inspect(bytes:Uint8Array,recipe:Recipe,sides:number):Promise<Inspection>;
 prepare(bytes:Uint8Array,recipe:Recipe,blankBorder:boolean):Promise<Uint8Array>;
 verify(bytes:Uint8Array,recipe:Recipe,sides:number):Promise<Inspection>;
}
const adapters:Record<string,ProductAdapter>={'business-card':{inspect,prepare,verify}};
export function product(id:string){const adapter=adapters[id];if(!adapter)throw new Error('No validated processing adapter is configured for this product.');return adapter;}
