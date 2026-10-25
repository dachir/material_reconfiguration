import {test} from 'node:test';
import assert from 'node:assert/strict';
import {needsSaveBeforeCopy,sameRevision} from '../src/chantier-state.js';

test('copy never saves a submitted/cancelled source, even if a control marked it dirty',()=>{
 for(const docstatus of [1,2])assert.equal(needsSaveBeforeCopy({dirty:true,docstatus,editable:false}),false);
 assert.equal(needsSaveBeforeCopy({dirty:true,docstatus:0,editable:true}),true);
 assert.equal(needsSaveBeforeCopy({dirty:false,docstatus:0,editable:true}),false);
 assert.equal(needsSaveBeforeCopy({dirty:true,docstatus:0,editable:false}),false);
});
test('revision comparisons preserve microseconds but normalize transport formatting',()=>{
 assert.equal(sameRevision('2026-10-23 09:19:58','2026-10-23T09:19:58.000000'),true);
 assert.equal(sameRevision('2026-10-23 09:19:58.1','2026-10-23 09:19:58.100000'),true);
 assert.equal(sameRevision('2026-10-23 09:19:58.816994','2026-10-23 09:19:58.816995'),false);
 assert.equal(sameRevision(null,null),false);
});
